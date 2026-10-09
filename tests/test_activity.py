"""Inactivity and offline war protection against disposable saves."""
import time
import unittest
from unittest.mock import patch
import test_expansion as fixture
from test_upgrade import app
import activity

class ActivityTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    balance=fixture.ExpansionTests.balance
    tile=fixture.ExpansionTests.tile
    faction=fixture.ExpansionTests.faction

    def mark(self,uid,active,login=0,heartbeat=0,paused=0):
        activity.state(self.conn,uid)
        self.conn.execute('UPDATE player_activity SET last_activity=?,last_login=?,heartbeat=?,paused=? WHERE user_id=?',(active,login,heartbeat,paused,uid));self.conn.commit()

    def test_polling_cannot_extend_deadline_or_resume(self):
        stamp=int(time.time());self.mark(self.a,stamp-1800)
        for path in ('/api/me','/api/activity','/api/income'):
            response=self.client.get(path);self.assertEqual(response.status_code,200,response.json)
        income=self.client.get('/api/income').json
        self.assertTrue(income['paused']);self.assertEqual(income['value_per_min'],0)
        self.assertTrue(self.post('/api/activity',{'active':True}).json['inactive'])
        self.assertEqual(self.conn.execute('SELECT last_activity FROM player_activity WHERE user_id=?',(self.a,)).fetchone()[0],stamp-1800)
        self.assertEqual(self.post('/api/troops/build',{'amount':1}).status_code,423)
        self.assertEqual(self.post('/api/activity/resume',{}).status_code,200)
        self.assertEqual(self.post('/api/troops/build',{'amount':1}).status_code,200)

    def test_earth_production_stops_at_exact_deadline_without_backlog(self):
        stamp=int(time.time());self.tile('200,200',self.a,'farm')
        self.mark(self.a,stamp-3600)
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-3600,self.a));self.conn.commit()
        rate=app.income_rates(self.conn,self.a)[0]['food'];before=self.balance(self.a,'food')
        with patch.object(activity.time,'time',return_value=stamp):app.auto_collect(self.a,self.conn)
        self.conn.commit();self.assertAlmostEqual(self.balance(self.a,'food')-before,rate*30)
        before=self.balance(self.a,'food')
        with patch.object(activity.time,'time',return_value=stamp+3600):app.auto_collect(self.a,self.conn)
        self.conn.commit();self.assertAlmostEqual(self.balance(self.a,'food'),before)
        self.assertEqual(self.post('/api/activity/resume',{}).status_code,200)
        self.assertAlmostEqual(self.balance(self.a,'food'),before)

    def test_human_ping_renews_active_deadline_but_presence_ping_does_not(self):
        stamp=int(time.time());self.mark(self.a,stamp-1700)
        self.post('/api/activity',{'active':False})
        self.assertEqual(self.client.get('/api/activity').json['deadline'],stamp+100)
        self.post('/api/activity',{'active':True})
        self.assertGreaterEqual(self.client.get('/api/activity').json['deadline'],stamp+1800)
        self.assertEqual(self.post('/api/activity',{'active':'true'}).status_code,400)

    def test_successful_login_tracks_login_and_logout_clears_online_presence(self):
        self.conn.execute('UPDATE users SET password=? WHERE id=?',(app.generate_password_hash('activity-test-password'),self.a));self.conn.commit()
        username=self.conn.execute('SELECT username FROM users WHERE id=?',(self.a,)).fetchone()[0]
        response=self.post('/api/login',{'username':username,'password':'activity-test-password'})
        self.assertEqual(response.status_code,200,response.json)
        row=activity.state(self.conn,self.a)
        self.assertGreater(row['last_login'],0);self.assertGreater(row['heartbeat'],0)
        token=None
        with self.client.session_transaction() as s:token=s['csrf']
        self.assertEqual(self.client.post('/api/logout',json={},headers={'X-WC-CSRF':token}).status_code,200)
        self.assertEqual(activity.state(self.conn,self.a)['heartbeat'],0)

    def test_orbital_and_planetary_production_stop_while_paused(self):
        import json,space
        stamp=int(time.time());self.tile('200,200',self.a,'space_agency')
        self.conn.execute('UPDATE users SET research=? WHERE id=?',(json.dumps(['spaceflight']),self.a))
        self.conn.execute("INSERT INTO space_program(user_id,state,planet,collected,last_mined,cargo,visited) VALUES(?,'surface','moon',?,?,'{}','[]')",(self.a,stamp-3600,stamp-3600))
        self.conn.execute("INSERT INTO space_businesses VALUES(?,'satellite',1)",(self.a,))
        self.conn.execute("INSERT INTO planet_tiles VALUES(?,'moon',3,3,1)",(self.a,));self.conn.commit()
        self.mark(self.a,stamp-3600)
        before=self.balance(self.a,'money')
        with patch.object(activity.time,'time',return_value=stamp):space.collect_space(self.conn,self.a)
        self.conn.commit();self.assertAlmostEqual(self.balance(self.a,'money')-before,20000*30)
        cargo=self.conn.execute('SELECT cargo FROM space_program WHERE user_id=?',(self.a,)).fetchone()[0]
        before=self.balance(self.a,'money')
        with patch.object(activity.time,'time',return_value=stamp+3600):space.collect_space(self.conn,self.a)
        self.conn.commit();self.assertEqual(self.balance(self.a,'money'),before)
        self.assertEqual(self.conn.execute('SELECT cargo FROM space_program WHERE user_id=?',(self.a,)).fetchone()[0],cargo)

    def test_recent_offline_faction_member_prevents_war(self):
        own=self.faction(self.a);target=self.faction(self.b);stamp=int(time.time())
        self.mark(self.b,stamp,stamp,heartbeat=0)
        r=self.post('/api/faction/war/declare',{'faction_id':target})
        self.assertEqual(r.status_code,400,r.json)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM faction_rel WHERE a=? AND b=?',(own,target)).fetchone()[0],0)
        self.mark(self.b,stamp,stamp,heartbeat=stamp)
        self.assertEqual(self.post('/api/faction/war/declare',{'faction_id':target}).status_code,200)

    def test_old_offline_login_is_not_protected_and_new_member_is(self):
        self.faction(self.a);target=self.faction(self.b);stamp=int(time.time())
        self.mark(self.b,stamp-90000,stamp-86400,heartbeat=0,paused=1)
        self.assertEqual(self.post('/api/faction/war/declare',{'faction_id':target}).status_code,200)
        self.conn.execute('DELETE FROM faction_rel');self.conn.execute('UPDATE users SET faction_id=? WHERE id=?',(target,self.mod));self.conn.commit()
        self.mark(self.mod,stamp,stamp,heartbeat=0)
        self.assertEqual(self.post('/api/faction/war/declare',{'faction_id':target}).status_code,400)

    def test_inactive_member_does_not_receive_treasury_income(self):
        fid=self.faction(self.a);stamp=int(time.time())
        self.conn.execute('UPDATE users SET faction_id=? WHERE id=?',(fid,self.b))
        self.conn.execute('UPDATE factions SET treasury=10000,last_tick=? WHERE id=?',(stamp-600,fid));self.conn.commit()
        self.mark(self.a,stamp);self.mark(self.b,stamp-3600)
        before=self.balance(self.b,'money');app.faction_tick(self.conn,fid);self.conn.commit()
        self.assertEqual(self.balance(self.b,'money'),before)
        self.assertAlmostEqual(self.conn.execute('SELECT treasury FROM factions WHERE id=?',(fid,)).fetchone()[0],9950)

    def test_current_territory_count_and_income_reduce_claim_cost_after_losses(self):
        for i in range(20):self.tile('200,'+str(200+i),self.a,'market')
        large=app.claim_price(self.conn,self.a,'plains')['money']
        self.conn.execute('UPDATE territories SET owner_id=? WHERE owner_id=? AND grid_key!="200,200"',(self.b,self.a));self.conn.commit()
        smaller=app.claim_price(self.conn,self.a,'plains')['money']
        self.assertLess(smaller,large)
        self.conn.execute('UPDATE territories SET owner_id=NULL WHERE owner_id=?',(self.a,));self.conn.commit()
        self.assertEqual(app.claim_price(self.conn,self.a,'plains'),{'money':app.CLAIM_COST})

    def test_transferring_paused_land_cannot_revive_its_income_backlog(self):
        stamp=int(time.time());self.tile('200,200',self.a,'farm')
        self.mark(self.a,stamp-3600,paused=1);self.mark(self.b,stamp)
        self.conn.execute('UPDATE territories SET last_collected=? WHERE grid_key="200,200"',(stamp-86400,))
        self.conn.execute('UPDATE territories SET owner_id=? WHERE grid_key="200,200"',(self.b,));self.conn.commit()
        collected=self.conn.execute('SELECT last_collected FROM territories WHERE grid_key="200,200"').fetchone()[0]
        self.assertGreaterEqual(collected,stamp)
        before=self.balance(self.b,'food');app.auto_collect(self.b,self.conn);self.conn.commit()
        self.assertEqual(self.balance(self.b,'food'),before)

    def test_farms_and_lumberyards_are_affordable_and_produce_more(self):
        self.assertEqual(app.BUILDINGS['farm']['production']['food'],12)
        self.assertEqual(app.BUILDINGS['lumberyard']['production']['wood'],10)
        self.assertNotIn('terrain',app.BUILDINGS['lumberyard'])
        self.tile('200,200',self.a)
        self.assertEqual(self.post('/api/building/build',{'grid_key':'200,200','type':'lumberyard'}).status_code,200)

    def test_public_policies_and_idempotent_activity_migration(self):
        for path in ('/terms','/privacy'):
            r=app.app.test_client().get(path);self.assertEqual(r.status_code,200);self.assertIn(b'9 October 2026',r.data)
        self.mark(self.a,int(time.time())-3600,paused=1);before=dict(self.conn.execute('SELECT * FROM player_activity WHERE user_id=?',(self.a,)).fetchone())
        app.migrate_v16(app.get_db);app.migrate_v16(app.get_db)
        self.assertEqual(before,dict(self.conn.execute('SELECT * FROM player_activity WHERE user_id=?',(self.a,)).fetchone()))

    def test_migration_updates_shipped_building_defaults_and_preserves_custom_values(self):
        import json
        old={'name':'Farm','icon':'🌾','desc':'+6 food/min per level','cost':{'money':90,'wood':25},'production':{'food':6}}
        custom={'name':'Custom wood mill','icon':'🪵','desc':'Host settings','cost':{'money':1},'production':{'wood':99}}
        self.conn.execute('DELETE FROM schema_migrations WHERE version=16')
        for key,data in [('farm',old),('lumberyard',custom)]:self.conn.execute("INSERT OR REPLACE INTO live_catalog VALUES('buildings',?,?)",(key,json.dumps(data)))
        self.conn.commit();app.migrate_v16(app.get_db)
        farm=json.loads(self.conn.execute("SELECT data FROM live_catalog WHERE category='buildings' AND item_key='farm'").fetchone()[0])
        self.assertEqual(farm['production']['food'],12)
        self.assertEqual(json.loads(self.conn.execute("SELECT data FROM live_catalog WHERE category='buildings' AND item_key='lumberyard'").fetchone()[0]),custom)
        # Only disposable test definitions are cleared; restore catalog defaults for subsequent tests.
        self.conn.execute("DELETE FROM live_catalog WHERE category='buildings' AND item_key IN ('farm','lumberyard')");self.conn.commit()

if __name__=='__main__':unittest.main()
