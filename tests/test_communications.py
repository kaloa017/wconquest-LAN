"""Private analytics, quotas and code authentication on disposable databases."""
import io
import json
import time
import unittest
import urllib.error
from unittest.mock import patch,Mock
from werkzeug.security import generate_password_hash
import test_expansion as fixture
from test_upgrade import app
import email_verification as mail
import traffic_controls
import features

class CommunicationTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    def setUp(self):
        fixture.ExpansionTests.setUp(self)
        self.conn.execute('DELETE FROM guest_visits');self.conn.execute('DELETE FROM ip_bans')
        for table in ('email_challenges','email_outbox','email_budget','email_request_limits','account_emails'):self.conn.execute('DELETE FROM '+table)
        features._limits.clear();traffic_controls.invalidate()
        app.set_setting(self.conn,'email_verification',json.dumps(mail.DEFAULT))
        self.conn.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash('friend-password'),self.a));self.conn.commit()
        self.username=self.conn.execute('SELECT username FROM users WHERE id=?',(self.a,)).fetchone()[0]
        self.admin_client=self.login(self.admin)
        self.env=patch.dict('os.environ',{'BREVO_API_KEY':'disposable-test-key','EMAIL_FROM':'accounts@example.org'})
        self.env.start();self.addCleanup(self.env.stop)
    def enable(self,**changes):
        s={**mail.DEFAULT,'enabled':True,**changes};app.set_setting(self.conn,'email_verification',json.dumps(s));self.conn.commit()
        self.conn.execute('INSERT OR IGNORE INTO account_emails(user_id,email) VALUES(?,?)',(self.a,'friend@example.org'));self.conn.commit()
    def signin(self,**extra):
        return self.post('/api/login',dict(username=self.username,password='friend-password',**extra))
    def code(self):
        row=self.conn.execute('SELECT payload FROM email_outbox ORDER BY id DESC LIMIT 1').fetchone()
        return json.loads(mail.cipher().decrypt(row['payload'].encode()))['code']

    def test_crawler_filters_and_duplicate_ip_visit_totals_are_private(self):
        for agent,count in [('Mozilla/5.0 Firefox/130',2),('Googlebot/2.1',1)]:
            guest=app.app.test_client()
            for _ in range(count):guest.get('/',headers={'User-Agent':agent},environ_overrides={'REMOTE_ADDR':'198.51.100.11'})
        all_rows=self.admin_client.get('/api/admin/analytics?q=198.51.100.11').json
        self.assertEqual(all_rows['summary']['pageviews'],3)
        self.assertEqual(all_rows['visits'][0]['ip_visits'],3);self.assertEqual(all_rows['visits'][0]['ip_records'],2)
        for traffic,expected in [('human',2),('crawler',1),('unknown',0)]:
            data=self.admin_client.get('/api/admin/analytics?traffic='+traffic).json
            self.assertEqual(data['summary']['pageviews'],expected)
            self.assertEqual(sum(x['sessions'] for x in data['countries']),data['summary']['guest_sessions'])
        self.assertEqual(self.client.get('/api/admin/analytics?traffic=crawler').status_code,403)
        self.assertEqual(self.admin_client.get('/api/admin/analytics?traffic=bad').status_code,400)
        self.assertNotIn('Googlebot',json.dumps(all_rows)) # raw User-Agent not stored or returned

    def test_ip_restrictions_expiry_own_address_and_spoof_protection(self):
        data=dict(action='ban',ip='198.51.100.12',minutes=5,reason='Disposable test',confirm=True)
        self.assertEqual(self.post('/api/admin/ip-bans',data).status_code,403)
        self.assertEqual(self.post('/api/admin/ip-bans',data,self.admin_client).status_code,200)
        guest=app.app.test_client()
        for path in ('/','/api/bootstrap','/api/spectator/sync'):
            self.assertEqual(guest.get(path,environ_overrides={'REMOTE_ADDR':data['ip']},headers={'X-Forwarded-For':'1.1.1.1'}).status_code,403)
        self.assertEqual(guest.get('/api/bootstrap').status_code,200)
        self.assertEqual(self.post('/api/admin/ip-bans',{**data,'ip':'127.0.0.1'},self.admin_client).status_code,400)
        self.conn.execute('UPDATE ip_bans SET expires_at=1');self.conn.commit();traffic_controls.invalidate()
        self.assertEqual(guest.get('/api/bootstrap',environ_overrides={'REMOTE_ADDR':data['ip']}).status_code,200)

    def test_guest_snapshot_contains_delta_and_no_private_addresses(self):
        guest=app.app.test_client();first=guest.get('/api/spectator/sync').json
        self.assertTrue(first['map']['reset']);self.assertIsInstance(first['online'],list);self.assertIsInstance(first['fallout'],list)
        unchanged=guest.get('/api/spectator/sync?since='+first['map']['version']).json
        self.assertFalse(unchanged['map']['reset']);self.assertEqual(unchanged['map']['changed'],[])
        self.assertNotIn('127.0.0.1',json.dumps(first))

    def test_email_code_required_single_use_and_no_admin_code_disclosure(self):
        self.enable()
        reply=self.signin();self.assertTrue(reply.json['email_required']);code=self.code()
        with self.client.session_transaction() as s:self.assertNotIn('user_id',s)
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertIn('Incorrect',self.signin(email_code='abcdefgh').json['error'])
        valid=self.signin(email_code=code);self.assertTrue(valid.json['success'],valid.json)
        self.assertGreater(self.conn.execute('SELECT verified_at FROM account_emails WHERE user_id=?',(self.a,)).fetchone()[0],0)
        replay=self.signin(email_code=code);self.assertIn('expired',replay.json['error'])
        private=self.admin_client.get('/api/admin/email').json
        self.assertNotIn(code,json.dumps(private));self.assertNotIn('disposable-test-key',json.dumps(private));self.assertNotIn('code_hash',json.dumps(private))
        self.assertEqual(self.client.get('/api/admin/email').status_code,401) # pending login cleared prior session

    def test_cooldowns_attempt_limits_and_quota_only_fallback(self):
        self.enable(daily_limit=2)
        self.signin();initial=self.conn.execute('SELECT COUNT(*) FROM email_outbox').fetchone()[0]
        self.signin();limited=self.signin(resend_email=True)
        self.assertTrue(limited.json['email_required']);self.assertIn('wait',limited.json['error'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM email_outbox').fetchone()[0],initial)
        for _ in range(6):reply=self.signin(email_code='wrong')
        self.assertIn('Too many',reply.json['error'])
        self.conn.execute('INSERT OR REPLACE INTO email_budget VALUES(?,2)',(mail.day(),));self.conn.commit()
        fallback=self.signin();self.assertTrue(fallback.json['success']);self.assertTrue(fallback.json['email_fallback'])
        self.enable(daily_limit=2,quota_fallback=False)
        blocked=self.signin();self.assertTrue(blocked.json['email_required']);self.assertNotIn('success',blocked.json)

    def test_user_email_password_checks_and_verified_address_change(self):
        self.enable();self.conn.execute('DELETE FROM account_emails');self.conn.commit()
        self.assertEqual(self.post('/api/profile/email',dict(email='bad')).status_code,403)
        result=self.post('/api/profile/email',dict(email='friend@example.org',password='friend-password'))
        self.assertTrue(result.json['email_required'],result.json);code=self.code()
        self.assertTrue(self.post('/api/profile/email',dict(action='verify',code=code)).json['success'])
        changed=self.post('/api/profile/email',dict(email='other@example.org',password='friend-password'))
        self.assertIn('current email',changed.json['error'])
        self.assertEqual(self.conn.execute('SELECT email FROM account_emails WHERE user_id=?',(self.a,)).fetchone()[0],'friend@example.org')

    def test_delivery_releases_write_lock_encrypts_payload_and_clears_it(self):
        self.enable();self.signin();code=self.code()
        self.assertNotIn(code,self.conn.execute('SELECT payload FROM email_outbox').fetchone()[0])
        def provider(req,timeout):
            # A second connection can write while the provider is contacted.
            conn=app.get_db();conn.execute('BEGIN IMMEDIATE');conn.rollback();conn.close()
            self.assertEqual(req.full_url,'https://api.brevo.com/v3/smtp/email')
            self.assertIn(code,json.loads(req.data)['htmlContent'])
            response=Mock();response.__enter__=Mock(return_value=io.BytesIO(b'{"messageId":"test-message"}'));response.__exit__=Mock(return_value=False);return response
        with patch('email_verification.urllib.request.urlopen',side_effect=provider):mail.deliver_once()
        row=self.conn.execute('SELECT status,payload FROM email_outbox').fetchone();self.assertEqual(row['status'],'accepted');self.assertEqual(row['payload'],'')

    def test_provider_error_does_not_disable_email_but_credit_exhaustion_does(self):
        self.enable();self.signin()
        err=urllib.error.HTTPError('https://api.brevo.com',401,'Unauthenticated',{},io.BytesIO(b'{}'))
        with patch('email_verification.urllib.request.urlopen',side_effect=err):mail.deliver_once()
        self.assertTrue(self.signin().json['email_required'])
        self.conn.execute('DELETE FROM email_challenges');self.conn.commit();self.signin()
        err=urllib.error.HTTPError('https://api.brevo.com',400,'Credits',{},io.BytesIO(b'{"code":"not_enough_credits"}'))
        with patch('email_verification.urllib.request.urlopen',side_effect=err):mail.deliver_once()
        self.assertTrue(self.signin().json['email_fallback'])

    def test_map_batch_reuses_army_aggregate(self):
        keys=[f'200,{i}' for i in range(1001)]
        with patch('features.army_map',wraps=features.army_map) as aggregate:features.map_snapshot(self.conn,keys)
        self.assertEqual(aggregate.call_count,1)

if __name__=='__main__':unittest.main()
