"""验证配置热更新、真实 HTTP/WS 路由、密钥保留与失败时禁止采用猜测文字。"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1] / "gateway"
sys.path.insert(0, str(ROOT))
from gateway_config import GatewayConfig

spec = importlib.util.spec_from_file_location("testable_voice_gateway", ROOT / "voice_gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class GatewayConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = GatewayConfig(self.directory.name)
        gateway.SETTINGS = self.store
        gateway.CACHE.clear()
        self.calls = []
        self.local_text = "暂停"
        self.cloud_text = "你好"
        self.playlists = [{"uri": "apple_music://playlist/test-pop"}]
        upstream = web.Application()
        upstream.router.add_post("/v1/audio/transcriptions", self.transcription)
        upstream.router.add_post("/v1/audio/speech", self.speech)
        upstream.router.add_get("/v1/models", self.models)
        upstream.router.add_get("/local", self.local)
        upstream.router.add_post("/api", self.ma)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        self.store.update({
            "asr_base_url": str(self.upstream.make_url("/v1")).rstrip("/"),
            "asr_model": "custom/vendor-ASR-v2",
            "asr_api_key": "unit-test-key",
            "tts_base_url": str(self.upstream.make_url("/v1")).rstrip("/"),
            "tts_model": "custom/tts-v2", "tts_voice": "custom-voice",
            "tts_api_key": "unit-test-tts-key",
            "local_asr_url": str(self.upstream.make_url("/local")),
            "ma_url": str(self.upstream.make_url("/")).rstrip("/"),
            "ma_queue_id": "test-bedroom", "ma_token": "unit-test-ma-key",
            "local_first": True,
        })
        application = web.Application(middlewares=[gateway.local_only])
        application.on_startup.append(gateway.startup)
        application.on_cleanup.append(gateway.cleanup)
        application.router.add_get("/config", gateway.gateway_config)
        application.router.add_post("/config", gateway.gateway_config)
        application.router.add_get("/asr", gateway.recognize)
        application.router.add_get("/tts", gateway.tts)
        application.router.add_get("/models", gateway.asr_models)
        application.router.add_post("/music/control", gateway.music_control)
        application.router.add_post("/commands/plan", gateway.command_plan)
        self.client = TestClient(TestServer(application))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()
        self.directory.cleanup()

    async def transcription(self, request):
        data = await request.post()
        model = data["model"]
        self.assertTrue(data["file"].file.read().startswith(b"RIFF"))
        self.calls.append(("asr", model, request.headers.get("Authorization")))
        if model.startswith("custom/failing"):
            return web.json_response({"error": "unavailable"}, status=503)
        return web.json_response({"text": self.cloud_text})

    async def speech(self, request):
        body = await request.json()
        self.calls.append(("tts", body, request.headers.get("Authorization")))
        return web.Response(body=b"ID3" + b"synthetic-test-audio" * 100, content_type="audio/mpeg")

    async def models(self, request):
        return web.json_response({"data": [{"id": "custom/vendor-ASR-v2"}, {"id": "another/ASR"}]})

    async def local(self, request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            if message.type == aiohttp.WSMsgType.TEXT and message.data == "Done":
                await socket.send_json({"text": self.local_text, "is_final": True})
                await socket.send_str("Done!")
                break
        await socket.close()
        return socket

    async def ma(self, request):
        body = await request.json()
        self.calls.append(("ma", body, request.headers.get("Authorization")))
        if body["command"] == "player_queues/get":
            return web.json_response({"items": 11, "current_index": 2})
        if body["command"] == "music/search":
            return web.json_response({"playlists": self.playlists})
        return web.json_response({})

    async def recognize(self,path="/asr"):
        async with self.client.ws_connect(path) as socket:
            await socket.send_bytes(b"\0" * 6400)
            await socket.send_str("Done")
            async for message in socket:
                if message.type == aiohttp.WSMsgType.TEXT and message.data.startswith("{"):
                    result = json.loads(message.data)
                    if result.get("is_final"):
                        return result
        self.fail("没有返回最终识别结果")

    async def test_noise_and_followup_are_silent_without_executing(self):
        self.store.update({'local_first':False})
        for text,path in [('嗯','/asr'),('啊嗯','/asr'),('歌词里的故事','/asr?followup=1')]:
            self.cloud_text=text
            result=await self.recognize(path)
            self.assertTrue(result['ignored'])
            self.assertEqual(result['text'],'')
        self.assertFalse(any(c[0]=='ma' for c in self.calls))

    async def test_compound_plan_in_final_frame_and_preview_have_no_actions(self):
        self.store.update({'local_first':False})
        self.cloud_text='暂停然后把音量调到三十'
        result=await self.recognize()
        self.assertEqual([s['text'] for s in result['command_plan']['steps']],['暂停','把音量调到30'])
        response=await self.client.post('/commands/plan',json={'text':self.cloud_text})
        self.assertEqual((await response.json())['steps'],result['command_plan']['steps'])
        self.assertFalse(any(c[0]=='ma' for c in self.calls))
        for patch in ({'max_compound_steps':True},{'max_compound_steps':7},{'suppress_noise_only':'yes'}):
            response=await self.client.post('/config',json=patch)
            self.assertEqual(response.status,400)

    async def test_secrets_not_returned_and_blank_preserves(self):
        response = await self.client.get("/config")
        body = await response.json()
        self.assertNotIn("asr_api_key", body)
        self.assertTrue(body["asr_api_key_configured"])
        self.assertNotIn("unit-test-key", json.dumps(body))
        await self.client.post("/config", json={"asr_api_key": "", "asr_model": "new/ASR"})
        self.assertEqual(self.store.snapshot()["asr_api_key"], "unit-test-key")
        reloaded = GatewayConfig(self.directory.name)
        self.assertEqual(reloaded.snapshot()["asr_model"], "new/ASR")
        await self.client.post("/config", json={"clear_asr_api_key": True})
        self.assertEqual(self.store.snapshot()["asr_api_key"], "")

    async def test_arbitrary_model_and_hot_update(self):
        self.store.update({"local_first": False})
        result = await self.recognize()
        self.assertEqual(result["backend"], "cloud:custom/vendor-ASR-v2")
        self.assertEqual(self.calls[-1][1], "custom/vendor-ASR-v2")
        await self.client.post("/config", json={"asr_model": "new/model-without-code-change"})
        await self.recognize()
        self.assertEqual(self.calls[-1][1], "new/model-without-code-change")

    async def test_explicit_local_short_command_skips_cloud(self):
        result = await self.recognize()
        self.assertEqual(result["backend"], "local-fast")
        self.assertEqual(result["text"], "暂停")
        self.assertEqual(self.calls, [])

    async def test_uncertain_local_failure_requires_retry(self):
        self.local_text = "放手歌"
        self.store.update({"asr_model": "custom/failing", "asr_fallback_model": "custom/failing-backup"})
        result = await self.recognize()
        self.assertEqual(result["text"], "")
        self.assertIn("error", result)
        self.assertFalse(result["retryable"])
        self.assertEqual([c[1] for c in self.calls], ["custom/failing", "custom/failing-backup"])

    async def test_configured_fallback_is_used(self):
        self.local_text = "放手歌"
        self.store.update({"asr_model": "custom/failing", "asr_fallback_model": "custom/backup"})
        result = await self.recognize()
        self.assertEqual(result["backend"], "cloud:custom/backup")
        self.assertEqual([c[1] for c in self.calls], ["custom/failing", "custom/backup"])

    async def test_available_backup_empty_text_can_retry_despite_primary_service_error(self):
        self.store.update({"local_first": False, "asr_model": "custom/failing",
                           "asr_fallback_model": "custom/backup"})
        self.cloud_text = ""
        result = await self.recognize()
        self.assertEqual(result["text"], "")
        self.assertTrue(result["retryable"])

    async def test_empty_or_incomplete_cloud_is_never_executed(self):
        self.local_text = "放手歌"
        for text in ["", "打开我的"]:
            self.cloud_text = text
            result = await self.recognize()
            self.assertEqual(result["text"], "")
            self.assertIn("error", result)
            self.assertTrue(result["retryable"])

    async def test_invalid_update_does_not_modify_saved_config(self):
        before = self.store.path.read_bytes()
        for patch in [{"asr_timeout_seconds": 0}, {"asr_timeout_seconds": True},
                      {"asr_base_url": "https://user:password@example.com/v1"},
                      {"asr_model": "invalid model"}, {"unknown_field": 1}]:
            response = await self.client.post("/config", json=patch)
            self.assertEqual(response.status, 400)
            self.assertEqual(self.store.path.read_bytes(), before)

    async def test_foreign_origin_cannot_update(self):
        response = await self.client.post("/config", json={"asr_model": "changed"},
                                          headers={"Origin": "https://unrelated.example"})
        self.assertEqual(response.status, 403)

    async def test_tts_uses_configured_model_voice_and_separate_key(self):
        response = await self.client.get("/tts", params={"text": "你好"})
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.read()).startswith(b"ID3"))
        kind, body, authorization = self.calls[-1]
        self.assertEqual(body["model"], "custom/tts-v2")
        self.assertEqual(body["voice"], "custom-voice")
        self.assertEqual(authorization, "Bearer unit-test-tts-key")

    async def test_models_and_ma_connection_are_configurable(self):
        response = await self.client.get("/models")
        self.assertIn("another/ASR", (await response.json())["models"])
        response = await self.client.post("/music/control", json={"text": "暂停"})
        self.assertTrue((await response.json())["accepted"])
        await self.client.server.app["music_jobs"].join()
        commands = [c for c in self.calls if c[0] == "ma"]
        self.assertTrue(commands)
        self.assertTrue(all(c[1]["args"].get("queue_id") == "test-bedroom" for c in commands))
        self.assertTrue(all(c[2] == "Bearer unit-test-ma-key" for c in commands))

    async def test_random_music_selects_playlist_and_shuffles_instead_of_resuming(self):
        response = await self.client.post("/music/control", json={"text": "随机播放点音乐"})
        result = await response.json()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["operation"], "random")
        await self.client.server.app["music_jobs"].join()
        commands = [c[1] for c in self.calls if c[0] == "ma"]
        self.assertNotIn("players/cmd/play", [c["command"] for c in commands])
        playback = next(c["args"] for c in commands if c["command"] == "player_queues/play_media")
        self.assertEqual(playback, {"queue_id": "test-bedroom", "media": self.playlists[0]["uri"],
                                    "option": "replace", "shuffle": True})
        repeat = next(c["args"] for c in commands if c["command"] == "player_queues/repeat")
        self.assertEqual(repeat["repeat_mode"], "off")

    async def test_random_music_search_failure_does_not_replace_current_queue(self):
        self.playlists = []
        with self.assertRaises(RuntimeError):
            await gateway.perform_music(self.client.server.app, "random")
        self.assertEqual([c[1]["command"] for c in self.calls], ["music/search"])

    async def test_music_explanations_negations_and_named_queries_are_not_generic_random(self):
        for text in ["随机播放是什么意思", "不要随机播放音乐", "随机播放晴天", "随机播放流行歌曲",
                     "解释一下暂停", "如果我说暂停会怎样"]:
            response = await self.client.post("/music/control", json={"text": text, "dry_run": True})
            self.assertFalse((await response.json())["handled"], text)
        self.assertEqual(self.calls, [])

    async def test_bare_play_is_complete_but_missing_power_or_song_arguments_are_not(self):
        self.store.update({"local_first": False})
        self.cloud_text = "播放"
        result = await self.recognize()
        self.assertEqual(result["text"], "播放")
        self.assertNotIn("error", result)
        for text in ["打开", "放", "播放周杰伦的"]:
            self.assertTrue(gateway.is_incomplete_transcription(text), text)

    async def test_music_request_wrappers_reuse_core_grammar_without_cloud_or_execution(self):
        for text, operation in [("随机播放点音乐", "random"), ("请帮我随机播放点音乐好吗", "random"),
                                ("麻烦帮我随便放点歌听听", "random"), ("能不能帮我播放吧", "resume"),
                                ("请给我暂停一下可以吗", "pause"), ("可以帮我切换一下首好吗", "next")]:
            response = await self.client.post("/music/control", json={"text": text, "dry_run": True})
            result = await response.json()
            self.assertEqual(result.get("operation"), operation, text)
            self.assertFalse(result["executed"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
