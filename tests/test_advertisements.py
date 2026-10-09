"""Admin-only banner configuration and safe public rendering data."""
import unittest,json
import test_expansion as fixture
from test_upgrade import app
from advertisements import DEFAULT

class AdvertisementTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    def setUp(self):
        fixture.ExpansionTests.setUp(self)
        self.conn.execute("DELETE FROM game_settings WHERE key='advertisement'");self.conn.commit()

    def test_only_admin_can_view_editor_or_change_banner(self):
        for client in (self.client,self.login(self.mod),self.login(self.b)):
            self.assertEqual(client.get('/api/admin/advertisement').status_code,403)
            self.assertEqual(self.post('/api/admin/advertisement',DEFAULT,client).status_code,403)
        self.conn.execute('UPDATE users SET is_moderator=2 WHERE id=?',(self.b,));self.conn.commit()
        self.assertEqual(self.post('/api/admin/advertisement',DEFAULT,self.login(self.b)).status_code,403)
        self.assertEqual(app.app.test_client().get('/api/admin/advertisement').status_code,401)

    def test_full_configuration_persists_is_public_and_audited(self):
        data={**DEFAULT,'enabled':True,'title':'Community event','message':'Join us this weekend!','link':'https://example.org/event','image':'/static/example.jpg','font_size':16,'width':300,'alignment':'center'}
        r=self.post('/api/admin/advertisement',data,self.login(self.admin));self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(app.app.test_client().get('/api/advertisement').json['banner'],data)
        self.assertEqual(json.loads(app.get_setting(self.conn,'advertisement')),data)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log WHERE actor_id=? AND action='advertisement_updated'",(self.admin,)).fetchone()[0],1)
        self.assertEqual(self.post('/api/admin/advertisement',{**data,'enabled':False},self.login(self.admin)).status_code,200)
        self.assertEqual(self.client.get('/api/advertisement').json,{'banner':{'enabled':False}})

    def test_unsafe_urls_styles_and_malformed_values_are_rejected(self):
        admin=self.login(self.admin)
        for change in ({'link':'javascript:alert(1)'},{'image':'data:text/html,hello'},{'image':'http://example.org/x.jpg'},
                       {'image':'/static/../secret'},{'background':'red;position:fixed'},{'text_color':123},
                       {'width':100000},{'font_size':True},{'enabled':'yes'},{'title':['bad']},{'html':'<script>'},{'enabled':True}):
            r=self.post('/api/admin/advertisement',{**DEFAULT,**change},admin)
            self.assertEqual(r.status_code,400,(change,r.json))
        self.assertIsNone(app.get_setting(self.conn,'advertisement'))

if __name__=='__main__':unittest.main()
