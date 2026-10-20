"""Admin dashboard, consistent exports and explicit account lifecycle controls."""
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from flask import jsonify, request, session, send_file, Response, abort
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import features
import server_health

core = None
_backup_lock = threading.Lock()
_operation_lock = threading.Lock()
_request_lock = threading.Lock()
_requests = deque(maxlen=512)
_request_count = 0
_server_errors = 0
ACCOUNT_FIELDS = ('id','username','created_at','last_seen','is_admin','is_moderator','is_banned',
    'is_donator','donator_tier','muted_until','timeout_until','faction_id','money','food','wood',
    'metal','oil','steel','uranium','gems','army','boats','planes','nukes','rockets','research')
OWNED = {'notifications':'user_id','achievements':'user_id','wonders':'owner_id',
    'faction_contributions':'user_id','stock_holdings':'user_id','stock_transactions':'user_id',
    'eva_deployments':'user_id','casino_rounds':'user_id','bank_offers':'owner_id',
    'space_program':'user_id','space_businesses':'user_id','planet_tiles':'user_id',
    'player_activity':'user_id','away_earnings':'user_id','war_seen':'user_id',
    'research_projects':'user_id','megaprojects':'user_id','recruitment_progress':'user_id',
    'faction_requests':'user_id','faction_bans':'user_id','request_stats':'user_id'}
PAIRED = {'alliances':('requester_id','target_id'),'embassies':('host_id','owner_id'),
    'trades':('from_id','to_id'),'loans':('lender_id','borrower_id'),'merges':('from_id','to_id'),
    'exchanges':('sender','recipient'),'trade_discussion':('sender','recipient'),
    'bank_loans':('lender','borrower'),'campaigns':('attacker','defender')}


def db():return core['get_db']()


def settings(conn):
    try:values=json.loads(core['get_setting'](conn,'server_controls','{}'))
    except (ValueError,TypeError):values={}
    return dict(registration_open=values.get('registration_open',True),
                maintenance=values.get('maintenance',False),message=values.get('message','The host is performing maintenance. Please try again later.'))


def seen_rows(conn, query='', page=1, public=False):
    # Last seen is last contact with the game, including visible-page polling.
    where='WHERE u.username LIKE ? ESCAPE "!"'+(' AND u.is_banned=0' if public else '')
    term='%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
    count=conn.execute('SELECT COUNT(*) FROM users u '+where,(term,)).fetchone()[0]
    fields='u.id,u.username,u.color' if public else ','.join('u.'+key for key in ACCOUNT_FIELDS)
    rows=conn.execute(f'''SELECT {fields},MAX(COALESCE(u.last_seen,0),COALESCE(p.last_login,0),COALESCE(p.last_activity,0)) seen
        FROM users u LEFT JOIN player_activity p ON p.user_id=u.id {where}
        ORDER BY u.username COLLATE NOCASE LIMIT 50 OFFSET ?''',(term,(page-1)*50)).fetchall()
    with features._lock:
        pending={}
        for value in features._stats.values():
            if value['user_id']:pending[value['user_id']]=max(pending.get(value['user_id'],0),value['last_seen'])
    now=int(time.time());players=[]
    for row in rows:
        data=dict(row);stamp=max(data.pop('seen'),pending.get(data['id'],0))
        data['last_seen_at']=datetime.fromtimestamp(stamp,timezone.utc).isoformat() if stamp else None
        data['online']=stamp>now-180 if stamp else False
        data['last_seen_label']='Online recently' if data['online'] else (f'{max(1,(now-stamp)//60)} minutes ago' if now-stamp<3600 else f'{(now-stamp)//3600} hours ago' if now-stamp<86400 else f'{(now-stamp)//86400} days ago') if stamp else 'Never recorded'
        if not public:data['last_seen_unix']=stamp;data['last_seen']=stamp
        players.append(data)
    return dict(players=players,page=page,pages=max(1,(count+49)//50),total=count)


def directory():
    page=features.integer(request.args.get('page',1),1,100000)
    query=request.args.get('q','')[:80]
    return jsonify(seen_rows(db(),query,page,public=request.path=='/api/players'))


def server_status():return jsonify(settings(db()))


def server_settings():
    conn=db()
    if request.method=='GET':return jsonify(settings(conn))
    data=features.body()
    for key in ('registration_open','maintenance'):
        if not isinstance(data.get(key),bool):raise ValueError('Choose true or false for '+key)
    message=data.get('message','')
    if not isinstance(message,str) or not 3<=len(message.strip())<=500:raise ValueError('Maintenance message must contain 3–500 characters')
    core['set_setting'](conn,'server_controls',json.dumps({**{k:data[k] for k in ('registration_open','maintenance')},'message':message.strip()}))
    return jsonify(success=True,message='Server controls saved')


def backup_directory():return Path(core['DB_PATH']).resolve().parent/'admin-backups'


def backup_listing(directory, pattern):
    try:
        entries=[]
        for path in directory.iterdir():
            if pattern.fullmatch(path.name) and not path.is_symlink():
                target=path/'game.db' if path.is_dir() else path
                if target.is_file():entries.append(dict(name=path.name,bytes=target.stat().st_size,created_unix=int(path.stat().st_mtime)))
        return dict(available=True,items=sorted(entries,key=lambda item:item['created_unix'],reverse=True)[:30])
    except OSError:return dict(available=False,items=[])


def health():
    conn=db();path=Path(core['DB_PATH']).resolve()
    machine=server_health.snapshot(path.parent)
    q=lambda sql:conn.execute(sql).fetchone()[0]
    start=time.perf_counter();conn.execute('SELECT 1').fetchone();latency=(time.perf_counter()-start)*1000
    daily=backup_listing(Path('/var/backups/wconquest'),re.compile(r'wconquest-\d{8}T\d{6}-\d{9}Z'))
    manual=backup_listing(backup_directory(),re.compile(r'save-\d+-[a-f0-9]+\.db'))
    next_tick=q('SELECT next_tick FROM scheduler_state WHERE id=1')
    with _request_lock:
        samples=sorted(_requests)
        traffic=dict(requests_since_start=_request_count,server_errors_since_start=_server_errors,
            samples=len(samples),p95_ms=round(samples[max(0,int(len(samples)*.95)-1)],2) if samples else None)
    response=dict(host=machine,traffic=traffic,version=core['VERSION'],server_time_unix=int(time.time()),
        database=dict(bytes=path.stat().st_size,wal_bytes=Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0,
            latency_ms=round(latency,2),journal=q('PRAGMA journal_mode'),schema=q('SELECT MAX(version) FROM schema_migrations')),
        game=dict(users=q('SELECT COUNT(*) FROM users'),banned=q('SELECT COUNT(*) FROM users WHERE is_banned=1'),
            territories=q('SELECT COUNT(*) FROM territories WHERE owner_id IS NOT NULL'),buildings=q('SELECT COUNT(*) FROM buildings'),
            factions=q('SELECT COUNT(*) FROM factions'),active_campaigns=q("SELECT COUNT(*) FROM campaigns WHERE status='active'"),
            research_projects=q('SELECT COUNT(*) FROM research_projects'),chat_messages=q('SELECT COUNT(*) FROM chat')),
        scheduler=dict(enabled=os.getenv('DISABLE_SCHEDULER')!='1',next_tick_unix=next_tick,
            overdue_seconds=max(0,int(time.time())-next_tick) if next_tick else None),
        backups=dict(manual=manual,daily=daily),controls=settings(conn))
    return jsonify(response)


def account():
    uid=features.integer(request.args.get('user_id'),1)
    conn=db();row=conn.execute('SELECT '+','.join(ACCOUNT_FIELDS)+',otp_secret FROM users WHERE id=?',(uid,)).fetchone()
    if not row:abort(404)
    data=dict(row);data['two_factor_enabled']=bool(data.pop('otp_secret'))
    # Include current last-seen value from the bounded presence cache.
    for player in seen_rows(conn,row['username'])['players']:
        if player['id']==uid:data.update({key:player[key] for key in ('last_seen_unix','last_seen_at','last_seen_label','online')})
    data['territories']=conn.execute('SELECT COUNT(*) FROM territories WHERE owner_id=?',(uid,)).fetchone()[0]
    data['buildings']=conn.execute('SELECT COUNT(*) FROM buildings b JOIN territories t USING(grid_key) WHERE t.owner_id=?',(uid,)).fetchone()[0]
    data['research']=json.loads(data['research'] or '[]')
    data['project']=dict(project) if (project:=conn.execute('SELECT * FROM research_projects WHERE user_id=?',(uid,)).fetchone()) else None
    return jsonify(data)


def account_action():
    data=features.body();uid=features.integer(data.get('user_id'),1);conn=db()
    target=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not target:abort(404)
    if data.get('confirm') is not True:raise ValueError('Review and confirm this account action')
    action=data.get('action');value=data.get('value')
    if action=='role':
        if value not in ('player','moderator','senior','admin'):raise ValueError('Choose a valid role')
        if uid==session['user_id']:raise ValueError('You cannot change your own staff role')
        if target['is_admin'] and value!='admin' and conn.execute('SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_banned=0').fetchone()[0]<=1:raise ValueError('Keep at least one active administrator')
        conn.execute('UPDATE users SET is_admin=?,is_moderator=?,auth_version=auth_version+1 WHERE id=?',(int(value=='admin'),2 if value=='moderator' else 1 if value=='senior' else 0,uid))
    elif action=='revoke_sessions':conn.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?',(uid,))
    elif action=='clear_timeout':conn.execute('UPDATE users SET timeout_until=0,timeout_started=0,timeout_by="",timeout_message="" WHERE id=?',(uid,))
    elif action=='unmute':conn.execute('UPDATE users SET muted_until=0 WHERE id=?',(uid,))
    elif action=='research':
        if value not in core['RESEARCH_TREE']:raise ValueError('Unknown research')
        owned=set(json.loads(target['research'] or '[]'));tech=core['RESEARCH_TREE'][value]
        if not set(tech.get('requires',[]))<=owned:raise ValueError('Grant prerequisite research first')
        core['auto_collect'](uid,conn,force=True)
        owned.add(value);conn.execute('UPDATE users SET research=? WHERE id=?',(json.dumps(sorted(owned)),uid))
        project=conn.execute('SELECT * FROM research_projects WHERE user_id=? AND tech=?',(uid,value)).fetchone()
        if project:
            conn.execute('UPDATE users SET money=money+? WHERE id=?',(project['paid'],uid))
            conn.execute('DELETE FROM research_projects WHERE user_id=?',(uid,))
    else:raise ValueError('Unknown account action')
    features.audit(conn,'account_'+action,uid,{'value':value})
    return jsonify(success=True,message='Account updated')


def deletion_plan(conn,uid):
    target=conn.execute('SELECT id,username,is_admin,faction_id FROM users WHERE id=?',(uid,)).fetchone()
    if not target:abort(404)
    if uid==session['user_id']:raise ValueError('You cannot delete your own account from the dashboard')
    if target['is_admin'] and conn.execute('SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_banned=0').fetchone()[0]<=1:raise ValueError('Keep at least one active administrator')
    counts={'territories':conn.execute('SELECT COUNT(*) FROM territories WHERE owner_id=?',(uid,)).fetchone()[0],
            'buildings':conn.execute('SELECT COUNT(*) FROM buildings b JOIN territories t USING(grid_key) WHERE t.owner_id=?',(uid,)).fetchone()[0],
            'chat':conn.execute('SELECT COUNT(*) FROM chat WHERE user_id=?',(uid,)).fetchone()[0]}
    for table,columns in PAIRED.items():counts[table]=conn.execute(f'SELECT COUNT(*) FROM {table} WHERE {columns[0]}=? OR {columns[1]}=?',(uid,uid)).fetchone()[0]
    return dict(user_id=uid,username=target['username'],is_admin=bool(target['is_admin']),faction_id=target['faction_id'],counts=counts)


def signer():return URLSafeTimedSerializer(core['app'].secret_key,salt='admin-delete-account')


def plan_digest(plan):return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()


def delete_preview():
    plan=deletion_plan(db(),features.integer(request.args.get('user_id'),1))
    plan['token']=signer().dumps(dict(actor=session['user_id'],digest=plan_digest(plan)))
    return jsonify(plan)


def delete_account():
    data=features.body();uid=features.integer(data.get('user_id'),1);conn=db();plan=deletion_plan(conn,uid)
    if data.get('confirm') is not True or data.get('typed_username')!=plan['username']:raise ValueError('Type the exact username and confirm deletion')
    reason=data.get('reason','')
    if not isinstance(reason,str) or not 5<=len(reason.strip())<=500:raise ValueError('Provide a reason of 5–500 characters')
    try:token=signer().loads(data.get('token',''),max_age=300)
    except (BadSignature,SignatureExpired):raise ValueError('Deletion review expired; review the account again')
    if token.get('actor')!=session['user_id'] or token.get('digest')!=plan_digest(plan):raise ValueError('Account changed; review deletion again')
    from expansion import finish_campaign
    for campaign in conn.execute("SELECT * FROM campaigns WHERE status='active' AND (attacker=? OR defender=?)",(uid,uid)).fetchall():
        finish_campaign(conn,campaign,'ended','Offensive ended because an account was deleted by an administrator')
    features.leave_faction(conn,uid)
    conn.execute('DELETE FROM war_seen WHERE rel_id NOT IN (SELECT id FROM faction_rel)')
    # Land returns to unclaimed; buildings and deployed units do not remain as free gifts.
    conn.execute('DELETE FROM buildings WHERE grid_key IN (SELECT grid_key FROM territories WHERE owner_id=?)',(uid,))
    conn.execute('UPDATE territories SET owner_id=NULL,garrison=0,boats=0,planes=0,last_collected=? WHERE owner_id=?',(int(time.time()),uid))
    for table,column in OWNED.items():conn.execute(f'DELETE FROM {table} WHERE {column}=?',(uid,))
    for table,columns in PAIRED.items():conn.execute(f'DELETE FROM {table} WHERE {columns[0]}=? OR {columns[1]}=?',(uid,uid))
    conn.execute('DELETE FROM moderation_confirmations WHERE actor=? OR owner=? OR recipient=?',(uid,uid,uid))
    conn.execute('DELETE FROM chat WHERE user_id=?',(uid,))
    # Structured historical authors are anonymized; arbitrary text requires manual privacy review.
    for table,column in (('battle_log','attacker'),('battle_log','defender'),('strike_events','actor'),('announcements','author'),('chat','admin_actor'),('users','timeout_by')):
        conn.execute(f'UPDATE {table} SET {column}=? WHERE {column}=?',('[deleted player]',plan['username']))
    conn.execute('UPDATE audit_log SET actor_id=NULL,actor="[deleted player]",ip=NULL WHERE actor_id=?',(uid,))
    conn.execute('UPDATE audit_log SET target_id=NULL WHERE target_id=?',(uid,))
    # Delist the country and any dissolved faction, cashing out other investors at last quote.
    for quote in conn.execute("SELECT * FROM stock_prices WHERE (kind='country' AND target_id=?) OR (kind='faction' AND target_id NOT IN (SELECT id FROM factions))",(uid,)).fetchall():
        for holding in conn.execute('SELECT user_id,quantity FROM stock_holdings WHERE symbol=?',(quote['symbol'],)).fetchall():
            conn.execute('UPDATE users SET money=money+? WHERE id=?',(holding['quantity']*quote['price']*(1-core['STOCK_FEE']),holding['user_id']))
        for table in ('stock_prices','stock_history','stock_holdings'):conn.execute(f'DELETE FROM {table} WHERE symbol=?',(quote['symbol'],))
    conn.execute('DELETE FROM users WHERE id=?',(uid,))
    features.audit(conn,'account_deleted',details={'former_id':uid,'counts':plan['counts'],'reason':reason.strip()})
    # Avoid resurrecting private presence data when scheduler flushes its in-memory cache.
    with features._lock:
        for key in [key for key,value in features._stats.items() if value['user_id']==uid]:features._stats.pop(key,None)
    return jsonify(success=True,message='Account deleted; land released. Backups, ideas and free-text records require separate privacy review.')


def export_users():
    conn=db();rows=[];page=1
    while True:
        batch=seen_rows(conn,page=page);rows.extend(batch['players'])
        if page>=batch['pages']:break
        page+=1
    features.audit(conn,'users_exported',details={'format':request.args.get('format','json'),'count':len(rows)})
    if request.args.get('format')=='csv':
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(ACCOUNT_FIELDS)+['last_seen_at','online','last_seen_label','last_seen_unix'])
        writer.writeheader()
        for row in rows:
            # Prevent spreadsheet formula injection through player-controlled text.
            writer.writerow({key:("'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value) for key,value in row.items()})
        response=Response('\ufeff'+stream.getvalue(),mimetype='text/csv');name='users.csv'
    else:
        for row in rows:row['research']=json.loads(row['research'] or '[]')
        response=jsonify(format_version=1,exported_at_unix=int(time.time()),users=rows);name='users.json'
    response.headers['Content-Disposition']='attachment; filename="'+name+'"'
    response.headers['Cache-Control']='private, no-store'
    return response


def database_copy(destination):
    path=Path(core['DB_PATH']).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as source:
        with closing(sqlite3.connect(destination)) as copied:
            deadline=time.monotonic()+20
            def progress(*args):
                if time.monotonic()>deadline:raise RuntimeError('Database copy timed out; retry while the server is quiet')
            source.backup(copied,pages=256,progress=progress,sleep=.02)
    os.chmod(destination,0o600)


def database_download():
    if not _backup_lock.acquire(blocking=False):return jsonify(error='Another database copy is running; try again shortly'),409
    path=None
    try:
        # A separate read-only connection snapshots committed state, including WAL data.
        fd,name=tempfile.mkstemp(prefix='wc-admin-',suffix='.db');os.close(fd);path=Path(name)
        database_copy(path)
        features.audit(db(),'database_downloaded',details={'bytes':path.stat().st_size})
        response=send_file(path,as_attachment=True,download_name='game.db',mimetype='application/vnd.sqlite3',conditional=False)
        response.headers['Cache-Control']='private, no-store, max-age=0'
        # Windows cannot unlink an open file. Close the send_file stream before removing it.
        original=response.response
        def stream():
            try:yield from original
            finally:
                if hasattr(original,'close'):original.close()
                path.unlink(missing_ok=True)
        response.response=stream()
        return response
    except Exception:
        if path:path.unlink(missing_ok=True)
        raise
    finally:_backup_lock.release()


def database_check():
    if not _operation_lock.acquire(blocking=False):return jsonify(error='A database check is already running'),409
    try:
        conn=db();deadline=time.monotonic()+3
        conn.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        try:
            checks=[row[0] for row in conn.execute('PRAGMA quick_check')]
            references=[dict(row) for row in conn.execute('PRAGMA foreign_key_check')][:20]
        except sqlite3.OperationalError:raise ValueError('Check exceeded its time limit; run the host CLI during a quiet period')
        finally:conn.set_progress_handler(None,0)
        return jsonify(success=checks==['ok'] and not references,checks=checks[:20],foreign_key_errors=references)
    finally:_operation_lock.release()


def backup_create():
    if not _backup_lock.acquire(blocking=False):return jsonify(error='Another database copy is running'),409
    path=None
    try:
        directory=backup_directory();directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        existing=backup_listing(directory,re.compile(r'save-\d+-[a-f0-9]+\.db'))['items']
        if len(existing)>=10:raise ValueError('Ten manual snapshots already exist. Archive or remove old copies through the host filesystem first.')
        import secrets
        path=directory/f'save-{int(time.time())}-{secrets.token_hex(4)}.db'
        database_copy(path)
        features.audit(db(),'manual_backup_created',details={'name':path.name,'bytes':path.stat().st_size})
        return jsonify(success=True,message='Private database snapshot created',name=path.name)
    except Exception:
        if path:path.unlink(missing_ok=True)
        raise
    finally:_backup_lock.release()


def install(namespace):
    global core
    core=namespace;app=core['app']
    for path,methods,fn in (
        ('health',['GET'],health),('accounts',['GET'],directory),('account',['GET'],account),
        ('account/action',['POST'],account_action),('account/delete-preview',['GET'],delete_preview),
        ('account/delete',['POST'],delete_account),('users/export',['POST'],export_users),
        ('database/download',['POST'],database_download),('database/check',['POST'],database_check),
        ('backups/create',['POST'],backup_create),('server/settings',['GET','POST'],server_settings)):
        app.add_url_rule('/api/admin/'+path,'dashboard_'+fn.__name__,core['require_admin'](fn),methods=methods)
    app.add_url_rule('/api/players','public_player_directory',directory)
    app.add_url_rule('/api/server/status','public_server_status',server_status)
    @app.after_request
    def count_requests(response):
        global _request_count,_server_errors
        if request.path.startswith('/api/'):
            from flask import g
            elapsed=(time.perf_counter()-getattr(g,'started',time.perf_counter()))*1000
            with _request_lock:
                _request_count+=1;_server_errors+=int(response.status_code>=500);_requests.append(elapsed)
        return response
    @app.before_request
    def controls_gate():
        if request.method!='POST' or not request.path.startswith('/api/'):return
        state=settings(db())
        if request.path=='/api/register' and not state['registration_open']:return jsonify(error='New account registration is currently closed'),403
        if not state['maintenance'] or request.path in ('/api/login','/api/logout','/api/forgot_password'):return
        uid=session.get('user_id')
        user=db().execute('SELECT is_admin FROM users WHERE id=?',(uid,)).fetchone() if uid else None
        if not user or not user['is_admin']:return jsonify(error=state['message'],maintenance=True),503
