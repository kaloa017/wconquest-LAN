"""v6 services: host safety, efficient map sync, optional fleets and progression.

install_features wires handlers into the existing Flask route names so old clients
and saves remain compatible. New UI uses the same game core and database.
"""
import gzip, hashlib, hmac, io, ipaddress, json, math, os, random, re, secrets, socket, sqlite3, threading, time
from collections import OrderedDict
from functools import wraps
from pathlib import Path
from flask import request, session, jsonify, g, send_file, abort, has_request_context
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from config import *
from geography import cell_land, cell_coastal, cell_japan, landmark_key, island_feature
from runtime import finish_transaction, close_transaction

core = None
_stats=OrderedDict();_limits=OrderedDict();_lock=threading.RLock()
_map_cache={};_music_lock=threading.Lock();_ideas_lock=threading.Lock()
_rate_settings={'requests':REQUESTS_PER_MINUTE,'auth':AUTH_REQUESTS_PER_MINUTE,'chat':CHAT_COOLDOWN,'trades':STOCK_TRADE_COOLDOWN}

def db(): return core['get_db']()
def integer(value,minimum=0,maximum=10**9):
    if isinstance(value,bool): raise ValueError('Expected an integer')
    if isinstance(value,str) and re.fullmatch(r'-?\d+',value): value=int(value)
    if not isinstance(value,int) or not minimum<=value<=maximum: raise ValueError(f'Expected integer between {minimum} and {maximum}')
    return value
def body():
    d=request.get_json(silent=True)
    if not isinstance(d,dict): abort(400,description='Expected a JSON object')
    return d
def audit(conn,action,target=None,details=None):
    conn.execute('INSERT INTO audit_log(ts,actor_id,actor,action,target_id,ip,details) VALUES(?,?,?,?,?,?,?)',
        (int(time.time()),session.get('user_id'),session.get('username','Guest'),action,target,request.remote_addr,json.dumps(details or {})))

def religion_for(conn,uid):
    u=conn.execute('SELECT religion FROM users WHERE id=?',(uid,)).fetchone()
    return RELIGIONS.get(u['religion'] if u else None,{})

def fleet_available(conn,uid,kind):
    if kind not in ('boats','planes'): raise ValueError('Unknown fleet')
    u=conn.execute(f'SELECT faction_id,{kind} FROM users WHERE id=?',(uid,)).fetchone()
    if not u:return 0
    shared=conn.execute(f'SELECT COALESCE(SUM({kind}),0) FROM users WHERE faction_id=? AND id<>? AND share_{kind}=1',(u['faction_id'],uid)).fetchone()[0] if u['faction_id'] else 0
    return u[kind]+shared

def fleet_change(conn,uid,kind,amount):
    amount=int(amount)
    if amount>=0:
        # Purchases and returns remain owned by the acting player.
        conn.execute(f'UPDATE users SET {kind}={kind}+? WHERE id=?',(amount,uid));return
    needed=-amount
    if fleet_available(conn,uid,kind)<needed: raise ValueError('Insufficient available fleet')
    u=conn.execute('SELECT faction_id FROM users WHERE id=?',(uid,)).fetchone()
    rows=conn.execute(f'SELECT id,{kind} FROM users WHERE id=? OR (faction_id=? AND share_{kind}=1) ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END,id',(uid,u['faction_id'],uid)).fetchall()
    # Record contributors so surviving vessels are returned to their owners.
    taken=[]
    for r in rows:
        n=min(needed,r[kind]);needed-=n
        if n: conn.execute(f'UPDATE users SET {kind}={kind}-? WHERE id=?',(n,r['id']));taken.append((r['id'],n))
        if not needed:break
    if has_request_context() and request.path in ('/api/boats/attack','/api/planes/attack'):
        g.fleet_debits=(kind,taken)

def pool_get(conn,uid,kind):
    if kind in ('boats','planes'): return fleet_available(conn,uid,kind)
    u=conn.execute('SELECT army,faction_id FROM users WHERE id=?',(uid,)).fetchone()
    if not u:return 0
    f=conn.execute('SELECT army FROM factions WHERE id=?',(u['faction_id'],)).fetchone() if u['faction_id'] else None
    return f['army'] if f else u['army']

def pool_add(conn,uid,kind,amount):
    if kind in ('boats','planes'):
        # Combat refunds are allocated proportionally to the vessels committed.
        if amount>0 and has_request_context() and getattr(g,'fleet_debits',None) and g.fleet_debits[0]==kind:
            taken=g.fleet_debits[1];total=sum(n for _,n in taken);left=int(amount)
            shares=[int(amount*n/total) for _,n in taken]
            for i in range(left-sum(shares)): shares[i%len(shares)]+=1
            for (owner,_),n in zip(taken,shares): fleet_change(conn,owner,kind,n)
            g.fleet_debits=None;return
        return fleet_change(conn,uid,kind,amount)
    f=core['fac_id'](conn,uid)
    if f:
        conn.execute('UPDATE factions SET army=MAX(0,army+?) WHERE id=?',(int(amount),f))
        if amount>0 and (not has_request_context() or request.path not in ('/api/attack','/api/boats/attack','/api/planes/attack')):
            conn.execute('INSERT INTO faction_contributions(user_id,faction_id,army) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET army=army+excluded.army',(uid,f,int(amount)))
    else:conn.execute('UPDATE users SET army=MAX(0,army+?) WHERE id=?',(int(amount),uid))

def join_faction(conn,uid,fid):
    u=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();f=conn.execute('SELECT color FROM factions WHERE id=?',(fid,)).fetchone()
    conn.execute('UPDATE factions SET army=army+? WHERE id=?',(u['army'],fid))
    conn.execute('UPDATE users SET army=0,faction_id=?,color=? WHERE id=?',(fid,f['color'],uid))
    conn.execute('INSERT OR REPLACE INTO faction_contributions VALUES(?,?,?)',(uid,fid,u['army']))
    conn.execute('DELETE FROM faction_requests WHERE user_id=?',(uid,))

def leave_faction(conn,uid,ban=False):
    fid=core['fac_id'](conn,uid)
    if not fid:return
    f=conn.execute('SELECT * FROM factions WHERE id=?',(fid,)).fetchone()
    n=core['faction_members'](conn,fid)
    contribution=conn.execute('SELECT army FROM faction_contributions WHERE user_id=? AND faction_id=?',(uid,fid)).fetchone()
    total=conn.execute('SELECT COALESCE(SUM(army),0) FROM faction_contributions WHERE faction_id=?',(fid,)).fetchone()[0]
    share=int(f['army']*contribution['army']/total) if contribution and total else 0
    if n==1:share=f['army']
    conn.execute('UPDATE factions SET army=army-? WHERE id=?',(share,fid))
    conn.execute('UPDATE users SET army=?,faction_id=NULL,color=COALESCE(base_color,color) WHERE id=?',(share,uid))
    conn.execute('DELETE FROM faction_contributions WHERE user_id=?',(uid,))
    if ban:conn.execute('INSERT OR REPLACE INTO faction_bans VALUES(?,?,?)',(fid,uid,(int(time.time())//86400+1)*86400))
    if f['leader_id']==uid:
        nxt=conn.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id LIMIT 1',(fid,)).fetchone()
        if nxt:conn.execute('UPDATE factions SET leader_id=? WHERE id=?',(nxt['id'],fid))
        else:
            for table in ('faction_research','faction_requests','faction_bans'):conn.execute(f'DELETE FROM {table} WHERE faction_id=?',(fid,))
            conn.execute('DELETE FROM faction_rel WHERE a=? OR b=?',(fid,fid));conn.execute('DELETE FROM factions WHERE id=?',(fid,))

def army_map(conn):
    users=conn.execute('SELECT u.id,u.faction_id,u.army,COUNT(t.id) n FROM users u LEFT JOIN territories t ON t.owner_id=u.id GROUP BY u.id').fetchall()
    factions={r['id']:r['army'] for r in conn.execute('SELECT id,army FROM factions')}
    counts={}
    for u in users:
        if u['faction_id']:counts[u['faction_id']]=counts.get(u['faction_id'],0)+u['n']
    return {u['id']:(factions.get(u['faction_id'],u['army']),max(1,counts.get(u['faction_id'],u['n']))) for u in users}

def water(conn,key):
    core['parse_key'](key)
    # Grandfather existing ownership, but never trust old client water reports.
    if conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id IS NOT NULL',(key,)).fetchone():return False
    if key.startswith('island:'):
        feature=island_feature(key)
        if feature and feature['properties'].get('grid_tiles'):return True
        if island_legacy_owner(conn,key):return True
    elif large_island_legacy_owner(conn,key):return True
    return not cell_land(key)

def large_island_legacy_owner(conn,key):
    from geography import island_neighbors,rings_intersect_cell
    a,b=core['parse_key'](key)
    candidates=[k for k in island_neighbors(a,b,include_grid=True) if island_feature(k)['properties'].get('grid_tiles')]
    if not candidates:return None
    rows=conn.execute('SELECT grid_key FROM territories WHERE owner_id IS NOT NULL AND grid_key IN ('+','.join('?' for _ in candidates)+')',candidates)
    for row in rows:
        if rings_intersect_cell(island_feature(row['grid_key'])['geometry']['coordinates'],a,b):return row['grid_key']
    return None

def island_legacy_owner(conn,key):
    feature=island_feature(key)
    if not feature:return None
    from geography import rings_intersect_cell
    a,b,c,d=feature['properties']['bounds']
    for row in conn.execute("SELECT grid_key,owner_id FROM territories WHERE owner_id IS NOT NULL AND grid_key NOT LIKE 'island:%'"):
        lat,lng=core['parse_key'](row['grid_key'])
        if (lng+1)*GRID>=a and lng*GRID<=c and (lat+1)*GRID>=b and lat*GRID<=d and rings_intersect_cell(feature['geometry']['coordinates'],lat,lng):return row['grid_key']
    return None
def coastal(conn,key):
    a,b=core['parse_key'](key)
    if key.startswith('island:'):return not water(conn,key)
    return not water(conn,key) and (cell_coastal(key) or any(water(conn,k) for k in core['adj_keys'](a,b) if k.startswith('island:') or (-473<=int(k.split(',')[0])<=472 and -1000<=int(k.split(',')[1])<=999)))
def touch_presence(uid):
    # Request stats are flushed on the scheduler, not once per API poll.
    return None

def rate_allowed(key,limit):
    if limit==0:return True
    now=time.time();slot=int(now//60)
    with _lock:
        previous=_limits.get(key)
        count=previous[1]+1 if previous and previous[0]==slot else 1
        _limits[key]=(slot,count);_limits.move_to_end(key)
        while len(_limits)>MAX_TRACKED_CLIENTS:_limits.popitem(last=False)
    return count<=limit

def before_request():
    g.started=time.perf_counter()
    if not request.path.startswith('/api/'):return
    if not rate_allowed('ip:'+str(request.remote_addr),_rate_settings['requests']): return jsonify(error='Too many requests; wait a minute'),429
    if request.path in ('/api/login','/api/register','/api/forgot_password'):
        if not rate_allowed('auth:'+str(request.remote_addr),_rate_settings['auth']):return jsonify(error='Too many account attempts; wait a minute'),429
    uid=session.get('user_id')
    if uid:
        conn=db();u=conn.execute('SELECT auth_version,is_banned FROM users WHERE id=?',(uid,)).fetchone()
        if not u or u['is_banned'] or session.get('auth_version',0)!=u['auth_version']:
            session.clear()
            if request.path not in ('/api/login','/api/logout'):return jsonify(error='Session ended; please log in again'),401
    if request.method=='POST':
        if not hmac.compare_digest(request.headers.get('X-WC-CSRF',''),session.get('csrf','!')):return jsonify(error='Refresh the page to renew your request token'),403
        if request.mimetype!='multipart/form-data':
            d=body()
            for key,value in d.items():
                if key in ('message','text','name','tag','descr','color','resource','unit','kind','channel','action','rank','type','key','give_res','get_res','symbol','side','idea','image','image_url','recovery_code','reset_pin','pin') and not isinstance(value,str):raise ValueError('Expected text for '+key)
                if key in ('ban','promote','accept','enabled','water','from_treasury','display_faction_colors','share_boats','share_planes','music_muted') and not isinstance(value,bool) and key!='water':raise ValueError('Expected true or false for '+key)
                if key in ('amount','troops','boats','planes','minutes','user_id','faction_id','to_id','host_id','request_id','loan_id','rel_id','merge_id','trade_id','give_amt','get_amt'):
                    integer(value,0,10**9)
                if key in ('grid_key','from_key','target_key') and value:core['parse_key'](value)
                if key in ('username','new_username','to_username') and not isinstance(value,str):raise ValueError('Expected a name')
                if 'password' in key and (not isinstance(value,str) or len(value)>256):raise ValueError('Invalid password')
            if request.path=='/api/admin/announce':
                from urllib.parse import urlsplit
                if not isinstance(d.get('message'),str) or len(d['message'])>4000:raise ValueError('Announcement must be below 4,000 characters')
                if d.get('image_url') and (not isinstance(d['image_url'],str) or len(d['image_url'])>2048 or urlsplit(d['image_url']).scheme not in ('http','https')):raise ValueError('Image URL must use HTTP or HTTPS')
            if request.path in ('/api/profile/change_password','/api/admin/reset_password') and len(d.get('new_password',''))<8:raise ValueError('New passwords need at least 8 characters')
            if request.path in ('/api/admin/give_money','/api/admin/give_resource','/api/admin/give_territory') and d.get('confirm') is not True:raise ValueError('Cheating is unethical and unfair to other players. Explicit confirmation required.')
    return None

def after_request(response):
    conn=g.get('db')
    if response.status_code<400 and request.method=='POST' and conn:
        if request.path.startswith('/api/admin/'):
            d=request.get_json(silent=True) or {}
            safe={k:v for k,v in d.items() if k in ('user_id','resource','amount','grid_key','type','ban','promote','minutes','faction_id','key','value','action')}
            audit(conn,request.path,d.get('user_id'),safe)
        if request.path in ('/api/admin/reset_password','/api/profile/change_password'):
            uid=(request.get_json(silent=True) or {}).get('user_id',session.get('user_id'))
            conn.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?',(uid,))
            if uid==session.get('user_id'):session['auth_version']=conn.execute('SELECT auth_version FROM users WHERE id=?',(uid,)).fetchone()[0]
            audit(conn,'password_changed',uid)
    response=finish_transaction(response)
    if response.status_code>=400 and request.path in ('/api/forgot_password','/api/profile/recovery','/api/admin/recovery') and conn:
        audit(conn,'recovery_rejected',details={'route':request.path,'status':response.status_code})
        sqlite3.Connection.commit(conn)
    if request.path.startswith('/api/'):
        uid=session.get('user_id');ip=request.remote_addr or '';peer=request.environ.get('werkzeug.proxy_fix.orig',{}).get('REMOTE_ADDR',ip)
        key=f'{uid or 0}:{ip}:{peer}'
        with _lock:
            s=_stats.setdefault(key,{'client':key,'user_id':uid,'ip':ip,'peer_ip':peer,'requests':0,'last_seen':0})
            s['requests']+=1;s['last_seen']=int(time.time());_stats.move_to_end(key)
            if len(_stats)>MAX_TRACKED_CLIENTS:_stats.popitem(last=False)
    response.headers['X-Content-Type-Options']='nosniff'
    # Map providers need a browser referrer; cross-origin requests disclose only
    # the site's origin, never the player's page path or query string.
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['X-Frame-Options']='DENY'
    if response.mimetype=='application/json' and request.path!='/api/islands':response.headers['Cache-Control']='no-store'
    # Never compress credentials/recovery responses alongside attacker input.
    if request.method=='GET' and request.path in ('/api/territories','/api/map/sync','/api/buildings','/api/fallout') and request.accept_encodings['gzip']>0 and response.status_code==200:
        raw=response.get_data()
        if len(raw)>512:response.set_data(gzip.compress(raw,compresslevel=3));response.headers['Content-Encoding']='gzip';response.headers['Vary']='Accept-Encoding'
    response.headers['Server-Timing']=f'app;dur={(time.perf_counter()-g.get("started",time.perf_counter()))*1000:.2f}'
    return response

def error_response(error):
    if isinstance(error,HTTPException):return jsonify(error=error.description),error.code
    if isinstance(error,(ValueError,TypeError,KeyError,OverflowError)):return jsonify(error='Invalid request: '+str(error)[:120]),400
    if isinstance(error,sqlite3.IntegrityError):return jsonify(error='The action conflicts with existing data'),409
    if isinstance(error,sqlite3.OperationalError):
        core['app'].logger.exception('Database operation failed');return jsonify(error='Server busy; try again shortly'),503
    core['app'].logger.exception('Request failed');return jsonify(error='Unexpected server error'),500

def register_account():
    d=body();name=d.get('username','').strip();password=d.get('password','')
    if not re.fullmatch(r'[\w .-]{3,20}',name):raise ValueError('Name must be 3–20 letters, numbers, spaces, dots or dashes')
    if len(password)<8:raise ValueError('Password needs at least 8 characters')
    code=secrets.token_urlsafe(24);conn=db()
    cursor=conn.execute('INSERT INTO users(username,password,color,base_color,recovery_hash) VALUES(?,?,?,?,?)',(name,generate_password_hash(password),random.choice(PLAYER_COLORS),None,generate_password_hash(code)))
    conn.execute('UPDATE users SET base_color=color WHERE id=?',(cursor.lastrowid,))
    audit(conn,'recovery_generated',cursor.lastrowid)
    return jsonify(success=True,message='Account created. Save your recovery code; it is shown once.',recovery_code=code,is_admin=False)

def login_account():
    d=body();conn=db();u=conn.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(d.get('username',''),)).fetchone()
    if not u or not core['password_matches'](u['password'],d.get('password','')):return jsonify(error='Invalid username or password'),401
    if u['is_banned']:return jsonify(error='Account banned'),403
    if len(u['password'])==64:conn.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(d['password']),u['id']))
    csrf=session.get('csrf',secrets.token_urlsafe(32));session.clear();session.update(user_id=u['id'],username=u['username'],auth_version=u['auth_version'],csrf=csrf)
    return jsonify(success=True,user={'id':u['id'],'username':u['username'],'color':u['color'],'is_admin':bool(u['is_admin'])})

def recover_account():
    d=body();conn=db();u=conn.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(d.get('username',''),)).fetchone()
    code=d.get('recovery_code',d.get('reset_pin',''));password=d.get('new_password','')
    if not isinstance(code,str) or len(code)>128 or len(password)<8:raise ValueError('Enter a recovery code and a password with at least 8 characters')
    allowed=False;which=None
    if u:
        if u['recovery_hash'] and check_password_hash(u['recovery_hash'],code):allowed=True;which='player'
        elif u['reset_code_hash'] and u['reset_code_until']>time.time() and check_password_hash(u['reset_code_hash'],code):allowed=True;which='admin'
    if not allowed:
        # Rejected attempts are logged in an independent transaction by the limiter flush.
        return jsonify(error='Invalid or expired recovery code'),400
    conn.execute('UPDATE users SET password=?,auth_version=auth_version+1,recovery_hash=NULL,reset_code_hash=NULL,reset_code_until=0,reset_pin=NULL WHERE id=?',(generate_password_hash(password),u['id']))
    audit(conn,'account_recovered',u['id'],{'code_type':which});return jsonify(success=True,message='Password reset. Log in and generate a new recovery code.')

def profile_recovery():
    d=body();conn=db();u=conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if not core['password_matches'](u['password'],d.get('password','')):return jsonify(error='Incorrect password'),403
    code=secrets.token_urlsafe(24);conn.execute('UPDATE users SET recovery_hash=?,reset_pin=NULL WHERE id=?',(generate_password_hash(code),session['user_id']))
    audit(conn,'recovery_generated',session['user_id']);return jsonify(success=True,recovery_code=code,message='Save this code securely; it is shown once.')

def bootstrap():
    session.setdefault('csrf',secrets.token_urlsafe(32))
    return jsonify(csrf=session['csrf'],version=VERSION,community=COMMUNITY,ideologies=IDEOLOGIES,religions=RELIGIONS,
        faction_colors=FACTION_COLORS,prices={'boat':{'money':BOAT_COST_M,'wood':BOAT_COST_W},'plane':{'money':PLANE_COST_M,'metal':PLANE_COST_X,'oil':PLANE_COST_O},'voyage_money':VOYAGE_MONEY,'voyage_wood':VOYAGE_WOOD},stock_fee=STOCK_FEE,stock_interval=STOCK_INTERVAL)

def map_snapshot(conn):
    am=army_map(conn)
    rows=conn.execute('''SELECT t.grid_key,t.owner_id,t.terrain,t.population,u.username,u.color,u.base_color,u.capital_key,
        b.type bt,b.level bl,f.tag,f.color faction_color FROM territories t JOIN users u ON u.id=t.owner_id
        LEFT JOIN buildings b ON b.grid_key=t.grid_key LEFT JOIN factions f ON f.id=u.faction_id WHERE t.owner_id IS NOT NULL''').fetchall()
    return {r['grid_key']:{'grid_key':r['grid_key'],'owner_id':r['owner_id'],'owner':r['username'],'color':r['color'] or '#888','base_color':r['base_color'] or r['color'],
        'faction_color':r['faction_color'],'terrain':r['terrain'],'population':r['population'],'garrison':int(am[r['owner_id']][0]/am[r['owner_id']][1]**.55+3),
        'boats':0,'planes':0,'building':r['bt'],'blevel':r['bl'],'tag':r['tag'],'capital':r['capital_key']==r['grid_key']} for r in rows}

def map_sync():
    conn=db();conn.execute('BEGIN') if not conn.in_transaction else None
    epoch=conn.execute('SELECT value FROM map_epoch WHERE id=1').fetchone()[0]
    seq=conn.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='map_changes'),0)").fetchone()[0]
    version=f'{epoch}:{seq}'
    since=request.args.get('since','')
    if since==version:return jsonify(version=version,reset=False,changed=[],removed=[])
    with _lock:
        if _map_cache.get('version')!=version:_map_cache.update(version=version,tiles=map_snapshot(conn))
        tiles=_map_cache['tiles']
    try:old_epoch,old_seq=map(int,since.split(':'))
    except (ValueError,TypeError):old_epoch,old_seq=-1,-1
    floor=conn.execute('SELECT COALESCE(MIN(seq),0) FROM map_changes').fetchone()[0]
    reset=old_epoch!=epoch or old_seq<floor-1 or old_seq>seq
    if reset:return jsonify(version=version,reset=True,changed=list(tiles.values()),removed=[])
    keys={r['grid_key'] for r in conn.execute('SELECT grid_key FROM map_changes WHERE seq>?',(old_seq,))}
    return jsonify(version=version,reset=False,changed=[tiles[k] for k in keys if k in tiles],removed=[k for k in keys if k not in tiles])

def territories_full():
    conn=db();return jsonify(list(map_snapshot(conn).values()))

def profile_preferences():
    d=body();allowed={'display_faction_colors','share_boats','share_planes','music_muted','music_volume','donator_title'};conn=db()
    for key,value in d.items():
        if key not in allowed:raise ValueError('Unknown setting')
        if key=='donator_title':
            if not conn.execute('SELECT is_donator FROM users WHERE id=?',(session['user_id'],)).fetchone()[0]:abort(403)
            if value not in ('Supporter','Patron','Island Guardian'):raise ValueError('Choose a supporter title')
        elif key=='music_volume':
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('Volume must be between 0 and 1')
        elif not isinstance(value,bool):raise ValueError('Toggle must be true or false')
        conn.execute(f'UPDATE users SET {key}=? WHERE id=?',(value,session['user_id']))
    return jsonify(success=True,message='Preferences saved')

def religion_set():
    d=body();key=d.get('id');conn=db();u=conn.execute('SELECT religion,religion_ts FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if key not in RELIGIONS:raise ValueError('Unknown religion')
    remaining=max(0,int(u['religion_ts']+RELIGION_COOLDOWN-time.time())) if u['religion'] else 0
    if remaining:return jsonify(error='Religion can change once per 24 hours',cooldown=remaining),409
    conn.execute('UPDATE users SET religion=?,religion_ts=? WHERE id=?',(key,int(time.time()),session['user_id']))
    return jsonify(success=True,message='Religion adopted')

def me_details(conn,u,uid):
    out=core['_v5_me_extra'](conn,u,uid)
    out.update({k:u[k] for k in ('religion','display_faction_colors','share_boats','share_planes','music_volume','music_muted','last_seen_version','is_donator','donator_title','rank_override','ideas_banned')})
    if u['rank_override']:
        rank=next((r for r in RANKS if r[2]==u['rank_override']),None)
        if rank:out['rank']={'icon':rank[1],'name':rank[2]}
    out['religion_cooldown']=max(0,int(u['religion_ts']+RELIGION_COOLDOWN-time.time())) if u['religion'] else 0
    out['daily_ready']=u['last_daily']!=int(time.time()//86400)
    out['own_boats']=u['boats'];out['own_planes']=u['planes'];out['has_recovery']=bool(u['recovery_hash'])
    return out

def choose_slot(conn,value,current=None):
    if value is None:
        used={r['color_slot'] for r in conn.execute('SELECT color_slot FROM factions WHERE color_slot IS NOT NULL')}
        available=[s for s in range(8) if s not in used]
        if not available:raise ValueError('All eight faction colours are taken')
        return available[0]
    if isinstance(value,str) and value in FACTION_COLORS:value=FACTION_COLORS.index(value)
    slot=integer(value,0,7)
    existing=conn.execute('SELECT id FROM factions WHERE color_slot=?',(slot,)).fetchone()
    if existing and existing['id']!=current:raise ValueError('That colour belongs to another faction')
    return slot

def faction_create():
    d=body();uid=session['user_id'];conn=db();name=d.get('name','').strip();tag=d.get('tag','').strip().upper()
    if not 3<=len(name)<=24 or not 2<=len(tag)<=4 or not tag.isalnum():raise ValueError('Name 3–24 characters; tag 2–4 letters or digits')
    if conn.execute('SELECT COUNT(*) FROM factions').fetchone()[0]>=MAX_FACTIONS:raise ValueError('Maximum eight factions reached')
    u=conn.execute('SELECT money,faction_id FROM users WHERE id=?',(uid,)).fetchone()
    if u['faction_id']:raise ValueError('Leave your faction first')
    if u['money']<FACTION_COST:raise ValueError(f'Founding costs {FACTION_COST}')
    slot=choose_slot(conn,d.get('color_slot'));cur=conn.execute('INSERT INTO factions(name,tag,leader_id,color,color_slot,last_tick) VALUES(?,?,?,?,?,?)',(name,tag,uid,FACTION_COLORS[slot],slot,int(time.time())))
    conn.execute('UPDATE users SET money=money-? WHERE id=?',(FACTION_COST,uid));join_faction(conn,uid,cur.lastrowid)
    return jsonify(success=True,message='Faction founded',achievements=core['award_achievements'](conn,uid))

def faction_settings():
    d=body();conn=db();f,err=core['_my_fac'](conn,session['user_id'],True)
    if err:return jsonify(error=err[0]),err[1]
    mode=d.get('mode',f['mode'])
    if mode not in ('open','invite','closed'):raise ValueError('Invalid mode')
    slot=choose_slot(conn,d.get('color_slot',d.get('color',f['color_slot'])),f['id'])
    conn.execute('UPDATE factions SET mode=?,color=?,color_slot=?,descr=? WHERE id=?',(mode,FACTION_COLORS[slot],slot,str(d.get('descr',f['descr'] or ''))[:140],f['id']))
    conn.execute('UPDATE users SET color=? WHERE faction_id=?',(FACTION_COLORS[slot],f['id']))
    return jsonify(success=True,message='Faction settings saved')

def faction_page():
    conn=db();fid=integer(request.args.get('id',str(core['fac_id'](conn,session['user_id']) or 0)),0)
    f=conn.execute('SELECT * FROM factions WHERE id=?',(fid,)).fetchone()
    if not f:return jsonify(faction=None)
    out=core['faction_dict'](conn,f)
    out['boats']=conn.execute('SELECT COALESCE(SUM(boats),0) FROM users WHERE faction_id=? AND share_boats=1',(fid,)).fetchone()[0]
    out['planes']=conn.execute('SELECT COALESCE(SUM(planes),0) FROM users WHERE faction_id=? AND share_planes=1',(fid,)).fetchone()[0]
    out['color_slot']=f['color_slot']
    out['shared_boats']=out['boats'];out['shared_planes']=out['planes'];out['is_leader']=f['leader_id']==session['user_id']
    return jsonify(faction=out)

def wonders_list():
    conn=db();uid=session['user_id'];own={r['key']:r for r in conn.execute('SELECT * FROM wonders WHERE owner_id=?',(uid,))}
    keys=[r['grid_key'] for r in conn.execute('SELECT grid_key FROM territories WHERE owner_id=?',(uid,))]
    japan=any(cell_japan(k) for k in keys);out=[]
    for key,info in WONDERS.items():
        if info.get('hidden') and not japan and key not in own:continue
        out.append({'key':key,**info,'owned':key in own,'owner_id':uid if key in own else None,'owner':session['username'] if key in own else None,
            'required_tile':None,'can_build':bool(keys) and (japan if info.get('country')=='JPN' else True)})
    return jsonify(out)

def wonders_buy():
    d=body();key=d.get('key');uid=session['user_id'];conn=db()
    if key not in WONDERS:raise ValueError('Unknown wonder')
    if conn.execute('SELECT 1 FROM wonders WHERE key=? AND owner_id=?',(key,uid)).fetchone():raise ValueError('You already own this wonder')
    info=WONDERS[key];keys=[r['grid_key'] for r in conn.execute('SELECT grid_key FROM territories WHERE owner_id=?',(uid,))]
    if not keys:raise ValueError('Claim your first territory to found a country before purchasing wonders')
    if info.get('country')=='JPN' and not any(cell_japan(k) for k in keys):raise ValueError('Own territory in Japan to unlock this secret country wonder')
    u=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not core['can_afford'](u,info['cost']):raise ValueError('Need '+core['fmt_cost'](info['cost']))
    core['pay'](conn,uid,info['cost']);conn.execute('INSERT INTO wonders(key,owner_id,ts,grid_key) VALUES(?,?,?,NULL)',(key,uid,int(time.time())))
    return jsonify(success=True,message=info['name']+' completed',achievements=core['award_achievements'](conn,uid))

def eva_wonder_for_image(name):
    # Old custom JPG filenames remain usable for migrated EVA-01 owners.
    match=re.match(r'^eva[_-](00|01|02)(?:[_-]|\.jpg$)',name)
    return 'eva_'+match.group(1) if match else 'eva_01'

def eva_gallery():
    conn=db();uid=session['user_id']
    owned={r['key'] for r in conn.execute("SELECT key FROM wonders WHERE owner_id=? AND key IN ('eva_00','eva_01','eva_02')",(uid,))}
    folder=Path(core['app'].static_folder)/'eva';images=[]
    if folder.exists() and owned:
        for path in sorted(folder.glob('*.jpg')):
            key=eva_wonder_for_image(path.name)
            if key in owned and re.fullmatch(r'[a-z0-9_-]+\.jpg',path.name):
                images.append({'name':path.stem.replace('_',' ').title(),'wonder':key,'unit':WONDERS[key]['name'],'url':'/static/eva/'+path.name})
            if len(images)>=24:break
    return jsonify(images=images,cosmetic_only=True)

def eva_deploy():
    d=body();conn=db();uid=session['user_id'];key=d.get('grid_key');name=d.get('image')
    core['parse_key'](key)
    if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9_-]+\.jpg',name):raise ValueError('Choose a JPG portrait')
    wonder=eva_wonder_for_image(name)
    if not conn.execute('SELECT 1 FROM wonders WHERE owner_id=? AND key=?',(uid,wonder)).fetchone():abort(403)
    if not conn.execute('SELECT 1 FROM territories WHERE owner_id=? AND grid_key=?',(uid,key)).fetchone():raise ValueError('Place the cosmetic unit on your own tile')
    path=Path(core['app'].static_folder)/'eva'/name
    if not path.is_file() or path.stat().st_size>1024*1024 or path.read_bytes()[:3]!=b'\xff\xd8\xff':raise ValueError('JPG must be a real JPEG below 1 MB')
    conn.execute('INSERT INTO eva_deployments VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET grid_key=excluded.grid_key,image=excluded.image',(uid,key,name))
    return jsonify(success=True,message=WONDERS[wonder]['name']+' placed. No combat or economy effects.')

def eva_deployments():
    conn=db();units=[]
    for row in conn.execute('SELECT e.user_id,e.grid_key,e.image FROM eva_deployments e JOIN territories t ON t.grid_key=e.grid_key AND t.owner_id=e.user_id'):
        wonder=eva_wonder_for_image(row['image'])
        if conn.execute('SELECT 1 FROM wonders WHERE owner_id=? AND key=?',(row['user_id'],wonder)).fetchone():units.append(dict(row))
    return jsonify(units=units,cosmetic_only=True)

def market():
    conn=db();uid=session['user_id'];fid=core['fac_id'](conn,uid)
    rows=conn.execute('''SELECT p.*,u.faction_id target_faction,CASE WHEN p.kind='country' THEN u.username ELSE f.name END name
        FROM stock_prices p LEFT JOIN users u ON p.kind='country' AND p.target_id=u.id
        LEFT JOIN factions f ON p.kind='faction' AND p.target_id=f.id ORDER BY p.symbol''').fetchall()
    assets=[]
    for row in rows:
        item=dict(row);target_faction=item.pop('target_faction')
        item['investable']=not (item['kind']=='country' and (item['target_id']==uid or (fid and target_faction==fid))) and not (item['kind']=='faction' and item['target_id']==fid)
        assets.append(item)
    holdings=[dict(r) for r in conn.execute('SELECT h.*,p.price,h.quantity*p.price value FROM stock_holdings h JOIN stock_prices p USING(symbol) WHERE user_id=?',(uid,))]
    symbol=request.args.get('symbol','');history=[dict(r) for r in conn.execute('SELECT ts,price FROM stock_history WHERE symbol=? ORDER BY ts',(symbol,))]
    return jsonify(assets=assets,portfolio=holdings,history=history,fee=STOCK_FEE,interval=STOCK_INTERVAL)

def stock_trade():
    d=body();uid=session['user_id'];conn=db();qty=integer(d.get('quantity'),1,STOCK_MAX_QUANTITY);symbol=d.get('symbol');side=d.get('side')
    if side not in ('buy','sell'):raise ValueError('Choose buy or sell')
    p=conn.execute('SELECT * FROM stock_prices WHERE symbol=?',(symbol,)).fetchone();u=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not p:raise ValueError('Unknown investment')
    if time.time()-u['stock_trade_ts']<_rate_settings['trades']:return jsonify(error='Wait a few seconds between trades'),429
    fid=u['faction_id']
    if side=='buy' and ((p['kind']=='country' and (p['target_id']==uid or (fid and core['fac_id'](conn,p['target_id'])==fid))) or (p['kind']=='faction' and p['target_id']==fid)):raise ValueError('You cannot invest in yourself or your own faction members')
    h=conn.execute('SELECT * FROM stock_holdings WHERE user_id=? AND symbol=?',(uid,symbol)).fetchone();owned=h['quantity'] if h else 0
    value=qty*p['price'];fee=value*STOCK_FEE
    if side=='buy':
        if owned+qty>STOCK_MAX_POSITION:raise ValueError('Position limit reached')
        if u['money']<value+fee:raise ValueError('Insufficient money including fee')
        conn.execute('UPDATE users SET money=money-? WHERE id=?',(value+fee,uid))
        conn.execute('INSERT INTO stock_holdings VALUES(?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET quantity=quantity+excluded.quantity,cost_basis=cost_basis+excluded.cost_basis',(uid,symbol,qty,value+fee))
    else:
        if qty>owned:raise ValueError('You do not own that many shares')
        conn.execute('UPDATE users SET money=money+? WHERE id=?',(value-fee,uid))
        conn.execute('UPDATE stock_holdings SET quantity=quantity-?,cost_basis=cost_basis*(quantity-?)/quantity WHERE user_id=? AND symbol=?',(qty,qty,uid,symbol))
        conn.execute('DELETE FROM stock_holdings WHERE quantity=0')
    conn.execute('INSERT INTO stock_transactions(user_id,symbol,side,quantity,price,fee,ts) VALUES(?,?,?,?,?,?,?)',(uid,symbol,side,qty,p['price'],fee,int(time.time())))
    conn.execute('UPDATE users SET stock_trade_ts=? WHERE id=?',(time.time(),uid))
    return jsonify(success=True,message=f'{side.title()} completed',fee=fee)

def scheduler_tick():
    """SQLite lease keeps scheduled writes single-owner across WSGI processes."""
    conn=db();now=int(time.time())
    try:
        conn.execute('BEGIN IMMEDIATE')
        with _lock:
            pending=list(_stats.values());_stats.clear()
        for s in pending:
            conn.execute('INSERT INTO request_stats VALUES(?,?,?,?,?,?) ON CONFLICT(client) DO UPDATE SET requests=requests+excluded.requests,last_seen=excluded.last_seen',tuple(s[k] for k in ('client','user_id','ip','peer_ip','requests','last_seen')))
            if s['user_id']:conn.execute('UPDATE users SET last_seen=? WHERE id=?',(s['last_seen'],s['user_id']))
        settings=core['get_setting'](conn,'rate_limits')
        if settings:_rate_settings.update(json.loads(settings));core['CHAT_COOLDOWN']=_rate_settings['chat']
        due=conn.execute('SELECT next_tick FROM scheduler_state WHERE id=1').fetchone()[0]
        if now>=due:
            conn.execute('UPDATE scheduler_state SET next_tick=? WHERE id=1',(now+SCHEDULER_INTERVAL,))
            win_time=core['get_setting'](conn,'win_time')
            if core['get_setting'](conn,'winner_id') and win_time and now-float(win_time)>=WIN_COUNTDOWN:core['do_game_reset'](conn)
            for u in conn.execute('SELECT id FROM users WHERE is_banned=0').fetchall():core['auto_collect'](u['id'],conn)
            targets=[]
            for r in conn.execute('SELECT u.id,COUNT(t.id) n,u.last_seen FROM users u LEFT JOIN territories t ON t.owner_id=u.id WHERE u.is_banned=0 GROUP BY u.id'):
                targets.append(('country',r['id'],r['n'],r['last_seen']))
            for r in conn.execute('SELECT f.id,COUNT(t.id) n,MAX(u.last_seen) last_seen FROM factions f LEFT JOIN users u ON u.faction_id=f.id LEFT JOIN territories t ON t.owner_id=u.id GROUP BY f.id'):
                targets.append(('faction',r['id'],r['n'],r['last_seen'] or 0))
            live=set()
            for kind,target,n,active in targets:
                symbol=('C' if kind=='country' else 'F')+str(target);live.add(symbol)
                anchor=min(STOCK_MAX_PRICE*.8,max(STOCK_MIN_PRICE*2,20+math.sqrt(n)*8+(5 if now-active<600 else 0)))
                conn.execute('INSERT OR IGNORE INTO stock_prices VALUES(?,?,?,?,?,?)',(symbol,kind,target,anchor,anchor,0))
                p=conn.execute('SELECT * FROM stock_prices WHERE symbol=?',(symbol,)).fetchone()
                if now-p['last_tick']>=STOCK_INTERVAL:
                    event=core['ev_type'](conn);event_shift=STOCK_EVENT_SHIFT.get(event,0)
                    price=min(STOCK_MAX_PRICE,max(STOCK_MIN_PRICE,p['price']+(anchor-p['price'])*STOCK_REVERSION+p['price']*(random.uniform(-STOCK_VOLATILITY,STOCK_VOLATILITY)+event_shift)))
                    conn.execute('UPDATE stock_prices SET price=?,anchor=?,last_tick=? WHERE symbol=?',(price,anchor,now,symbol))
                    conn.execute('INSERT OR REPLACE INTO stock_history VALUES(?,?,?)',(symbol,now,price))
                    conn.execute('DELETE FROM stock_history WHERE symbol=? AND ts NOT IN (SELECT ts FROM stock_history WHERE symbol=? ORDER BY ts DESC LIMIT ?)',(symbol,symbol,STOCK_HISTORY_LIMIT))
            # Liquidate delisted shares at their last price, so account/faction deletion cannot strand money.
            for p in conn.execute('SELECT symbol,price FROM stock_prices').fetchall():
                if p['symbol'] not in live:
                    for h in conn.execute('SELECT user_id,quantity FROM stock_holdings WHERE symbol=?',(p['symbol'],)):
                        conn.execute('UPDATE users SET money=money+? WHERE id=?',(h['quantity']*p['price']*(1-STOCK_FEE),h['user_id']))
                    for table in ('stock_holdings','stock_history','stock_prices'):conn.execute(f'DELETE FROM {table} WHERE symbol=?',(p['symbol'],))
            conn.execute('DELETE FROM map_changes WHERE seq<(SELECT COALESCE(MAX(seq),0)-20000 FROM map_changes)')
            conn.execute('DELETE FROM request_stats WHERE client NOT IN (SELECT client FROM request_stats ORDER BY last_seen DESC LIMIT ?)',(MAX_TRACKED_CLIENTS,))
            conn.execute('DELETE FROM audit_log WHERE id<(SELECT COALESCE(MAX(id),0)-10000 FROM audit_log)')
            conn.execute('DELETE FROM stock_transactions WHERE id<(SELECT COALESCE(MAX(id),0)-20000 FROM stock_transactions)')
        conn.commit()
    except Exception:
        conn.rollback()
        with _lock:
            for s in locals().get('pending',[]):
                old=_stats.get(s['client'])
                if old:old['requests']+=s['requests']
                else:_stats[s['client']]=s
        raise
    finally:conn.close()

def scheduler_loop():
    while True:
        try:scheduler_tick()
        except Exception:core['app'].logger.exception('Scheduled update failed')
        time.sleep(SAVE_INTERVAL)

def admin_requests():
    conn=db();rows={r['client']:dict(r) for r in conn.execute('SELECT r.*,u.username FROM request_stats r LEFT JOIN users u ON u.id=r.user_id')}
    with _lock:
        for key,s in _stats.items():
            if key in rows:rows[key]['requests']+=s['requests'];rows[key]['last_seen']=s['last_seen']
            else:
                rows[key]=dict(s);u=conn.execute('SELECT username FROM users WHERE id=?',(s['user_id'],)).fetchone();rows[key]['username']=u[0] if u else 'Guest'
    sort=request.args.get('sort','requests');sort=sort if sort in ('requests','username','ip','last_seen') else 'requests'
    aggregate={}
    for r in rows.values():
        key=r['user_id'] or r['client'];item=aggregate.setdefault(key,{'user_id':r['user_id'],'username':r['username'] or 'Guest','ip':set(),'peer_ip':set(),'requests':0,'last_seen':0})
        item['ip'].add(r['ip']);item['peer_ip'].add(r['peer_ip']);item['requests']+=r['requests'];item['last_seen']=max(item['last_seen'],r['last_seen'])
    users=[dict(r,ip=', '.join(sorted(r['ip'])),peer_ip=', '.join(sorted(r['peer_ip']))) for r in aggregate.values()]
    return jsonify(clients=sorted(rows.values(),key=lambda r:r.get(sort) or '',reverse=sort in ('requests','last_seen')),users=sorted(users,key=lambda r:r.get(sort) or '',reverse=sort in ('requests','last_seen')),limits=_rate_settings)

def admin_audit():
    before=integer(request.args.get('before',str(2**62)),0,2**63-1)
    return jsonify(entries=[dict(r) for r in db().execute('SELECT * FROM audit_log WHERE id<? ORDER BY id DESC LIMIT 100',(before,))])

def admin_rate_limits():
    d=body();settings={k:integer(d.get(k,_rate_settings[k]),0,10**9) for k in ('requests','auth','chat','trades')}
    core['set_setting'](db(),'rate_limits',json.dumps(settings));_rate_settings.update(settings)
    core['CHAT_COOLDOWN']=settings['chat']
    with _lock:_limits.clear()
    return jsonify(success=True,message='Rate limits saved')

def admin_recovery():
    d=body();uid=integer(d.get('user_id'),1);conn=db()
    if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise ValueError('Player not found')
    code=secrets.token_urlsafe(24);conn.execute('UPDATE users SET reset_code_hash=?,reset_code_until=? WHERE id=?',(generate_password_hash(code),int(time.time())+3600,uid))
    audit(conn,'admin_reset_code_generated',uid)
    return jsonify(success=True,reset_code=code,expires_in=3600,message='One-time code expires in one hour. Share privately.')

def admin_player():
    d=body();uid=integer(d.get('user_id'),1);action=d.get('action');conn=db()
    if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise ValueError('Player not found')
    cheats=('resources','spawn','instant_build','give_money','give_resource')
    if action in cheats and d.get('confirm') is not True:raise ValueError('Cheating is unethical and unfair to other players. Confirm this action.')
    if action=='rank':
        rank=d.get('rank')
        if rank not in ('Automatic','Donator') and rank not in {r[2] for r in RANKS}:raise ValueError('Choose an existing rank')
        conn.execute('UPDATE users SET rank_override=?,is_donator=CASE WHEN ?="Donator" THEN 1 ELSE is_donator END WHERE id=?',(None if rank in ('Automatic','Donator') else rank,rank,uid))
        audit(conn,'rank_changed',uid,{'rank':rank})
    elif action=='donator':
        enabled=d.get('enabled')
        if not isinstance(enabled,bool):raise ValueError('Choose whether Donator is enabled')
        conn.execute('UPDATE users SET is_donator=? WHERE id=?',(int(enabled),uid));audit(conn,'donator_rank_changed',uid,{'enabled':enabled})
    elif action=='ideas_ban':
        enabled=d.get('enabled')
        if not isinstance(enabled,bool):raise ValueError('Choose whether ideas are blocked')
        conn.execute('UPDATE users SET ideas_banned=? WHERE id=?',(int(enabled),uid))
        audit(conn,'ideas_ban_changed',uid,{'enabled':enabled})
    elif action=='kick':conn.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?',(uid,))
    elif action=='reset_resources':
        if d.get('confirm') is not True:raise ValueError('Confirm resetting resources to zero')
        resources=('money','food','wood','metal','oil','steel','uranium','gems')
        selected=d.get('resource','all')
        if selected!='all' and selected not in resources:raise ValueError('Choose a valid resource or all resources')
        keys=resources if selected=='all' else (selected,)
        user=conn.execute('SELECT '+','.join(keys)+' FROM users WHERE id=?',(uid,)).fetchone()
        before={key:user[key] for key in keys}
        conn.execute('UPDATE users SET '+','.join(key+'=0' for key in keys)+' WHERE id=?',(uid,))
        audit(conn,'resources_reset',uid,{'resource':selected,'before':before,'after':{key:0 for key in keys}})
        return jsonify(success=True,message=('All resources' if selected=='all' else selected.title())+' reset to zero')
    elif action=='reset':
        if d.get('confirm') is not True:raise ValueError('Confirm resetting this player')
        leave_faction(conn,uid);conn.execute('DELETE FROM buildings WHERE grid_key IN (SELECT grid_key FROM territories WHERE owner_id=?)',(uid,))
        conn.execute('UPDATE territories SET owner_id=NULL WHERE owner_id=?',(uid,))
        conn.execute('UPDATE users SET money=200,wood=100,food=100,metal=100,oil=25,steel=0,uranium=0,gems=0,army=10,boats=0,planes=0,nukes=0,capital_key=NULL,capital_ts=0 WHERE id=?',(uid,))
        conn.execute('UPDATE users SET research="[]",religion=NULL,religion_ts=0,ideology=NULL WHERE id=?',(uid,))
        for table in ('wonders','stock_holdings','achievements'):conn.execute(f'DELETE FROM {table} WHERE '+('owner_id' if table=='wonders' else 'user_id')+'=?',(uid,))
    elif action=='faction':
        fid=integer(d.get('faction_id',0),0);f=conn.execute('SELECT 1 FROM factions WHERE id=?',(fid,)).fetchone() if fid else None
        if fid and not f:raise ValueError('Faction not found')
        if fid!=core['fac_id'](conn,uid):
            leave_faction(conn,uid)
            if fid:join_faction(conn,uid,fid)
    elif action in ('resources','give_money','give_resource'):
        key=d.get('resource');amount=integer(d.get('amount'),0,10**9)
        if action=='give_money':key='money'
        if key not in ('money','wood','food','metal','oil','steel','uranium','gems'):raise ValueError('Unknown resource')
        expression=f'{key}+?' if action!='resources' else '?'
        conn.execute(f'UPDATE users SET {key}={expression} WHERE id=?',(amount,uid))
    elif action=='spawn':
        key=d.get('resource');amount=integer(d.get('amount'),1,1000000)
        if key not in ('army','boats','planes'):raise ValueError('Unknown unit')
        pool_add(conn,uid,key,amount)
    elif action in ('tile','delete_tile','instant_build'):
        key=d.get('grid_key');core['parse_key'](key)
        if action=='tile':
            if not conn.execute('SELECT 1 FROM territories WHERE grid_key=?',(key,)).fetchone():
                a,b=core['parse_key'](key);terrain=core['get_terrain'](a,b);conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,population) VALUES(?,?,?,?)',(key,uid,terrain,core['get_population'](terrain,a,b)))
            else:conn.execute('UPDATE territories SET owner_id=? WHERE grid_key=?',(uid,key))
        elif action=='delete_tile':
            conn.execute('DELETE FROM buildings WHERE grid_key=?',(key,));conn.execute('DELETE FROM territories WHERE grid_key=?',(key,))
        else:
            if not conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id=?',(key,uid)).fetchone():raise ValueError('Player must own this tile')
            typ=d.get('type')
            if typ not in BUILDINGS:raise ValueError('Unknown building')
            conn.execute('INSERT INTO buildings VALUES(?,?,1) ON CONFLICT(grid_key) DO UPDATE SET type=excluded.type,level=1',(key,typ))
    else:raise ValueError('Unknown host action')
    return jsonify(success=True,message='Host action completed')

def music_path():return Path(core['DB_PATH']).resolve().parent/'media'/'world.mp3'
def music_info():
    with _music_lock:
        try:stamp=music_path().stat().st_mtime_ns
        except FileNotFoundError:stamp=None
        return jsonify(url='/music.mp3?v='+str(stamp) if stamp is not None else None)
def music_file():
    path=music_path()
    if not path.exists():abort(404)
    try:return send_file(path,mimetype='audio/mpeg',conditional=True)
    except FileNotFoundError:abort(404)
def music_upload():
    from mutagen.mp3 import MP3
    upload=request.files.get('file')
    if not upload or not upload.filename.lower().endswith('.mp3'):raise ValueError('Choose an MP3 file')
    content=upload.stream.read(MAX_MUSIC_BYTES+1)
    if not content or len(content)>MAX_MUSIC_BYTES:raise ValueError('MP3 must be between 1 byte and 15 MB')
    try:
        audio=MP3(io.BytesIO(content))
        if audio.info.length<=0:raise ValueError()
    except Exception:raise ValueError('File is not a valid MP3 audio stream')
    path=music_path();path.parent.mkdir(parents=True,exist_ok=True)
    with _music_lock:
        temporary=path.with_name('world-'+secrets.token_hex(12)+'.upload')
        try:temporary.write_bytes(content);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
    audit(db(),'music_replaced',details={'bytes':len(content)})
    return jsonify(success=True,message='Shared music replaced')

def music_remove():
    with _music_lock:
        path=music_path();removed=path.exists();path.unlink(missing_ok=True)
    audit(db(),'music_removed',details={'removed':removed})
    return jsonify(success=True,message='Shared music removed' if removed else 'No shared music is uploaded')

def admin_network():
    # Discover this machine's interfaces, rather than reporting a player's IP
    # or trusting a forwarded Host header. No external service is contacted.
    addresses=set()
    try:
        addresses.update(entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET))
    except OSError:
        pass
    addresses.add(request.environ.get('SERVER_ADDR',''))
    bind_host=os.environ.get('HOST','0.0.0.0')
    addresses.add(bind_host)
    lan=[]
    for address in addresses:
        try:ip=ipaddress.ip_address(address)
        except ValueError:continue
        if ip.version==4 and ip.is_private and not (ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast or ip.is_reserved):lan.append(str(ip))
    port=int(request.environ.get('SERVER_PORT') or os.environ.get('PORT',5000))
    try:local_only=ipaddress.ip_address(bind_host).is_loopback
    except ValueError:local_only=bind_host.lower()=='localhost'
    return jsonify(urls=[f'http://{ip}:{port}' for ip in sorted(lan)],local_only=local_only,
                   note='Share an address for your Wi-Fi or Ethernet network. The host firewall must allow the game port. These addresses work on the same network, not across the internet.')

def changelog():
    path=Path(core['app'].root_path)/'CHANGELOG.md';text=path.read_text(encoding='utf-8') if path.exists() else 'Welcome to version '+VERSION
    u=db().execute('SELECT last_seen_version FROM users WHERE id=?',(session['user_id'],)).fetchone()
    return jsonify(version=VERSION,show=u[0]!=VERSION,text=text)
def changelog_seen():
    db().execute('UPDATE users SET last_seen_version=? WHERE id=?',(VERSION,session['user_id']))
    return jsonify(success=True)

def ignore_water_reports():return jsonify(success=True,message='Terrain is validated by the server')
def land_file():return send_file(Path(core['app'].root_path)/'data'/'land.geojson',mimetype='application/json',conditional=True)

def terrain_cells():return send_file(Path(core['app'].root_path)/'data'/'land-cells.bin',mimetype='application/octet-stream',conditional=True,max_age=3600)
def islands_file():
    path=Path(core['app'].root_path)/'data'/'pacific-islands.geojson'
    compressed=request.accept_encodings['gzip']>0
    response=send_file(path.with_suffix('.geojson.gz') if compressed else path,mimetype='application/json',conditional=True,max_age=3600)
    if compressed:response.headers['Content-Encoding']='gzip'
    response.headers['Vary']='Accept-Encoding'
    return response

def ideas_path():return Path(core['DB_PATH']).resolve().parent/'ideas.txt'
def submit_idea():
    conn=db();uid=session['user_id'];user=conn.execute('SELECT username,ideas_banned,idea_last_sent FROM users WHERE id=?',(uid,)).fetchone()
    now=int(time.time());remaining=max(0,int(IDEAS_COOLDOWN)-(now-user['idea_last_sent']))
    if request.method=='GET':return jsonify(banned=bool(user['ideas_banned']),retry_after=remaining,interval=IDEAS_COOLDOWN)
    if user['ideas_banned']:return jsonify(error='The host has blocked your account from submitting ideas.'),403
    if remaining:
        response=jsonify(error=f'Please wait {remaining} seconds before sending another idea.',retry_after=remaining)
        response.headers['Retry-After']=str(remaining);return response,429
    text=body().get('idea')
    if not isinstance(text,str) or not 5<=len(text.strip())<=4000:raise ValueError('Write an idea between 5 and 4,000 characters')
    text=text.strip()
    if any(ord(char)<32 and char not in '\n\r\t' for char in text):raise ValueError('Remove control characters from your idea')
    username=user['username']
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    entry=f'[{stamp}] {username} (player {session["user_id"]})\n'+''.join('  '+line+'\n' for line in text.splitlines())+'\n'
    with _ideas_lock:
        with ideas_path().open('a',encoding='utf-8') as handle:handle.write(entry)
    conn.execute('UPDATE users SET idea_last_sent=? WHERE id=?',(now,uid))
    return jsonify(success=True,message='Thank you! Your idea has been saved for the host to review.')
def admin_ideas():
    path=ideas_path()
    with _ideas_lock:
        if not path.exists():return jsonify(text='No player ideas yet.')
        with path.open('rb') as handle:
            handle.seek(0,2);size=handle.tell();handle.seek(max(0,size-65536));text=handle.read().decode('utf-8',errors='replace')
    return jsonify(text=text,truncated=size>65536)

def install_features(namespace):
    global core
    core=namespace;app=core['app'];core['_v5_me_extra']=core['me_extra']
    conn=db()
    try:
        saved=core['get_setting'](conn,'rate_limits')
        if saved:_rate_settings.update(json.loads(saved))
        core['CHAT_COOLDOWN']=_rate_settings['chat']
    finally:conn.close()
    for name,fn in {'pool_get':pool_get,'pool_add':pool_add,'_join_faction':join_faction,'_leave_faction':leave_faction,'_army_map':army_map,'is_water':water,'is_coastal':coastal,'touch_last_seen':touch_presence,'me_extra':me_details,'ingest_water':lambda *a:None}.items():core[name]=fn
    app.before_request(before_request);app.after_request(after_request);app.teardown_request(close_transaction)
    app.register_error_handler(Exception,error_response)
    replacements={'register':register_account,'login':login_account,'forgot_password':recover_account,'get_territories':territories_full,'faction_create':faction_create,'faction_settings':faction_settings,'wonders_list':wonders_list,'wonders_buy':wonders_buy,'water_report':ignore_water_reports,'set_pin':profile_recovery}
    for name,fn in replacements.items():app.view_functions[name]=fn if name in ('register','login','forgot_password','get_territories') else core['require_login'](fn)
    routes=[('/api/bootstrap','GET',bootstrap,None),('/api/map/sync','GET',map_sync,None),('/api/profile/preferences','POST',profile_preferences,'login'),('/api/profile/recovery','POST',profile_recovery,'login'),('/api/religion/set','POST',religion_set,'login'),('/api/faction/page','GET',faction_page,'login'),('/api/eva','GET',eva_gallery,'login'),('/api/stocks','GET',market,'login'),('/api/stocks/trade','POST',stock_trade,'login'),('/api/admin/requests','GET',admin_requests,'admin'),('/api/admin/audit','GET',admin_audit,'admin'),('/api/admin/rate_limits','POST',admin_rate_limits,'admin'),('/api/admin/recovery','POST',admin_recovery,'admin'),('/api/admin/player','POST',admin_player,'admin'),('/api/admin/music','POST',music_upload,'admin'),('/api/music','GET',music_info,None),('/music.mp3','GET',music_file,None),('/api/changelog','GET',changelog,'login'),('/api/changelog/seen','POST',changelog_seen,'login')]
    for path,method,fn,guard in routes:app.add_url_rule(path,fn.__name__,core['require_'+guard](fn) if guard else fn,methods=[method])
    app.add_url_rule('/api/admin/music/remove','music_remove',core['require_admin'](music_remove),methods=['POST'])
    app.add_url_rule('/api/admin/network','admin_network',core['require_admin'](admin_network),methods=['GET'])
    app.add_url_rule('/api/land','land_file',land_file)
    app.add_url_rule('/api/terrain/cells','terrain_cells',terrain_cells)
    app.add_url_rule('/api/islands','islands_file',islands_file)
    app.add_url_rule('/api/ideas','submit_idea',core['require_login'](submit_idea),methods=['GET','POST'])
    app.add_url_rule('/api/admin/ideas','admin_ideas',core['require_admin'](admin_ideas),methods=['GET'])
    app.add_url_rule('/api/eva/deploy','eva_deploy',core['require_login'](eva_deploy),methods=['POST'])
    app.add_url_rule('/api/eva/deployments','eva_deployments',eva_deployments)
    if os.getenv('DISABLE_SCHEDULER')!='1':threading.Thread(target=scheduler_loop,name='game-scheduler',daemon=True).start()
