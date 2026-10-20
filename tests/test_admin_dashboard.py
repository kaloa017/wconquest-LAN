"""Private dashboard, live-save exports and account deletion on disposable saves."""
import csv
import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from test_upgrade import app
import admin_dashboard as dashboard
import features
import server_health
import guest_analytics


class DashboardTests(unittest.TestCase):
    serial=0

    def setUp(self):
        DashboardTests.serial+=1
        self.admin,self.uid=self.account('DashAdmin'+str(self.serial))
        self.player,self.pid=self.account('DashPlayer'+str(self.serial))
        conn=app.get_db();conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.uid,));conn.commit();conn.close()

    def tearDown(self):
        conn=app.get_db();conn.execute("DELETE FROM game_settings WHERE key IN ('server_controls','guest_analytics')");conn.commit();conn.close()

    def account(self,name):
        client=app.app.test_client();csrf=client.get('/api/bootstrap').json['csrf']
        headers={'X-WC-CSRF':csrf}
        result=client.post('/api/register',json={'username':name,'password':'dashboard-test-password'},headers=headers)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(client.post('/api/login',json={'username':name,'password':'dashboard-test-password'},headers=headers).status_code,200)
        return client,client.get('/api/me').json['id']

    def post(self,path,data=None,client=None):
        client=client or self.admin
        return client.post(path,json=data or {},headers={'X-WC-CSRF':client.get('/api/bootstrap').json['csrf']})

    def test_private_endpoints_deny_players_and_guests(self):
        for client in (self.player,app.app.test_client()):
            for path in ('health','accounts','account?user_id='+str(self.pid),'account/delete-preview?user_id='+str(self.pid),'server/settings','analytics'):
                self.assertIn(client.get('/api/admin/'+path).status_code,(401,403))
            for path in ('account/action','account/delete','users/export','database/download','database/check','backups/create','server/settings','analytics/settings','analytics/purge'):
                self.assertIn(self.post('/api/admin/'+path,client=client).status_code,(401,403))
        conn=app.get_db();conn.execute('UPDATE users SET is_moderator=1 WHERE id=?',(self.pid,));conn.commit();conn.close()
        self.assertEqual(self.player.get('/api/admin/health').status_code,403)
        self.assertEqual(self.player.get('/api/admin/analytics').status_code,403)

    def test_health_and_safe_account_details(self):
        result=self.admin.get('/api/admin/health')
        self.assertEqual(result.status_code,200,result.json)
        self.assertGreater(result.json['host']['disk']['total'],0)
        self.assertIn('no-store',result.headers['Cache-Control'])
        self.assertNotIn('secret',result.get_data(as_text=True))
        detail=self.admin.get('/api/admin/account?user_id='+str(self.pid)).json
        self.assertIn('last_seen_unix',detail);self.assertIn('two_factor_enabled',detail)
        for key in ('password','otp_secret','recovery_hash','reset_pin'):self.assertNotIn(key,detail)

    def test_public_last_seen_and_admin_unix(self):
        conn=app.get_db();stamp=int(time.time())-4000
        conn.execute('UPDATE users SET last_seen=? WHERE id=?',(stamp,self.pid))
        conn.execute('UPDATE player_activity SET last_login=?,last_activity=? WHERE user_id=?',(stamp,stamp,self.pid));conn.commit();conn.close()
        with features._lock:
            for key in [k for k,v in features._stats.items() if v['user_id']==self.pid]:features._stats.pop(key)
        public=app.app.test_client().get('/api/players?q=DashPlayer'+str(self.serial)).json['players'][0]
        self.assertEqual(public['id'],self.pid);self.assertIn('hours ago',public['last_seen_label'])
        self.assertNotIn('money',public);self.assertNotIn('last_seen_unix',public);self.assertNotIn('ip',public)
        private=self.admin.get('/api/admin/accounts?q=DashPlayer'+str(self.serial)).json['players'][0]
        self.assertIsInstance(private['last_seen_unix'],int)
        self.assertIsNotNone(public['last_seen_at'])

    def test_json_and_csv_exports_are_safe_and_machine_readable(self):
        conn=app.get_db();conn.execute('UPDATE users SET username=? WHERE id=?',('=Formula',self.pid));conn.commit();conn.close()
        exported=self.post('/api/admin/users/export?format=json')
        self.assertEqual(exported.status_code,200)
        row=next(row for row in exported.json['users'] if row['id']==self.pid)
        self.assertEqual(row['username'],'=Formula');self.assertIn('last_seen_unix',row)
        for key in ('password','otp_secret','recovery_hash','reset_pin','ip'):self.assertNotIn(key,row)
        result=self.post('/api/admin/users/export?format=csv')
        rows=list(csv.DictReader(io.StringIO(result.data.decode('utf-8-sig'))))
        self.assertEqual(next(row for row in rows if int(row['id'])==self.pid)['username'],"'=Formula")
        self.assertIn('attachment',result.headers['Content-Disposition'])

    def test_database_download_is_consistent_private_sqlite(self):
        result=self.post('/api/admin/database/download')
        self.assertEqual(result.status_code,200,result.get_data()[:200])
        self.assertEqual(result.headers['Content-Disposition'],'attachment; filename=game.db')
        self.assertIn('no-store',result.headers['Cache-Control'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'game.db';path.write_bytes(result.data)
            with closing(sqlite3.connect(path)) as copied:
                self.assertEqual(copied.execute('PRAGMA quick_check').fetchone()[0],'ok')
                self.assertIsNotNone(copied.execute('SELECT id FROM users WHERE id=?',(self.pid,)).fetchone())
        result.close()
        conn=app.get_db();self.assertGreater(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='database_downloaded'").fetchone()[0],0);conn.close()
        legacy=self.admin.get('/api/admin/export_db')
        self.assertEqual(legacy.status_code,200)
        self.assertIn('no-store',legacy.headers['Cache-Control'])
        self.assertIn(b'CREATE TABLE users',legacy.data);legacy.close()

    def test_manual_backup_and_integrity_checks(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(dashboard,'backup_directory',return_value=Path(folder)/'private'):
            result=self.post('/api/admin/backups/create');self.assertEqual(result.status_code,200,result.json)
            self.assertTrue((Path(folder)/'private'/result.json['name']).is_file())
        result=self.post('/api/admin/database/check');self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['checks'],['ok']);self.assertEqual(result.json['foreign_key_errors'],[])

    def test_maintenance_and_registration_controls_preserve_login(self):
        result=self.post('/api/admin/server/settings',{'registration_open':False,'maintenance':True,'message':'School server maintenance'})
        self.assertEqual(result.status_code,200,result.json)
        denied=self.post('/api/chat/send',{'channel':'global','message':'blocked during maintenance'},self.player)
        self.assertEqual(denied.status_code,503)
        guest=app.app.test_client();self.assertEqual(self.post('/api/register',{'username':'ClosedSignup','password':'test-password'},guest).status_code,403)
        self.assertEqual(self.post('/api/admin/database/check').status_code,200)
        self.assertEqual(self.post('/api/login',{'username':'DashPlayer'+str(self.serial),'password':'dashboard-test-password'},guest).status_code,200)
        self.assertEqual(guest.get('/api/server/status').json['message'],'School server maintenance')

    def test_roles_and_research_enforce_server_constraints(self):
        result=self.post('/api/admin/account/action',{'user_id':self.uid,'action':'role','value':'player','confirm':True})
        self.assertEqual(result.status_code,400)
        result=self.post('/api/admin/account/action',{'user_id':self.pid,'action':'role','value':'moderator','confirm':True})
        self.assertEqual(result.status_code,200,result.json)
        result=self.post('/api/admin/account/action',{'user_id':self.pid,'action':'research','value':'advanced_finance_4','confirm':True})
        self.assertEqual(result.status_code,400)
        result=self.post('/api/admin/account/action',{'user_id':self.pid,'action':'research','value':'agri','confirm':True})
        self.assertEqual(result.status_code,200,result.json)
        self.assertIn('agri',self.admin.get('/api/admin/account?user_id='+str(self.pid)).json['research'])
        for path,body in (('/api/admin/promote',{'user_id':self.uid,'promote':False}),('/api/admin/ban',{'user_id':self.uid,'ban':True})):
            self.assertEqual(self.post(path,body).status_code,400)

    def deletion(self,uid):
        result=self.admin.get('/api/admin/account/delete-preview?user_id='+str(uid))
        self.assertEqual(result.status_code,200,result.json)
        plan=result.json
        return dict(user_id=uid,token=plan['token'],typed_username=plan['username'],confirm=True,reason='Disposable regression account')

    def test_deletion_requires_review_exact_name_and_fresh_plan(self):
        self.assertEqual(self.admin.get('/api/admin/account/delete-preview?user_id='+str(self.uid)).status_code,400)
        data=self.deletion(self.pid)
        self.assertEqual(self.post('/api/admin/account/delete',{**data,'typed_username':'wrong'}).status_code,400)
        self.assertEqual(self.post('/api/admin/account/delete',{**data,'token':'forged'}).status_code,400)
        conn=app.get_db();conn.execute("INSERT INTO chat(channel,user_id,username,message) VALUES('global',?,?,'new message')",(self.pid,'DashPlayer'+str(self.serial)));conn.commit();conn.close()
        self.assertEqual(self.post('/api/admin/account/delete',data).status_code,400)
        self.assertEqual(self.admin.get('/api/admin/account?user_id='+str(self.pid)).status_code,200)

    def test_deletion_releases_land_preserves_others_and_revokes_login(self):
        conn=app.get_db();key='250,'+str(100+self.serial)
        conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population,garrison) VALUES(?,?,"plains",1000,50)',(key,self.pid))
        conn.execute('INSERT INTO buildings VALUES(?,"farm",2)',(key,))
        conn.execute("INSERT INTO exchanges(sender,recipient,give_json,want_json,status,created) VALUES(?,?, '{}','{}','pending',0)",(self.pid,self.uid))
        conn.execute("INSERT INTO bank_loans(lender,borrower,principal,rate,term_hours,total_due,created) VALUES(?,?,100,5,24,105,0)",(self.uid,self.pid))
        conn.execute("INSERT INTO campaigns(attacker,defender,from_key,target_key,troops,initial_troops,status) VALUES(?,?,?,?,20,20,'active')",(self.uid,self.pid,key,key))
        conn.execute("INSERT INTO chat(channel,user_id,username,message) VALUES('global',?,?,'remove me')",(self.pid,'DashPlayer'+str(self.serial)))
        conn.commit();before=conn.execute('SELECT army FROM users WHERE id=?',(self.uid,)).fetchone()[0];conn.close()
        result=self.post('/api/admin/account/delete',self.deletion(self.pid))
        self.assertEqual(result.status_code,200,result.json)
        conn=app.get_db();self.assertIsNone(conn.execute('SELECT 1 FROM users WHERE id=?',(self.pid,)).fetchone())
        tile=conn.execute('SELECT owner_id,garrison FROM territories WHERE grid_key=?',(key,)).fetchone();self.assertIsNone(tile['owner_id']);self.assertEqual(tile['garrison'],0)
        self.assertIsNone(conn.execute('SELECT 1 FROM buildings WHERE grid_key=?',(key,)).fetchone())
        self.assertEqual(conn.execute('SELECT army FROM users WHERE id=?',(self.uid,)).fetchone()[0],before+20)
        self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM chat WHERE user_id=?',(self.pid,)).fetchone()[0],0)
        conn.close()
        self.assertEqual(self.player.get('/api/me').status_code,401)

    def test_pi_telemetry_parsing_and_cache(self):
        flags=server_health.throttle_flags(0x50005)
        self.assertIn('Undervoltage',flags['current']);self.assertIn('Throttling',flags['since_boot'])
        memory=server_health.memory_linux('MemTotal: 8000 kB\nMemAvailable: 2000 kB\nSwapTotal: 1000 kB\nSwapFree: 500 kB')
        self.assertEqual(memory['percent'],75);self.assertEqual(memory['swap_used'],512000)
        with tempfile.TemporaryDirectory() as folder,patch.object(server_health,'collect',return_value={'sampled_at':42}) as collect:
            first=server_health.snapshot(Path(folder));second=server_health.snapshot(Path(folder))
            self.assertEqual(first,second);collect.assert_called_once()

    def test_guest_country_never_exposes_ip_or_city_and_updates_without_external_lookup(self):
        with patch.object(app,'_touch_spectator') as touch:
            self.assertEqual(self.post('/api/spectate').status_code,200)
            touch.assert_not_called()
        guest=app.app.test_client();csrf=guest.get('/api/bootstrap').json['csrf']
        with patch.dict('os.environ',{'ENABLE_IP_GEOLOOKUP':'0'}):
            result=guest.post('/api/spectate',json={},headers={'X-WC-CSRF':csrf},
                environ_overrides={'REMOTE_ADDR':'203.0.113.90','wconquest.country':'NO'})
        # The real proxy middleware strips an untrusted injected country, so test
        # the app helper under a validated request context separately.
        self.assertEqual(result.status_code,200)
        with app.app.test_request_context(environ_overrides={'wconquest.country':'NO'}):app._touch_spectator('203.0.113.90')
        guests=[row for row in guest.get('/api/online').json if row['type']=='spectator']
        row=next(row for row in guests if row.get('country_code')=='NO')
        self.assertEqual(row['flag'],'🇳🇴');self.assertEqual(row['username'],'Guest')
        self.assertEqual(row['city'],'');self.assertNotIn('ip',row)
        self.assertNotIn('203.0.113.90',json.dumps(guests))

    def test_guest_history_records_pages_and_presence_without_public_ip_leak(self):
        guest=app.app.test_client();address='198.51.100.72'
        response=guest.get('/',environ_overrides={'REMOTE_ADDR':address},headers={'CF-IPCountry':'NO','X-Forwarded-For':'1.1.1.1'})
        self.assertEqual(response.status_code,200)
        with guest.session_transaction() as stored:self.assertIn('guest_visit',stored)
        guest.get('/',environ_overrides={'REMOTE_ADDR':address})
        data=self.admin.get('/api/admin/analytics?q='+address).json
        self.assertEqual(len(data['visits']),1);row=data['visits'][0]
        self.assertEqual(row['ip'],address);self.assertEqual(row['pageviews'],2)
        self.assertIsNone(row['country_code'])  # direct client cannot spoof country headers
        self.assertNotIn('visitor_hash',row)
        self.assertIn('no-store',self.admin.get('/api/admin/analytics').headers['Cache-Control'])
        token=guest.get('/api/bootstrap').json['csrf']
        guest.post('/api/spectate',json={},headers={'X-WC-CSRF':token},environ_overrides={'REMOTE_ADDR':address})
        data=self.admin.get('/api/admin/analytics?q='+address).json
        self.assertEqual(data['visits'][0]['pageviews'],2)  # a heartbeat isn't a pageview
        self.assertNotIn(address,guest.get('/api/online').get_data(as_text=True))
        self.assertNotIn(address,guest.get('/api/players').get_data(as_text=True))

    def test_guest_history_retention_toggle_purge_and_schema_preserve_save(self):
        app.migrate_v20(app.get_db);app.migrate_v20(app.get_db)
        conn=app.get_db();conn.execute('INSERT INTO guest_visits(visitor_hash,ip,first_seen,last_seen) VALUES("expired", "192.0.2.9",1,1)');conn.commit();conn.close()
        result=self.post('/api/admin/analytics/settings',{'enabled':False,'retention_days':7})
        self.assertEqual(result.status_code,200,result.json)
        conn=app.get_db();self.assertIsNone(conn.execute('SELECT 1 FROM guest_visits WHERE visitor_hash="expired"').fetchone());conn.close()
        guest=app.app.test_client();guest.get('/',environ_overrides={'REMOTE_ADDR':'192.0.2.77'})
        self.assertEqual(self.admin.get('/api/admin/analytics?q=192.0.2.77').json['total'],0)
        self.assertEqual(self.post('/api/admin/analytics/settings',{'enabled':True,'retention_days':1000}).status_code,400)
        self.assertEqual(self.post('/api/admin/analytics/purge',{'confirm':True,'confirmation':'wrong'}).status_code,400)
        result=self.post('/api/admin/analytics/purge',{'confirm':True,'confirmation':'DELETE GUEST HISTORY'})
        self.assertEqual(result.status_code,200,result.json)
        conn=app.get_db();self.assertEqual(conn.execute('SELECT COUNT(*) FROM guest_visits').fetchone()[0],0)
        self.assertIsNotNone(conn.execute('SELECT id FROM users WHERE id=?',(self.pid,)).fetchone());conn.close()

    def test_guest_history_database_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.db'
            def connect():
                conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;return conn
            with closing(connect()) as conn:
                conn.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,ts INTEGER)');conn.commit()
            guest_analytics.migrate(connect)
            with closing(connect()) as conn:
                conn.executemany('INSERT INTO guest_visits(visitor_hash,ip,first_seen,last_seen) VALUES(?,"192.0.2.1",1,1)',((str(i),) for i in range(20005)))
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM guest_visits').fetchone()[0],20000)
                self.assertIsNone(conn.execute('SELECT 1 FROM guest_visits WHERE visitor_hash="0"').fetchone())

    def test_linux_pi_health_uses_fixed_read_only_commands(self):
        files={'/proc/device-tree/model':'Raspberry Pi 5 Model B\0','/proc/uptime':'1234.50 600.00',
            '/proc/meminfo':'MemTotal: 8000 kB\nMemAvailable: 2000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB',
            '/proc/stat':'cpu 20 0 20 100 0 0 0 0','/proc/self/status':'VmRSS: 1234 kB',
            '/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq':'2400000',
            '/proc/net/dev':'eth0: 1000 1 2 3 0 0 0 0 2000 1 4 5 0 0 0 0'}
        def command(args):
            if args[0]=='systemctl':return 'Id=wconquest.service\nLoadState=loaded\nActiveState=active\nSubState=running\nNRestarts=2'
            return "temp=52.1'C" if args[1]=='measure_temp' else 'throttled=0x50000'
        with tempfile.TemporaryDirectory() as folder,patch.object(server_health.platform,'system',return_value='Linux'),patch.object(server_health,'read',side_effect=files.get),patch.object(server_health.shutil,'which',side_effect=lambda name:name),patch.object(server_health,'command',side_effect=command) as commands,patch.object(server_health.os,'getloadavg',return_value=(.1,.2,.3),create=True),patch.object(server_health,'urlopen') as opened,patch.object(server_health,'_cpu',(100,80)):
            opened.return_value.__enter__.return_value.status=200
            result=server_health.collect(folder)
            self.assertEqual(result['temperature_c'],52.1);self.assertEqual(result['cpu_mhz'],2400)
            self.assertEqual(result['uptime_seconds'],1234.5);self.assertTrue(result['tunnel'])
            self.assertEqual(result['network'][0]['received'],1000)
            self.assertEqual(result['services'][0]['NRestarts'],'2')
            self.assertEqual(result['throttle']['current'],[]);self.assertIn('Undervoltage',result['throttle']['since_boot'])
            self.assertTrue(all(call.args[0][0] in ('systemctl','vcgencmd') for call in commands.call_args_list))


if __name__=='__main__':unittest.main()
