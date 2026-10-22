"""Resend integration checks: mocked transport, disposable save, no real email."""
import base64
import hashlib
import hmac
import io
import json
import time
import urllib.error
import uuid
from unittest.mock import patch,Mock
import test_communications as fixture
from test_upgrade import app
import email_inbound as inbound
import email_verification as mail


class ResendTests(fixture.CommunicationTests):
    # Inherit the existing password/code, abuse and legacy provider checks.
    def resend(self):
        env=patch.dict('os.environ',dict(EMAIL_PROVIDER='resend',RESEND_API_KEY='re_disposable',EMAIL_FROM='support@example.org',EMAIL_REPLY_TO='support@example.org',EMAIL_INBOUND_ADDRESS='support@example.org',EMAIL_FORWARD_TO='private@example.net',RESEND_WEBHOOK_SECRET='whsec_'+base64.b64encode(b'disposable-webhook-key').decode()))
        env.start();self.addCleanup(env.stop)

    def event(self,recipient='support@example.org',stamp=None,eid=None):
        stamp=str(stamp or int(time.time()));raw=json.dumps(dict(type='email.received',data=dict(email_id=eid or str(uuid.uuid4()),to=[recipient]))).encode()
        signature=base64.b64encode(hmac.new(b'disposable-webhook-key',b'msg_test.'+stamp.encode()+b'.'+raw,hashlib.sha256).digest()).decode()
        return raw,{'svix-id':'msg_test','svix-timestamp':stamp,'svix-signature':'v1,'+signature}

    def test_resend_delivery_sender_reply_to_idempotency_and_private_configuration(self):
        self.resend();self.enable();self.signin()
        def transport(req,timeout):
            self.assertEqual(req.full_url,'https://api.resend.com/emails')
            self.assertEqual(req.get_header('Authorization'),'Bearer re_disposable')
            message=json.loads(req.data)
            self.assertEqual(message['from'],'World Conquest <support@example.org>')
            self.assertEqual(message['reply_to'],'support@example.org')
            self.assertEqual(message['to'],['friend@example.org'])
            self.assertTrue(req.get_header('Idempotency-key'))
            conn=app.get_db();conn.execute('BEGIN IMMEDIATE');conn.rollback();conn.close()
            response=Mock();response.__enter__=Mock(return_value=io.BytesIO(b'{"id":"resend-test"}'));response.__exit__=Mock(return_value=False);return response
        with patch('email_verification.urllib.request.urlopen',side_effect=transport):mail.deliver_once()
        self.assertEqual(self.conn.execute('SELECT provider_id,status,payload FROM email_outbox').fetchone()[:],('resend-test','accepted',''))
        data=self.admin_client.get('/api/admin/email').json
        self.assertEqual(data['daily_max'],90);self.assertTrue(data['inbound']['configured'])
        for secret in ('re_disposable','private@example.net','disposable-webhook-key'):self.assertNotIn(secret,json.dumps(data))

    def test_daily_and_monthly_quota_fallback_but_not_rate_limit(self):
        self.resend();self.enable()
        for name in ('rate_limit_exceeded','daily_quota_exceeded','monthly_quota_exceeded'):
            self.conn.execute('DELETE FROM email_challenges');self.conn.execute('DELETE FROM email_outbox');app.set_setting(self.conn,'email_provider_pause','{}');self.conn.commit();self.signin()
            error=urllib.error.HTTPError('https://api.resend.com',429,'quota',{},io.BytesIO(json.dumps(dict(name=name)).encode()))
            with patch('email_verification.urllib.request.urlopen',side_effect=error):mail.deliver_once()
            reply=self.signin().json
            self.assertEqual(bool(reply.get('email_fallback')),name!='rate_limit_exceeded',reply)
        self.conn.execute('DELETE FROM email_budget');app.set_setting(self.conn,'email_provider_pause','{}')
        self.conn.execute('INSERT INTO email_budget VALUES(?,2700)',(mail.day()[:7]+'-01',));self.conn.commit()
        self.assertTrue(self.signin().json['email_fallback'])

    def test_signed_webhook_deduplicates_and_rejects_forgery_replay_and_other_aliases(self):
        self.resend();guest=app.app.test_client();raw,headers=self.event()
        self.assertEqual(guest.post('/integrations/resend/inbound',data=raw).status_code,400)
        self.assertEqual(guest.post('/integrations/resend/inbound',data=raw+b' ',headers=headers).status_code,400)
        stale,stale_headers=self.event(stamp=int(time.time())-600)
        self.assertEqual(guest.post('/integrations/resend/inbound',data=stale,headers=stale_headers).status_code,400)
        for _ in range(2):self.assertEqual(guest.post('/integrations/resend/inbound',data=raw,headers=headers).status_code,200)
        other,other_headers=self.event(recipient='other@example.org');guest.post('/integrations/resend/inbound',data=other,headers=other_headers)
        self.assertEqual(len(inbound.load(self.conn)),1)
        self.assertEqual(guest.get('/integrations/resend/inbound').status_code,405)
        self.assertEqual(guest.post('/api/admin/email',json={}).status_code,401)

    def test_forwarding_preserves_body_attachments_reply_address_and_only_private_destination(self):
        self.resend();guest=app.app.test_client();raw,headers=self.event();guest.post('/integrations/resend/inbound',data=raw,headers=headers)
        incoming=dict(to=['support@example.org'],**{'from':'Friend <friend@example.net>'},subject='Help',text='Support text',html='<p>Support text</p>')
        files=dict(data=[dict(filename='screen.png',size=100,download_url='https://attachments.resend.com/example',content_id='screen')])
        def transport(req,timeout):
            message=json.loads(req.data)
            self.assertEqual(message['to'],['private@example.net']);self.assertEqual(message['reply_to'],'friend@example.net')
            self.assertEqual(message['attachments'][0]['path'],'https://attachments.resend.com/example')
            self.assertIn('Support text',message['html']);self.assertEqual(message['subject'],'[Support] Help')
            conn=app.get_db();conn.execute('BEGIN IMMEDIATE');conn.rollback();conn.close()
            response=Mock();response.__enter__=Mock(return_value=io.BytesIO(b'{"id":"forwarded-test"}'));response.__exit__=Mock(return_value=False);return response
        with patch('email_inbound.api_get',side_effect=[incoming,files]),patch('email_verification.urllib.request.urlopen',side_effect=transport) as send:
            inbound.deliver_once();inbound.deliver_once();self.assertEqual(send.call_count,1)
        self.assertEqual(inbound.load(self.conn)[0]['status'],'forwarded')
        self.assertNotIn('Support text',json.dumps(inbound.load(self.conn)))

    def test_forwarding_loop_and_daily_bound_do_not_send(self):
        self.resend();guest=app.app.test_client();raw,headers=self.event();guest.post('/integrations/resend/inbound',data=raw,headers=headers)
        incoming=dict(to=['support@example.org'],**{'from':'support@example.org'})
        with patch('email_inbound.api_get',return_value=incoming),patch('email_verification.urllib.request.urlopen') as send:
            inbound.deliver_once();send.assert_not_called()
        self.assertEqual(inbound.load(self.conn)[0]['status'],'failed')
        rows=inbound.load(self.conn);now=int(time.time())
        for _ in range(10):rows.append(dict(id=str(uuid.uuid4()),created=now,status='forwarded',attempts=1,error='',reserved=True,reserved_day=now//86400,next_attempt=0))
        rows.append(dict(id=str(uuid.uuid4()),created=now,status='queued',attempts=0,error='',reserved=False,next_attempt=0));inbound.save(self.conn,rows);self.conn.commit()
        with patch('email_inbound.api_get') as fetch:inbound.deliver_once();fetch.assert_not_called()

    def test_forward_retry_reuses_identical_encrypted_request(self):
        self.resend();guest=app.app.test_client();raw,headers=self.event();guest.post('/integrations/resend/inbound',data=raw,headers=headers)
        incoming=dict(to=['support@example.org'],**{'from':'friend@example.net'},subject='Retry',text='Private body')
        requests=[]
        def transport(req,timeout):
            requests.append(req.data)
            if len(requests)==1:raise urllib.error.URLError('interrupted')
            response=Mock();response.__enter__=Mock(return_value=io.BytesIO(b'{"id":"retried"}'));response.__exit__=Mock(return_value=False);return response
        with patch('email_inbound.api_get',side_effect=[incoming,dict(data=[])]),patch('email_verification.urllib.request.urlopen',side_effect=transport):
            inbound.deliver_once()
            rows=inbound.load(self.conn);self.assertTrue(rows[0]['payload']);self.assertNotIn('Private body',json.dumps(rows))
            rows[0]['next_attempt']=0;inbound.save(self.conn,rows);self.conn.commit()
            inbound.deliver_once()
        self.assertEqual(requests[0],requests[1]);self.assertNotIn('payload',inbound.load(self.conn)[0])
