import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from transport_security import install_transport_security


class HTTPSTest(unittest.TestCase):
    def app(self):
        app = FastAPI()
        @app.get('/')
        def index():
            return {'ok': True}
        with patch.dict('os.environ', {'ALLOWED_HOSTS': 'public.example,localhost,127.0.0.1'}):
            install_transport_security(app)
        return app

    def test_http_redirects_to_https_with_query(self):
        with TestClient(self.app(), base_url='http://public.example', follow_redirects=False) as client:
            response = client.get('/?a=1')
            self.assertEqual(response.status_code, 308)
            self.assertEqual(response.headers['location'], 'https://public.example/?a=1')

    def test_https_allowed_unknown_host_rejected(self):
        with TestClient(self.app(), base_url='https://public.example') as client:
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/', headers={'host': 'attacker.example'}).status_code, 400)

    def test_proxy_headers_only_trusted_from_loopback(self):
        app = ProxyHeadersMiddleware(self.app(), trusted_hosts=['127.0.0.1'])
        for address, expected in [('127.0.0.1', 200), ('192.0.2.10', 308)]:
            with TestClient(app, base_url='http://public.example', client=(address, 4567), follow_redirects=False) as client:
                self.assertEqual(client.get('/', headers={'x-forwarded-proto': 'https'}).status_code, expected)

    def test_http_local_maintenance_requires_local_peer_and_no_proxy(self):
        with TestClient(self.app(), base_url='http://localhost', client=('127.0.0.1', 4567), follow_redirects=False) as client:
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/', headers={'cf-connecting-ip': '192.0.2.10'}).status_code, 308)
        with TestClient(self.app(), base_url='http://localhost', client=('192.0.2.10', 4567), follow_redirects=False) as client:
            self.assertEqual(client.get('/').status_code, 308)

    def test_docker_gateway_can_access_local_http_but_cannot_bypass_public_https(self):
        with patch.dict('os.environ', {'LOCAL_HTTP_PEERS': '172.30.80.1'}):
            app = self.app()
            with TestClient(app, base_url='http://localhost:8000', client=('172.30.80.1', 4567), follow_redirects=False) as client:
                self.assertEqual(client.get('/').status_code, 200)
                for headers in ({'cf-connecting-ip': '192.0.2.10'}, {'x-forwarded-for': '192.0.2.10'}, {'x-forwarded-proto': 'http'}):
                    self.assertEqual(client.get('/', headers=headers).status_code, 308)
                self.assertEqual(client.get('http://public.example/').status_code, 308)
            with TestClient(app, base_url='http://localhost:8000', client=('172.30.80.2', 4567), follow_redirects=False) as client:
                self.assertEqual(client.get('/').status_code, 308)
