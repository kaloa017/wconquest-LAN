"""Menu/content update regressions on isolated saves only."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
import test_expansion as fixture
from test_upgrade import app
from progression_content import NEW_BUILDINGS,MILESTONES
import activity


class PolishTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    tile=fixture.ExpansionTests.tile
    balance=fixture.ExpansionTests.balance

    def test_stats_personal_values_and_admin_only_world_aggregates(self):
        self.conn.execute('UPDATE users SET money=1234 WHERE id=?',(self.a,));self.conn.execute('UPDATE users SET money=999999 WHERE id=?',(self.b,));self.conn.commit()
        self.tile('200,200',self.a,'farm',2)
        own=self.client.get('/api/statistics').json
        self.assertEqual(own['resources']['money'],1234);self.assertEqual(own['totals']['buildings'],1)
        self.assertEqual(own['buildings'][0]['levels'],2);self.assertNotIn('accounts',own['totals'])
        self.assertEqual(self.client.get('/api/statistics?scope=world').status_code,403)
        self.assertEqual(app.app.test_client().get('/api/statistics').status_code,401)
        result=self.login(self.admin).get('/api/statistics?scope=world')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['resources']['money'],self.conn.execute('SELECT SUM(money) FROM users').fetchone()[0])
        self.assertEqual(result.json['totals']['accounts'],self.conn.execute('SELECT COUNT(*) FROM users').fetchone()[0])
        self.assertNotIn('password',json.dumps(result.json));self.assertNotIn('ip',result.json)

    def test_admin_notes_are_protected_and_not_in_player_changelog(self):
        self.assertEqual(self.client.get('/api/admin/release_notes').status_code,403)
        self.assertEqual(self.login(self.mod).get('/api/admin/release_notes').status_code,403)
        result=self.login(self.admin).get('/api/admin/release_notes')
        self.assertEqual(result.status_code,200);self.assertIn('default admin',result.json['text'])
        self.conn.execute('UPDATE users SET last_seen_version="6.8.0" WHERE id=?',(self.a,));self.conn.commit()
        text=self.client.get('/api/changelog').json['text']
        self.assertNotIn('guest analytics',text.lower());self.assertNotIn('default admin',text.lower())
        self.assertNotIn('database snapshot',text.lower());self.assertIn('buildings',text.lower())

    def test_new_buildings_have_real_yields_valid_gates_and_server_checks(self):
        self.assertEqual(len(NEW_BUILDINGS),12)
        context={'rs':set(),'ft':set(),'ide':{},'w':set(),'ev':None,'base':1,'religion':{}}
        base=app.tile_yield(context,'plains',None,0)
        for key in NEW_BUILDINGS:
            definition=app.BUILDINGS[key];self.assertIn(definition['needs'],app.RESEARCH_TREE)
            produced=app.tile_yield(context,'plains',key,2)
            for resource,rate in definition['production'].items():self.assertAlmostEqual(produced[resource]-base.get(resource,0),rate*2)
        self.tile('200,200',self.a)
        denied=self.post('/api/building/build',{'grid_key':'200,200','type':'commercial_hub'})
        self.assertEqual(denied.status_code,400);self.assertIn('research',denied.json['error'].lower())
        self.conn.execute('UPDATE users SET research=?,money=1000000000,steel=100000,gems=10000 WHERE id=?',(json.dumps(['trade','advanced_finance_1']),self.a));self.conn.commit()
        built=self.post('/api/building/build',{'grid_key':'200,200','type':'commercial_hub'})
        self.assertEqual(built.status_code,200,built.json)

    def test_achievements_keep_old_keys_and_award_new_milestones_once(self):
        self.assertEqual(len(MILESTONES),24);self.assertIn('first_blood',app.ACHIEVEMENTS)
        self.conn.execute('UPDATE users SET money=1000000000,research=? WHERE id=?',(json.dumps(list(app.RESEARCH_TREE)),self.a));self.conn.commit()
        first=app.award_achievements(self.conn,self.a);balance=self.balance(self.a,'money')
        self.assertIn('research_123',{row['key'] for row in first});self.assertIn('wealth_1b',{row['key'] for row in first})
        self.assertEqual(app.award_achievements(self.conn,self.a),[]);self.assertEqual(self.balance(self.a,'money'),balance)
        self.conn.commit()
        self.assertGreaterEqual(len(self.client.get('/api/achievements').json),54)

    def test_away_ack_suppresses_later_collections_from_the_same_absence(self):
        now=int(time.time());self.tile('200,200',self.a,'farm')
        activity.state(self.conn,self.a);since=now-600
        self.conn.execute('UPDATE player_activity SET last_activity=?,heartbeat=0,paused=0 WHERE user_id=?',(since,self.a))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(since,self.a));self.conn.commit()
        report=self.client.get('/api/away').json['summary'];self.assertIsNotNone(report)
        ack=self.post('/api/away',{'since':report['since']});self.assertEqual(ack.status_code,200,ack.json)
        # More production settles while this same old activity episode remains.
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(now-60,self.a));self.conn.commit()
        self.assertIsNone(self.client.get('/api/away').json['summary'])
        # A different activity episode is allowed its own future return summary.
        self.conn.execute('UPDATE player_activity SET last_activity=? WHERE user_id=?',(since+100,self.a))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(now-60,self.a));self.conn.commit()
        self.assertIsNotNone(self.client.get('/api/away').json['summary'])

    def test_retire_default_admin_transactionally_without_touching_named_players(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'save.db'
            with closing(sqlite3.connect(path)) as copy:self.conn.backup(copy)
            def connect():
                conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON');return conn
            with closing(connect()) as conn:
                conn.execute('DELETE FROM schema_migrations WHERE version=21')
                default=conn.execute('INSERT INTO users(username,password,is_admin) VALUES("admin","retired-test-only",1)').lastrowid
                before=conn.execute('SELECT money,research FROM users WHERE id=?',(self.a,)).fetchone();conn.commit()
            app.migrate_v21(connect);app.migrate_v21(connect)
            with closing(connect()) as conn:
                self.assertIsNone(conn.execute('SELECT 1 FROM users WHERE id=?',(default,)).fetchone())
                self.assertEqual(tuple(conn.execute('SELECT money,research FROM users WHERE id=?',(self.a,)).fetchone()),tuple(before))
                self.assertEqual(conn.execute('SELECT is_admin FROM users WHERE id=?',(self.admin,)).fetchone()[0],1)
                self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        rejected=self.post('/api/register',{'username':'ADMIN','password':'not-a-real-password'})
        self.assertEqual(rejected.status_code,400)
        self.assertEqual(self.post('/api/admin/change_username',{'user_id':self.a,'new_username':'Admin'},self.login(self.admin)).status_code,400)

    def test_default_account_retirement_never_deletes_the_only_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sole-owner.db'
            with closing(sqlite3.connect(path)) as copy:self.conn.backup(copy)
            def connect():
                conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;return conn
            with closing(connect()) as conn:
                conn.execute('DELETE FROM schema_migrations WHERE version=21');conn.execute('UPDATE users SET is_admin=0')
                uid=conn.execute('INSERT INTO users(username,password,is_admin) VALUES("admin","test-only",1)').lastrowid;conn.commit()
            app.migrate_v21(connect)
            with closing(connect()) as conn:self.assertEqual(conn.execute('SELECT is_admin FROM users WHERE id=?',(uid,)).fetchone()[0],1)


if __name__=='__main__':unittest.main()
