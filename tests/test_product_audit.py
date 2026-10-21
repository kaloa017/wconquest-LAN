"""Broad authorization inventory and semantic public documents on isolated saves."""
import re
import tempfile
from pathlib import Path
import unittest
import test_expansion as fixture
from test_upgrade import app
import features
from policies import render_document

class ProductAuditTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post

    def test_every_admin_route_denies_guest_and_player_without_changes(self):
        previous=features._rate_settings.copy();self.addCleanup(lambda:features._rate_settings.update(previous))
        features._rate_settings.update(requests=0,auth=0);features._limits.clear()
        guest=app.app.test_client()
        with guest.session_transaction() as session:session['csrf']='test-csrf'
        count=0;before=self.conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        for route in app.app.url_map.iter_rules():
            if not route.rule.startswith('/api/admin/'):continue
            path=re.sub(r'<[^>]+>','1',route.rule)
            for method in route.methods&{'GET','POST','DELETE','PUT','PATCH'}:
                for client in (guest,self.client):
                    response=client.open(path,method=method,json={'confirm':True},headers={'X-WC-CSRF':'test-csrf'})
                    self.assertIn(response.status_code,(401,403),f'{method} {path}: {response.status_code}')
                    count+=1
        self.assertGreater(count,80)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],before)

    def test_policies_are_semantic_escaped_and_use_shared_design(self):
        markup=render_document('# Title\nUpdated 21 October 2026\n\n## Section\n<script>alert(1)</script>\n\n- First\n- Second\n')
        self.assertIn('<h2>Section</h2>',markup);self.assertIn('<ul><li>First</li><li>Second</li></ul>',markup)
        self.assertNotIn('<script>',markup);self.assertIn('&lt;script&gt;',markup)
        for path in ('/terms','/privacy'):
            response=app.app.test_client().get(path);self.assertEqual(response.status_code,200)
            text=response.get_data(as_text=True)
            self.assertIn('product-ui.css?v='+app.VERSION,text);self.assertIn('class="policy-copy"',text)
            self.assertNotIn('<pre>',text);self.assertIn('<h2>',text)

    def test_asset_hash_changes_without_a_release_number_change(self):
        from asset_versions import asset_version
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'static'/'theme.css';path.parent.mkdir();path.write_text('first',encoding='utf-8')
            before=asset_version(directory,'/static/theme.css','6.12.0')
            path.write_text('second design',encoding='utf-8')
            after=asset_version(directory,'/static/theme.css','6.12.0')
            self.assertNotEqual(before,after);self.assertTrue(after.startswith('6.12.0&h='))
            self.assertEqual(asset_version(directory,'/outside.key','6.12.0'),'6.12.0')

if __name__=='__main__':unittest.main()
