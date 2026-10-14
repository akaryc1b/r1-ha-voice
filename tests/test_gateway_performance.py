"""验证音频字节保真、切歌预检复用和缓存边界，不访问真实设备。"""
import asyncio
import io
import json
import time
import unittest
import wave

import aiohttp
import numpy as np
from aiohttp import web

from test_gateway_configuration import GatewayConfigurationTests, gateway
from audio_transport import wav_bytes, sherpa_frame
from tts_cache import AudioCache


class AudioTransportTests(unittest.TestCase):
    def test_pcm16_wav_preserves_extreme_samples(self):
        raw = np.array([-32768, -1, 0, 1, 32767], dtype='<i2').tobytes()
        with wave.open(io.BytesIO(wav_bytes([raw[:4], raw[4:]], 'pcm_s16le')), 'rb') as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16000))
            self.assertEqual(audio.readframes(5), raw)
        actual = np.frombuffer(sherpa_frame(raw, 'pcm_s16le'), dtype='<f4')
        np.testing.assert_array_equal(actual, np.frombuffer(raw, dtype='<i2').astype('<f4') / 32768)

    def test_legacy_float_is_forwarded_unchanged(self):
        raw = np.array([-.5, 0, .5], dtype='<f4').tobytes()
        self.assertIs(sherpa_frame(raw, 'float32'), raw)
        with wave.open(io.BytesIO(wav_bytes([raw])), 'rb') as audio:
            self.assertEqual(audio.getnframes(), 3)

    def test_invalid_audio_does_not_get_truncated(self):
        for format_name in ('float32', 'pcm_s16le'):
            with self.assertRaises(ValueError):
                wav_bytes([b'\x01'], format_name)
            with self.assertRaises(ValueError):
                sherpa_frame(b'\x01', format_name)

    def test_lru_hits_keep_hot_audio_and_limit_bytes(self):
        cache = AudioCache(max_entries=2, max_bytes=6)
        cache['prompt'] = b'aa'
        cache['cold'] = b'bb'
        self.assertEqual(cache['prompt'], b'aa')
        cache['new'] = b'cc'
        self.assertNotIn('cold', cache)
        cache['large'] = b'12345'
        self.assertEqual(list(cache), ['large'])
        cache['too_large'] = b'1234567'
        self.assertEqual(list(cache), ['large'])

    def test_cache_accounting_across_mapping_mutations(self):
        cache = AudioCache(max_entries=3, max_bytes=8)
        def check():
            self.assertEqual(cache.current_bytes, sum(map(len, cache.values())))
        cache.update(a=b'12', b=b'345'); check()
        cache['a'] = b'1'; check()
        cache.setdefault('c', b'67'); check()
        cache.setdefault('c', b'ignored'); check()
        cache |= {'d': b'89'}; check()
        cache.pop('c'); check()
        cache.pop('missing', b'default'); check()
        cache.popitem(last=False); check()
        del cache['d']; check()
        with self.assertRaises(KeyError):
            del cache['missing']
        check()
        cache['mutable'] = bytearray(b'12'); check()
        cache.clear(); check()
        self.assertEqual(cache.current_bytes, 0)


class GatewayPerformanceTests(unittest.IsolatedAsyncioTestCase):
    # 复用已验证 HTTP/WS fixture，测试方法独立，避免重复跑整套基类测试。
    asyncTearDown = GatewayConfigurationTests.asyncTearDown
    models = GatewayConfigurationTests.models

    async def asyncSetUp(self, _setup=GatewayConfigurationTests.asyncSetUp):
        self.audio_uploads = []
        self.local_frames = []
        self.queue_index = 2
        self.mutation_started = asyncio.Event()
        self.mutation_gate = None
        self.speech_gate = None
        await _setup(self)
        self.store.update({'local_first': False})

    async def speech(self, request, _normal=GatewayConfigurationTests.speech):
        if self.speech_gate is None:
            return await _normal(self, request)
        await request.json()
        response = web.StreamResponse(headers={'Content-Type': 'audio/mpeg'})
        await response.prepare(request)
        await response.write(b'ID3' + b'a' * 1024)
        await self.speech_gate.wait()
        await response.write(b'b' * 1024)
        await response.write_eof()
        return response

    async def transcription(self, request):
        data = await request.post()
        self.audio_uploads.append(data['file'].file.read())
        self.calls.append(('asr', data['model']))
        return web.json_response({'text': self.cloud_text})

    async def local(self, request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            if message.type == aiohttp.WSMsgType.BINARY:
                self.local_frames.append(message.data)
            elif message.type == aiohttp.WSMsgType.TEXT and message.data == 'Done':
                await socket.send_json({'text': self.local_text, 'is_final': True})
                break
        await socket.close()
        return socket

    async def ma(self, request):
        body = await request.json()
        self.calls.append(('ma', body))
        if body['command'] == 'player_queues/get':
            return web.json_response({'items': 11, 'current_index': self.queue_index})
        if body['command'] == 'player_queues/play_index':
            self.mutation_started.set()
            if self.mutation_gate is not None:
                await self.mutation_gate.wait()
            self.queue_index = body['args']['index']
        if body['command'] == 'music/search':
            return web.json_response({'playlists': self.playlists})
        return web.json_response({})

    async def upload(self, data, format_name=None):
        url = '/asr' + ('?audio_format=' + format_name if format_name else '')
        async with self.client.ws_connect(url) as socket:
            await socket.send_bytes(data)
            await socket.send_str('Done')
            async for message in socket:
                if message.type == aiohttp.WSMsgType.TEXT and message.data.startswith('{'):
                    result = json.loads(message.data)
                    if result.get('is_final'):
                        return result
        self.fail('No final ASR result')

    async def test_pcm16_http_to_wav_and_sherpa(self):
        raw = np.array([-32768, -100, 0, 100, 32767], dtype='<i2').tobytes()
        self.assertEqual((await self.upload(raw, 'pcm_s16le'))['text'], self.cloud_text)
        with wave.open(io.BytesIO(self.audio_uploads[0]), 'rb') as audio:
            self.assertEqual(audio.readframes(5), raw)
        np.testing.assert_array_equal(np.frombuffer(b''.join(self.local_frames), dtype='<f4'),
                                      np.frombuffer(raw, dtype='<i2').astype('<f4') / 32768)

    async def test_legacy_client_still_works(self):
        raw = b'\0' * 6400
        self.assertEqual((await self.upload(raw))['text'], self.cloud_text)
        self.assertEqual(b''.join(self.local_frames), raw)

    async def test_bad_pcm_frame_never_calls_cloud(self):
        result = await self.upload(b'\x01', 'pcm_s16le')
        self.assertFalse(result['retryable'])
        self.assertEqual(result['text'], '')
        self.assertFalse(self.audio_uploads)

    async def test_valid_prefix_then_bad_pcm_frame_never_uploads_partial_audio(self):
        async with self.client.ws_connect('/asr?audio_format=pcm_s16le') as socket:
            await socket.send_bytes(b'\0' * 320)
            await socket.send_bytes(b'\x01')
            await socket.send_str('Done')
            result = None
            async for message in socket:
                if message.type == aiohttp.WSMsgType.TEXT and message.data.startswith('{'):
                    value = json.loads(message.data)
                    if value.get('is_final'):
                        result = value
                        break
        self.assertIsNotNone(result)
        self.assertEqual(result['text'], '')
        self.assertFalse(self.audio_uploads)

    async def test_empty_binary_frame_never_calls_cloud_or_accepts_local_guess(self):
        for format_name in ('pcm_s16le', None):
            result = await self.upload(b'', format_name)
            self.assertEqual(result['text'], '')
            self.assertTrue(result['retryable'])
            self.assertEqual(result['error'], gateway.ASR_RETRY_MESSAGE)
        self.assertFalse(self.audio_uploads)
        self.assertFalse(self.local_frames)

    async def test_audio_limit_uses_format_sample_width(self):
        self.store.update({'max_record_seconds': 3})
        result = await self.upload(b'\0' * (32000 * 3 + 2), 'pcm_s16le')
        self.assertIn('error', result)
        self.assertFalse(self.audio_uploads)

    async def test_audio_limit_across_multiple_pcm_frames_discards_valid_prefix(self):
        self.store.update({'max_record_seconds': 3})
        async with self.client.ws_connect('/asr?audio_format=pcm_s16le') as socket:
            await socket.send_bytes(b'\0' * 64000)
            await socket.send_bytes(b'\0' * 32002)
            await socket.send_str('Done')
            result = None
            async for message in socket:
                if message.type == aiohttp.WSMsgType.TEXT and message.data.startswith('{'):
                    value = json.loads(message.data)
                    if value.get('is_final'):
                        result = value
                        break
        self.assertIsNotNone(result)
        self.assertEqual(result['text'], '')
        self.assertFalse(self.audio_uploads)

    async def test_unknown_format_rejected_before_socket(self):
        response = await self.client.get('/asr?audio_format=opus')
        self.assertEqual(response.status, 400)

    async def control(self, text):
        response = await self.client.post('/music/control', json={'text': text})
        return await response.json()

    def ma_commands(self):
        return [call[1] for call in self.calls if call[0] == 'ma']

    async def test_idle_next_uses_one_queue_request(self):
        self.assertTrue((await self.control('下一首'))['accepted'])
        await self.client.server.app['music_jobs'].join()
        commands = self.ma_commands()
        self.assertEqual(sum(c['command'] == 'player_queues/get' for c in commands), 1)
        self.assertEqual(commands[-1]['args']['index'], 3)

    async def test_inflight_next_invalidates_other_precheck(self):
        self.mutation_gate = asyncio.Event()
        await self.control('下一首')
        await asyncio.wait_for(self.mutation_started.wait(), 1)
        try:
            await self.control('下一首')
        finally:
            self.mutation_gate.set()
        await self.client.server.app['music_jobs'].join()
        targets = [c['args']['index'] for c in self.ma_commands() if c['command'] == 'player_queues/play_index']
        self.assertEqual(targets, [3, 4])

    async def test_eight_parallel_next_requests_never_repeat_a_target(self):
        self.mutation_gate = asyncio.Event()
        self.assertTrue((await self.control('下一首'))['accepted'])
        await asyncio.wait_for(self.mutation_started.wait(), 1)
        try:
            responses = await asyncio.gather(*(self.control('下一首') for _ in range(8)))
        finally:
            self.mutation_gate.set()
        accepted = 1 + sum(bool(response.get('accepted')) for response in responses)
        await asyncio.wait_for(self.client.server.app['music_jobs'].join(), 2)
        targets = [c['args']['index'] for c in self.ma_commands() if c['command'] == 'player_queues/play_index']
        self.assertEqual(targets, list(range(3, 3 + accepted)))
        self.assertEqual(len(set(targets)), len(targets))

    async def test_expired_precheck_fetches_live_queue(self):
        app = self.client.server.app
        precheck = {'queue': {'items': 11, 'current_index': 0}, 'at': time.monotonic() - 1,
                    'generation': 0, 'revision': 0, 'queue_id': 'test-bedroom'}
        await gateway.perform_music(app, 'next', 0, precheck)
        self.assertEqual(self.ma_commands()[-1]['args']['index'], 3)

    async def test_random_query_and_provider_can_change(self):
        self.store.update({'default_random_query': '爵士', 'default_random_providers': []})
        await self.control('随机播放点音乐')
        await self.client.server.app['music_jobs'].join()
        search = next(c['args'] for c in self.ma_commands() if c['command'] == 'music/search')
        self.assertEqual(search['search_query'], '爵士')
        self.assertNotIn('providers', search)

    async def test_invalid_random_settings_preserve_previous(self):
        for patch in ({'default_random_query': ''}, {'default_random_providers': 'apple_music'},
                      {'default_random_providers': ['bad/id']}):
            with self.assertRaises(ValueError):
                self.store.update(patch)
        self.assertEqual(self.store.snapshot()['default_random_query'], '国语流行')

    async def test_old_tts_stream_cannot_repopulate_cache_after_configuration_change(self):
        self.speech_gate = asyncio.Event()
        response = await self.client.get('/tts', params={'text': '隔离缓存检查'})
        try:
            self.assertEqual(response.status, 200)
            changed = await self.client.post('/config', json={'tts_voice': 'changed-review-voice'})
            self.assertEqual(changed.status, 200)
        finally:
            self.speech_gate.set()
        await response.read()
        self.assertEqual(len(gateway.CACHE), 0)
        response = await self.client.get('/tts', params={'text': '隔离缓存检查'})
        await response.read()
        self.assertEqual(len(gateway.CACHE), 1)


# 不让 unittest 将导入的 fixture 基类当成本模块的另一套测试。
del GatewayConfigurationTests
