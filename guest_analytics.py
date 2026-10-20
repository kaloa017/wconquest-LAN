"""Private, bounded guest visit history; no third-party analytics or fingerprinting."""
import hashlib
import hmac
import ipaddress
import json
import secrets
import threading
import time
from flask import request, session, jsonify
import features

core=None
_prune_lock=threading.Lock()
_last_pruned={}


def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=20').fetchone():conn.commit();return
        conn.execute('''CREATE TABLE IF NOT EXISTS guest_visits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,visitor_hash TEXT NOT NULL,
            ip TEXT NOT NULL,country_code TEXT,first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,pageviews INTEGER NOT NULL DEFAULT 0,
            UNIQUE(visitor_hash,ip))''')
        conn.execute('CREATE INDEX IF NOT EXISTS guest_visits_last ON guest_visits(last_seen,id)')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS guest_history_cap AFTER INSERT ON guest_visits
            BEGIN DELETE FROM guest_visits WHERE id<=NEW.id-20000; END''')
        conn.execute('INSERT INTO schema_migrations VALUES(20,?)',(int(time.time()),));conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()


def settings(conn):
    try:stored=json.loads(core['get_setting'](conn,'guest_analytics','{}'))
    except (ValueError,TypeError):stored={}
    return dict(enabled=stored.get('enabled',True),retention_days=stored.get('retention_days',30))


def prune(conn,force=False):
    identity=core['DB_PATH'];stamp=int(time.time())
    with _prune_lock:
        if not force and stamp-_last_pruned.get(identity,0)<60:return
        days=settings(conn)['retention_days']
        conn.execute('DELETE FROM guest_visits WHERE last_seen<?',(stamp-days*86400,))
        conn.execute('DELETE FROM guest_visits WHERE id NOT IN (SELECT id FROM guest_visits ORDER BY last_seen DESC,id DESC LIMIT 20000)')
        _last_pruned[identity]=stamp


def record():
    if session.get('user_id'):return
    conn=core['get_db']()
    if not settings(conn)['enabled']:return
    try:ip=str(ipaddress.ip_address(request.remote_addr or ''))
    except ValueError:return
    visitor=session.get('guest_visit')
    if not isinstance(visitor,str) or len(visitor)!=32:visitor=secrets.token_hex(16);session['guest_visit']=visitor
    secret=core['app'].secret_key
    digest=hmac.new(secret.encode() if isinstance(secret,str) else secret,visitor.encode(),hashlib.sha256).hexdigest()
    stamp=int(time.time());country=request.environ.get('wconquest.country')
    old=conn.execute('SELECT id,last_seen,country_code FROM guest_visits WHERE visitor_hash=? AND ip=?',(digest,ip)).fetchone()
    pageview=int(request.path=='/')
    if not old:
        conn.execute('INSERT INTO guest_visits(visitor_hash,ip,country_code,first_seen,last_seen,pageviews) VALUES(?,?,?,?,?,?)',(digest,ip,country,stamp,stamp,pageview))
    elif pageview or stamp-old['last_seen']>=60 or country!=old['country_code']:
        conn.execute('UPDATE guest_visits SET last_seen=?,country_code=COALESCE(?,country_code),pageviews=pageviews+? WHERE id=?',(stamp,country,pageview,old['id']))
    prune(conn)


def analytics():
    conn=core['get_db']();state=settings(conn);cutoff=int(time.time())-state['retention_days']*86400
    page=features.integer(request.args.get('page',1),1,100000)
    query=request.args.get('q','')[:80].replace('!','!!').replace('%','!%').replace('_','!_')
    condition="last_seen>=? AND (ip LIKE ? ESCAPE '!' OR country_code LIKE ? ESCAPE '!')"
    values=(cutoff,'%'+query+'%','%'+query+'%')
    count=conn.execute('SELECT COUNT(*) FROM guest_visits WHERE '+condition,values).fetchone()[0]
    rows=[dict(row) for row in conn.execute('SELECT id,ip,country_code,first_seen,last_seen,pageviews FROM guest_visits WHERE '+condition+' ORDER BY last_seen DESC,id DESC LIMIT 50 OFFSET ?',(*values,(page-1)*50))]
    summary=dict(conn.execute('SELECT COUNT(*) guest_sessions,COUNT(DISTINCT ip) unique_ips,COALESCE(SUM(pageviews),0) pageviews FROM guest_visits WHERE last_seen>=?',(cutoff,)).fetchone())
    summary['recent_sessions']=conn.execute('SELECT COUNT(*) FROM guest_visits WHERE last_seen>=?',(max(cutoff,int(time.time())-86400),)).fetchone()[0]
    countries=[dict(row) for row in conn.execute('SELECT country_code,COUNT(*) sessions FROM guest_visits WHERE last_seen>=? GROUP BY country_code ORDER BY sessions DESC LIMIT 20',(cutoff,))]
    days=[dict(row) for row in conn.execute("SELECT strftime('%Y-%m-%d',first_seen,'unixepoch') day,COUNT(*) sessions FROM guest_visits WHERE last_seen>=? GROUP BY day ORDER BY day DESC LIMIT 30",(cutoff,))]
    features.audit(conn,'guest_analytics_viewed',details={'page':page})
    response=jsonify(visits=rows,summary=summary,countries=countries,days=days,settings=state,
        page=page,pages=max(1,(count+49)//50),total=count,maximum_records=20000)
    response.headers['Cache-Control']='private, no-store'
    return response


def save_settings():
    data=features.body();enabled=data.get('enabled');days=features.integer(data.get('retention_days'),7,90)
    if not isinstance(enabled,bool):raise ValueError('Choose whether guest history is enabled')
    conn=core['get_db']();core['set_setting'](conn,'guest_analytics',json.dumps(dict(enabled=enabled,retention_days=days)))
    prune(conn,force=True)
    features.audit(conn,'guest_analytics_settings',details={'enabled':enabled,'retention_days':days})
    return jsonify(success=True,message='Guest analytics settings saved')


def purge():
    data=features.body()
    if data.get('confirm') is not True or data.get('confirmation')!='DELETE GUEST HISTORY':raise ValueError('Type DELETE GUEST HISTORY and confirm')
    conn=core['get_db']();count=conn.execute('SELECT COUNT(*) FROM guest_visits').fetchone()[0]
    conn.execute('DELETE FROM guest_visits');features.audit(conn,'guest_history_deleted',details={'records':count})
    return jsonify(success=True,message=f'Deleted {count} guest history records from the live database; backups remain separate')


def install(namespace):
    global core
    core=namespace;app=core['app']
    for path,methods,fn in (('/api/admin/analytics',['GET'],analytics),('/api/admin/analytics/settings',['POST'],save_settings),('/api/admin/analytics/purge',['POST'],purge)):
        app.add_url_rule(path,fn.__name__,core['require_admin'](fn),methods=methods)
    @app.after_request
    def capture_guest(response):
        if response.status_code<400 and ((request.method=='GET' and request.path=='/') or (request.method=='POST' and request.path=='/api/spectate')):record()
        return response
