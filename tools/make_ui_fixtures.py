"""Generate browser fixtures using an isolated world, never the host save."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

project=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(project))


def main(output):
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wconquest-ui-',dir=output.parent) as scratch:
        os.environ.update(DB_PATH=str(Path(scratch)/'game.db'),DISABLE_SCHEDULER='1',SECRET_KEY='preview-only-secret-'*4)
        import app,features
        conn=app.get_db()
        for name,admin in [('Aurora',1),('Defender',0)]:
            conn.execute('INSERT INTO users(username,password,is_admin,money,food,wood,metal,oil,steel,uranium,gems,army,boats,planes,research,last_seen_version) VALUES(?,?,?,1000000000000,1000000,1000000,1000000,1000000,1000000,1000000,1000000,400000,500,500,?,?)',
                (name,'preview-only',admin,json.dumps(list(app.RESEARCH_TREE)),'6.3.6'))
        fa=conn.execute("INSERT INTO factions(name,tag,leader_id,color) VALUES('Aurora','AUR',1,'#3b82f6')").lastrowid
        fb=conn.execute("INSERT INTO factions(name,tag,leader_id,color) VALUES('Defenders','DEF',2,'#ef4444')").lastrowid
        features.join_faction(conn,1,fa);features.join_faction(conn,2,fb)
        conn.execute("INSERT INTO faction_rel(a,b,kind,status,ts) VALUES(?,?,'war','active',?)",(fa,fb,int(time.time())))
        for key,uid,building in [('200,200',1,'airport'),('200,199',1,'space_agency'),('201,200',1,'rocket_pad'),('200,201',2,None),('200,202',2,None),('200,203',2,None)]:
            conn.execute("INSERT INTO territories(grid_key,owner_id,terrain,population,invested,last_collected) VALUES(?,?,'plains',12500,1000,?)",(key,uid,int(time.time())))
            if building:conn.execute('INSERT INTO buildings VALUES(?,?,3)',(key,building))
        conn.execute("INSERT INTO space_program(user_id,state,planet,collected,last_mined,cargo,tutorial_seen) VALUES(1,'surface','moon',?,?,?,1)",(int(time.time()),int(time.time()),json.dumps({'iridium':72,'uranium':250})))
        conn.execute("INSERT INTO space_businesses VALUES(1,'satellite',2)")
        conn.execute("INSERT INTO planet_tiles VALUES(1,'moon',3,3,1)")
        conn.commit()
        client=app.app.test_client()
        with client.session_transaction() as session:session.update(user_id=1,username='Aurora',auth_version=0,csrf='preview-csrf')
        battle=client.post('/api/attack',json={'from_key':'200,200','target_key':'200,201','target_keys':['200,201','200,202'],'troops':12345},headers={'X-WC-CSRF':'preview-csrf'})
        if battle.status_code!=200:raise RuntimeError(str(battle.get_json()))
        fixtures={}
        for rule in app.app.url_map.iter_rules():
            if rule.rule.startswith('/api/') and 'GET' in rule.methods and not rule.arguments and rule.rule not in ('/api/terrain/cells','/api/islands','/api/land'):
                response=client.get(rule.rule)
                if response.is_json:fixtures[rule.rule]={'status':response.status_code,'data':response.get_json()}
        for key in ['200,200','200,201','200,202','200,203']:
            response=client.get('/api/territory/'+key)
            fixtures['/api/territory/'+key]={'status':response.status_code,'data':response.get_json()}
        Path(output).write_text(json.dumps(fixtures),encoding='utf-8')
        conn.close()
        print('Disposable-world browser fixtures saved.')


if __name__=='__main__':main(sys.argv[1])
