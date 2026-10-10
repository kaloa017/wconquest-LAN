"""Exercise the production proxy-header chain without a server or game save."""
import os,unittest
from unittest.mock import patch
from flask import Flask,request,jsonify
from waitress.proxy_headers import proxy_headers_middleware
import runtime,security

class ProxyStartupTests(unittest.TestCase):
    def client(self,clear=False):
        application=Flask(__name__);application.secret_key='isolated-proxy-test-key'
        security.install(application)
        @application.route('/api/check',methods=['GET','POST'])
        def check():
            return jsonify(scheme=request.scheme,host=request.host,ip=request.remote_addr,
                           forwarded=request.headers.get('X-Forwarded-Proto'))
        with patch.dict(os.environ,{'TRUSTED_PROXIES':'127.0.0.1/32,::1/128','PROXY_HOPS':'1'}):
            application.wsgi_app=proxy_headers_middleware(runtime.TrustedProxy(application.wsgi_app),clear_untrusted=clear)
        return application.test_client()

    def test_trusted_cloudflare_https_login_origin_survives_waitress(self):
        for peer in ('127.0.0.1','::1'):
            with self.subTest(peer=peer),patch.dict(os.environ,{'PROXY_MODE':'cloudflare'}):
                response=self.client().post('/api/check',base_url='http://game.trycloudflare.com',
                    headers={'Origin':'https://game.trycloudflare.com','X-Forwarded-Proto':'https','CF-Connecting-IP':'203.0.113.4'},
                    environ_overrides={'REMOTE_ADDR':peer},json={})
                self.assertEqual(response.status_code,200,response.json)
                self.assertEqual(response.json['scheme'],'https');self.assertEqual(response.json['ip'],'203.0.113.4')

    def test_waitress_default_stripping_reproduces_reported_error(self):
        response=self.client(clear=True).post('/api/check',base_url='http://game.trycloudflare.com',
            headers={'Origin':'https://game.trycloudflare.com','X-Forwarded-Proto':'https'},json={})
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.json['error'],'Request origin does not match this game')

    def test_untrusted_forwarding_is_stripped_and_foreign_origins_rejected(self):
        client=self.client();headers={'X-Forwarded-Proto':'https','X-Forwarded-For':'203.0.113.4'}
        response=client.get('/api/check',headers=headers,environ_overrides={'REMOTE_ADDR':'198.51.100.2'})
        self.assertEqual(response.json['scheme'],'http');self.assertEqual(response.json['ip'],'198.51.100.2')
        self.assertIsNone(response.json['forwarded'])
        response=client.post('/api/check',headers={**headers,'Origin':'https://localhost'},
                             environ_overrides={'REMOTE_ADDR':'198.51.100.2'},json={})
        self.assertEqual(response.status_code,403)
        self.assertEqual(client.post('/api/check',headers={'Origin':'https://evil.example'},json={}).status_code,403)

    def test_production_entrypoint_preserves_headers_for_application_trust(self):
        with patch('waitress.serve') as serve,patch.dict(os.environ,{'HOST':'127.0.0.1','PORT':'5055'}):
            application=Flask(__name__);runtime.serve_game(application)
        serve.assert_called_once_with(application,host='127.0.0.1',port=5055,threads=4,clear_untrusted_proxy_headers=False)

if __name__=='__main__':unittest.main()
