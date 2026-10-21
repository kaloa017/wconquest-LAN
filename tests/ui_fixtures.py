"""Create offline UI data through Flask's in-process client and a disposable save."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_upgrade import app


def fixtures():
    client=app.app.test_client()
    token=client.get('/api/bootstrap').json['csrf']
    headers={'X-WC-CSRF':token}
    client.post('/api/register',json={'username':'InterfaceTester','password':'disposable-test-password'},headers=headers)
    response=client.post('/api/login',json={'username':'InterfaceTester','password':'disposable-test-password'},headers=headers)
    if response.status_code!=200:raise RuntimeError('Unable to prepare isolated UI fixture')
    uid=client.get('/api/me').json['id']
    conn=app.get_db()
    conn.execute('UPDATE users SET is_admin=1,is_donator=1,money=1000000,army=1000,food=10000,wood=10000,metal=10000,oil=10000 WHERE id=?',(uid,))
    conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES("200,200",?,"plains",1000)',(uid,))
    conn.execute('INSERT INTO buildings(grid_key,type,level) VALUES("200,200","farm",2)')
    conn.commit();conn.close()
    endpoints=['/api/bootstrap','/api/me','/api/buildings','/api/research','/api/campaigns','/api/exchanges','/api/banks',
        '/api/space','/api/territories','/api/territory/200,200','/api/territory/200,201','/api/territory/0,0','/api/faction/page','/api/faction/list','/api/faction/info',
        '/api/leaderboard','/api/battle_log','/api/battle_log/all','/api/alliances','/api/embassy/list','/api/wonders',
        '/api/eva','/api/income','/api/capital','/api/cities','/api/stocks','/api/moderation/players','/api/catalog','/api/admin/users','/api/admin/stats',
        '/api/admin/requests','/api/admin/advertisement','/api/admin/chat_filter','/api/notifications','/api/profile/two_factor',
        '/api/map/sync','/api/online','/api/fallout','/api/music','/api/advertisement','/api/changelog','/api/chat',
        '/api/achievements','/api/playtime','/api/announcements','/api/space','/api/activity','/api/away','/api/wars/unseen','/api/eva/deployments']
    output={path:client.get(path).get_json() for path in endpoints}
    for path in ('/api/admin/health','/api/admin/server/settings','/api/admin/accounts','/api/players','/api/admin/analytics','/api/admin/release_notes','/api/statistics','/api/profile/email','/api/admin/email','/api/admin/ip-bans','/api/spectator/sync'):
        output[path]=client.get(path).get_json()
    output['/api/admin/account']=client.get('/api/admin/account?user_id='+str(uid)).get_json()
    conn=app.get_db()
    other=conn.execute('INSERT INTO users(username,password) VALUES("DeletionFixture","unusable-test-only-hash")').lastrowid
    conn.commit();conn.close()
    output['/api/admin/account/delete-preview']=client.get('/api/admin/account/delete-preview?user_id='+str(other)).get_json()
    return output


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(fixtures(),ensure_ascii=True))
