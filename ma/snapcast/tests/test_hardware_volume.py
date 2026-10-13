"""Hardware-volume tests use only an isolated local HTTP server."""
import importlib.util
from pathlib import Path
import unittest

from aiohttp import ClientResponseError, ClientSession, web

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('r1_hardware_volume',ROOT/'provider/r1_hardware_volume.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
R1HardwareVolume=module.R1HardwareVolume


class HardwareVolumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.level=4;self.last=4;self.fail=False;self.requests=[]
        async def handler(request):
            params=dict(request.query);self.requests.append(params)
            if self.fail:return web.json_response({'error':'unavailable'},status=503)
            operation=params['operation']
            if operation=='set':self.level=round(int(params['percent'])*15/100)
            elif operation=='mute':self.last=self.level;self.level=0
            elif operation=='unmute':self.level=self.last
            return web.json_response({'target':'music','level':self.level,'maximum':15,'percent':round(self.level*100/15)})
        app=web.Application();app.router.add_get('/voice_volume',handler)
        self.runner=web.AppRunner(app);await self.runner.setup()
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        self.url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/voice_volume'
        self.session=ClientSession();self.control=R1HardwareVolume(self.session,self.url)

    async def asyncTearDown(self):
        await self.session.close();await self.runner.cleanup()

    async def test_read_does_not_change_hardware(self):
        self.assertEqual(await self.control.request(),(27,False));self.assertEqual(self.level,4)

    async def test_set_reports_actual_quantized_volume(self):
        self.assertEqual(await self.control.request('set',41),(40,False));self.assertEqual(self.level,6)

    async def test_mute_restores_previous_hardware_step(self):
        await self.control.request('set',40)
        self.assertEqual(await self.control.request('mute'),(0,True))
        self.assertEqual(await self.control.request('unmute'),(40,False))

    async def test_failure_preserves_last_snapshot(self):
        await self.control.request();self.fail=True
        with self.assertRaises(ClientResponseError):await self.control.request()
        self.assertEqual(self.control.percent,27)

    async def test_never_changes_speech_stream(self):
        await self.control.request('set',20)
        self.assertTrue(all(q['target']=='music' for q in self.requests))

    async def test_invalid_request_and_endpoint_are_rejected(self):
        for url in ['http://example.invalid/other','http://user:password@example.invalid/voice_volume','http://example.invalid/voice_volume?target=speech']:
            with self.assertRaises(ValueError):R1HardwareVolume(self.session,url)
        with self.assertRaises(ValueError):await self.control.request('set',101)
        with self.assertRaises(ValueError):await self.control.request('speech')


if __name__=='__main__':unittest.main()
