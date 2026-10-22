"""Durable event delivery, away deduplication and production-scaled rewards."""
import json,time,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_expansion as fixture
from test_upgrade import app
import activity,player_events,expansion,daily_rewards

class EventTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    tile=fixture.ExpansionTests.tile
    balance=fixture.ExpansionTests.balance
    faction=fixture.ExpansionTests.faction

    def away(self):
        stamp=int(time.time());self.tile('200,200',self.a,'farm');activity.state(self.conn,self.a)
        self.conn.execute('UPDATE player_activity SET last_activity=?,heartbeat=0,paused=0 WHERE user_id=?',(stamp-600,self.a))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-600,self.a));self.conn.commit()
        return self.client.get('/api/away').json['summary']

    def test_two_tabs_claim_one_away_presentation_and_keep_history_after_refresh(self):
        summary=self.away();clients=[self.login(self.a),self.login(self.a)]
        def claim(client):return self.post('/api/away/claim',{'since':summary['since']},client).json
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(claim,clients))
        self.assertEqual(sum(bool(r.get('summary')) for r in responses),1)
        self.assertIsNone(self.client.get('/api/away').json['summary'])
        archived=[r for r in self.client.get('/api/notifications/history').json['events'] if r['type']=='away_summary']
        self.assertEqual(len(archived),1);self.assertEqual(archived[0]['data']['summary']['resources'],summary['resources'])
        self.assertIsNone(claim(self.login(self.a))['summary'])

    def test_future_ack_cannot_suppress_a_new_away_period(self):
        summary=self.away();wrong=self.post('/api/away',{'since':summary['since']+500})
        self.assertEqual(wrong.status_code,409);self.assertIsNotNone(self.client.get('/api/away').json['summary'])
        self.post('/api/away/claim',{'since':summary['since']})
        self.conn.execute('UPDATE player_activity SET last_activity=last_activity+100 WHERE user_id=?',(self.a,))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(int(time.time())-60,self.a));self.conn.commit()
        next_summary=self.client.get('/api/away').json['summary'];self.assertNotEqual(next_summary['since'],summary['since'])
        self.assertIsNotNone(self.post('/api/away/claim',{'since':next_summary['since']}).json['summary'])

    def test_claim_marks_the_current_authoritative_activity_boundary(self):
        summary=self.away();stamp=int(time.time())
        self.conn.execute('UPDATE player_activity SET last_activity=? WHERE user_id=?',(stamp,self.a));self.conn.commit()
        self.post('/api/away/claim',{'since':summary['since']})
        self.assertEqual(self.conn.execute('SELECT away_ack_activity FROM player_activity WHERE user_id=?',(self.a,)).fetchone()[0],stamp)

    def test_events_are_private_idempotent_presented_once_and_read_independently(self):
        player_events.emit(self.conn,self.a,'war_declared','Private war',{},'war:1')
        player_events.emit(self.conn,self.a,'war_declared','Private war',{},'war:1')
        player_events.emit(self.conn,self.b,'capital_lost','Other account',{},'war:1');self.conn.commit()
        self.assertEqual(len(self.client.get('/api/notifications').json),1)
        own=self.client.get('/api/notifications').json[0]['id'];other=self.conn.execute('SELECT id FROM notifications WHERE user_id=?',(self.b,)).fetchone()[0]
        first=self.post('/api/notifications/present',{'ids':[own,other]}).json['events'];self.assertEqual([r['id'] for r in first],[own])
        self.assertEqual(self.post('/api/notifications/present',{'ids':[own]}).json['events'],[])
        self.assertEqual(self.conn.execute('SELECT presented_at FROM notifications WHERE id=?',(other,)).fetchone()[0],0)
        self.assertEqual(len(self.client.get('/api/notifications').json),1)
        self.post('/api/notifications/dismiss',{'id':own});self.assertEqual(self.client.get('/api/notifications').json,[])
        self.assertEqual(self.client.get('/api/notifications/history').json['events'][0]['is_read'],1)
        self.assertEqual(app.app.test_client().get('/api/notifications/history').status_code,401)

    def test_event_history_is_bounded_and_paginated(self):
        for i in range(505):player_events.emit(self.conn,self.a,'info',str(i))
        self.conn.commit();self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id=?',(self.a,)).fetchone()[0],500)
        first=self.client.get('/api/notifications/history').json;second=self.client.get('/api/notifications/history?before='+str(first['next_before'])).json
        self.assertEqual(len(first['events']),50);self.assertFalse({r['id'] for r in first['events']} & {r['id'] for r in second['events']})

    def test_campaign_settlement_cannot_refund_the_same_force_twice(self):
        self.tile('200,200',self.a);self.tile('200,201',self.b)
        # Isolate settlement with an authoritative persisted force already committed.
        self.conn.execute('INSERT INTO campaigns(attacker,defender,from_key,target_key,troops,initial_troops,tactic,started,last_tick) VALUES(?,?,?,?,100,100,"balanced",?,?)',(self.a,self.b,'200,200','200,201',int(time.time()),int(time.time())))
        self.conn.execute('UPDATE users SET army=army-100 WHERE id=?',(self.a,));self.conn.commit()
        campaign=dict(self.conn.execute('SELECT * FROM campaigns WHERE attacker=?',(self.a,)).fetchone())
        before=app.pool_get(self.conn,self.a,'army');expansion.finish_campaign(self.conn,campaign,'ended','Returned')
        once=app.pool_get(self.conn,self.a,'army');expansion.finish_campaign(self.conn,campaign,'ended','Returned')
        self.assertEqual(once-before,100);self.assertEqual(app.pool_get(self.conn,self.a,'army'),once)

    def test_capital_loss_is_important_ordinary_captures_are_routine(self):
        self.tile('200,200',self.a);self.tile('200,201',self.a);self.conn.execute('UPDATE users SET capital_key="200,200" WHERE id=?',(self.a,));self.conn.commit()
        for key in ('200,200','200,201'):
            row=self.conn.execute('SELECT * FROM territories WHERE grid_key=?',(key,)).fetchone();a,b=app.parse_key(key);app.apply_victory(self.conn,self.b,key,'plains',row,a,b)
        self.conn.commit();events=self.client.get('/api/notifications').json
        self.assertEqual({r['type']:r['priority'] for r in events},{'capital_lost':1,'territory_lost':2})

    def test_daily_cash_scales_to_weekly_projection_and_resource_bundle_is_stable(self):
        with patch.dict(app.__dict__,{'income_rates':lambda conn,uid:({'money':100000,'food':200,'metal':20},0,{})}):
            first=self.client.get('/api/daily').json;second=self.client.get('/api/daily').json
            self.assertEqual(first['money'],100800000);self.assertEqual(first['resources'],second['resources']);self.assertEqual(len(first['resources']),3)
            result=self.post('/api/daily/claim',{'choice':'money'});self.assertEqual(result.status_code,200,result.json);self.assertEqual(result.json['rewards'],{'money':100800000})
            self.assertEqual(self.post('/api/daily/claim',{'choice':'resources'}).status_code,400)

    def test_simultaneous_daily_choices_share_one_claim_and_starter_minimums(self):
        offer=self.client.get('/api/daily').json;self.assertGreaterEqual(offer['money'],150)
        clients=[self.login(self.a),self.login(self.a)]
        def claim(pair):client,choice=pair;return self.post('/api/daily/claim',{'choice':choice},client).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(claim,zip(clients,['money','resources'])))
        self.assertEqual(sorted(result),[200,400])

    def test_naval_and_air_achievements_use_historical_victories(self):
        name=self.conn.execute('SELECT username FROM users WHERE id=?',(self.a,)).fetchone()[0]
        for kind in ('naval','air','land'):self.conn.execute('INSERT INTO battle_log(attacker,defender,grid_key,result,mode,details) VALUES(?,?,?,"victory",?,?)',(name,'wilderness','200,200',kind,'test'))
        keys={r['key'] for r in app.award_achievements(self.conn,self.a)};self.assertTrue({'admiral','ace'}<=keys)
        self.assertEqual(app.award_achievements(self.conn,self.a),[])

    def test_returning_login_collects_before_advancing_the_heartbeat(self):
        from werkzeug.security import generate_password_hash
        self.away();self.conn.execute('DELETE FROM away_earnings WHERE user_id=?',(self.a,))
        # Put uncollected income back on the tile to exercise the actual login path.
        stamp=int(time.time());self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-600,self.a))
        self.conn.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash('return-test-password'),self.a));self.conn.commit()
        name=self.conn.execute('SELECT username FROM users WHERE id=?',(self.a,)).fetchone()[0]
        result=self.post('/api/login',{'username':name,'password':'return-test-password'});self.assertEqual(result.status_code,200,result.json)
        self.assertIsNotNone(self.client.get('/api/away').json['summary'])

    def test_admin_account_updates_notify_only_the_affected_account(self):
        result=self.post('/api/admin/account/action',{'user_id':self.a,'action':'unmute','confirm':True},self.login(self.admin));self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(any(n['type']=='moderation' for n in self.client.get('/api/notifications').json))
        self.assertEqual(self.login(self.b).get('/api/notifications').json,[])

if __name__=='__main__':unittest.main()
