"""验证真实连接的 IP／CIDR 边界、WebSocket 及跨站防护。"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1] / 'gateway'
sys.path.insert(0, str(ROOT))
from gateway_config import GatewayConfig, client_allowed

spec = importlib.util.spec_from_file_location('network_test_gateway', ROOT / 'voice_gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class NetworkRulesTests(unittest.TestCase):
    def test_home_subnet_allows_changing_hosts_but_not_other_subnets(self):
        clients = ['127.0.0.1', '192.168.1.0/24']
        for peer in ('192.168.1.2', '192.168.1.3', '192.168.1.88', '192.168.1.254', '127.0.0.1'):
            self.assertTrue(client_allowed(peer, clients), peer)
        for peer in ('192.168.2.2', '192.168.10.2', '198.51.100.2', '127.0.0.2', None, '', 'bad'):
            self.assertFalse(client_allowed(peer, clients), peer)

    def test_exact_addresses_ipv6_and_mapped_ipv4(self):
        self.assertTrue(client_allowed('192.168.1.2', ['192.168.1.2']))
        self.assertFalse(client_allowed('192.168.1.3', ['192.168.1.2']))
        self.assertTrue(client_allowed('::ffff:192.168.1.2', ['192.168.1.0/24']))
        self.assertFalse(client_allowed('::ffff:192.168.2.2', ['192.168.1.0/24']))
        self.assertTrue(client_allowed('fd00:1::2', ['fd00:1::/64']))
        self.assertFalse(client_allowed('fd00:2::2', ['fd00:1::/64']))
        self.assertTrue(client_allowed('::1', ['::1']))
        self.assertFalse(client_allowed('192.168.1.2', ['fd00:1::/64']))

    def test_invalid_entries_do_not_grant_access(self):
        for entry in ('*', '192.168.1.*', '192.168.1.0/33', 'localhost', 'bad'):
            self.assertFalse(client_allowed('192.168.1.2', [entry]))

    def test_config_persists_cidr_and_rejects_invalid_updates_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = GatewayConfig(directory)
            expected = ['127.0.0.1', '192.168.1.0/24']
            settings.update({'allowed_clients': expected})
            self.assertEqual(GatewayConfig(directory).snapshot()['allowed_clients'], expected)
            before = settings.path.read_bytes()
            for invalid in ('192.168.1.*', '0.0.0.0/33', '*', 'localhost'):
                with self.assertRaises(ValueError):
                    settings.update({'allowed_clients': ['127.0.0.1', invalid]})
                self.assertEqual(settings.path.read_bytes(), before)
            with self.assertRaises(ValueError):
                settings.update({'allowed_clients': ['192.168.1.0/24']})


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 使用测试 socket 的真实 127.0.0.1 连接，只给网段以验证 CIDR 路径。
        self.clients = ['127.0.0.0/24']
        gateway.SETTINGS = SimpleNamespace(snapshot=lambda: {'allowed_clients': self.clients})
        async def handler(request):
            return web.json_response({'ready': True})
        async def websocket(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            await socket.send_str('ready')
            await socket.close()
            return socket
        application = web.Application(middlewares=[gateway.local_only])
        application.router.add_get('/health', handler)
        application.router.add_post('/config', handler)
        application.router.add_get('/asr', websocket)
        self.client = TestClient(TestServer(application))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_http_and_websocket_accept_a_peer_inside_cidr(self):
        self.assertEqual((await self.client.get('/health')).status, 200)
        async with self.client.ws_connect('/asr') as socket:
            self.assertEqual(await socket.receive_str(), 'ready')

    async def test_allowlist_hot_update_and_spoofed_proxy_headers(self):
        self.assertEqual((await self.client.get('/health')).status, 200)
        self.clients = ['192.168.1.0/24']
        response = await self.client.get('/health', headers={
            'X-Forwarded-For': '192.168.1.2', 'Forwarded': 'for=192.168.1.2'})
        self.assertEqual(response.status, 403)
        self.clients = ['127.0.0.0/24']
        self.assertEqual((await self.client.get('/health')).status, 200)

    async def test_foreign_origin_still_cannot_write_from_allowed_subnet(self):
        response = await self.client.post('/config', json={}, headers={'Origin': 'https://foreign.example'})
        self.assertEqual(response.status, 403)
        origin = str(self.client.make_url('/')).rstrip('/')
        response = await self.client.post('/config', json={}, headers={'Origin': origin})
        self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
