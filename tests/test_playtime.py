"""Visible browser time, no offline catch-up or per-tab multiplication."""
import time,unittest
from unittest.mock import patch
import test_expansion as fixture
from test_upgrade import app
import activity,playtime

class PlaytimeTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post

    def test_visible_heartbeats_count_once_across_multiple_tabs(self):
        stamp=int(time.time())
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp),0)
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp+30),30)
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp+30),30)
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp+60),60)

    def test_hiding_closing_or_long_gaps_stop_counting(self):
        stamp=int(time.time());playtime.record(self.conn,self.a,timestamp=stamp)
        self.assertEqual(playtime.record(self.conn,self.a,False,stamp+20),20)
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp+86400),20)
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp+86430),50)
        self.assertEqual(playtime.record(self.conn,self.a,timestamp=stamp+90000),50)

    def test_visible_afk_time_counts_without_resuming_income(self):
        stamp=int(time.time());activity.state(self.conn,self.a)
        self.conn.execute('UPDATE player_activity SET last_activity=?,paused=1 WHERE user_id=?',(stamp-3600,self.a));self.conn.commit()
        with patch.object(activity.time,'time',return_value=stamp):self.post('/api/activity',{'active':False,'visible':True})
        with patch.object(activity.time,'time',return_value=stamp+30):r=self.post('/api/activity',{'active':False,'visible':True})
        self.assertTrue(r.json['inactive']);self.assertEqual(r.json['play_seconds'],30)
        self.assertEqual(activity.state(self.conn,self.a)['heartbeat'],0)

    def test_authenticated_list_is_paginated_and_exposes_no_private_fields(self):
        stamp=int(time.time());playtime.record(self.conn,self.a,timestamp=stamp-30);playtime.record(self.conn,self.a,timestamp=stamp);self.conn.commit()
        r=self.client.get('/api/playtime');self.assertEqual(r.status_code,200,r.json)
        row=next(u for u in r.json['players'] if u['id']==self.a)
        self.assertEqual(row['seconds'],30);self.assertEqual(set(row),{'id','username','color','seconds'})
        self.assertLessEqual(len(r.json['players']),50)
        self.assertEqual(self.client.get('/api/playtime?page=0').status_code,400)
        self.assertEqual(app.app.test_client().get('/api/playtime').status_code,401)

    def test_visibility_validation_and_idempotent_migration(self):
        self.assertEqual(self.post('/api/activity',{'visible':'yes'}).status_code,400)
        stamp=int(time.time());playtime.record(self.conn,self.a,timestamp=stamp-20);playtime.record(self.conn,self.a,timestamp=stamp);self.conn.commit()
        app.migrate_v17(app.get_db);app.migrate_v17(app.get_db)
        self.assertEqual(activity.state(self.conn,self.a)['play_seconds'],20)

if __name__=='__main__':unittest.main()
