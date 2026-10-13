"""Real localhost HTTP/WS tests; no production settings or audio devices."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

ROOT=Path(__file__).resolve().parents[1]
CODE=ROOT if (ROOT/'voice_gateway.py').is_file() else ROOT/'gateway'
sys.path.insert(0,str(CODE))
spec=importlib.util.spec_from_file_location('log_test_gateway',CODE/'voice_gateway.py')
gateway=importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)


class EventLogHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        gateway.SETTINGS=gateway.GatewayConfig(self.temp.name)
        gateway.CACHE.clear()
        self.cloud_text='hello';self.cloud_status=200;self.tts_status=200
        self.search_started=asyncio.Event();self.search_delay=0
        upstream=web.Application()
        upstream.router.add_post('/v1/audio/transcriptions',self.asr)
        upstream.router.add_post('/v1/audio/speech',self.tts)
        upstream.router.add_get('/local',self.local)
        upstream.router.add_post('/api',self.ma)
        self.upstream=TestServer(upstream);await self.upstream.start_server()
        base=str(self.upstream.make_url('/')).rstrip('/')
        gateway.SETTINGS.update({'asr_base_url':base+'/v1','asr_model':'custom/asr',
            'asr_fallback_model':'','asr_api_key':'UNIT_ASR_SECRET','local_first':False,
            'local_asr_url':base+'/local','tts_base_url':base+'/v1','tts_model':'custom/tts',
            'tts_api_key':'UNIT_TTS_SECRET','ma_url':base,'ma_token':'UNIT_MA_SECRET',
            'ma_queue_id':'test_queue'})
        app=web.Application(middlewares=[gateway.local_only])
        app['event_log_dir']=self.temp.name
        app.on_startup.append(gateway.startup);app.on_cleanup.append(gateway.cleanup)
        app.router.add_get('/logs',gateway.event_history)
        for path in ('/logs/config','/logs/clear','/logs/events'):
            app.router.add_post(path,gateway.event_history)
        app.router.add_get('/logs/config',gateway.event_history)
        app.router.add_get('/asr',gateway.recognize);app.router.add_get('/tts',gateway.tts)
        app.router.add_post('/music/control',gateway.music_control)
        self.client=TestClient(TestServer(app));await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close();await self.upstream.close();self.temp.cleanup()

    async def asr(self,request):
        await request.post()
        return web.json_response({'text':self.cloud_text},status=self.cloud_status)

    async def tts(self,request):
        await request.json()
        return web.Response(body=b'ID3synthetic-fixture',status=self.tts_status)

    async def ma(self,request):
        data=await request.json()
        if data['command']=='music/search':
            self.search_started.set();await asyncio.sleep(self.search_delay)
            return web.json_response({'playlists':[{'uri':'apple_music://playlist/synthetic'}]})
        return web.json_response({})

    async def local(self,request):
        ws=web.WebSocketResponse();await ws.prepare(request)
        async for message in ws:
            if message.type==aiohttp.WSMsgType.TEXT and message.data=='Done':
                await ws.send_json({'text':'local guess','is_final':True});break
        return ws

    async def enable(self):
        response=await self.client.post('/logs/config',json={'enabled':True,'level':'DEBUG'})
        self.assertEqual(response.status,200)
        return await response.json()

    async def entries(self):
        response=await self.client.get('/logs?limit=100')
        self.assertEqual(response.status,200)
        raw=await response.read();self.assertLessEqual(len(raw),262144)
        return json.loads(raw)['entries']

    async def recognize(self):
        async with self.client.ws_connect('/asr?turn=42') as ws:
            await ws.send_bytes(b'\0'*6400);await ws.send_str('Done')
            async for msg in ws:
                if msg.type==aiohttp.WSMsgType.TEXT and msg.data.startswith('{'):
                    result=json.loads(msg.data)
                    if result.get('is_final'):return result
        self.fail('No final ASR result')

    async def test_default_disabled_device_ingestion_config_clear_and_stale_generation(self):
        response=await self.client.get('/logs/config');state=await response.json()
        self.assertFalse(state['enabled']);self.assertEqual(state['level'],'INFO')
        state=await self.enable()
        event={'stage':'AI','source':'gateway','turn':8,'fields':{'response':'ok','api_key':'secret'}}
        response=await self.client.post('/logs/events',json={'generation':state['generation'],'events':[event]})
        self.assertEqual((await response.json())['accepted'],1)
        self.assertEqual((await self.entries())[0]['source'],'device')
        response=await self.client.post('/logs/clear',json={});new=await response.json()
        self.assertGreater(new['generation'],state['generation'])
        response=await self.client.post('/logs/events',json={'generation':state['generation'],'events':[event]})
        self.assertTrue((await response.json())['stale']);self.assertEqual(await self.entries(),[])

    async def test_schema_limits_and_request_body_budget(self):
        state=await self.enable()
        for body in ({'events':[]},{'generation':True,'events':[]},
                     {'generation':state['generation'],'events':[{'stage':'ASR'}]*33},
                     {'generation':state['generation'],'events':[{'stage':[]}]},
                     {'generation':state['generation'],'events':[{'stage':'ASR','fields':{'executed':1}}]}):
            response=await self.client.post('/logs/events',json=body);self.assertEqual(response.status,400)
        for query in ('0','101','abc'):
            self.assertEqual((await self.client.get('/logs?limit='+query)).status,400)
        self.assertEqual((await self.client.post('/logs/config',json={'level':['INFO']})).status,400)
        self.assertEqual((await self.client.post('/logs/events',data=b' '*262145)).status,413)
        async def oversized():
            for _ in range(33):yield b' '*8192
        self.assertEqual((await self.client.post('/logs/events',data=oversized())).status,413)

    async def test_browser_same_origin_and_local_allowlist(self):
        for path in ('/logs/config','/logs/clear','/logs/events'):
            response=await self.client.post(path,json={},headers={'Origin':'https://foreign.invalid'})
            self.assertEqual(response.status,403)
        origin=str(self.client.make_url('/')).rstrip('/')
        self.assertEqual((await self.client.post('/logs/config',json={'enabled':True},headers={'Origin':origin})).status,200)
        self.assertEqual((await self.client.post('/logs/config',json={},headers={'Origin':origin.replace('http:','https:')})).status,403)
        config=gateway.SETTINGS.snapshot();config['allowed_clients']=['192.0.2.5']
        gateway.SETTINGS=SimpleNamespace(snapshot=lambda:config)
        self.assertEqual((await self.client.get('/logs')).status,403)

    async def test_own_asr_ma_tts_events_safe_fields_and_backend_completion(self):
        await self.enable()
        self.assertEqual((await self.recognize())['text'],'hello')
        response=await self.client.post('/music/control',json={'text':'暂停','turn':42})
        self.assertTrue((await response.json())['accepted'])
        await self.client.server.app['music_jobs'].join()
        response=await self.client.get('/tts?text=hello&turn=42');await response.read()
        entries=await self.entries()
        self.assertTrue(any(e['stage']=='ASR' and e['fields'].get('text')=='hello' and e['turn']==42 for e in entries))
        for stage,status in [('MA','accepted'),('MA','completed'),('TTS','first_audio')]:
            self.assertTrue(any(e['stage']==stage and e['fields'].get('status')==status for e in entries))
        raw=json.dumps(entries)
        for secret in ('UNIT_ASR_SECRET','UNIT_TTS_SECRET','UNIT_MA_SECRET','Authorization','http://'):
            self.assertNotIn(secret,raw)

    async def test_cloud_service_failure_and_empty_text_use_distinct_controlled_messages(self):
        await self.enable();self.cloud_status=503
        result=await self.recognize()
        self.assertFalse(result['retryable']);self.assertEqual(result['error'],gateway.ASR_UNAVAILABLE_MESSAGE)
        entries=await self.entries()
        self.assertTrue(any(e['fields'].get('error_kind')=='http_status' and e['fields'].get('model')=='custom/asr' for e in entries))
        self.cloud_status=200;self.cloud_text=''
        result=await self.recognize()
        self.assertTrue(result['retryable']);self.assertEqual(result['error'],gateway.ASR_RETRY_MESSAGE)

    async def test_tts_failure_is_structured_and_preserves_bad_gateway(self):
        await self.enable();self.tts_status=503
        self.assertEqual((await self.client.get('/tts?text=failed')).status,502)
        self.assertTrue(any(e['stage']=='TTS' and e['fields'].get('status')=='failed' for e in await self.entries()))

    async def test_slow_music_search_preemption_is_logged_without_old_play(self):
        await self.enable();self.search_delay=.3
        response=await self.client.post('/music/control',json={'text':'随机播放点音乐','turn':41})
        self.assertTrue((await response.json())['accepted'])
        await asyncio.wait_for(self.search_started.wait(),1)
        response=await self.client.post('/music/control',json={'text':'暂停','turn':42})
        self.assertTrue((await response.json())['accepted'])
        await asyncio.wait_for(self.client.server.app['music_jobs'].join(),.2)
        entries=await self.entries()
        self.assertTrue(any(e['stage']=='MA' and e['turn']==41 and e['fields'].get('status')=='preempted' for e in entries))
        self.assertFalse(any(e['stage']=='MA' and e['turn']==41 and e['fields'].get('status')=='completed' for e in entries))
        self.assertTrue(any(e['stage']=='MA' and e['turn']==42 and e['fields'].get('status')=='completed' for e in entries))


if __name__=='__main__':unittest.main(verbosity=2)
