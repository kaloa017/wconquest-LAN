"""Map, moderation and late-game checks use the existing disposable save fixture."""
import gzip,json,time,unittest
from pathlib import Path
from unittest.mock import patch
import test_expansion as fixture
from test_upgrade import app,features
import community_tools,research,space


class PerformanceUpdateTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    tile=fixture.ExpansionTests.tile

    def test_map_cache_reads_only_changed_territory_and_preserves_rest(self):
        self.tile('200,200',self.a);self.tile('200,201',self.b)
        first=self.client.get('/api/map/sync').json
        self.conn.execute('INSERT INTO buildings VALUES("200,200","farm",1)');self.conn.commit()
        original=features.map_snapshot
        with patch.object(features,'map_snapshot',wraps=original) as snapshot:
            delta=self.client.get('/api/map/sync?since='+first['version']).json
        self.assertFalse(delta['reset']);self.assertEqual([t['grid_key'] for t in delta['changed']],['200,200'])
        self.assertEqual(set(snapshot.call_args.args[1]),{'200,200'})
        self.assertIn('200,201',features._map_cache['tiles'])
        self.conn.execute('DELETE FROM territories WHERE grid_key="200,201"');self.conn.commit()
        removed=self.client.get('/api/map/sync?since='+delta['version']).json
        self.assertEqual(removed['removed'],['200,201'])
        self.assertNotIn('200,201',features._map_cache['tiles'])

    def test_geography_is_public_compressed_and_content_addressed(self):
        public=app.app.test_client();manifest=public.get('/static/map/manifest.json')
        self.assertEqual(manifest.status_code,200);self.assertIn('public',manifest.headers['Cache-Control'])
        self.assertNotIn('Set-Cookie',manifest.headers)
        index=manifest.json;url=next(iter(index['regions'].values()))
        raw=public.get(url);encoded=public.get(url,headers={'Accept-Encoding':'gzip'})
        self.assertEqual(gzip.decompress(encoded.data),raw.data)
        self.assertIn('immutable',encoded.headers['Cache-Control'])
        conditional=public.get(url,headers={'If-None-Match':raw.headers['ETag']});self.assertEqual(conditional.status_code,304);conditional.close()
        self.assertEqual(len(index['islands']),3268)
        self.assertNotIn('geometry',index['islands'][0])
        self.assertIn('no-store',self.client.get('/api/map/sync').headers['Cache-Control'])
        manifest.close();raw.close();encoded.close()
        terrain=public.get('/api/terrain/cells',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(len(gzip.decompress(terrain.data)),236500);terrain.close()

    def test_map_regions_reconstruct_original_geography_exactly(self):
        root=Path(app.__file__).parent;index=json.loads((root/'static/map/manifest.json').read_text(encoding='utf-8'))
        originals=json.loads((root/'data/pacific-islands.geojson').read_text(encoding='utf-8'))['features']
        result={}
        for url in index['regions'].values():
            for feature in json.loads((root/url.lstrip('/')).read_text(encoding='utf-8'))['features']:result[feature['properties']['key']]=feature
        self.assertEqual(result,{f['properties']['key']:f for f in originals})

    def test_word_filter_blocks_messages_and_edits_but_not_substrings(self):
        admin=self.login(self.admin);data={'enabled':True,'words':['bAdWoRd','blocked phrase']}
        self.assertEqual(self.post('/api/admin/chat_filter',data,self.login(self.mod)).status_code,403)
        self.assertEqual(self.post('/api/admin/chat_filter',data,admin).status_code,200)
        for path,body in [('/api/chat/send',{'message':'BADWORD!'}),('/api/trade/discussion',{'to_id':self.b,'message':'bad\u200bword'}),('/api/admin/chat_edit',{'id':1,'text':'blocked   phrase'}),('/api/admin/chat_as',{'user_id':self.a,'message':'badword'})]:
            response=self.post(path,body,admin if path.startswith('/api/admin/') else None)
            self.assertEqual(response.status_code,400,response.json);self.assertIn('blocked',response.json['error'])
        self.assertFalse(community_tools.blocked('badwordish',data))
        self.assertTrue(community_tools.blocked('ＢＡＤＷＯＲＤ',data))
        self.post('/api/admin/chat_filter',{'enabled':False,'words':data['words']},admin)
        self.assertEqual(self.post('/api/chat/send',{'message':'badword'}).status_code,200)
        app.set_setting(self.conn,'chat_word_filter','');self.conn.commit()

    def test_filter_validation_and_state_preserve_existing_users(self):
        admin=self.login(self.admin)
        for data in [{'enabled':True,'words':['']},{'enabled':'true','words':[]},{'enabled':True,'words':['x']*201}]:
            self.assertEqual(self.post('/api/admin/chat_filter',data,admin).status_code,400)
        self.assertIsNotNone(self.conn.execute('SELECT id FROM users WHERE id=?',(self.a,)).fetchone())

    def test_public_link_preview_contains_metadata_without_login(self):
        with patch.dict('os.environ',{'PUBLIC_URL':'https://www.world-conquest.lol'}):
            response=app.app.test_client().get('/')
        html=response.get_data(as_text=True)
        self.assertIn('property="og:title" content="World Conquest"',html)
        self.assertIn('content="https://www.world-conquest.lol/static/share-card.png"',html)
        self.assertIn('summary_large_image',html)
        self.assertIn('/static/map-performance.js?v='+app.VERSION,html)
        image=app.app.test_client().get('/static/share-card.png')
        self.assertTrue(image.data.startswith(b'\x89PNG'));self.assertEqual(image.status_code,200)
        # Guest analytics now establishes an anonymous session on the landing
        # page. Public preview HTML still contains no account or CSRF secrets.
        self.assertIn('HttpOnly',response.headers.get('Set-Cookie',''))
        self.assertIn('SameSite=Lax',response.headers.get('Set-Cookie',''))
        self.assertNotIn('guest_visit',html)
        self.assertNotIn('"csrf":',html)
        image.close()

    def test_extended_tree_has_no_cycles_and_legacy_costs_are_unchanged(self):
        tree=app.RESEARCH_TREE;self.assertEqual(len(tree),123);self.assertEqual(tree['agri']['cost'],100)
        def visit(key,path):
            self.assertNotIn(key,path)
            for previous in tree[key]['requires']:self.assertIn(previous,tree);visit(previous,path|{key})
        for key in tree:visit(key,set())
        self.assertEqual(tree['advanced_finance_4']['cost'],5000000000)
        self.assertEqual(self.post('/api/research/unlock',{'tech':'advanced_finance_1'}).status_code,400)

    def test_new_research_changes_real_production_combat_and_space(self):
        self.tile('200,200',self.a,'bank')
        base=app.income_rates(self.conn,self.a)[0]['money']
        mods=app.attack_mods(self.conn,self.a,set(),'land',200,200)[0]
        self.conn.execute('UPDATE users SET research=? WHERE id=?',(json.dumps(['advanced_finance_1','advanced_command_1','advanced_cargo_1','advanced_mineral_1','advanced_propulsion_1','advanced_networks_1']),self.a));self.conn.commit()
        self.assertAlmostEqual(app.income_rates(self.conn,self.a)[0]['money'],base*1.04)
        self.assertGreater(len(app.attack_mods(self.conn,self.a,app.user_research(self.conn,self.a),'land',200,200)[0]),len(mods))
        self.assertEqual(space.cargo_capacity(self.conn,self.a),11200)
        self.assertAlmostEqual(space.mining_multiplier(self.conn,self.a),1.08)
        self.assertLess(space.travel_time(self.conn,self.a,'moon'),180)
        self.assertAlmostEqual(research.speed(self.conn,self.a),1.08)

    def test_research_completion_settles_old_production_before_grant(self):
        self.tile('200,200',self.a,'bank');stamp=int(time.time())
        self.conn.execute('INSERT INTO research_projects VALUES(?,?,?,?,?,?,?)',(self.a,'advanced_finance_1',1,1800,stamp-10,1,100000));self.conn.commit()
        seen=[];collect=research.core['auto_collect']
        def settlement(uid,conn,force=False):
            seen.append('advanced_finance_1' in app.user_research(conn,uid))
            return collect(uid,conn,force=force)
        with patch.dict(research.core,{'auto_collect':settlement}):research.tick(self.conn,self.a)
        self.assertEqual(seen,[False]);self.assertIn('advanced_finance_1',app.user_research(self.conn,self.a))

    def test_more_expeditions_and_projects_extend_existing_progress(self):
        self.assertEqual(app.SPACE_PLANETS['titan']['previous'],'europa')
        self.assertEqual(app.SPACE_PLANETS['neptune']['previous'],'enceladus')
        self.assertEqual(app.MEGAPROJECTS['antimatter_forge']['requires'],'star_gate')
        self.assertEqual(len(app.MEGAPROJECTS),6)
        before=self.conn.execute('SELECT research FROM users WHERE id=?',(self.a,)).fetchone()[0]
        response=self.client.get('/api/space');self.assertEqual(response.status_code,200)
        self.assertEqual(before,self.conn.execute('SELECT research FROM users WHERE id=?',(self.a,)).fetchone()[0])


if __name__=='__main__':unittest.main()
