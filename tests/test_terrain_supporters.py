import os,sys,tempfile,unittest,json,time,math,sqlite3
from pathlib import Path
os.environ['DISABLE_SCHEDULER']='1';sys.dont_write_bytecode=True
PROJECT=Path(__file__).resolve().parents[1]
scratch=tempfile.TemporaryDirectory(dir=PROJECT/'tests');os.environ['DB_PATH']=str(Path(scratch.name)/'game.db');sys.path.insert(0,str(PROJECT))
import app,features,geography
from migrations import migrate_v7,backup_before_upgrade
class TerrainSupporterTests(unittest.TestCase):
    serial=0
    def setUp(self):
        self.client=app.app.test_client();features._limits.clear();features._rate_settings.update(requests=0,auth=0,chat=0,trades=0);app.CHAT_COOLDOWN=0
        self.csrf=self.client.get('/api/bootstrap').json['csrf']
        TerrainSupporterTests.serial+=1;self.name='Terrain Test '+str(self.serial)
        self.assertEqual(self.post('/api/register',{'username':self.name,'password':'testpassword'}).status_code,200)
        self.assertEqual(self.post('/api/login',{'username':self.name,'password':'testpassword'}).status_code,200)
        self.uid=self.client.get('/api/me').json['id']
    def post(self,path,data):return self.client.post(path,json=data,headers={'X-WC-CSRF':self.csrf})
    def admin(self):
        conn=app.get_db();conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.uid,));conn.commit();conn.close()
    def test_unlimited_and_configurable_limits(self):
        self.assertTrue(all(features.rate_allowed('test',0) for _ in range(20000)));self.assertNotIn('test',features._limits)
        for _ in range(260):self.assertEqual(self.client.get('/api/bootstrap').status_code,200)
        for _ in range(15):self.assertNotEqual(self.post('/api/login',{'username':'Missing','password':'badpassword'}).status_code,429)
        for i in range(3):self.assertEqual(self.post('/api/chat/send',{'message':str(i),'channel':'global'}).status_code,200)
        self.assertEqual(self.post('/api/admin/rate_limits',{'requests':2,'auth':0,'chat':0,'trades':0}).status_code,403)
        self.admin();self.assertEqual(self.post('/api/admin/rate_limits',{'requests':2,'auth':0,'chat':0,'trades':0}).status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,200);self.assertEqual(self.client.get('/api/bootstrap').status_code,200);self.assertEqual(self.client.get('/api/bootstrap').status_code,429)
        features._limits.clear();self.assertEqual(self.post('/api/admin/rate_limits',{'requests':0,'auth':0,'chat':0,'trades':0}).status_code,200)
        conn=app.get_db();saved=json.loads(app.get_setting(conn,'rate_limits'));conn.close();self.assertEqual(saved,{'requests':0,'auth':0,'chat':0,'trades':0})
        self.assertEqual(self.post('/api/admin/rate_limits',{'requests':-1,'auth':0}).status_code,400)
        self.assertEqual(self.post('/api/admin/rate_limits',{'requests':0,'auth':0,'chat':3,'trades':4}).status_code,200)
        self.assertEqual(self.post('/api/chat/send',{'message':'too fast'}).status_code,429)
        self.post('/api/admin/rate_limits',{'requests':0,'auth':0,'chat':0,'trades':0})
    def test_donator_is_admin_managed_and_cosmetic(self):
        before=self.client.get('/api/me').json
        self.assertEqual(self.post('/api/profile/preferences',{'donator_title':'Patron'}).status_code,403)
        self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'donator','enabled':True}).status_code,403)
        self.admin();self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'donator','enabled':True}).status_code,200)
        self.assertEqual(self.post('/api/profile/preferences',{'donator_title':'<script>'}).status_code,400)
        self.assertEqual(self.post('/api/profile/preferences',{'donator_title':'Patron'}).status_code,200)
        after=self.client.get('/api/me').json;self.assertTrue(after['is_donator']);self.assertEqual(after['donator_title'],'Patron')
        for k in ('money','army','food','wood','metal','oil','rank'):self.assertEqual(before[k],after[k])
        row=next(p for p in self.client.get('/api/leaderboard').json if p['id']==self.uid);self.assertTrue(row['is_donator'])
        self.post('/api/chat/send',{'message':'Supporter message'});self.assertTrue(self.client.get('/api/chat').json['messages'][-1]['is_donator'])
        self.post('/api/admin/player',{'user_id':self.uid,'action':'donator','enabled':False});self.assertFalse(self.client.get('/api/me').json['is_donator'])
        self.assertEqual(self.post('/api/profile/preferences',{'donator_title':'Supporter'}).status_code,403)
    def test_precise_iceland_and_independent_islands(self):
        inland=f'{math.floor(65.267/.18)},{math.floor(-14.394/.18)}';ocean=f'{math.floor(65.25/.18)},{math.floor(-13.5/.18)}'
        self.assertTrue(geography.cell_land(inland));self.assertFalse(geography.cell_land(ocean))
        conn=app.get_db();conn.execute('INSERT OR REPLACE INTO water_cells VALUES(?,1)',(inland,));conn.execute('INSERT OR REPLACE INTO water_cells VALUES(?,0)',(ocean,));conn.commit()
        self.assertFalse(app.is_water(conn,inland));self.assertTrue(app.is_water(conn,ocean));conn.close()
        data=json.loads((PROJECT/'data'/'pacific-islands.geojson').read_text());keys=[f['properties']['key'] for f in data['features']];self.assertEqual(len(keys),len(set(keys)));self.assertGreater(len(keys),2000)
        feature=[f for f in geography._islands.values() if not f['properties'].get('grid_tiles') and -175<f['properties']['lng']<-165 and -20<f['properties']['lat']<-10][1];island=feature['properties']['key'];self.assertIsNotNone(island)
        detail=self.client.get('/api/territory/'+island);self.assertEqual(detail.status_code,200);self.assertFalse(detail.json['water']);self.assertTrue(detail.json['coastal'])
        response=self.post('/api/territory/claim',{'grid_key':island});self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.post('/api/territory/claim',{'grid_key':island}).status_code,400)
        self.assertEqual(self.post('/api/territory/claim',{'grid_key':'island:unknown'}).status_code,400)
        with self.client.get('/api/terrain/cells') as response:self.assertEqual(response.data,(PROJECT/'data'/'land-cells.bin').read_bytes())
        with self.client.get('/api/islands',headers={'Accept-Encoding':'gzip'}) as response:self.assertEqual(response.headers.get('Content-Encoding'),'gzip')
    def test_legacy_island_ownership_preserved_without_double_claim(self):
        geography.load();f=next(f for f in geography._islands.values() if not f['properties'].get('grid_tiles') and -175<f['properties']['lng']<-165 and -20<f['properties']['lat']<-10);island=f['properties']['key'];a,b=geography.island_grid(island);key=f'{a},{b}'
        conn=app.get_db();conn.execute('INSERT OR REPLACE INTO territories(grid_key,owner_id,terrain,population,invested) VALUES(?,?,"plains",1234,567)',(key,self.uid));conn.commit();conn.close()
        detail=self.client.get('/api/territory/'+island).json;self.assertTrue(detail['water']);self.assertEqual(detail['legacy_tile'],key)
        self.assertEqual(self.post('/api/territory/claim',{'grid_key':island}).status_code,400)
        conn=app.get_db();row=conn.execute('SELECT population,invested FROM territories WHERE grid_key=?',(key,)).fetchone();self.assertEqual(tuple(row),(1234,567));conn.execute('DELETE FROM territories WHERE grid_key=?',(key,));conn.commit();conn.close()
        self.assertEqual(self.post('/api/territory/claim',{'grid_key':island}).status_code,200)
    def test_tropical_production_and_migration_once(self):
        tropical=next((a,b) for a in range(-110,110) for b in range(-1000,1000) if app.get_terrain(a,b)=='tropical' and geography.cell_land(f'{a},{b}'))
        a,b=tropical;self.assertGreater(app.get_population('tropical',a,b),0);self.assertEqual(app.TERRAIN_RES['tropical'],('food',11))
        conn=app.get_db();conn.execute('DELETE FROM schema_migrations WHERE version IN (7,8,9,10,11,12,13,14,15,16,17)');conn.execute('INSERT OR REPLACE INTO water_cells VALUES("1,1",1)');money=conn.execute('SELECT money FROM users WHERE id=?',(self.uid,)).fetchone()[0];conn.commit();conn.close()
        backup_before_upgrade(app.DB_PATH);migrate_v7(app.get_db)
        conn=app.get_db();self.assertEqual(conn.execute('SELECT COUNT(*) FROM water_cells').fetchone()[0],0);self.assertEqual(conn.execute('SELECT money FROM users WHERE id=?',(self.uid,)).fetchone()[0],money)
        app.set_setting(conn,'rate_limits',json.dumps({'requests':17,'auth':0,'chat':0,'trades':0}));conn.commit();conn.close();migrate_v7(app.get_db)
        conn=app.get_db();self.assertEqual(json.loads(app.get_setting(conn,'rate_limits'))['requests'],17);conn.close()
        self.assertTrue(list((Path(app.DB_PATH).parent/'backups').glob('*before-v17*.db')))

    def test_ideas_saved_as_private_text(self):
        guest=app.app.test_client();token=guest.get('/api/bootstrap').json['csrf']
        self.assertEqual(guest.post('/api/ideas',json={'idea':'An idea from a guest'},headers={'X-WC-CSRF':token}).status_code,401)
        self.assertEqual(self.post('/api/ideas',{'idea':'x'}).status_code,400)
        self.assertEqual(self.post('/api/ideas',{'idea':'x'*4001}).status_code,400)
        self.assertEqual(self.post('/api/ideas',{'idea':'More island adventures!\nLet us explore together.'}).status_code,200)
        text=features.ideas_path().read_text(encoding='utf-8');self.assertIn(self.name,text);self.assertIn('  Let us explore together.',text)
        self.assertEqual(self.client.get('/api/admin/ideas').status_code,403)
        self.admin();self.assertIn('More island adventures!',self.client.get('/api/admin/ideas').json['text'])
        self.assertEqual(self.client.get('/ideas.txt').status_code,404)

    def test_rank_override_requires_admin_and_does_not_grant_powers(self):
        self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'rank','rank':'Emperor'}).status_code,403)
        self.admin();self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'rank','rank':'Admin'}).status_code,400)
        self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'rank','rank':'Emperor'}).status_code,200)
        self.assertEqual(self.client.get('/api/me').json['rank']['name'],'Emperor')
        row=next(p for p in self.client.get('/api/leaderboard').json if p['id']==self.uid);self.assertEqual(row['rank']['name'],'Emperor')
        self.post('/api/admin/player',{'user_id':self.uid,'action':'rank','rank':'Automatic'});self.assertEqual(self.client.get('/api/me').json['rank']['name'],'Settler')

    def test_country_wonders_need_no_selected_tile(self):
        self.assertEqual(self.post('/api/wonders/buy',{'key':'statue'}).status_code,400)
        conn=app.get_db();conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"plains",1234)',('363,-80',self.uid))
        conn.execute('UPDATE users SET money=10000000,wood=10000000,metal=10000000,oil=10000000,steel=10000000,gems=10000000 WHERE id=?',(self.uid,));conn.commit();conn.close()
        listing=self.client.get('/api/wonders').json;self.assertTrue(all(w['required_tile'] is None and w['can_build'] for w in listing))
        result=self.post('/api/wonders/buy',{'key':'statue'});self.assertEqual(result.status_code,200,result.json)
        conn=app.get_db();self.assertIsNone(conn.execute('SELECT grid_key FROM wonders WHERE key="statue" AND owner_id=?',(self.uid,)).fetchone()[0]);conn.close()
        self.assertEqual(self.post('/api/wonders/buy',{'key':'statue'}).status_code,400)
        self.assertEqual(self.post('/api/wonders/buy',{'key':'eva_00'}).status_code,400)

    def test_eva_split_migration_preserves_legacy_unlock_and_balances(self):
        from migrations import migrate_v9
        conn=app.get_db();money=conn.execute('SELECT money FROM users WHERE id=?',(self.uid,)).fetchone()[0]
        conn.execute('DELETE FROM schema_migrations WHERE version=9')
        conn.execute('INSERT INTO wonders(key,owner_id,ts,grid_key) VALUES("eva",?,123,NULL)',(self.uid,));conn.commit();conn.close()
        migrate_v9(app.get_db);migrate_v9(app.get_db)
        conn=app.get_db();keys={r['key'] for r in conn.execute('SELECT key FROM wonders WHERE owner_id=?',(self.uid,))}
        self.assertTrue({'eva_00','eva_01','eva_02'}<=keys);self.assertNotIn('eva',keys)
        self.assertEqual(conn.execute('SELECT money FROM users WHERE id=?',(self.uid,)).fetchone()[0],money)
        conn.close()

    def test_eva_portraits_require_the_matching_wonder(self):
        folder=PROJECT/'static'/'eva';folder.mkdir(exist_ok=True)
        names=['eva_00_test_access.jpg','eva_01_test_access.jpg','eva_02_test_access.jpg']
        try:
            for name in names:(folder/name).write_bytes(b'\xff\xd8\xfftest')
            conn=app.get_db();conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population,invested) VALUES("197,768",?,"forest",1000,0)',(self.uid,))
            conn.execute('UPDATE users SET money=1000000,steel=500 WHERE id=?',(self.uid,));conn.commit();conn.close()
            wonders=self.client.get('/api/wonders').json
            self.assertEqual({w['key'] for w in wonders if w['key'].startswith('eva_')},{'eva_00','eva_01','eva_02'})
            self.assertEqual(self.post('/api/wonders/buy',{'key':'eva_00'}).status_code,200)
            gallery=self.client.get('/api/eva').json['images'];urls={i['url'] for i in gallery}
            self.assertIn('/static/eva/'+names[0],urls);self.assertNotIn('/static/eva/'+names[1],urls)
            self.assertEqual(self.post('/api/eva/deploy',{'grid_key':'197,768','image':names[1]}).status_code,403)
            self.assertEqual(self.post('/api/eva/deploy',{'grid_key':'197,768','image':names[0]}).status_code,200)
            self.assertTrue(any(u['user_id']==self.uid for u in self.client.get('/api/eva/deployments').json['units']))
            self.assertEqual(self.post('/api/eva/deploy',{'grid_key':'197,768','image':'../secret.jpg'}).status_code,400)
        finally:
            conn=app.get_db();conn.execute('DELETE FROM territories WHERE grid_key="197,768" AND owner_id=?',(self.uid,));conn.commit();conn.close()
            for name in names:(folder/name).unlink(missing_ok=True)

    def test_public_community_defaults_are_redacted(self):
        self.assertEqual(self.client.get('/api/bootstrap').json['community']['vipps_number'],'')

    def test_ideas_cooldown_and_admin_submission_ban(self):
        self.assertEqual(self.client.get('/api/ideas').status_code,200)
        self.assertEqual(self.post('/api/ideas',{'idea':'First useful suggestion'}).status_code,200)
        response=self.post('/api/ideas',{'idea':'Another useful suggestion'});self.assertEqual(response.status_code,429)
        self.assertGreater(response.json['retry_after'],0);self.assertIn('Retry-After',response.headers)
        conn=app.get_db();conn.execute('UPDATE users SET idea_last_sent=0 WHERE id=?',(self.uid,));conn.commit();conn.close()
        self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'ideas_ban','enabled':True}).status_code,403)
        self.admin();self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'ideas_ban','enabled':True}).status_code,200)
        self.assertTrue(self.client.get('/api/ideas').json['banned'])
        self.assertEqual(self.post('/api/ideas',{'idea':'Blocked suggestion'}).status_code,403)
        self.assertEqual(self.client.get('/api/me').status_code,200)
        self.assertEqual(self.post('/api/admin/player',{'user_id':self.uid,'action':'ideas_ban','enabled':False}).status_code,200)
        self.assertEqual(self.post('/api/ideas',{'idea':'Unblocked useful suggestion'}).status_code,200)

    def test_large_island_grid_and_antarctic_land(self):
        self.assertIsNone(geography.island_at(21.3,-157.8))
        island=geography.island_at(21.3,-157.8,include_grid=True);self.assertTrue(geography.island_feature(island)['properties']['grid_tiles'])
        keys=[f'{math.floor(lat/.18)},{math.floor(lng/.18)}' for lat,lng in [(21.3,-157.8),(21.4,-157.9),(-75,0),(-80,90),(-80,-170)]]
        for key in keys:self.assertTrue(geography.cell_land(key),key)
        self.assertFalse(geography.cell_land(f'{math.floor(-60/.18)},0'))
        self.assertEqual(self.post('/api/territory/claim',{'grid_key':island}).status_code,400)
        conn=app.get_db();conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"tropical",1000)',(island,self.uid));conn.commit()
        self.assertFalse(app.is_water(conn,island));self.assertTrue(app.is_water(conn,keys[0]));conn.execute('DELETE FROM territories WHERE grid_key=?',(island,));conn.commit()
        self.assertFalse(app.is_water(conn,keys[0]));conn.close()
        antarctic=keys[-1];result=self.post('/api/territory/claim',{'grid_key':antarctic});self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.client.get('/api/territory/'+antarctic).json['terrain'],'tundra')

    def test_admin_can_reset_one_or_all_resource_balances(self):
        values={'money':1200,'food':240,'wood':350,'metal':450,'oil':50,'steel':60,'uranium':70,'gems':80}
        conn=app.get_db();conn.execute('UPDATE users SET '+','.join(key+'=?' for key in values)+',army=93,boats=4,planes=5 WHERE id=?',list(values.values())+[self.uid]);conn.commit();conn.close()
        request={'user_id':self.uid,'action':'reset_resources','resource':'metal','confirm':True}
        self.assertEqual(self.post('/api/admin/player',request).status_code,403)
        self.admin();self.assertEqual(self.post('/api/admin/player',dict(request,confirm=False)).status_code,400)
        self.assertEqual(self.post('/api/admin/player',dict(request,resource='army')).status_code,400)
        self.assertEqual(self.post('/api/admin/player',dict(request,resource='money=999')).status_code,400)
        self.assertEqual(self.post('/api/admin/player',request).status_code,200)
        conn=app.get_db();row=conn.execute('SELECT * FROM users WHERE id=?',(self.uid,)).fetchone()
        for key,value in values.items():self.assertEqual(row[key],0 if key=='metal' else value)
        conn.close();self.assertEqual(self.post('/api/admin/player',dict(request,resource='all')).status_code,200)
        conn=app.get_db();row=conn.execute('SELECT * FROM users WHERE id=?',(self.uid,)).fetchone()
        for key in values:self.assertEqual(row[key],0)
        self.assertEqual((row['army'],row['boats'],row['planes']),(93,4,5))
        entries=[json.loads(r['details']) for r in conn.execute('SELECT details FROM audit_log WHERE action="resources_reset" AND target_id=?',(self.uid,))]
        self.assertEqual(len(entries),2);self.assertEqual(entries[0]['before']['metal'],450);self.assertEqual(entries[1]['resource'],'all');conn.close()

    def test_small_island_port_and_naval_landing(self):
        from unittest.mock import patch
        geography.load();conn=app.get_db();owned={r['grid_key'] for r in conn.execute('SELECT grid_key FROM territories WHERE owner_id IS NOT NULL')}
        choices=[f['properties']['key'] for f in geography._islands.values() if not f['properties'].get('grid_tiles') and f['properties']['key'] not in owned]
        source=choices[0];target=next(key for key in choices[1:] if app.cell_distance(source,key)>10)
        conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"tropical",100)',(source,self.uid))
        conn.execute('INSERT INTO buildings VALUES(?,"port",1)',(source,))
        conn.execute('UPDATE users SET research=?,money=10000000,wood=10000000,army=100,boats=5 WHERE id=?',(json.dumps(['shipyard']),self.uid));conn.commit();conn.close()
        for key in (source,target):
            detail=self.client.get('/api/territory/'+key).json;self.assertTrue(detail['coastal']);self.assertFalse(detail['water'])
        with patch('app.random.random',return_value=0):response=self.post('/api/boats/attack',{'from_key':source,'target_key':target,'boats':1})
        self.assertEqual(response.status_code,200,response.json)
        conn=app.get_db();self.assertEqual(conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(target,)).fetchone()[0],self.uid);conn.close()

    def test_shore_inside_land_cells_counts_as_coast(self):
        geography.load();candidate=None
        for n,byte in enumerate(geography._coasts):
            if not byte:continue
            for bit in range(8):
                if not byte&(1<<bit):continue
                offset=n*8+bit;a=offset//2000-473;b=offset%2000-1000
                if -472<a<472 and -999<b<999 and all(geography.cell_land(f'{a+da},{b+db}') for da in (-1,0,1) for db in (-1,0,1)):
                    candidate=f'{a},{b}';break
            if candidate:break
        self.assertIsNotNone(candidate)
        conn=app.get_db();self.assertFalse(app.is_water(conn,candidate));self.assertTrue(app.is_coastal(conn,candidate));conn.close()
