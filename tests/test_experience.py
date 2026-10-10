"""Public hosting and progression regressions against disposable databases only."""
import json,time,unittest,os
from unittest.mock import patch,Mock
import test_expansion as fixture
from test_upgrade import app
import activity,security,two_factor,research,space,expansion

class ExperienceTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    tile=fixture.ExpansionTests.tile
    faction=fixture.ExpansionTests.faction
    balance=fixture.ExpansionTests.balance

    def test_banner_rgb_alternating_and_legacy_configuration(self):
        from advertisements import DEFAULT,validate
        legacy={key:value for key,value in DEFAULT.items() if key not in ('color_mode','alternate_color','cycle_seconds')}
        self.assertEqual(validate(legacy)['color_mode'],'solid')
        data={**DEFAULT,'enabled':True,'title':'Visible now','background':'rgb(12, 128, 255)','color_mode':'alternate','cycle_seconds':6}
        r=self.post('/api/admin/advertisement',data,self.login(self.admin));self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(app.app.test_client().get('/api/advertisement').json['banner']['background'],'#0c80ff')
        for key,value in [('background','rgb(256, 0, 0)'),('color_mode','url(evil)'),('cycle_seconds',1)]:
            self.assertEqual(self.post('/api/admin/advertisement',{**data,key:value},self.login(self.admin)).status_code,400)

    def test_new_religion_reaches_catalog_bootstrap_and_can_be_adopted(self):
        key='test_belief';definition={'name':'New belief','desc':'Test description','atk':1.05}
        self.assertEqual(self.post('/api/admin/catalog',{'category':'religions','item_key':key,'definition':definition},self.login(self.mod)).status_code,403)
        r=self.post('/api/admin/catalog',{'category':'religions','item_key':key,'definition':definition},self.login(self.admin));self.assertEqual(r.status_code,200,r.json)
        self.assertIn(key,self.client.get('/api/catalog').json['religions'])
        self.assertIn(key,self.client.get('/api/bootstrap').json['religions'])
        self.assertEqual(self.post('/api/religion/set',{'id':key}).status_code,200)
        self.conn.execute("DELETE FROM live_catalog WHERE category='religions' AND item_key=?",(key,));self.conn.execute("UPDATE game_settings SET value=CAST(value AS INTEGER)+1 WHERE key='catalog_revision'");self.conn.commit()

    def test_leaderboard_exposes_all_players_playtime_and_verified_donations(self):
        for i in range(22):self.player('Rank'+str(i))
        activity.state(self.conn,self.a);self.conn.execute('UPDATE player_activity SET play_seconds=3661 WHERE user_id=?',(self.a,));self.conn.commit()
        self.assertEqual(self.post('/api/admin/donations',{'user_id':self.a,'amount_nok':1000,'confirm':True},self.login(self.mod)).status_code,403)
        r=self.post('/api/admin/donations',{'user_id':self.a,'amount_nok':1000,'confirm':True},self.login(self.admin));self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['tier'],'Founder')
        rows=app.app.test_client().get('/api/leaderboard').json;self.assertGreater(len(rows),20)
        own=next(row for row in rows if row['id']==self.a);self.assertEqual(own['play_seconds'],3661);self.assertEqual(own['donated_ore'],100000)
        self.assertNotIn('otp_secret',own);self.assertNotIn('ip',own)
        self.assertEqual(self.post('/api/admin/donations',{'user_id':self.a,'amount_nok':-1,'confirm':True},self.login(self.admin)).status_code,400)

    def test_donation_tiers_enforced_server_side(self):
        for tier,allowed in [('Supporter',False),('Champion',True)]:
            self.post('/api/admin/donator_tier',{'user_id':self.a,'tier':tier},self.login(self.admin))
            r=self.post('/api/profile/name_style',{'name_color':'#aabbcc','name_font':'mono','name_rgb':True})
            self.assertEqual(r.status_code,200 if allowed else 400,r.json)
        self.assertEqual(self.post('/api/profile/name_style',{'name_glow':True}).status_code,400)
        self.post('/api/admin/donator_tier',{'user_id':self.a,'tier':'Founder'},self.login(self.admin))
        self.assertEqual(self.post('/api/profile/name_style',{'name_badge':'👑','name_glow':True}).status_code,200)

    def test_private_trade_discussion_and_mute(self):
        self.assertEqual(self.post('/api/trade/discussion',{'to_id':self.b,'message':'Wood for food?'}).status_code,200)
        recipient=self.login(self.b);r=recipient.get('/api/trade/discussion?to_id='+str(self.a));self.assertEqual(r.json['messages'][0]['message'],'Wood for food?')
        unrelated=self.login(self.mod);self.assertEqual(unrelated.get('/api/trade/discussion?to_id='+str(self.a)).json['messages'],[])
        self.assertEqual(app.app.test_client().get('/api/trade/discussion?to_id='+str(self.a)).status_code,401)
        self.conn.execute('UPDATE users SET muted_until=? WHERE id=?',(int(time.time())+600,self.a));self.conn.commit()
        self.assertEqual(self.post('/api/trade/discussion',{'to_id':self.b,'message':'Muted'}).status_code,403)

    def test_offline_earnings_summary_survives_pause_and_acknowledges_once(self):
        stamp=int(time.time());self.tile('200,200',self.a,'farm');activity.state(self.conn,self.a)
        self.conn.execute('UPDATE player_activity SET last_activity=?,heartbeat=0,paused=1 WHERE user_id=?',(stamp-10800,self.a))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp-10800,self.a));self.conn.commit()
        rate=app.income_rates(self.conn,self.a)[0]['food'];before=self.balance(self.a,'food')
        report=self.client.get('/api/away').json['summary'];self.assertAlmostEqual(report['resources']['food'],rate*120,delta=rate/30)
        after=self.balance(self.a,'food');self.assertGreater(after,before)
        self.assertEqual(self.client.get('/api/away').json['summary']['resources'],report['resources']);self.assertEqual(self.balance(self.a,'food'),after)
        self.post('/api/activity/resume',{});self.assertEqual(self.post('/api/away',{}).status_code,200);self.assertIsNone(self.client.get('/api/away').json['summary'])

    def test_war_popup_private_target_only_and_acknowledged_once(self):
        fa=self.faction(self.a);fb=self.faction(self.b);stamp=int(time.time());activity.state(self.conn,self.b)
        self.conn.execute('UPDATE player_activity SET last_login=0 WHERE user_id=?',(self.b,));self.conn.commit()
        self.assertEqual(self.post('/api/faction/war/declare',{'faction_id':fb}).status_code,200)
        other=self.login(self.b);r=other.get('/api/wars/unseen');self.assertEqual(len(r.json['wars']),1);war=r.json['wars'][0]
        self.assertIn('not a win probability',war['explanation']);self.assertEqual(self.client.get('/api/wars/unseen').json['wars'],[])
        self.assertEqual(self.post('/api/wars/unseen',{'rel_id':war['id']}).status_code,404)
        self.assertEqual(self.post('/api/wars/unseen',{'rel_id':war['id']},other).status_code,200);self.assertEqual(other.get('/api/wars/unseen').json['wars'],[])

    def test_research_is_timed_prerequisites_enforced_and_old_unlocks_kept(self):
        stamp=int(time.time());self.conn.execute('UPDATE users SET research=? WHERE id=?',(json.dumps(['castle']),self.a));self.conn.commit()
        self.assertEqual(self.post('/api/research/unlock',{'tech':'gunpowder'}).status_code,400)
        with patch.object(research,'time',Mock(time=lambda: stamp)):r=self.post('/api/research/unlock',{'tech':'iron'})
        self.assertEqual(r.status_code,200,r.json);self.assertNotIn('iron',json.loads(self.conn.execute('SELECT research FROM users WHERE id=?',(self.a,)).fetchone()[0]))
        self.assertEqual(self.post('/api/research/unlock',{'tech':'agri'}).status_code,400)
        duration=app.RESEARCH_TREE['iron']['duration_seconds']
        with patch.object(research,'time',Mock(time=lambda: stamp+duration+1)):r=self.client.get('/api/research')
        self.assertIsNone(r.json['project']);self.assertIn('iron',r.json['research']);self.assertIn('castle',r.json['research'])
        before=self.balance(self.a,'money');self.client.get('/api/research');self.assertEqual(self.balance(self.a,'money'),before)

    def test_lab_speed_is_not_retroactive_and_is_bounded(self):
        stamp=int(time.time());self.tile('200,200',self.a)
        with patch.object(research,'time',Mock(time=lambda: stamp)):self.post('/api/research/unlock',{'tech':'agri'})
        duration=app.RESEARCH_TREE['agri']['duration_seconds']
        with patch.object(research,'time',Mock(time=lambda: stamp+100)):self.post('/api/building/build',{'grid_key':'200,200','type':'laboratory'});r=self.client.get('/api/research')
        self.assertAlmostEqual(r.json['speed'],1.15)
        row=self.conn.execute('SELECT remaining FROM research_projects WHERE user_id=?',(self.a,)).fetchone();self.assertAlmostEqual(row[0],duration-100)
        self.conn.execute('UPDATE buildings SET level=100 WHERE grid_key="200,200"');self.conn.commit();self.assertEqual(research.speed(self.conn,self.a),3)

    def test_admin_progression_controls_reject_moderators_and_are_audited(self):
        self.post('/api/research/unlock',{'tech':'iron'})
        data={'user_id':self.a,'action':'research_complete','confirm':True}
        self.assertEqual(self.post('/api/admin/control',data,self.login(self.mod)).status_code,403)
        self.assertEqual(self.post('/api/admin/control',{**data,'confirm':False},self.login(self.admin)).status_code,400)
        self.assertEqual(self.post('/api/admin/control',data,self.login(self.admin)).status_code,200)
        self.assertIn('iron',json.loads(self.conn.execute('SELECT research FROM users WHERE id=?',(self.a,)).fetchone()[0]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='host_control' AND target_id=?",(self.a,)).fetchone()[0],1)

    def test_frontage_symmetry_and_private_campaign_forecast(self):
        r={'terrain':'mountains','A':1000,'D':1000,'def_force':1000}
        attack,defense,width=expansion.combat_strengths(r,1000,'balanced','hold',1,100,1)
        self.assertEqual(attack,defense);self.assertEqual(width,45)
        self.tile('200,200',self.a);r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100});self.assertEqual(r.status_code,200,r.json)
        c=self.client.get('/api/campaigns').json['campaigns'][0];self.assertIn('forecast',c);self.assertIn('food_per_tick',c['forecast'])
        self.assertEqual(self.login(self.mod).get('/api/campaigns').json['campaigns'],[])

    def test_megaprojects_require_progression_and_completion_before_income(self):
        stamp=int(time.time());self.tile('200,200',self.a,'space_agency')
        self.conn.execute('UPDATE users SET research=?,money=1000000000000,steel=1000000,gems=1000000,uranium=1000000 WHERE id=?',(json.dumps(['spaceflight','stellar_engineering']),self.a))
        self.conn.execute('INSERT INTO space_program(user_id,collected,last_mined,visited) VALUES(?,?,?,?)',(self.a,stamp,stamp,'[]'));self.conn.commit()
        self.assertEqual(self.post('/api/space/megaproject',{'project':'orbital_ring'}).status_code,400)
        self.conn.execute('UPDATE space_program SET visited=? WHERE user_id=?',(json.dumps(['moon','mars','europa']),self.a));self.conn.commit()
        self.assertEqual(self.post('/api/space/megaproject',{'project':'dyson_swarm'}).status_code,400)
        r=self.post('/api/space/megaproject',{'project':'orbital_ring'})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(space.income(self.conn,self.a).get('money',0),0)
        self.assertEqual(self.post('/api/space/megaproject',{'project':'orbital_ring'}).status_code,400)
        ready=self.conn.execute('SELECT ready_at FROM megaprojects WHERE user_id=?',(self.a,)).fetchone()[0]
        with patch.object(space.time,'time',return_value=ready+1):space.collect_space(self.conn,self.a,force=True)
        self.conn.commit();self.assertEqual(space.income(self.conn,self.a)['money'],1500000)
        before=self.balance(self.a,'money')
        with patch.object(space.time,'time',return_value=ready+1):space.collect_space(self.conn,self.a,force=True)
        self.conn.commit();self.assertEqual(self.balance(self.a,'money'),before)

    def test_origin_payload_headers_and_session_expiry(self):
        with self.client.session_transaction() as s:token=s['csrf']
        r=self.client.post('/api/activity',json={},headers={'X-WC-CSRF':token,'Origin':'https://evil.example'});self.assertEqual(r.status_code,403)
        self.assertEqual(self.client.post('/api/activity',json={},headers={'X-WC-CSRF':token,'Sec-Fetch-Site':'cross-site'}).status_code,403)
        self.assertEqual(self.client.post('/api/activity',json={'large':'x'*300000},headers={'X-WC-CSRF':token}).status_code,413)
        r=self.client.get('/api/me');self.assertIn("object-src 'none'",r.headers['Content-Security-Policy']);self.assertIn('camera=()',r.headers['Permissions-Policy'])
        with self.client.session_transaction() as s:s['issued_at']=int(time.time())-13*3600
        self.assertEqual(self.client.get('/api/me').status_code,401)

    def test_auth_security_limit_survives_unlimited_game_settings(self):
        security._attempts.clear();client=app.app.test_client();token=client.get('/api/bootstrap').json['csrf']
        with patch.dict(os.environ,{'AUTH_ATTEMPTS_PER_MINUTE':'2'}):
            for i in range(2):self.assertEqual(client.post('/api/login',json={'username':'missing','password':'wrong'},headers={'X-WC-CSRF':token}).status_code,401)
            r=client.post('/api/login',json={'username':'missing','password':'wrong'},headers={'X-WC-CSRF':token});self.assertEqual(r.status_code,429);self.assertEqual(r.headers['Retry-After'],'60')
        security._attempts.clear()

    def test_two_factor_matches_standard_vector_setup_login_and_replay_protection(self):
        def send(path,data):
            with self.client.session_transaction() as session:token=session.get('csrf')
            return self.client.post(path,json=data,headers={'X-WC-CSRF':token})
        self.assertEqual(two_factor.code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',1),'287082')
        password='strong-test-password';self.conn.execute('UPDATE users SET password=? WHERE id=?',(app.generate_password_hash(password),self.a));self.conn.commit()
        r=send('/api/profile/two_factor',{'action':'setup','password':password});self.assertEqual(r.status_code,200,r.json);secret=r.json['secret'];stamp=int(time.time())+1
        with patch.object(two_factor,'time',Mock(time=lambda: stamp)):r=send('/api/profile/two_factor',{'action':'enable','password':password,'code':two_factor.code(secret,stamp//30)})
        self.assertEqual(r.status_code,200,r.json);self.assertNotIn('otp_secret',self.client.get('/api/me').json)
        username=self.conn.execute('SELECT username FROM users WHERE id=?',(self.a,)).fetchone()[0]
        send('/api/logout',{});self.csrf=self.client.get('/api/bootstrap').json['csrf']
        self.assertEqual(send('/api/login',{'username':username,'password':password}).status_code,401);self.assertEqual(self.client.get('/api/me').status_code,401)
        with patch.object(two_factor,'time',Mock(time=lambda: stamp+30)):r=send('/api/login',{'username':username,'password':password,'otp':two_factor.code(secret,stamp//30+1)})
        self.assertEqual(r.status_code,200,r.json)
        send('/api/logout',{});self.csrf=self.client.get('/api/bootstrap').json['csrf']
        with patch.object(two_factor,'time',Mock(time=lambda: stamp+30)):r=send('/api/login',{'username':username,'password':password,'otp':two_factor.code(secret,stamp//30+1)})
        self.assertEqual(r.status_code,401,r.json)

if __name__=='__main__':unittest.main()
