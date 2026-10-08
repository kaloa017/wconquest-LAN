"""Regression tests for the audit, using the existing isolated test database."""
import unittest, time, os, tempfile
from unittest.mock import patch
from flask import Flask
from test_upgrade import app, features

class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from migrations import migrate_v6,migrate_v7,migrate_v8,migrate_v9,migrate_v10,migrate_v11
        cls.saved_db=app.DB_PATH;cls.scratch=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        app.DB_PATH=str(Path(cls.scratch.name)/'game.db')
        app.init_db();app.migrate_v4();app.migrate_v5()
        for migrate in (migrate_v6,migrate_v7,migrate_v8,migrate_v9,migrate_v10,migrate_v11):migrate(app.get_db)
        features._map_cache.clear()
    @classmethod
    def tearDownClass(cls):
        app.DB_PATH=cls.saved_db;features._map_cache.clear();features._stats.clear();cls.scratch.cleanup()
    def setUp(self):
        self.client=app.app.test_client()
        self.csrf=self.client.get('/api/bootstrap').json['csrf']
        name='Audit'+str(time.time_ns())[-12:]
        self.post('/api/register',{'username':name,'password':'testpassword'})
        self.post('/api/login',{'username':name,'password':'testpassword'})
        self.uid=self.client.get('/api/me').json['id']
    def connection(self):
        conn=app.get_db();self.addCleanup(conn.close);return conn
    def post(self,path,data):return self.client.post(path,json=data,headers={'X-WC-CSRF':self.csrf})
    def user(self,conn,label):
        return conn.execute('INSERT INTO users(username,password) VALUES(?,?)',(label+str(time.time_ns())[-8:],app.ph('testpassword'))).lastrowid
    def faction(self,conn,members):
        fid=conn.execute('INSERT INTO factions(name,tag,leader_id,color) VALUES(?,?,?,?)',('Audit'+str(time.time_ns()),format(conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM factions').fetchone()[0],'04x'),members[0],'#ef4444')).lastrowid
        for uid in members:features.join_faction(conn,uid,fid)
        return fid
    def test_loan_cannot_transfer_faction_mates_vehicles(self):
        conn=self.connection();owner=self.user(conn,'Owner');borrower=self.user(conn,'Borrower')
        self.faction(conn,[self.uid,owner]);conn.execute('UPDATE users SET boats=5,share_boats=1 WHERE id=?',(owner,))
        lid=conn.execute("INSERT INTO loans(lender_id,borrower_id,unit,amount,status,ts) VALUES(?,?, 'boats',3,'pending',0)",(self.uid,borrower)).lastrowid
        conn.commit();conn.close()
        self.assertEqual(self.post('/api/loan/respond',{'loan_id':lid,'accept':True}).status_code,400)
        conn=self.connection();self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(owner,)).fetchone()[0],5);conn.close()
    def test_loan_return_does_not_take_shared_vehicles(self):
        conn=self.connection();owner=self.user(conn,'Owner');lender=self.user(conn,'Lender')
        self.faction(conn,[self.uid,owner]);conn.execute('UPDATE users SET boats=5,share_boats=1 WHERE id=?',(owner,))
        lid=conn.execute("INSERT INTO loans(lender_id,borrower_id,unit,amount,status,ts) VALUES(?,?, 'boats',3,'active',0)",(lender,self.uid)).lastrowid
        conn.commit();conn.close();self.assertEqual(self.post('/api/loan/return',{'loan_id':lid}).status_code,200)
        conn=self.connection();self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(owner,)).fetchone()[0],5);self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(lender,)).fetchone()[0],0);conn.close()
    def test_malformed_text_and_toggles_are_rejected(self):
        conn=self.connection();conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.uid,));conn.commit();conn.close()
        for url,data in [('/api/chat/send',{'message':42}),('/api/faction/create',{'name':[],'tag':'AA'}),('/api/admin/ban',{'user_id':self.uid,'ban':'false'}),('/api/admin/set_setting',{'key':'income_mult','value':'nan'})]:
            with self.subTest(url=url):self.assertEqual(self.post(url,data).status_code,400)
    def test_explicit_session_secret_has_minimum_length(self):
        from runtime import initialize_security
        with patch.dict(os.environ,{'SECRET_KEY':'weak'}):
            with self.assertRaises(RuntimeError):initialize_security(Flask('audit'))

    def test_disband_preserves_army_and_personal_colors(self):
        conn=self.connection();mate=self.user(conn,'Mate');conn.execute('UPDATE users SET army=30,base_color="#123456" WHERE id=?',(self.uid,));conn.execute('UPDATE users SET army=10,base_color=color WHERE id=?',(mate,));fid=self.faction(conn,[self.uid,mate]);conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.uid,));conn.commit();conn.close()
        self.assertEqual(self.post('/api/admin/disband_faction',{'faction_id':fid}).status_code,200)
        with self.connection() as conn:
            rows=conn.execute('SELECT army,faction_id,color,base_color FROM users WHERE id IN (?,?)',(self.uid,mate)).fetchall()
            self.assertEqual(sum(r['army'] for r in rows),40);self.assertTrue(all(r['faction_id'] is None for r in rows));self.assertTrue(all(r['color']==r['base_color'] for r in rows))
        conn.close()
    def test_assigning_same_faction_is_a_noop(self):
        conn=self.connection();fid=self.faction(conn,[self.uid]);conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.uid,));conn.commit();conn.close()
        self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'faction','faction_id':fid}).status_code,200)
        conn=self.connection();self.assertEqual(app.fac_id(conn,self.uid),fid);self.assertIsNotNone(conn.execute('SELECT id FROM factions WHERE id=?',(fid,)).fetchone());conn.close()
    def test_round_reset_does_not_duplicate_faction_army(self):
        conn=self.connection();mate=self.user(conn,'Mate');fid=self.faction(conn,[self.uid,mate]);app.do_game_reset(conn)
        features.leave_faction(conn,self.uid);features.leave_faction(conn,mate)
        self.assertEqual(conn.execute('SELECT SUM(army) FROM users WHERE id IN (?,?)',(self.uid,mate)).fetchone()[0],10);conn.rollback();conn.close()
    def test_blast_includes_owned_and_unowned_custom_islands(self):
        from geography import load,island_feature
        import geography
        load();key=next(k for k,f in geography._islands.items() if not f['properties']['grid_tiles']);a,b=app.parse_key(key)
        conn=self.connection();conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"plains",100)',(key,self.uid));conn.execute('INSERT INTO buildings VALUES(?,"port",1)',(key,))
        owners,_=app.devastate(conn,a,b,1,int(time.time())+3600,'nuke')
        self.assertEqual(owners[self.uid],1);self.assertIsNone(conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(key,)).fetchone()[0]);self.assertTrue(app.fallout_active(conn,key));self.assertIsNone(conn.execute('SELECT 1 FROM buildings WHERE grid_key=?',(key,)).fetchone());conn.rollback();conn.close()
    def test_map_delta_refreshes_other_group_tiles(self):
        conn=self.connection();mate=self.user(conn,'Mate');fid=self.faction(conn,[self.uid,mate]);conn.execute('UPDATE factions SET army=100 WHERE id=?',(fid,))
        for key,uid in [('100,100',self.uid),('101,100',mate)]:conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"plains",100)',(key,uid))
        conn.commit();conn.close();first=self.client.get('/api/map/sync').json
        conn=self.connection();conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES("102,100",?,"plains",100)',(mate,));conn.commit();conn.close()
        delta=self.client.get('/api/map/sync?since='+first['version']).json;changed={t['grid_key']:t for t in delta['changed']}
        self.assertIn('100,100',changed);self.assertIn('101,100',changed);self.assertEqual(changed['100,100']['garrison'],int(100/3**.55+3))

    def test_stock_list_uses_constant_query_count(self):
        from flask import session
        conn=self.connection();mate=self.user(conn,'Mate');fid=self.faction(conn,[self.uid,mate])
        for uid in (self.uid,mate):conn.execute('INSERT INTO stock_prices VALUES(?,?,?,?,?,0)',('C'+str(uid),'country',uid,100,100))
        conn.commit();conn.close()
        with app.app.test_request_context('/api/stocks'):
            session['user_id']=self.uid;c=app.get_db();queries=[];c.set_trace_callback(queries.append)
            assets=features.market().json['assets'];c.set_trace_callback(None)
            self.assertLessEqual(sum(q.lstrip().upper().startswith('SELECT') for q in queries),4)
            self.assertFalse(next(a for a in assets if a['symbol']=='C'+str(mate))['investable']);self.assertTrue(all('target_faction' not in a for a in assets))
    def test_spectator_queue_is_bounded_and_deduplicated(self):
        import queue
        fake=queue.Queue(maxsize=2)
        with patch.object(app,'_geo_queue',fake),patch.object(app,'_geo_pending',set()),patch.object(app,'_geo_cache',{}),patch.object(app,'_spectators',{}),patch.dict(os.environ,{'ENABLE_IP_GEOLOOKUP':'1'}):
            for _ in range(100):app._touch_spectator('192.0.2.1')
            app._touch_spectator('192.0.2.2');app._touch_spectator('192.0.2.3')
            self.assertEqual(fake.qsize(),2);self.assertEqual(len(app._geo_pending),2)

    def test_workers_wait_for_new_session_secret(self):
        from runtime import initialize_security
        with patch.dict(os.environ,{'SECRET_KEY':''}),patch('runtime.os.open',side_effect=FileExistsError),patch('runtime.Path.read_text',side_effect=['','a'*64]):
            server=Flask('audit');initialize_security(server);self.assertEqual(server.secret_key,'a'*64)
    def test_read_only_event_endpoint_does_not_write(self):
        with app.app.test_request_context('/api/income'):
            c=app.get_db();queries=[];c.set_trace_callback(queries.append);app.current_event(c);c.set_trace_callback(None)
            self.assertFalse(any(q.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for q in queries))
    def test_scheduler_resets_expired_round_without_online_players(self):
        conn=self.connection();app.set_setting(conn,'winner_id',self.uid);app.set_setting(conn,'win_time',int(time.time())-app.WIN_COUNTDOWN-1);conn.execute('UPDATE users SET money=999 WHERE id=?',(self.uid,));conn.execute('UPDATE scheduler_state SET next_tick=0 WHERE id=1');conn.commit();conn.close()
        with patch.object(features,'AUTO_RESET_ROUNDS',True):features.scheduler_tick()
        conn=self.connection();self.assertIsNone(app.get_setting(conn,'winner_id'));self.assertEqual(conn.execute('SELECT money FROM users WHERE id=?',(self.uid,)).fetchone()[0],200)
    def test_merge_rejects_absent_inviting_country(self):
        conn=self.connection();mid=conn.execute("INSERT INTO merges(from_id,to_id,status,ts) VALUES(999999,?,'pending',0)",(self.uid,)).lastrowid;conn.commit();conn.close()
        self.assertEqual(self.post('/api/merge/respond',{'merge_id':mid,'accept':True}).status_code,409)
    def test_music_info_handles_concurrent_removal(self):
        with app.app.test_request_context('/api/music'),patch('features.Path.stat',side_effect=FileNotFoundError):self.assertIsNone(features.music_info().json['url'])

    def test_concurrent_cold_geography_initializes_once(self):
        import geography
        from concurrent.futures import ThreadPoolExecutor
        keys=('_land','_coasts','_japan','_islands','_island_cells')
        saved={key:getattr(geography,key) for key in keys}
        try:
            for key in keys:setattr(geography,key,None)
            original=geography.PolygonIndex
            with patch.object(geography,'PolygonIndex',wraps=original) as constructor:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    result=list(pool.map(lambda _:geography.island_neighbors(0,0),range(24)))
                self.assertTrue(all(value==result[0] for value in result))
                self.assertEqual(constructor.call_count,1)
                self.assertIsNotNone(geography._island_cells)
        finally:
            for key,value in saved.items():setattr(geography,key,value)

    def test_stale_winner_cannot_reset_existing_world_by_default(self):
        conn=self.connection();app.set_setting(conn,'winner_id',self.uid);app.set_setting(conn,'winner_name','Previous winner');app.set_setting(conn,'win_time',int(time.time())-86400)
        conn.execute('UPDATE users SET money=999 WHERE id=?',(self.uid,))
        conn.execute("INSERT INTO territories(grid_key,owner_id,terrain,population,last_collected) VALUES('20,20',?,'plains',100,?) ON CONFLICT(grid_key) DO UPDATE SET owner_id=excluded.owner_id",(self.uid,int(time.time())))
        conn.execute('UPDATE scheduler_state SET next_tick=0 WHERE id=1');conn.commit();conn.close()
        with patch.object(app,'AUTO_RESET_ROUNDS',False),patch.object(features,'AUTO_RESET_ROUNDS',False):
            status=self.client.get('/api/game/status');self.assertEqual(status.status_code,200);self.assertFalse(status.json['automatic_reset']);self.assertIsNone(status.json['reset_in'])
            features.scheduler_tick()
        conn=self.connection();self.assertEqual(conn.execute('SELECT money FROM users WHERE id=?',(self.uid,)).fetchone()[0],999)
        self.assertEqual(conn.execute("SELECT owner_id FROM territories WHERE grid_key='20,20'").fetchone()[0],self.uid);self.assertEqual(int(app.get_setting(conn,'winner_id')),self.uid);conn.close()
