"""Verified security and accounting defects, using disposable saves only."""
import os,time,unittest,sqlite3,tempfile
from pathlib import Path
from contextlib import closing
from unittest.mock import patch,Mock
import test_expansion as fixture
from test_upgrade import app
import security,research

class AuditFixTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    tile=fixture.ExpansionTests.tile
    faction=fixture.ExpansionTests.faction
    balance=fixture.ExpansionTests.balance

    def test_password_change_cannot_revoke_another_account(self):
        self.conn.execute('UPDATE users SET password=? WHERE id=?',(app.ph('test-only'),self.a));self.conn.commit()
        other_own_session=self.login(self.a);victim=self.login(self.b)
        r=self.post('/api/profile/change_password',{'current_password':'test-only','new_password':'new-password','user_id':self.b})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.balance(self.a,'auth_version'),1)
        self.assertEqual(self.balance(self.b,'auth_version'),0)
        self.assertEqual(victim.get('/api/me').status_code,200)
        self.assertEqual(self.client.get('/api/me').status_code,200)
        self.assertEqual(other_own_session.get('/api/me').status_code,401)

    def test_profile_authentication_attempts_are_limited(self):
        security._attempts.clear();self.addCleanup(security._attempts.clear)
        with patch.dict(os.environ,AUTH_ATTEMPTS_PER_MINUTE='2'):
            for _ in range(2):self.assertEqual(self.post('/api/profile/two_factor',{'action':'disable','password':'bad','code':'123456'}).status_code,403)
            r=self.post('/api/profile/two_factor',{'action':'disable','password':'bad','code':'123456'})
            self.assertEqual(r.status_code,429,r.json);self.assertEqual(r.headers['Retry-After'],'60')
            self.assertEqual(self.client.get('/api/me').status_code,200)

    def test_rejected_auth_attempts_still_bound_tracker(self):
        security._attempts.clear();self.addCleanup(security._attempts.clear)
        with patch.dict(os.environ,AUTH_ATTEMPTS_PER_MINUTE='1'),patch.object(security,'MAX_AUTH_CLIENTS',4,create=True):
            for i in range(10):
                for _ in range(2):
                    self.client.post('/api/login',json={'username':'same','password':'bad'},environ_overrides={'REMOTE_ADDR':'192.0.2.'+str(i)})
                self.assertLessEqual(len(security._attempts),4)

    def test_player_reset_clears_only_target_progression(self):
        stamp=int(time.time())
        for uid in (self.a,self.b):
            self.conn.execute('UPDATE users SET rockets=5 WHERE id=?',(uid,))
            self.conn.execute('INSERT INTO research_projects VALUES(?,?,?,?,?,?,?)',(uid,'castle',3600,3600,stamp,1,100))
            self.conn.execute('INSERT INTO megaprojects VALUES(?,?,?,?)',(uid,'orbital_ring',2,stamp+100))
            self.conn.execute('INSERT INTO away_earnings VALUES(?,?,?,?)',(uid,'{"food":100}',stamp-100,stamp))
            self.conn.execute('INSERT INTO recruitment_progress VALUES(?,.5)',(uid,))
        self.conn.commit()
        r=self.post('/api/admin/player',{'user_id':self.a,'action':'reset','confirm':True},self.login(self.admin))
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.balance(self.a,'rockets'),0)
        for table in ('research_projects','megaprojects','away_earnings','recruitment_progress'):
            self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=?',(self.a,)).fetchone()[0],0)
            self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=?',(self.b,)).fetchone()[0],1)
        self.assertEqual(self.balance(self.b,'rockets'),5)

    def test_resource_reset_settles_old_income_even_below_poll_interval(self):
        self.tile('200,200',self.a,'farm');stamp=int(time.time())
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-10,self.a));self.conn.commit()
        r=self.post('/api/admin/player',{'user_id':self.a,'action':'reset_resources','resource':'food','confirm':True},self.login(self.admin))
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.balance(self.a,'food'),0)
        self.assertGreaterEqual(self.conn.execute('SELECT last_collected FROM territories WHERE owner_id=?',(self.a,)).fetchone()[0],stamp)

    def test_demolition_keeps_income_earned_before_demolition(self):
        self.tile('200,200',self.a,'farm',2);stamp=int(time.time());before=self.balance(self.a,'food')
        rate=app.income_rates(self.conn,self.a)[0]['food']
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-600,self.a));self.conn.commit()
        r=self.post('/api/building/demolish',{'grid_key':'200,200'})
        self.assertEqual(r.status_code,200,r.json)
        self.assertAlmostEqual(self.balance(self.a,'food')-before,rate*10,delta=rate/20)

    def test_new_laboratory_changes_active_project_speed_immediately(self):
        self.tile('200,200',self.a);stamp=int(time.time())
        self.conn.execute('UPDATE users SET research=? WHERE id=?',('["castle","engineering"]',self.a))
        self.conn.execute('INSERT INTO research_projects VALUES(?,?,?,?,?,?,?)',(self.a,'iron',3600,3600,stamp,1,100))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-10,self.a));self.conn.commit()
        r=self.post('/api/building/build',{'grid_key':'200,200','type':'laboratory'})
        self.assertEqual(r.status_code,200,r.json)
        self.assertAlmostEqual(self.conn.execute('SELECT speed FROM research_projects WHERE user_id=?',(self.a,)).fetchone()[0],1.15)
        self.assertGreaterEqual(self.conn.execute('SELECT last_collected FROM territories WHERE owner_id=?',(self.a,)).fetchone()[0],stamp)

    def test_recruitment_is_independent_of_collection_frequency_and_persists(self):
        self.tile('200,200',self.a,'barracks');self.tile('200,201',self.b,'barracks')
        stamp=int(time.time());army_a=self.balance(self.a,'army');army_b=self.balance(self.b,'army')
        import activity
        for uid in (self.a,self.b):activity.state(self.conn,uid,stamp)
        self.conn.execute('UPDATE territories SET last_collected=?',(stamp,));self.conn.commit()
        for offset in (30,60):
            with patch.object(app,'time',Mock(time=lambda:stamp+offset)):
                app.auto_collect(self.a,self.conn)
            self.conn.commit()
        with patch.object(app,'time',Mock(time=lambda:stamp+60)):app.auto_collect(self.b,self.conn)
        self.conn.commit()
        self.assertEqual(self.balance(self.a,'army')-army_a,3)
        self.assertEqual(self.balance(self.b,'army')-army_b,3)
        with patch.object(app,'time',Mock(time=lambda:stamp+90)):app.auto_collect(self.a,self.conn)
        self.conn.commit()
        check=app.get_db();self.addCleanup(check.close)
        self.assertAlmostEqual(check.execute('SELECT remainder FROM recruitment_progress WHERE user_id=?',(self.a,)).fetchone()[0],.5)
        with patch.object(app,'time',Mock(time=lambda:stamp+120)):app.auto_collect(self.a,check)
        check.commit();self.assertEqual(self.balance(self.a,'army')-army_a,6)

    def test_recruitment_migration_is_idempotent_and_preserves_existing_save(self):
        self.conn.execute('INSERT INTO recruitment_progress VALUES(?,.5)',(self.a,));self.conn.commit()
        before=self.balance(self.a,'money')
        app.migrate_v19(app.get_db);app.migrate_v19(app.get_db)
        self.assertEqual(self.balance(self.a,'money'),before)
        self.assertEqual(self.conn.execute('SELECT remainder FROM recruitment_progress WHERE user_id=?',(self.a,)).fetchone()[0],.5)

    def test_explicit_round_reset_clears_queued_progression(self):
        stamp=int(time.time())
        self.conn.execute('INSERT INTO research_projects VALUES(?,?,?,?,?,?,?)',(self.a,'castle',3600,3600,stamp,1,100))
        self.conn.execute('INSERT INTO recruitment_progress VALUES(?,.5)',(self.a,))
        self.conn.execute('INSERT INTO megaprojects VALUES(?,?,?,?)',(self.a,'orbital_ring',2,stamp+100))
        self.conn.execute('INSERT INTO away_earnings VALUES(?,?,?,?)',(self.a,'{"food":100}',stamp-100,stamp))
        app.do_game_reset(self.conn);self.conn.commit()
        for table in ('research_projects','megaprojects','away_earnings','recruitment_progress'):
            self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],0)

    def test_construction_does_not_retroactively_add_new_building_income(self):
        self.tile('200,200',self.a);stamp=int(time.time());before=self.balance(self.a,'food')
        rate=app.income_rates(self.conn,self.a)[0]['food']
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-600,self.a));self.conn.commit()
        r=self.post('/api/building/build',{'grid_key':'200,200','type':'farm'})
        self.assertEqual(r.status_code,200,r.json)
        self.assertAlmostEqual(self.balance(self.a,'food')-before,rate*10,delta=rate/20)

    def test_building_rolls_back_if_production_destroys_ownership(self):
        self.tile('200,200',self.a);before=self.balance(self.a,'money')
        def destroy(uid,conn,force=False):conn.execute('UPDATE territories SET owner_id=NULL WHERE owner_id=?',(uid,))
        with patch.object(app,'auto_collect',destroy):
            r=self.post('/api/building/build',{'grid_key':'200,200','type':'farm'})
        self.assertEqual(r.status_code,409,r.json)
        self.assertEqual(self.balance(self.a,'money'),before)
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key="200,200"').fetchone()[0],self.a)
        self.assertIsNone(self.conn.execute('SELECT 1 FROM buildings WHERE grid_key="200,200"').fetchone())

    def test_schema18_upgrade_backs_up_and_preserves_accounts_and_land(self):
        from migrations import backup_before_upgrade
        self.tile('200,200',self.a,'farm',2)
        with tempfile.TemporaryDirectory(dir=self.scratch.name) as directory:
            target=Path(directory)/'old-save.db'
            with closing(sqlite3.connect(target)) as dest, dest:
                self.conn.backup(dest)
                dest.execute('DROP TABLE recruitment_progress')
                dest.execute('DELETE FROM schema_migrations WHERE version IN (19,20)')
            backup_before_upgrade(target)
            backups=list((target.parent/'backups').glob('*before-v20*.db'));self.assertEqual(len(backups),1)
            def connect():
                conn=sqlite3.connect(target);conn.row_factory=sqlite3.Row;return conn
            app.migrate_v19(connect);app.migrate_v20(connect);backup_before_upgrade(target)
            self.assertEqual(len(list((target.parent/'backups').glob('*.db'))),1)
            with closing(connect()) as check:
                self.assertEqual(check.execute('SELECT money FROM users WHERE id=?',(self.a,)).fetchone()[0],self.balance(self.a,'money'))
                self.assertEqual(check.execute('SELECT level FROM buildings WHERE grid_key="200,200"').fetchone()[0],2)
                self.assertEqual(check.execute('SELECT owner_id FROM territories WHERE grid_key="200,200"').fetchone()[0],self.a)
                self.assertEqual(check.execute('SELECT COUNT(*) FROM recruitment_progress').fetchone()[0],0)
            with closing(sqlite3.connect(backups[0])) as original:
                self.assertIsNone(original.execute('SELECT 1 FROM schema_migrations WHERE version=19').fetchone())
