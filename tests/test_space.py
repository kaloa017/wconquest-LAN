"""Expeditions exercise real authenticated routes against a disposable save."""
import json
import time
import unittest
from unittest.mock import patch
import test_expansion as fixture
from test_upgrade import app
import space
from config import SPACE_BUSINESSES, SPACE_PLANETS, SPACE_CARGO_CAPACITY, SPACE_IRIDIUM_PRICE, MAX_ACCUM_MINS


class SpaceTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    balance=fixture.ExpansionTests.balance
    tile=fixture.ExpansionTests.tile

    def unlock(self,uid=None):
        uid=self.a if uid is None else uid
        key='200,200' if uid==self.a else '210,210'
        self.conn.execute("UPDATE users SET research=?,money=1000000000000,steel=100000000,uranium=100000000,gems=100000000,oil=100000000 WHERE id=?",(json.dumps(['manhattan','spaceflight']),uid))
        self.conn.commit();self.tile(key,uid,'space_agency',3)
        client=self.client if uid==self.a else self.login(uid)
        self.assertEqual(client.get('/api/space').status_code,200)

    def program(self):return dict(self.conn.execute('SELECT * FROM space_program WHERE user_id=?',(self.a,)).fetchone())

    def arrive(self):
        self.conn.execute('UPDATE space_program SET arrival=? WHERE user_id=?',(int(time.time())-1,self.a));self.conn.commit()
        return self.client.get('/api/space').json

    def test_unlock_requires_personal_agency_and_tutorial_ack(self):
        self.assertFalse(self.client.get('/api/space').json['unlocked'])
        self.assertEqual(self.post('/api/space/business',{'business':'satellite','quantity':1}).status_code,400)
        self.unlock();self.assertTrue(self.client.get('/api/space').json['tutorial_required'])
        self.assertEqual(self.post('/api/space/tutorial/seen',{}).status_code,200)
        self.assertFalse(self.client.get('/api/space').json['tutorial_required'])
        self.conn.execute("DELETE FROM buildings WHERE type='space_agency'");self.conn.commit()
        self.assertFalse(self.client.get('/api/space').json['unlocked'])

    def test_orbital_purchase_has_no_arbitrary_quantity_cap(self):
        self.unlock();before=self.balance(self.a,'money')
        r=self.post('/api/space/business',{'business':'satellite','quantity':5000})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.balance(self.a,'money'),before-5000*SPACE_BUSINESSES['satellite']['cost']['money'])
        self.assertEqual(self.client.get('/api/space').json['holdings']['satellite'],5000)

    def test_orbital_income_settled_before_purchase_and_bounded_offline(self):
        self.unlock();self.post('/api/space/business',{'business':'satellite','quantity':1})
        stamp=int(time.time());self.conn.execute('UPDATE space_program SET collected=? WHERE user_id=?',(stamp-20,self.a));self.conn.commit()
        before=self.balance(self.a,'money')
        with patch.object(space.time,'time',return_value=stamp):r=self.post('/api/space/business',{'business':'satellite','quantity':1})
        self.assertEqual(r.status_code,200,r.json)
        self.assertAlmostEqual(self.balance(self.a,'money'),before-5000000+20000*20/60,places=2)
        before=self.balance(self.a,'money');space.collect_space(self.conn,self.a,stamp+86400);self.conn.commit()
        self.assertAlmostEqual(self.balance(self.a,'money')-before,40000*MAX_ACCUM_MINS,places=2)
        space.collect_space(self.conn,self.a,stamp+86400);self.conn.commit()
        self.assertAlmostEqual(self.balance(self.a,'money')-before,40000*MAX_ACCUM_MINS,places=2)

    def test_expensive_round_trip_is_paid_once_and_cargo_delivered_once(self):
        self.unlock();before=self.balance(self.a,'money')
        r=self.post('/api/space/depart',{'planet':'moon'});self.assertEqual(r.status_code,200,r.json)
        fees=SPACE_PLANETS['moon']['outbound']['money']+SPACE_PLANETS['moon']['return']['money']
        self.assertEqual(self.balance(self.a,'money'),before-fees)
        self.assertEqual(self.post('/api/space/depart',{'planet':'moon'}).status_code,400)
        self.assertEqual(self.post('/api/space/mine',{'x':3,'y':3}).status_code,400)
        self.assertEqual(self.arrive()['program']['state'],'surface')
        self.conn.execute('UPDATE space_program SET cargo=? WHERE user_id=?',(json.dumps({'iridium':7,'gems':20}),self.a));self.conn.commit()
        before=self.balance(self.a,'money');gems=self.balance(self.a,'gems')
        self.assertEqual(self.post('/api/space/return',{}).status_code,200)
        self.assertEqual(self.post('/api/space/return',{}).status_code,400)
        self.assertEqual(self.balance(self.a,'money'),before)
        self.assertEqual(self.arrive()['program']['state'],'earth')
        self.assertEqual(self.balance(self.a,'money'),before+7*SPACE_IRIDIUM_PRICE)
        self.assertEqual(self.balance(self.a,'gems'),gems+20)
        self.client.get('/api/space');self.assertEqual(self.balance(self.a,'money'),before+7*SPACE_IRIDIUM_PRICE)
        self.assertEqual(self.program()['cargo'],'{}');self.assertIn('moon',json.loads(self.program()['visited']))

    def test_personal_maps_are_identical_and_cannot_be_monopolized(self):
        self.unlock();self.unlock(self.b);other=self.login(self.b)
        self.post('/api/space/depart',{'planet':'moon'});self.post('/api/space/depart',{'planet':'moon'},other)
        self.conn.execute("UPDATE space_program SET arrival=0");self.conn.commit()
        one=self.client.get('/api/space').json;two=other.get('/api/space').json
        self.assertEqual(one['tiles'],two['tiles']);self.assertEqual(len(one['tiles']),36)
        self.assertEqual(self.post('/api/space/mine',{'x':3,'y':3,'user_id':self.b}).status_code,200)
        self.assertEqual(other.get('/api/space').json['tiles'][21]['level'],0)
        self.assertEqual(self.client.get('/api/space').json['tiles'][21]['level'],1)
        self.assertEqual(other.get('/api/space?user_id='+str(self.a)).json['program']['user_id'],self.b)

    def test_mines_require_adjacency_and_stop_at_cargo_capacity(self):
        self.unlock();self.post('/api/space/depart',{'planet':'moon'});self.arrive()
        self.assertEqual(self.post('/api/space/mine',{'x':0,'y':0}).status_code,400)
        self.assertEqual(self.post('/api/space/mine',{'x':3,'y':3}).status_code,200)
        self.assertEqual(self.post('/api/space/mine',{'x':4,'y':3}).status_code,200)
        stamp=int(time.time());self.conn.execute('UPDATE space_program SET last_mined=?,cargo=? WHERE user_id=?',(stamp-7200,json.dumps({'gems':SPACE_CARGO_CAPACITY-1}),self.a));self.conn.commit()
        space.collect_space(self.conn,self.a,stamp);self.conn.commit()
        cargo=json.loads(self.program()['cargo']);self.assertAlmostEqual(sum(cargo.values()),SPACE_CARGO_CAPACITY)
        space.collect_space(self.conn,self.a,stamp+7200);self.conn.commit()
        self.assertEqual(json.loads(self.program()['cargo']),cargo)

    def test_planet_gates_and_retained_mines(self):
        self.unlock();self.assertEqual(self.post('/api/space/depart',{'planet':'mars'}).status_code,400)
        self.post('/api/space/depart',{'planet':'moon'});self.arrive();self.post('/api/space/mine',{'x':3,'y':3})
        self.post('/api/space/return',{});self.arrive()
        self.assertEqual(self.post('/api/space/depart',{'planet':'mars'}).status_code,200)
        self.arrive();self.post('/api/space/return',{});self.arrive()
        self.assertEqual(self.post('/api/space/depart',{'planet':'europa'}).status_code,200)
        self.arrive();self.post('/api/space/return',{});self.arrive()
        self.post('/api/space/depart',{'planet':'moon'});snapshot=self.arrive()
        self.assertEqual(snapshot['tiles'][21]['level'],1)

    def test_agency_loss_does_not_strand_prepaid_return(self):
        self.unlock();self.post('/api/space/depart',{'planet':'moon'});self.arrive()
        self.conn.execute("DELETE FROM buildings WHERE type='space_agency'");self.conn.commit()
        self.assertEqual(self.post('/api/space/return',{}).status_code,200)
        self.assertEqual(self.arrive()['program']['state'],'earth')

    def test_bad_inputs_and_insufficient_money_leave_balances_unchanged(self):
        self.unlock();before=self.balance(self.a,'money')
        for amount in (0,-1,1.5,True,2**53):
            self.assertEqual(self.post('/api/space/business',{'business':'satellite','quantity':amount}).status_code,400)
        self.assertEqual(self.post('/api/space/business',{'business':'bogus','quantity':1}).status_code,400)
        self.assertEqual(self.post('/api/space/business',{'business':[],'quantity':1}).status_code,400)
        self.assertEqual(self.post('/api/space/depart',{'planet':{}}).status_code,400)
        self.assertEqual(self.balance(self.a,'money'),before)
        self.conn.execute('UPDATE users SET money=1 WHERE id=?',(self.a,));self.conn.commit()
        self.assertEqual(self.post('/api/space/depart',{'planet':'moon'}).status_code,400)
        self.assertEqual(self.balance(self.a,'money'),1);self.assertEqual(self.program()['state'],'earth')
        self.assertEqual(app.app.test_client().get('/api/space').status_code,401)

    def test_migration_is_idempotent_and_preserves_existing_progress(self):
        self.unlock();self.post('/api/space/business',{'business':'satellite','quantity':2})
        before=self.balance(self.a,'money');program=self.program()
        app.migrate_v14(app.get_db);app.migrate_v15(app.get_db)
        self.assertEqual(self.balance(self.a,'money'),before);self.assertEqual(self.program(),program)
        self.assertEqual(self.client.get('/api/space').json['holdings']['satellite'],2)

    def test_mine_income_is_settled_before_upgrade(self):
        self.unlock();self.post('/api/space/depart',{'planet':'moon'});self.arrive();self.post('/api/space/mine',{'x':3,'y':3})
        stamp=int(time.time());self.conn.execute('UPDATE space_program SET last_mined=? WHERE user_id=?',(stamp-20,self.a));self.conn.commit()
        with patch.object(space.time,'time',return_value=stamp):self.assertEqual(self.post('/api/space/mine',{'x':3,'y':3}).status_code,200)
        resource=space.resource_at('moon',3,3)
        self.assertAlmostEqual(json.loads(self.program()['cargo'])[resource],space.SPACE_RESOURCE_RATES[resource]*20/60)

    def test_admin_reset_clears_space_progress_only_for_selected_player(self):
        self.unlock();self.unlock(self.b);self.post('/api/space/business',{'business':'satellite','quantity':1})
        r=self.post('/api/admin/player',{'user_id':self.a,'action':'reset','confirm':True},self.login(self.admin))
        self.assertEqual(r.status_code,200,r.json)
        self.assertIsNone(self.conn.execute('SELECT * FROM space_program WHERE user_id=?',(self.a,)).fetchone())
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM space_businesses WHERE user_id=?',(self.a,)).fetchone()[0],0)
        self.assertIsNotNone(self.conn.execute('SELECT * FROM space_program WHERE user_id=?',(self.b,)).fetchone())

    def test_income_projection_includes_orbital_businesses(self):
        self.unlock();self.post('/api/space/business',{'business':'satellite','quantity':2})
        projection=self.client.get('/api/income').json
        self.assertEqual(projection['orbital_rates']['money'],40000)
        self.assertGreaterEqual(projection['rates']['money'],40000)
        self.assertGreaterEqual(projection['totals']['money'],40000*projection['minutes'])

    def test_concurrent_arrival_cannot_deliver_cargo_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        self.unlock();self.conn.execute("UPDATE space_program SET state='returning',planet='moon',arrival=0,cargo=? WHERE user_id=?",(json.dumps({'iridium':7}),self.a));self.conn.commit()
        before=self.balance(self.a,'money');clients=[self.login(self.a),self.login(self.a)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses=list(executor.map(lambda client:client.get('/api/space'),clients))
        self.assertTrue(all(r.status_code==200 for r in responses))
        self.assertEqual(self.balance(self.a,'money'),before+7*SPACE_IRIDIUM_PRICE)
        self.assertEqual(self.program()['cargo'],'{}')
