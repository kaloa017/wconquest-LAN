import os,sys,tempfile,unittest,sqlite3,time,hashlib,io
from pathlib import Path
from contextlib import closing
os.environ['DISABLE_SCHEDULER']='1'
PROJECT=Path(__file__).resolve().parents[1]
scratch=tempfile.TemporaryDirectory(dir=PROJECT/'tests');os.environ['DB_PATH']=str(Path(scratch.name)/'game.db')
sys.path.insert(0,str(PROJECT))
import app,features

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        features._limits.clear()
        self.client=app.app.test_client();self.csrf=self.client.get('/api/bootstrap').json['csrf']
    def post(self,path,data):return self.client.post(path,json=data,headers={'X-WC-CSRF':self.csrf})
    def account(self,name):
        r=self.post('/api/register',{'username':name,'password':'testpassword'});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.post('/api/login',{'username':name,'password':'testpassword'}).status_code,200)
        return r.json
    def test_accounts_and_recovery(self):
        r=self.account('Recovery');uid=self.client.get('/api/me').json['id']
        self.assertEqual(self.client.post('/api/logout',json={}).status_code,403)
        self.post('/api/logout',{})
        self.csrf=self.client.get('/api/bootstrap').json['csrf']
        code=r['recovery_code'];self.assertEqual(self.post('/api/forgot_password',{'username':'Recovery','recovery_code':code,'new_password':'newpassword'}).status_code,200)
        self.assertEqual(self.post('/api/forgot_password',{'username':'Recovery','recovery_code':code,'new_password':'thirdpassword'}).status_code,400)
    def test_religion_and_preferences(self):
        self.account('Believer');self.assertEqual(self.post('/api/religion/set',{'id':'shinto'}).status_code,200)
        self.assertEqual(self.post('/api/religion/set',{'id':'folk'}).status_code,409)
        self.assertEqual(self.post('/api/profile/preferences',{'share_boats':True,'display_faction_colors':False}).status_code,200)
        self.assertEqual(self.post('/api/profile/preferences',{'music_volume':2}).status_code,400)

    def test_new_buildings_produce_configured_resources(self):
        context={'rs':set(),'ft':set(),'ide':{},'w':set(),'ev':None,'base':1,'religion':{}}
        base=app.tile_yield(context,'plains',None,0)
        for key in ('farm','lumberyard','refinery','solar_farm'):
            output=app.tile_yield(context,'plains',key,2)
            for resource,rate in app.BUILDINGS[key]['production'].items():self.assertAlmostEqual(output[resource]-base.get(resource,0),rate*2)
    def test_admin_private_and_kick(self):
        self.account('Hosttest');uid=self.client.get('/api/me').json['id'];conn=app.get_db();conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(uid,));conn.commit();conn.close()
        self.assertEqual(self.client.get('/api/admin/requests').status_code,200)
        r=self.post('/api/admin/recovery',{'user_id':uid});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.post('/api/admin/player',{'user_id':uid,'action':'spawn','resource':'boats','amount':4}).status_code,400)
        self.assertEqual(self.post('/api/admin/player',{'user_id':uid,'action':'spawn','resource':'boats','amount':4,'confirm':True}).status_code,200)
        self.assertEqual(self.post('/api/admin/player',{'user_id':uid,'action':'kick'}).status_code,200)
        self.assertEqual(self.client.get('/api/me').status_code,401)
    def test_delta_stocks_and_fleets(self):
        self.account('Investor');uid=self.client.get('/api/me').json['id'];conn=app.get_db();conn.execute('UPDATE users SET money=1000000 WHERE id=?',(uid,));conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES("200,200",?,"plains",100)',(uid,));conn.commit();conn.close()
        r=self.client.get('/api/map/sync').json;version=r['version'];self.assertTrue(r['reset']);r=self.client.get('/api/map/sync?since='+version).json;self.assertEqual(r['changed'],[])
        self.assertEqual(self.post('/api/faction/create',{'name':'Test Faction','tag':'TF','color_slot':0}).status_code,200)
        self.assertEqual(self.client.get('/api/faction/page').status_code,200)
        features.scheduler_tick();stocks=self.client.get('/api/stocks').json;self.assertGreater(len(stocks['assets']),0)
        self.assertEqual(self.post('/api/stocks/trade',{'symbol':'C'+str(uid),'side':'buy','quantity':1}).status_code,400)
        other=next(a for a in stocks['assets'] if a['investable']);r=self.post('/api/stocks/trade',{'symbol':other['symbol'],'side':'buy','quantity':1});self.assertEqual(r.status_code,200,r.json)
    def test_route_privacy_and_validation(self):
        self.assertEqual(self.client.get('/api/admin/requests').status_code,401)
        self.assertEqual(self.post('/api/territory/claim',{'grid_key':'01,2'}).status_code,400)
        self.assertNotIn('ip',str(self.client.get('/api/online').json))

    def test_atomic_spending_and_gzip(self):
        from concurrent.futures import ThreadPoolExecutor
        self.account('Concurrent');uid=self.client.get('/api/me').json['id'];other=app.app.test_client();token=other.get('/api/bootstrap').json['csrf']
        other.post('/api/login',json={'username':'Concurrent','password':'testpassword'},headers={'X-WC-CSRF':token})
        conn=app.get_db();cost=app.troop_cost_for(conn,uid,set());conn.execute('UPDATE users SET money=? WHERE id=?',(cost,uid));conn.commit();conn.close()
        with ThreadPoolExecutor(2) as executor:
            a=executor.submit(self.post,'/api/troops/build',{'amount':1});b=executor.submit(other.post,'/api/troops/build',json={'amount':1},headers={'X-WC-CSRF':token});statuses=sorted([a.result().status_code,b.result().status_code])
        self.assertEqual(statuses,[200,400])
        conn=app.get_db();self.assertEqual(conn.execute('SELECT money FROM users WHERE id=?',(uid,)).fetchone()[0],0);conn.close()
        r=self.client.get('/api/buildings',headers={'Accept-Encoding':'gzip'});self.assertEqual(r.headers.get('Content-Encoding'),'gzip')

    def test_music_validation_and_changelog(self):
        self.account('Music Host');uid=self.client.get('/api/me').json['id'];conn=app.get_db();conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(uid,));conn.commit();conn.close()
        r=self.client.post('/api/admin/music',data={'file':(io.BytesIO(b'not an mp3'),'fake.mp3')},headers={'X-WC-CSRF':self.csrf});self.assertEqual(r.status_code,400)
        content=(b'\xff\xfb\x90\x64'+bytes(413))*8
        r=self.client.post('/api/admin/music',data={'file':(io.BytesIO(content),'test.mp3')},headers={'X-WC-CSRF':self.csrf});self.assertEqual(r.status_code,200,r.json)
        response=self.client.get('/music.mp3');self.assertEqual(response.status_code,200);response.close()
        self.assertTrue(self.client.get('/api/changelog').json['show']);self.post('/api/changelog/seen',{});self.assertFalse(self.client.get('/api/changelog').json['show'])

    def test_fleet_ownership_and_faction_cap(self):
        self.account('Fleet Owner');uid=self.client.get('/api/me').json['id'];conn=app.get_db()
        second=conn.execute('INSERT INTO users(username,password,boats,planes) VALUES("Fleet Mate",?,9,7)',(app.ph('testpassword'),)).lastrowid
        fid=conn.execute('INSERT INTO factions(name,tag,leader_id,color,color_slot) VALUES("Fleet Guild","FG",?,"#fff",1)',(uid,)).lastrowid
        features.join_faction(conn,uid,fid);features.join_faction(conn,second,fid)
        self.assertEqual(features.fleet_available(conn,uid,'boats'),0)
        conn.execute('UPDATE users SET share_boats=1 WHERE id=?',(second,));self.assertEqual(features.fleet_available(conn,uid,'boats'),9)
        features.fleet_change(conn,uid,'boats',-3);features.leave_faction(conn,second);self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(second,)).fetchone()[0],6)
        for i in range(2,8):conn.execute('INSERT INTO factions(name,tag,leader_id,color,color_slot) VALUES(?,?,?,?,?)',(f'Faction{i}',f'Z{i}',uid,app.FACTION_COLORS[i],i))
        conn.commit();conn.close()
        self.assertEqual(self.post('/api/faction/create',{'name':'Overflow Faction','tag':'OF','color_slot':0}).status_code,400)

    def test_wonders_per_player_and_japan_cosmetics(self):
        self.account('Wonder One');uid=self.client.get('/api/me').json['id'];conn=app.get_db()
        second=conn.execute('INSERT INTO users(username,password) VALUES("Wonder Two",?)',(app.ph('testpassword'),)).lastrowid
        conn.execute('UPDATE users SET money=1000000,metal=1000,steel=1000 WHERE id IN (?,?)',(uid,second))
        for key,owner in [('197,768',uid),('196,768',second)]:conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,"plains",100)',(key,owner))
        conn.commit();conn.close()
        r=self.post('/api/wonders/buy',{'key':'colossus','grid_key':'197,768'});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.post('/api/wonders/buy',{'key':'colossus','grid_key':'197,768'}).status_code,400)
        self.assertEqual(self.post('/api/wonders/buy',{'key':'statue'}).status_code,200)
        self.assertEqual(self.post('/api/wonders/buy',{'key':'eva_00','grid_key':'197,768'}).status_code,200)
        self.assertTrue(self.client.get('/api/eva').json['cosmetic_only'])
        self.post('/api/logout',{});self.csrf=self.client.get('/api/bootstrap').json['csrf'];self.post('/api/login',{'username':'Wonder Two','password':'testpassword'})
        self.assertEqual(self.post('/api/wonders/buy',{'key':'colossus','grid_key':'196,768'}).status_code,200)

    def test_legacy_migration_preserves_values(self):
        from migrations import migrate_v6,backup_before_upgrade
        legacy=Path(scratch.name)/'legacy.db'
        with closing(sqlite3.connect(legacy)) as dst:
            dst.executescript((PROJECT/'tests'/'legacy_schema.sql').read_text(encoding='utf-8'))
            for uid in (2,3):dst.execute('INSERT INTO users(id,username,password) VALUES(?,?,?)',(uid,'legacy'+str(uid),hashlib.sha256(b'oldpassword').hexdigest()))
            dst.commit()
        def connect():
            conn=sqlite3.connect(legacy);conn.row_factory=sqlite3.Row;return conn
        conn=connect();fid=conn.execute('INSERT INTO factions(name,tag,leader_id,color,army,boats,planes) VALUES("Legacy","LG",2,"#fff",31,9,7)').lastrowid
        conn.execute('UPDATE users SET faction_id=?,boats=2,planes=3,reset_pin="123456" WHERE id IN (2,3)',(fid,));conn.execute('INSERT INTO wonders VALUES("statue",2,123)');before=[tuple(r) for r in conn.execute('SELECT id,money,research FROM users ORDER BY id')];conn.commit();conn.close()
        backup_before_upgrade(legacy);migrate_v6(connect);migrate_v6(connect);conn=connect()
        self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT id,money,research FROM users ORDER BY id')])
        self.assertEqual(conn.execute('SELECT SUM(boats),SUM(planes) FROM users WHERE faction_id=?',(fid,)).fetchone()[:],(13,13))
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM wonders WHERE owner_id=2').fetchone()[0],1)
        self.assertTrue(conn.execute('SELECT recovery_hash FROM users WHERE id=2').fetchone()[0]);self.assertEqual(conn.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0],1);conn.close()

if __name__=='__main__':unittest.main(verbosity=2)
