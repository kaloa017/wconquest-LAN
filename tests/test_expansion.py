"""Exercise v6.4 against disposable saves, never the host's game.db."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from test_upgrade import app, features
import expansion


class ExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved=app.DB_PATH; cls.scratch=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        app.DB_PATH=str(Path(cls.scratch.name)/'game.db')
        app.init_db(); app.migrate_v4(); app.migrate_v5()
        for migrate in (app.migrate_v6,app.migrate_v7,app.migrate_v8,app.migrate_v9,app.migrate_v10,app.migrate_v11,app.migrate_v12,app.migrate_v13,app.migrate_v14,app.migrate_v15): migrate(app.get_db)
        features._map_cache.clear()

    @classmethod
    def tearDownClass(cls):
        app.DB_PATH=cls.saved; features._map_cache.clear(); features._stats.clear(); cls.scratch.cleanup()

    def setUp(self):
        self.conn=app.get_db(); self.addCleanup(self.conn.close)
        self.conn.execute('DELETE FROM campaigns'); self.conn.execute('DELETE FROM territories'); self.conn.execute('DELETE FROM buildings'); self.conn.execute('DELETE FROM fallout')
        self.a=self.player('Sender'); self.b=self.player('Receiver'); self.admin=self.player('Admin',admin=1); self.mod=self.player('Moderator',moderator=1)
        self.conn.commit(); self.client=self.login(self.a)

    def player(self,label,admin=0,moderator=0):
        return self.conn.execute('INSERT INTO users(username,password,is_admin,is_moderator,money,food,metal,oil,army) VALUES(?,?,?,?,100000,100000,10000,10000,1000)',
            (label+str(time.time_ns()),'test-only',admin,moderator)).lastrowid

    def login(self,uid):
        client=app.app.test_client()
        with client.session_transaction() as s: s.update(user_id=uid,username=self.conn.execute('SELECT username FROM users WHERE id=?',(uid,)).fetchone()[0],auth_version=0,csrf='test-csrf')
        return client

    def post(self,path,data,client=None): return (client or self.client).post(path,json=data,headers={'X-WC-CSRF':'test-csrf'})
    def balance(self,uid,key): return self.conn.execute(f'SELECT {key} FROM users WHERE id=?',(uid,)).fetchone()[0]
    def tile(self,key,uid,building=None,level=1):
        self.conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"plains",100)',(key,uid))
        if building:self.conn.execute('INSERT INTO buildings VALUES(?,?,?)',(key,building,level))
        self.conn.commit()

    def faction(self,uid):
        fid=self.conn.execute('INSERT INTO factions(name,tag,leader_id,color) VALUES(?,?,?,?)',('Faction'+str(uid),str(uid),uid,'#123456')).lastrowid
        features.join_faction(self.conn,uid,fid);self.conn.commit();return fid

    def declare_war(self):
        fa=self.faction(self.a);fb=self.faction(self.b)
        rid=self.conn.execute("INSERT INTO faction_rel(a,b,kind,status,ts) VALUES(?,?,'war','active',?)",(fa,fb,int(time.time()))).lastrowid
        self.conn.commit();return rid

    def test_roles_and_timeout_enforced_on_reads_and_writes(self):
        self.assertEqual(self.client.get('/api/moderation/players').status_code,403)
        moderator=self.login(self.mod)
        self.assertEqual(moderator.get('/api/admin/requests').status_code,403)
        self.assertEqual(self.post('/api/admin/moderator',{'user_id':self.a,'enabled':True},moderator).status_code,403)
        self.assertEqual(self.post('/api/moderation/action',{'user_id':self.admin,'action':'timeout','minutes':5,'message':'test reason'},moderator).status_code,403)
        r=self.post('/api/moderation/action',{'user_id':self.a,'action':'timeout','minutes':5,'message':'Please stop griefing'},moderator)
        self.assertEqual(r.status_code,200,r.json)
        r=self.client.get('/api/me');self.assertEqual(r.status_code,423);self.assertEqual(r.json['timeout']['message'],'Please stop griefing');self.assertEqual(r.json['timeout']['duration'],300)
        self.assertTrue(r.json['timeout']['moderator'].startswith('Moderator'))
        self.assertEqual(self.post('/api/exchanges/send',{'to_id':self.b,'give':{'money':1}}).status_code,423)
        self.assertEqual(self.client.get('/api/moderation/status').status_code,200)
        self.post('/api/moderation/action',{'user_id':self.a,'action':'timeout','minutes':0,'message':'Cleared'},moderator)
        self.assertEqual(self.client.get('/api/me').status_code,200)

    def test_mute_and_admin_grant_revoke(self):
        admin=self.login(self.admin)
        self.assertEqual(self.post('/api/admin/moderator',{'user_id':self.a,'enabled':True},admin).status_code,200)
        self.assertEqual(self.client.get('/api/moderation/players').status_code,200)
        self.post('/api/admin/moderator',{'user_id':self.a,'enabled':False},admin)
        self.assertEqual(self.client.get('/api/moderation/players').status_code,403)
        self.post('/api/moderation/action',{'user_id':self.a,'action':'mute','minutes':10,'message':'Chat rules'},self.login(self.mod))
        self.assertGreater(self.balance(self.a,'muted_until'),time.time())
        self.assertEqual(self.post('/api/chat/send',{'channel':'global','message':'hello'}).status_code,403)

    def test_weaker_moderator_has_only_moderation_powers(self):
        admin=self.login(self.admin)
        self.assertEqual(self.post('/api/admin/moderator',{'user_id':self.b,'enabled':True,'role':'moderator'},admin).status_code,200)
        weak=self.login(self.b)
        self.assertEqual(self.balance(self.b,'is_moderator'),2)
        self.assertEqual(self.post('/api/moderation/action',{'user_id':self.a,'action':'mute','minutes':5,'message':'Chat rules'},weak).status_code,200)
        self.assertEqual(self.post('/api/moderation/action',{'user_id':self.mod,'action':'timeout','minutes':5,'message':'Chat rules'},weak).status_code,403)
        self.assertEqual(self.post('/api/moderation/action',{'user_id':self.admin,'action':'timeout','minutes':5,'message':'Chat rules'},weak).status_code,403)
        self.assertEqual(self.post('/api/moderation/takeover',{'stage':1},weak).status_code,403)
        self.assertEqual(self.post('/api/admin/moderator',{'user_id':self.a,'enabled':True},weak).status_code,403)
        self.assertEqual(self.post('/api/admin/catalog',{'category':'buildings','key':'blocked','definition':{}},weak).status_code,403)

    def test_takeover_requires_ordered_single_use_actor_bound_confirmations(self):
        self.tile('200,200',self.a,'farm',2);moderator=self.login(self.mod)
        r=self.post('/api/moderation/takeover',{'stage':1,'grid_key':'200,200','to_id':self.b,'reason':'Resolve disputed land'},moderator);self.assertEqual(r.status_code,200,r.json);token=r.json['token']
        self.assertEqual(self.post('/api/moderation/takeover',{'stage':3,'token':token,'confirm':True},moderator).status_code,400)
        self.assertEqual(self.post('/api/moderation/takeover',{'stage':2,'token':token,'confirm':True},self.login(self.admin)).status_code,400)
        self.assertEqual(self.post('/api/moderation/takeover',{'stage':2,'token':token,'confirm':True},moderator).status_code,200)
        self.assertEqual(self.post('/api/moderation/takeover',{'stage':3,'token':token,'confirm':True},moderator).status_code,200)
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories').fetchone()[0],self.b)
        self.assertEqual(self.conn.execute('SELECT level FROM buildings').fetchone()[0],2)
        self.assertEqual(self.post('/api/moderation/takeover',{'stage':3,'token':token,'confirm':True},moderator).status_code,400)

    def test_gift_all_assets_and_tile_preserves_totals(self):
        self.tile('200,200',self.a,'farm',3)
        self.conn.execute('UPDATE users SET boats=10,planes=10,nukes=10,rockets=10,wood=10,steel=10,uranium=10,gems=10 WHERE id=?',(self.a,));self.conn.commit()
        before={key:self.balance(self.a,key)+self.balance(self.b,key) for key in expansion.ASSETS}
        give={key:2 for key in expansion.ASSETS};give['territories']=['200,200']
        r=self.post('/api/exchanges/send',{'to_id':self.b,'give':give});self.assertEqual(r.status_code,200,r.json)
        for key in expansion.ASSETS:self.assertEqual(self.balance(self.a,key)+self.balance(self.b,key),before[key])
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories').fetchone()[0],self.b)
        self.assertEqual(self.conn.execute('SELECT level FROM buildings').fetchone()[0],3)

    def test_offer_rechecks_balances_and_rejects_replay(self):
        r=self.post('/api/exchanges/send',{'to_id':self.b,'give':{'money':50},'want':{'metal':100}});self.assertEqual(r.status_code,200,r.json)
        oid=self.conn.execute('SELECT MAX(id) FROM exchanges').fetchone()[0];other=self.login(self.b)
        self.conn.execute('UPDATE users SET metal=0 WHERE id=?',(self.b,));self.conn.commit();before=self.balance(self.a,'money')
        self.assertEqual(self.post('/api/exchanges/respond',{'offer_id':oid,'action':'accept'},other).status_code,400)
        self.assertEqual(self.balance(self.a,'money'),before)
        self.conn.execute('UPDATE users SET metal=100 WHERE id=?',(self.b,));self.conn.commit()
        self.assertEqual(self.post('/api/exchanges/respond',{'offer_id':oid,'action':'accept'},other).status_code,200)
        self.assertEqual(self.balance(self.a,'money'),before-50)
        self.assertEqual(self.post('/api/exchanges/respond',{'offer_id':oid,'action':'accept'},other).status_code,404)

    def test_no_negative_or_fractional_assets_or_faction_vehicle_theft(self):
        for amount in (-1,1.5,True,float('inf')):
            self.assertEqual(self.post('/api/exchanges/send',{'to_id':self.b,'give':{'money':amount}}).status_code,400)
        fid=self.faction(self.a);features.join_faction(self.conn,self.b,fid);self.conn.execute('UPDATE users SET boats=100,share_boats=1 WHERE id=?',(self.b,));self.conn.commit()
        self.assertEqual(self.post('/api/exchanges/send',{'to_id':self.admin,'give':{'boats':1}}).status_code,400)

    def test_legacy_recurring_gift_accepts_zero_return(self):
        r=self.post('/api/trade/propose',{'to_id':self.b,'give_res':'money','give_amt':10,'get_res':'money','get_amt':0});self.assertEqual(r.status_code,200,r.json)
        tid=self.conn.execute('SELECT MAX(id) FROM trades').fetchone()[0]
        self.post('/api/trade/respond',{'trade_id':tid,'accept':True},self.login(self.b))
        self.conn.execute('UPDATE trades SET last_run=? WHERE id=?',(int(time.time())-601,tid));before=self.balance(self.a,'money')
        expansion.run_trades(self.conn,self.a);self.conn.commit();self.assertEqual(self.balance(self.a,'money'),before-10)

    def test_campaign_commit_commands_tick_and_refund(self):
        self.declare_war()
        self.tile('200,200',self.a);self.tile('200,201',self.b)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100,'tactic':'careful'});self.assertEqual(r.status_code,200,r.json);cid=r.json['campaign_id']
        self.assertEqual(app.pool_get(self.conn,self.a,'army'),900)
        self.assertEqual(self.post('/api/campaigns/order',{'campaign_id':cid,'action':'retreat'},self.login(self.b)).status_code,403)
        self.assertEqual(self.post('/api/campaigns/order',{'campaign_id':cid,'action':'posture','posture':'entrench'},self.login(self.b)).status_code,200)
        expansion.tick_campaigns(self.conn,int(time.time())+20);self.conn.commit()
        campaign=self.conn.execute('SELECT * FROM campaigns WHERE id=?',(cid,)).fetchone();self.assertLess(campaign['attack_org'],100);self.assertLess(campaign['defense_org'],100)
        remaining=campaign['troops'];self.assertEqual(self.post('/api/campaigns/order',{'campaign_id':cid,'action':'retreat'}).status_code,200)
        self.assertEqual(app.pool_get(self.conn,self.a,'army'),900+remaining)
        self.assertEqual(self.post('/api/campaigns/order',{'campaign_id':cid,'action':'retreat'}).status_code,404)

    def test_peacetime_attack_rejected_without_spending_troops(self):
        self.tile('200,200',self.a);self.tile('200,201',self.b)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100})
        self.assertEqual(r.status_code,400,r.json);self.assertIn('Declare war',r.json['error'])
        self.assertEqual(self.balance(self.a,'army'),1000)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0],0)

    def test_neutral_land_does_not_require_war(self):
        self.tile('200,200',self.a);self.tile('200,201',None)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100})
        self.assertEqual(r.status_code,200,r.json)

    def test_naval_and_air_attacks_require_war_without_spending_units(self):
        self.tile('200,200',self.a,'port');self.tile('200,210',self.b)
        self.conn.execute('UPDATE users SET boats=2,planes=2 WHERE id=?',(self.a,));self.conn.commit()
        with patch.object(app,'is_coastal',return_value=True):
            r=self.post('/api/boats/attack',{'from_key':'200,200','target_key':'200,210','boats':1})
        self.assertEqual(r.status_code,400,r.json);self.assertIn('Declare war',r.json['error'])
        self.conn.execute("UPDATE buildings SET type='airport' WHERE grid_key='200,200'");self.conn.commit()
        r=self.post('/api/planes/attack',{'from_key':'200,200','target_key':'200,210','planes':1})
        self.assertEqual(r.status_code,400,r.json);self.assertIn('Declare war',r.json['error'])
        for key,amount in (('army',1000),('boats',2),('planes',2)):
            self.assertEqual(self.balance(self.a,key),amount)

    def test_peace_stops_campaign_and_refunds_survivors(self):
        rid=self.declare_war();self.tile('200,200',self.a);self.tile('200,201',self.b)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100})
        self.assertEqual(r.status_code,200,r.json)
        self.conn.execute("UPDATE faction_rel SET status='ended' WHERE id=?",(rid,));self.conn.commit()
        expansion.tick_campaigns(self.conn,int(time.time())+20);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT status FROM campaigns').fetchone()[0],'ended')
        self.assertEqual(app.pool_get(self.conn,self.a,'army'),1000)
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',('200,201',)).fetchone()[0],self.b)

    def test_war_check_covers_individuals_allies_and_ended_wars(self):
        self.assertIsNotNone(app.attack_block(self.conn,self.a,self.b))
        rid=self.declare_war();self.assertIsNone(app.attack_block(self.conn,self.a,self.b))
        self.assertIsNone(app.attack_block(self.conn,self.a,None))
        self.conn.execute("UPDATE faction_rel SET kind='ally' WHERE id=?",(rid,))
        self.assertIsNotNone(app.attack_block(self.conn,self.a,self.b))
        self.conn.execute("UPDATE faction_rel SET kind='war',status='ended' WHERE id=?",(rid,))
        self.assertIsNotNone(app.attack_block(self.conn,self.a,self.b))

    def test_rocket_cannot_damage_peaceful_bystander(self):
        self.declare_war();self.tile('200,200',self.a,'rocket_pad');self.tile('200,201',self.b)
        self.tile('200,202',self.mod,'farm')
        self.conn.execute('UPDATE users SET rockets=1 WHERE id=?',(self.a,));self.conn.commit()
        r=self.post('/api/rockets/launch',{'from_key':'200,200','target_key':'200,201'})
        self.assertEqual(r.status_code,400,r.json);self.assertIn('Declare war',r.json['error'])
        self.assertEqual(self.balance(self.a,'rockets'),1)
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',('200,201',)).fetchone()[0],self.b)
        self.assertIsNotNone(self.conn.execute('SELECT * FROM buildings WHERE grid_key=?',('200,202',)).fetchone())

    def test_nuke_cannot_damage_peaceful_bystander(self):
        self.declare_war();self.tile('200,180',self.a,'silo');self.tile('200,201',self.b)
        self.tile('200,202',self.mod,'farm')
        self.conn.execute('UPDATE users SET nukes=1 WHERE id=?',(self.a,));self.conn.commit()
        with patch.object(app.random,'randint',return_value=5):
            r=self.post('/api/nuke/launch',{'from_key':'200,180','target_key':'200,201'})
        self.assertEqual(r.status_code,400,r.json);self.assertIn('Declare war',r.json['error'])
        self.assertEqual(self.balance(self.a,'nukes'),1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM fallout').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',('200,201',)).fetchone()[0],self.b)

    def test_nuke_allowed_against_country_at_war(self):
        self.declare_war();self.tile('200,180',self.a,'silo');self.tile('200,201',self.b)
        self.conn.execute('UPDATE users SET nukes=1 WHERE id=?',(self.a,));self.conn.commit()
        with patch.object(app.random,'randint',return_value=5):
            r=self.post('/api/nuke/launch',{'from_key':'200,180','target_key':'200,201'})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.balance(self.a,'nukes'),0)
        self.assertIsNone(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',('200,201',)).fetchone()[0])

    def test_campaign_can_capture_and_survives_migration(self):
        self.declare_war()
        self.tile('200,200',self.a);self.tile('200,201',self.b)
        self.conn.execute('UPDATE factions SET army=1 WHERE id=?',(app.fac_id(self.conn,self.b),));self.conn.commit()
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':1000,'tactic':'balanced'});self.assertEqual(r.status_code,200,r.json)
        expansion.migrate(app.get_db)
        for tick in range(1,12): expansion.tick_campaigns(self.conn,int(time.time())+tick*11);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key="200,201"').fetchone()[0],self.a)
        self.assertEqual(self.conn.execute('SELECT status FROM campaigns').fetchone()[0],'victory')

    def test_war_unlimited_and_nonleader_can_end_it(self):
        fa=self.faction(self.a);fb=self.faction(self.b)
        member=self.player('Member');features.join_faction(self.conn,member,fa)
        rid=self.conn.execute("INSERT INTO faction_rel(a,b,kind,status,ts,score_a,score_b) VALUES(?,?,'war','active',?,24,0)",(fa,fb,int(time.time()))).lastrowid
        expansion.war_score(self.conn,self.a,self.b);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT status FROM faction_rel WHERE id=?',(rid,)).fetchone()[0],'active')
        r=self.post('/api/faction/war/end',{'rel_id':rid,'action':'surrender'},self.login(member));self.assertEqual(r.status_code,200,r.json)

    def test_battle_data_and_defense_orders_are_private_to_participants(self):
        self.declare_war();member=self.player('Faction mate')
        features.join_faction(self.conn,member,app.fac_id(self.conn,self.b));self.conn.commit()
        self.tile('200,200',self.a);self.tile('200,201',self.b);self.tile('200,202',self.b)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','target_keys':['200,201','200,202'],'troops':100})
        self.assertEqual(r.status_code,200,r.json);cid=r.json['campaign_id']
        self.assertEqual(self.client.get('/api/campaigns').json['campaigns'][0]['targets_remaining'],['200,202'])
        self.assertEqual(self.login(self.b).get('/api/campaigns').json['campaigns'][0]['targets_remaining'],[])
        for uid in (member,self.admin,self.mod):self.assertEqual(self.login(uid).get('/api/campaigns').json['campaigns'],[])
        self.assertEqual(app.app.test_client().get('/api/campaigns').status_code,401)
        self.assertEqual(self.post('/api/campaigns/order',{'campaign_id':cid,'action':'posture','posture':'entrench'},self.login(member)).status_code,403)

    def test_planned_route_carries_survivors_to_next_target(self):
        self.declare_war();self.tile('200,200',self.a);self.tile('200,201',self.b);self.tile('200,202',self.b)
        self.conn.execute('UPDATE factions SET army=0 WHERE id=?',(app.fac_id(self.conn,self.b),));self.conn.commit()
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','target_keys':['200,201','200,202'],'troops':1000})
        self.assertEqual(r.status_code,200,r.json)
        stamp=int(time.time())
        payment=Mock(wraps=app.pay)
        with patch.dict(expansion.core,pay=payment):
            for tick in range(1,35):expansion.tick_campaigns(self.conn,stamp+tick*3)
        self.assertEqual(payment.call_count,1)
        charged=payment.call_args.args[2]
        self.assertGreater(charged['money'],0);self.assertGreater(charged['oil'],0)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM territories WHERE owner_id=?',(self.a,)).fetchone()[0],3)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0],1)
        c=self.conn.execute('SELECT * FROM campaigns').fetchone()
        self.assertEqual(c['status'],'victory');self.assertEqual(app.pool_get(self.conn,self.a,'army'),c['troops'])
        self.assertLess(self.balance(self.a,'oil'),9990)

    def test_land_travel_requires_both_resources_before_reserving_troops(self):
        self.tile('200,200',self.a)
        for resource in ('money','oil'):
            self.conn.execute('UPDATE users SET money=100000,oil=10000 WHERE id=?',(self.a,))
            self.conn.execute(f'UPDATE users SET {resource}=0 WHERE id=?',(self.a,));self.conn.commit()
            before={key:self.balance(self.a,key) for key in ('money','oil','army')}
            r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':1000})
            self.assertEqual(r.status_code,400,r.json)
            self.assertEqual(before,{key:self.balance(self.a,key) for key in before})
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0],0)

    def test_queued_land_surcharge_does_not_change_initial_or_air_costs(self):
        self.assertEqual(app.military_travel_cost('land',1000),{'money':100,'oil':10})
        self.assertEqual(app.military_travel_cost('land',1000,queued=True),{'money':125,'oil':13})
        self.assertEqual(app.military_travel_cost('air',2,10),{'money':400,'oil':20})
        self.assertEqual(app.military_travel_cost('air',2,10,queued=True),{'money':400,'oil':20})

    def test_queued_advance_stops_without_funds_and_refunds_survivors(self):
        self.tile('200,200',self.a)
        self.conn.execute('UPDATE users SET money=100,oil=10 WHERE id=?',(self.a,));self.conn.commit()
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','target_keys':['200,201','200,202'],'troops':1000})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.balance(self.a,'money'),0);self.assertEqual(self.balance(self.a,'oil'),0)
        for tick in range(1,35):expansion.tick_campaigns(self.conn,int(time.time())+tick*3)
        self.conn.commit();c=self.conn.execute('SELECT * FROM campaigns').fetchone()
        self.assertEqual(c['status'],'victory');self.assertIn('not enough money and oil',c['summary'])
        self.assertEqual(c['target_key'],'200,201');self.assertEqual(self.balance(self.a,'army'),c['troops'])
        self.assertIsNone(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key="200,202"').fetchone())

    def test_air_travel_charges_distance_and_rejects_insufficient_funds(self):
        self.tile('200,200',self.a,'airport');self.conn.execute('UPDATE users SET planes=10 WHERE id=?',(self.a,));self.conn.commit()
        for resource in ('money','oil'):
            self.conn.execute('UPDATE users SET money=100000,oil=10000 WHERE id=?',(self.a,))
            self.conn.execute(f'UPDATE users SET {resource}=0 WHERE id=?',(self.a,));self.conn.commit()
            before={key:self.balance(self.a,key) for key in ('money','oil','planes','army')}
            r=self.post('/api/planes/attack',{'from_key':'200,200','target_key':'200,210','planes':2})
            self.assertEqual(r.status_code,400,r.json);self.assertEqual(before,{key:self.balance(self.a,key) for key in before})
        self.conn.execute('UPDATE users SET money=100000,oil=10000 WHERE id=?',(self.a,));self.conn.commit()
        result=dict(win=False,A=1,D=2,weather='clear',amods=[],dmods=[],msg='Test retreat')
        with patch.dict(app.planes_attack.__wrapped__.__globals__,do_assault=lambda *args:result,award_achievements=lambda *args:[]):
            r=self.post('/api/planes/attack',{'from_key':'200,200','target_key':'200,210','planes':2})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['travel_cost'],{'money':400,'oil':20})
        self.assertEqual(self.balance(self.a,'money'),99600);self.assertEqual(self.balance(self.a,'oil'),9980)

    def test_invalid_plans_do_not_reserve_troops(self):
        self.declare_war();self.tile('200,200',self.a);self.tile('200,201',self.b)
        for route in ([],['200,201','200,201'],['200,201','200,205'],['200,202'],['200,201',False],['200,201']*65):
            r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','target_keys':route,'troops':100})
            self.assertEqual(r.status_code,400,r.json)
        self.assertEqual(app.pool_get(self.conn,self.a,'army'),1000)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0],0)

    def test_bulk_unit_and_weapon_purchases_follow_affordability(self):
        self.tile('200,200',self.a,'port');self.tile('200,201',self.a,'airport')
        self.tile('200,202',self.a,'uranium_mine');self.tile('200,203',self.a,'enrichment');self.tile('200,204',self.a,'nuclear_plant');self.tile('200,205',self.a,'rocket_pad')
        self.conn.execute('UPDATE users SET research=?,money=1000000000000,wood=100000000,metal=100000000,oil=100000000,steel=100000000,uranium=100000000 WHERE id=?',
            (json.dumps(['shipyard','airforce','nuclear_physics','rocketry','manhattan']),self.a));self.conn.commit()
        for path,key in (('/api/troops/build','army'),('/api/boats/build','boats'),('/api/planes/build','planes'),('/api/rockets/build','rockets'),('/api/nuke/build','nukes')):
            before=self.balance(self.a,key)
            r=self.post(path,{'grid_key':'200,200','amount':5000})
            self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.balance(self.a,key),before+5000)
            self.assertEqual(self.post(path,{'grid_key':'200,200','amount':0}).status_code,400)

    def test_changelog_acknowledges_shown_version_without_regressing_seen(self):
        self.conn.execute('UPDATE users SET last_seen_version=? WHERE id=?',('6.3.6',self.a));self.conn.commit()
        self.assertEqual(self.post('/api/changelog/seen',{'version':'6.4.1'}).status_code,200)
        self.assertEqual(self.client.get('/api/changelog').json['show'],True)
        self.assertEqual(self.post('/api/changelog/seen',{'version':'6.3.6'}).status_code,200)
        self.assertEqual(self.balance(self.a,'last_seen_version'),'6.4.1')
        self.assertEqual(self.post('/api/changelog/seen',{'version':'99.0.0'}).status_code,400)
        self.assertEqual(self.post('/api/changelog/seen',{}).status_code,200)
        self.assertEqual(self.client.get('/api/changelog').json['show'],False)

    def test_route_stops_if_next_target_leaves_war(self):
        self.declare_war();self.tile('200,200',self.a);self.tile('200,201',self.b);self.tile('200,202',self.b)
        self.conn.execute('UPDATE factions SET army=0 WHERE id=?',(app.fac_id(self.conn,self.b),));self.conn.commit()
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','target_keys':['200,201','200,202'],'troops':1000})
        self.assertEqual(r.status_code,200,r.json)
        self.conn.execute('UPDATE territories SET owner_id=? WHERE grid_key=?',(self.mod,'200,202'));self.conn.commit()
        for tick in range(1,20):expansion.tick_campaigns(self.conn,int(time.time())+tick*3)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',('200,202',)).fetchone()[0],self.mod)
        self.assertEqual(self.conn.execute('SELECT status FROM campaigns').fetchone()[0],'victory')

    def test_survivors_return_to_original_faction_after_commander_leaves(self):
        self.declare_war();original=app.fac_id(self.conn,self.a)
        member=self.player('Remain');features.join_faction(self.conn,member,original);self.conn.commit()
        self.tile('200,200',self.a);self.tile('200,201',self.b)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100})
        self.assertEqual(r.status_code,200,r.json)
        self.conn.execute('UPDATE users SET faction_id=NULL WHERE id=?',(self.a,));self.conn.commit()
        before=self.conn.execute('SELECT army FROM factions WHERE id=?',(original,)).fetchone()[0]
        expansion.tick_campaigns(self.conn,int(time.time())+20);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT army FROM factions WHERE id=?',(original,)).fetchone()[0],before+100)
        self.assertEqual(self.balance(self.a,'army'),0)

    def test_player_reset_cannot_restore_old_committed_troops_on_next_tick(self):
        self.declare_war();self.tile('200,200',self.a);self.tile('200,201',self.b)
        self.assertEqual(self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100}).status_code,200)
        r=self.post('/api/admin/player',{'user_id':self.a,'action':'reset','confirm':True},self.login(self.admin))
        self.assertEqual(r.status_code,200,r.json)
        expansion.tick_campaigns(self.conn,int(time.time())+20);self.conn.commit()
        self.assertEqual(self.balance(self.a,'army'),10)
        self.assertEqual(self.conn.execute('SELECT status FROM campaigns').fetchone()[0],'ended')

    def test_recent_history_does_not_hide_older_active_battles(self):
        self.declare_war();self.tile('200,200',self.a);self.tile('200,201',self.b)
        r=self.post('/api/attack',{'from_key':'200,200','target_key':'200,201','troops':100});cid=r.json['campaign_id']
        for _ in range(80):
            self.conn.execute("INSERT INTO campaigns(attacker,defender,from_key,target_key,troops,initial_troops,status) VALUES(?,?,'200,200','200,201',0,10,'retreated')",(self.a,self.b))
        self.conn.commit();rows=self.client.get('/api/campaigns').json['campaigns']
        self.assertEqual(rows[0]['id'],cid);self.assertEqual(rows[0]['status'],'active')
        self.assertEqual(len(rows),21)

    def test_game_editor_rejects_regular_players_and_moderators(self):
        definition={'category':'buildings','item_key':'blocked_test','definition':{'name':'Forbidden','cost':{'money':1},'production':{'money':1000}}}
        self.assertEqual(self.post('/api/admin/catalog',definition).status_code,403)
        self.assertEqual(self.post('/api/admin/catalog',definition,self.login(self.mod)).status_code,403)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM live_catalog WHERE item_key='blocked_test'").fetchone())

    def test_rocket_cost_damage_cooldown_and_ownership(self):
        self.declare_war()
        self.tile('200,200',self.a,'rocket_pad');self.tile('200,201',self.b,'fort',2)
        money=self.balance(self.a,'money');r=self.post('/api/rockets/build',{'amount':2});self.assertEqual(r.status_code,200,r.json);self.assertEqual(self.balance(self.a,'money'),money-3000)
        r=self.post('/api/rockets/launch',{'from_key':'200,200','target_key':'200,201'});self.assertEqual(r.status_code,200,r.json)
        self.assertIsNone(self.conn.execute('SELECT level FROM buildings WHERE grid_key="200,201"').fetchone())
        self.assertIsNone(self.conn.execute('SELECT owner_id FROM territories WHERE grid_key="200,201"').fetchone()[0])
        self.assertFalse(self.conn.execute('SELECT 1 FROM fallout WHERE grid_key="200,201"').fetchone())
        self.assertEqual(self.post('/api/rockets/launch',{'from_key':'200,200','target_key':'200,201'}).status_code,400)
        self.assertEqual(self.balance(self.a,'rockets'),1)
        self.assertEqual(self.client.get('/api/strikes').json['events'][-1]['kind'],'rocket')

    def test_casino_ownership_limits_and_exact_payout(self):
        self.tile('200,200',self.a,'casino',1);before=self.balance(self.a,'money')
        self.assertEqual(self.post('/api/casino/play',{'grid_key':'200,200','bet':100,'choice':'seven'},self.login(self.b)).status_code,400)
        self.assertEqual(self.post('/api/casino/play',{'grid_key':'200,200','bet':1001,'choice':'seven'}).status_code,400)
        with patch('expansion.secrets.randbelow',side_effect=[2,3]):
            r=self.post('/api/casino/play',{'grid_key':'200,200','bet':100,'choice':'seven'})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['dice'],[3,4]);self.assertEqual(self.balance(self.a,'money'),before+400)
        self.assertEqual(self.post('/api/casino/play',{'grid_key':'200,200','bet':100,'choice':'seven'}).status_code,400)

    def test_building_counts_and_repeat_migration_preserve_save(self):
        self.tile('200,200',self.a,'farm',2);self.tile('200,201',self.a,'farm',3)
        r=self.client.get('/api/me');self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['building_counts']['farm'],{'count':2,'levels':5})
        money=self.balance(self.a,'money');expansion.migrate(app.get_db);expansion.migrate(app.get_db)
        self.assertEqual(self.balance(self.a,'money'),money);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM territories').fetchone()[0],2)


if __name__=='__main__': unittest.main()
