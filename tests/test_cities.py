"""Capital/city mechanics on disposable saves; no production accounts or geography edits."""
import json,time,unittest
from concurrent.futures import ThreadPoolExecutor
import test_expansion as fixture
from test_upgrade import app
from geography import cell_land
import cities

class CityTests(unittest.TestCase):
    setUpClass=classmethod(fixture.ExpansionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.ExpansionTests.tearDownClass.__func__)
    setUp=fixture.ExpansionTests.setUp
    player=fixture.ExpansionTests.player
    login=fixture.ExpansionTests.login
    post=fixture.ExpansionTests.post
    tile=fixture.ExpansionTests.tile
    balance=fixture.ExpansionTests.balance

    def capital(self,key='200,200',building=None,level=1):
        self.tile(key,self.a,building,level)
        self.conn.execute('UPDATE users SET capital_key=?,capital_ts=? WHERE id=?',(key,int(time.time()),self.a))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE grid_key=?',(int(time.time()),key));self.conn.commit()
        return key

    def test_city_registry_is_saved_playable_deterministic_and_public(self):
        rows=cities.catalog()['cities'];self.assertGreater(len(rows),1500)
        self.assertEqual(len({r['id'] for r in rows}),len(rows))
        for row in rows:
            self.assertTrue(row['population']>=250000 or row['national_capital'])
            self.assertTrue(cell_land(row['grid_key']),row['name'])
        for name in ('Oslo','London','Tokyo','New York'):
            self.assertTrue(any(r['name']==name for r in rows),name)
        response=app.app.test_client().get('/api/cities');self.assertEqual(response.status_code,200)
        self.assertNotIn('owner_id',response.json['cities'][0]);self.assertIn('public',response.headers['Cache-Control'])
        response.close()
        csv=app.app.test_client().get('/api/cities.csv');self.assertEqual(csv.status_code,200);self.assertIn(b'grid_key',csv.data);csv.close()

    def test_city_and_capital_buffs_stack_once_and_are_local(self):
        self.assertEqual(cities.bonuses(None,{'key':None,'districts':{}})['base_troops'],0)
        key=next(k for k,v in cities.city_index().items() if len(v)>1)
        self.capital(key,'barracks',2)
        self.conn.execute('INSERT INTO capital_districts VALUES(?,?,?)',(key,'military_academy',1));self.conn.commit()
        context=app.yield_ctx(self.conn,self.a)
        ordinary=app.tile_yield(context,'plains','barracks',2)
        special=app.tile_yield(context,'plains','barracks',2,key)
        for resource,value in ordinary.items():self.assertAlmostEqual(special[resource],value*3)
        self.assertEqual(cities.troops(context,key,'barracks',2,app.BUILDINGS),(6+12+60)*3)
        self.assertEqual(cities.troops(context,'200,200','barracks',2,app.BUILDINGS),6)
        self.assertEqual(cities.bonuses(key,context['capital'])['defense'],1.25*1.75)

    def test_collection_and_displayed_rates_agree_including_fractional_recruitment(self):
        key=self.capital('200,200','barracks',2);stamp=int(time.time())
        self.conn.execute('INSERT INTO capital_districts VALUES(?,?,?)',(key,'royal_treasury',1))
        self.conn.execute('UPDATE territories SET last_collected=? WHERE grid_key=?',(stamp-60,key));self.conn.commit()
        rates,recruits,_=app.income_rates(self.conn,self.a);before=self.balance(self.a,'money');army=app.pool_get(self.conn,self.a,'army')
        from unittest.mock import patch
        with patch('time.time',return_value=stamp):app.auto_collect(self.a,self.conn,force=True)
        self.assertAlmostEqual(self.balance(self.a,'money')-before,rates['money'])
        self.assertEqual(app.pool_get(self.conn,self.a,'army')-army,recruits)

    def test_upgrades_keep_normal_building_and_enforce_costs_owner_and_level_limit(self):
        key=self.capital(building='farm');self.conn.execute('UPDATE users SET money=1000000000,metal=1000000,wood=1000000,steel=1000000 WHERE id=?',(self.a,));self.conn.commit()
        self.assertEqual(app.app.test_client().get('/api/capital').status_code,401)
        self.assertEqual(self.post('/api/capital/district',{'type':'civic_center','grid_key':key},self.login(self.b)).status_code,403)
        before=self.balance(self.a,'money')
        result=self.post('/api/capital/district',{'type':'civic_center','grid_key':key})
        self.assertEqual(result.status_code,200,result.json);self.assertEqual(before-self.balance(self.a,'money'),25000)
        self.assertEqual(self.conn.execute('SELECT type FROM buildings WHERE grid_key=?',(key,)).fetchone()[0],'farm')
        self.assertEqual(self.client.get('/api/capital').json['districts'][0]['level'],1)
        self.conn.execute('UPDATE capital_districts SET level=10 WHERE grid_key=?',(key,));self.conn.commit()
        before=self.balance(self.a,'money');self.assertEqual(self.post('/api/capital/district',{'type':'civic_center','grid_key':key}).status_code,400)
        self.assertEqual(before,self.balance(self.a,'money'))
        self.assertEqual(self.post('/api/capital/district',{'type':[],'grid_key':key}).status_code,400)

    def test_capital_move_settles_old_rates_and_dormant_districts_reactivate_only_at_current_capital(self):
        old=self.capital();self.tile('201,200',self.a)
        self.conn.execute('INSERT INTO capital_districts VALUES(?,?,?)',(old,'command_bunker',4))
        self.conn.execute('UPDATE users SET capital_ts=0 WHERE id=?',(self.a,));self.conn.commit()
        result=self.post('/api/capital/set',{'grid_key':'201,200'});self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(cities.capital_context(self.conn,self.a),{'key':'201,200','districts':{}})
        self.assertEqual(cities.bonuses(old,cities.capital_context(self.conn,self.a))['defense'],1)
        self.assertEqual(self.conn.execute('SELECT level FROM capital_districts WHERE grid_key=?',(old,)).fetchone()[0],4)
        self.assertEqual(self.post('/api/capital/set',{'grid_key':old}).status_code,400)

    def test_capture_transfers_dormant_districts_and_abandonment_cleans_them(self):
        key=self.capital();self.conn.execute('INSERT INTO capital_districts VALUES(?,?,?)',(key,'imperial_guard',2));self.conn.commit()
        tile=self.conn.execute('SELECT * FROM territories WHERE grid_key=?',(key,)).fetchone()
        app.apply_victory(self.conn,self.b,key,'plains',tile,200,200)
        self.assertIsNone(cities.capital_context(self.conn,self.a)['key'])
        self.assertEqual(cities.capital_context(self.conn,self.b)['districts'],{})
        self.conn.execute('UPDATE users SET capital_key=? WHERE id=?',(key,self.b))
        self.assertEqual(cities.capital_context(self.conn,self.b)['districts'],{'imperial_guard':2})
        self.conn.execute('UPDATE territories SET owner_id=NULL WHERE grid_key=?',(key,))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM capital_districts WHERE grid_key=?',(key,)).fetchone()[0],0)

    def test_simultaneous_upgrades_cannot_double_spend(self):
        key=self.capital();self.conn.execute('UPDATE users SET money=25000,wood=1500,metal=500 WHERE id=?',(self.a,));self.conn.commit()
        first,second=self.login(self.a),self.login(self.a)
        def upgrade(client):return self.post('/api/capital/district',{'type':'civic_center','grid_key':key},client).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(upgrade,(first,second)))
        self.assertEqual(sorted(statuses),[200,400]);self.assertEqual(self.balance(self.a,'money'),0)
        self.assertEqual(self.conn.execute('SELECT level FROM capital_districts WHERE grid_key=?',(key,)).fetchone()[0],1)

    def test_detail_exposes_named_city_and_actual_defense_modifier(self):
        key=cities.catalog()['cities'][0]['grid_key'];self.capital(key)
        response=self.client.get('/api/territory/'+key);self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(response.json['cities']);self.assertEqual(response.json['urban_bonuses']['production'],3)
        defense=app.defense_of(self.conn,self.a,key,'plains')
        self.assertIn(('City / capital stronghold',1.25*1.75),defense['mods'])
        self.conn.execute('INSERT INTO capital_districts VALUES(?,?,?)',(key,'command_bunker',2))
        self.assertGreater(app.defense_of(self.conn,self.a,key,'plains')['mult'],defense['mult'])

if __name__=='__main__':unittest.main()
