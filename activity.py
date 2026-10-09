"""Human activity controls passive production; polling never renews the deadline."""
import time,json
from flask import request, session, jsonify
from config import INACTIVITY_SECONDS, WAR_RECENT_LOGIN_SECONDS, ONLINE_SECONDS, BUILDINGS

core=None

def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''CREATE TABLE IF NOT EXISTS player_activity(
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            last_activity INTEGER NOT NULL,last_login INTEGER NOT NULL DEFAULT 0,
            heartbeat INTEGER NOT NULL DEFAULT 0,paused INTEGER NOT NULL DEFAULT 0)''')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=16').fetchone():conn.commit();return
        old_defaults={
            'farm':{'name':'Farm','icon':'🌾','desc':'+6 food/min per level','cost':{'money':90,'wood':25},'production':{'food':6}},
            'lumberyard':{'name':'Lumberyard','icon':'🪵','desc':'+5 wood/min per level; forests only','cost':{'money':110,'metal':15},'terrain':['forest'],'production':{'wood':5}},
        }
        for key,definition in old_defaults.items():
            saved=conn.execute("SELECT data FROM live_catalog WHERE category='buildings' AND item_key=?",(key,)).fetchone()
            if saved and json.loads(saved['data'])==definition:
                conn.execute("UPDATE live_catalog SET data=? WHERE category='buildings' AND item_key=?",(json.dumps(BUILDINGS[key]),key))
        # Existing saves lack login timestamps. Last seen is a conservative proxy.
        conn.execute('INSERT OR IGNORE INTO player_activity(user_id,last_activity,last_login) SELECT id,?,COALESCE(last_seen,0) FROM users',(int(time.time()),))
        # Transferring paused land cannot resurrect its unearned production for a new owner.
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS discard_paused_tile_backlog AFTER UPDATE OF owner_id ON territories
            WHEN OLD.owner_id IS NOT NEW.owner_id AND EXISTS(
                SELECT 1 FROM player_activity WHERE user_id=OLD.owner_id AND
                (paused=1 OR last_activity+{INACTIVITY_SECONDS}<=CAST(strftime('%s','now') AS INTEGER)))
            BEGIN UPDATE territories SET last_collected=CAST(strftime('%s','now') AS INTEGER) WHERE id=NEW.id; END''')
        conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES(16,?)',(int(time.time()),))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

def state(conn,uid,timestamp=None):
    timestamp=int(time.time()) if timestamp is None else timestamp
    stored=conn.execute('SELECT * FROM player_activity WHERE user_id=?',(uid,)).fetchone()
    if stored is None:
        conn.execute('INSERT OR IGNORE INTO player_activity(user_id,last_activity) VALUES(?,?)',(uid,timestamp))
        stored=conn.execute('SELECT * FROM player_activity WHERE user_id=?',(uid,)).fetchone()
    row=dict(stored)
    row['deadline']=row['last_activity']+INACTIVITY_SECONDS
    row['inactive']=bool(row['paused'] or timestamp>=row['deadline'])
    if row['inactive'] and not row['paused']:
        conn.execute('UPDATE player_activity SET paused=1 WHERE user_id=?',(uid,))
    return row

def production_cutoff(conn,uid,timestamp):
    row=state(conn,uid)
    return min(timestamp,row['deadline'])

def heartbeat():
    conn=core['get_db']();uid=session['user_id'];stamp=int(time.time());row=state(conn,uid,stamp)
    from playtime import record,total
    if request.method=='POST':
        data=request.get_json(silent=True)
        if data is None:data={}
        if not isinstance(data,dict):return jsonify(error='Send an activity object'),400
        if not isinstance(data.get('active',False),bool):return jsonify(error='active must be true or false'),400
        visible=data.get('visible',True)
        if not isinstance(visible,bool):return jsonify(error='visible must be true or false'),400
        record(conn,uid,visible,stamp)
        if data.get('active') and visible and not row['inactive']:
            # Settle production before moving the boundary; never revive expired income.
            core['auto_collect'](uid,conn)
            conn.execute('UPDATE player_activity SET last_activity=? WHERE user_id=?',(stamp,uid))
        conn.execute('UPDATE player_activity SET heartbeat=? WHERE user_id=?',(stamp if visible and not row['inactive'] else 0,uid))
        row=state(conn,uid,stamp)
    return jsonify(inactive=row['inactive'],deadline=row['deadline'],server_time=stamp,play_seconds=total(row,stamp))

def resume():
    conn=core['get_db']();uid=session['user_id'];stamp=int(time.time())
    row=state(conn,uid,stamp)
    if not row['inactive']:return jsonify(success=True,inactive=False,deadline=row['deadline'],server_time=stamp)
    core['auto_collect'](uid,conn)
    # Discard all paused production, including partial collection intervals.
    conn.execute('UPDATE territories SET last_collected=? WHERE owner_id=?',(stamp,uid))
    conn.execute('UPDATE space_program SET collected=?,last_mined=? WHERE user_id=?',(stamp,stamp,uid))
    conn.execute('UPDATE player_activity SET last_activity=?,heartbeat=?,paused=0 WHERE user_id=?',(stamp,stamp,uid))
    return jsonify(success=True,inactive=False,deadline=stamp+INACTIVITY_SECONDS,server_time=stamp,message='Welcome back! Production has resumed.')

def war_protection(conn,faction_id,timestamp=None):
    stamp=int(time.time()) if timestamp is None else timestamp
    for player in conn.execute('SELECT id,username FROM users WHERE faction_id=? AND is_banned=0',(faction_id,)).fetchall():
        row=state(conn,player['id'],stamp)
        online=not row['inactive'] and row['heartbeat']>stamp-ONLINE_SECONDS
        if row['last_login']>stamp-WAR_RECENT_LOGIN_SECONDS and not online:
            return 'Cannot declare war: '+player['username']+' logged in within 24 hours and must currently be online.'
    return None

def install(namespace):
    global core
    core=namespace;app=core['app']
    app.add_url_rule('/api/activity','player_activity',core['require_login'](heartbeat),methods=['GET','POST'])
    app.add_url_rule('/api/activity/resume','resume_activity',core['require_login'](resume),methods=['POST'])
    @app.before_request
    def activity_gate():
        uid=session.get('user_id')
        if not uid or not request.path.startswith('/api/'):return
        if not core['get_db']().execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():return
        if request.path in ('/api/login','/api/register','/api/forgot_password','/api/logout'):return
        row=state(core['get_db'](),uid)
        if row['inactive'] and request.method!='GET' and request.path not in ('/api/activity','/api/activity/resume'):
            return jsonify(error='Production paused after 30 minutes of inactivity. Press Keep playing to continue.',inactive=True),423
    @app.after_request
    def record_login(response):
        if response.status_code==200 and request.path=='/api/income' and session.get('user_id'):
            row=state(core['get_db'](),session['user_id']);payload=response.get_json()
            payload['paused']=row['inactive']
            if row['inactive']:
                for field in ('rates','totals','orbital_rates'):payload[field]={key:0 for key in payload.get(field,{})}
                payload['troops_per_min']=0;payload['value_per_min']=0
            response.set_data(core['app'].json.dumps(payload))
        if response.status_code==200 and request.path=='/api/login' and response.get_json(silent=True).get('success'):
            uid=session.get('user_id')
            if uid:
                conn=core['get_db']();row=state(conn,uid);stamp=int(time.time())
                conn.execute('UPDATE player_activity SET last_login=?,heartbeat=? WHERE user_id=?',(stamp,0 if row['inactive'] else stamp,uid))
                if not row['inactive']:
                    core['auto_collect'](uid,conn)
                    conn.execute('UPDATE player_activity SET last_activity=? WHERE user_id=?',(stamp,uid))
        if request.path=='/api/logout' and response.status_code==200 and getattr(request,'activity_logout_uid',None):
            from playtime import record
            conn=core['get_db']();uid=request.activity_logout_uid
            record(conn,uid,False)
            conn.execute('UPDATE player_activity SET heartbeat=0 WHERE user_id=?',(uid,))
        return response
    @app.before_request
    def remember_logout():
        if request.path=='/api/logout':request.activity_logout_uid=session.get('user_id')
