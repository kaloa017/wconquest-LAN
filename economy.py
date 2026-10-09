"""Live host tuning, player banks and supporter cosmetics."""
import copy
import json
import math
import re
import threading
import time
from flask import abort, jsonify, request, session
import config
import features
import expansion

core={}
_lock=threading.RLock()
_catalog_revision=None
DEFAULTS={name:copy.deepcopy(getattr(config,name)) for name in ('BUILDINGS','WONDERS','IDEOLOGIES','RELIGIONS')}
CATEGORIES={'buildings':'BUILDINGS','wonders':'WONDERS','ideologies':'IDEOLOGIES','religions':'RELIGIONS'}
RESOURCES=('money','food','wood','metal','oil','steel','uranium','gems')
FONTS=('default','serif','mono','rounded')
TIERS=('Supporter','Patron','Champion','Legend')
MULTIPLIERS={'atk','def','yield','money','food','wood','metal','oil','steel','uranium','gems','troop','research','claim','casualty'}
EXTRAS={'yield_per_level','troops_per_level','def_per_level','research_discount_per_level','research_discount','casualty_per_level','claim_discount_per_level','range_per_level','floor','capacity','range','max_bonus','money_per_level','lat','lng'}

def db(): return core['get_db']()
def now(): return int(time.time())

def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=13').fetchone(): conn.commit();return
        existing={r['name'] for r in conn.execute('PRAGMA table_info(users)')}
        for name,definition in [('donator_tier','TEXT NOT NULL DEFAULT "Supporter"'),('name_color','TEXT NOT NULL DEFAULT ""'),
                ('name_font','TEXT NOT NULL DEFAULT "default"'),('name_rgb','INTEGER NOT NULL DEFAULT 0')]:
            if name not in existing: conn.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
        for statement in [
            '''CREATE TABLE IF NOT EXISTS live_catalog(category TEXT NOT NULL,item_key TEXT NOT NULL,data TEXT NOT NULL,
                PRIMARY KEY(category,item_key))''',
            '''CREATE TABLE IF NOT EXISTS bank_offers(owner_id INTEGER PRIMARY KEY,rate REAL NOT NULL DEFAULT 5,
                term_hours INTEGER NOT NULL DEFAULT 24,enabled INTEGER NOT NULL DEFAULT 1)''',
            '''CREATE TABLE IF NOT EXISTS bank_loans(id INTEGER PRIMARY KEY,lender INTEGER NOT NULL,borrower INTEGER NOT NULL,
                principal INTEGER NOT NULL,rate REAL NOT NULL,term_hours INTEGER NOT NULL,total_due REAL NOT NULL,
                paid REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',created INTEGER NOT NULL,due INTEGER NOT NULL DEFAULT 0)''',
            '''CREATE TRIGGER IF NOT EXISTS user_name_style_update AFTER UPDATE OF is_donator,donator_tier,name_color,name_font,name_rgb ON users
                BEGIN INSERT INTO map_changes(grid_key) SELECT grid_key FROM territories WHERE owner_id=NEW.id; END'''
        ]: conn.execute(statement)
        conn.execute('INSERT OR IGNORE INTO game_settings VALUES("catalog_revision","0")')
        conn.execute('INSERT INTO schema_migrations VALUES(13,?)',(now(),));conn.commit()
    except Exception: conn.rollback();raise
    finally: conn.close()

def refresh_catalog(conn):
    global _catalog_revision
    revision=core['get_setting'](conn,'catalog_revision','0')
    with _lock:
        # Include DB identity so isolated saves and host saves never share tuning.
        identity=(core['DB_PATH'],revision)
        if _catalog_revision==identity:return
        current=copy.deepcopy(DEFAULTS)
        for row in conn.execute('SELECT * FROM live_catalog'):
            if row['category'] in CATEGORIES:current[CATEGORIES[row['category']]][row['item_key']]=json.loads(row['data'])
        for name,entries in current.items():
            core[name]=entries;setattr(config,name,entries);setattr(features,name,entries)
        _catalog_revision=identity

def before_catalog():
    if not request.path.startswith('/api/'):return
    refresh_catalog(db())
    if request.method=='POST':
        category={'/api/building/build':'buildings','/api/wonders/buy':'wonders','/api/ideology/set':'ideologies','/api/religion/set':'religions'}.get(request.path)
        if category:
            d=features.body(); key=d.get('type') if category=='buildings' else d.get('key') if category=='wonders' else d.get('id')
            if core[CATEGORIES[category]].get(key,{}).get('enabled') is False:raise ValueError('The host has disabled new purchases/adoption of this item')

def finite(value,low=0,high=10**12):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:raise ValueError(f'Choose a finite number between {low} and {high}')
    return value

def validate_item(category,key,data):
    if category not in CATEGORIES or not isinstance(key,str) or not re.fullmatch('[a-z][a-z0-9_]{1,47}',key):raise ValueError('Use a category and a lowercase key of 2–48 letters, digits or underscores')
    if not isinstance(data,dict):raise ValueError('Provide an item definition')
    allowed={'name','desc','icon','cost','production','terrain','needs','coastal','enabled','country','hidden'}|MULTIPLIERS|EXTRAS
    if any(k not in allowed for k in data):raise ValueError('Unknown effect or property')
    result={}
    for field,value in data.items():
        if field in ('name','desc','icon','country','needs'):
            limit=1000 if field=='desc' else 80
            if not isinstance(value,str) or len(value)>limit:raise ValueError('Invalid '+field)
            if field=='needs' and value and value not in core['RESEARCH_TREE']:raise ValueError('Unknown research requirement')
            if field=='country' and value and value!='JPN':raise ValueError('Only the existing Japan requirement is supported')
            if value or field in ('name','desc','icon'):result[field]=value
        elif field in ('enabled','coastal','hidden'):
            if not isinstance(value,bool):raise ValueError('Expected a toggle')
            result[field]=value
        elif field=='terrain':
            if not isinstance(value,list) or any(v not in core['TERRAIN_RES'] for v in value):raise ValueError('Choose known terrain types')
            if value:result[field]=value
        elif field in ('cost','production'):
            if not isinstance(value,dict) or any(k not in RESOURCES for k in value):raise ValueError('Choose known resource types')
            result[field]={k:finite(v) for k,v in value.items()}
        else:result[field]=finite(value,-180 if field in ('lat','lng') else 0,180 if field in ('lat','lng') else 100 if field in MULTIPLIERS else 10**6)
    if not result.get('name','').strip():raise ValueError('Give the item a name')
    result.setdefault('desc','');result.setdefault('icon','🏛');result.setdefault('enabled',True)
    if category in ('buildings','wonders'):
        result.setdefault('cost',{})
        if category=='buildings':result.setdefault('production',{})
    if category=='religions':result.setdefault('atk',1)
    return result

def catalog():
    conn=db();refresh_catalog(conn)
    return jsonify(revision=core['get_setting'](conn,'catalog_revision','0'),
        **{category:core[name] for category,name in CATEGORIES.items()})

def catalog_save():
    conn=db();d=features.body();category=d.get('category');key=d.get('item_key');definition=validate_item(category,key,d.get('definition'))
    # Settle production at the previous rates before publishing new economics.
    for u in conn.execute('SELECT id FROM users WHERE is_banned=0').fetchall():core['auto_collect'](u['id'],conn)
    conn.execute('INSERT INTO live_catalog VALUES(?,?,?) ON CONFLICT(category,item_key) DO UPDATE SET data=excluded.data',(category,key,json.dumps(definition)))
    revision=int(core['get_setting'](conn,'catalog_revision','0'))+1;core['set_setting'](conn,'catalog_revision',revision)
    features.audit(conn,'catalog_update',None,dict(category=category,key=key,definition=definition))
    return jsonify(success=True,message='Definition saved. Players receive it at their next sync.',revision=str(revision))

def bank_list():
    conn=db();uid=session['user_id']
    rows=conn.execute('''SELECT u.id owner_id,u.username,COALESCE(o.rate,5) rate,COALESCE(o.term_hours,24) term_hours,
        COALESCE(o.enabled,1) enabled,COUNT(*) branches FROM users u JOIN territories t ON t.owner_id=u.id
        JOIN buildings b ON b.grid_key=t.grid_key AND b.type='bank' LEFT JOIN bank_offers o ON o.owner_id=u.id
        WHERE u.is_banned=0 GROUP BY u.id ORDER BY u.username''')
    loans=conn.execute('''SELECT l.*,a.username lender_name,b.username borrower_name FROM bank_loans l
        JOIN users a ON a.id=l.lender JOIN users b ON b.id=l.borrower WHERE lender=? OR borrower=? ORDER BY l.id DESC LIMIT 80''',(uid,uid))
    return jsonify(banks=[dict(r) for r in rows],loans=[dict(r) for r in loans])

def bank_settings():
    conn=db();uid=session['user_id'];d=features.body()
    if not core['sum_levels'](conn,uid,'bank'):raise ValueError('Build and own a Bank first')
    rate=finite(d.get('rate'),0,100);term=features.integer(d.get('term_hours'),1,720);enabled=d.get('enabled',True)
    if not isinstance(enabled,bool):raise ValueError('Choose enabled or disabled')
    conn.execute('INSERT INTO bank_offers VALUES(?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET rate=excluded.rate,term_hours=excluded.term_hours,enabled=excluded.enabled',(uid,rate,term,enabled))
    return jsonify(success=True,message='Bank terms updated. Existing loans keep their agreed terms.')

def bank_request():
    conn=db();uid=session['user_id'];d=features.body();lender=features.integer(d.get('lender_id'),1);principal=features.integer(d.get('principal'),1,2**53-1)
    if uid==lender:raise ValueError('Choose another player’s bank')
    lender_user=expansion.user(conn,lender)
    if not lender_user or lender_user['is_banned'] or lender_user['timeout_until']>now() or not core['sum_levels'](conn,lender,'bank'):raise ValueError('This bank is unavailable')
    terms=conn.execute('SELECT * FROM bank_offers WHERE owner_id=?',(lender,)).fetchone()
    if terms and not terms['enabled']:raise ValueError('This bank is closed to new loans')
    if conn.execute("SELECT COUNT(*) FROM bank_loans WHERE borrower=? AND status='pending'",(uid,)).fetchone()[0]>=20:raise ValueError('Cancel an old request first')
    rate=terms['rate'] if terms else 5;term=terms['term_hours'] if terms else 24;total=principal*(1+rate/100)
    conn.execute('INSERT INTO bank_loans(lender,borrower,principal,rate,term_hours,total_due,created) VALUES(?,?,?,?,?,?,?)',(lender,uid,principal,rate,term,total,now()))
    expansion.note(conn,lender,f'{session["username"]} requests {principal} money from your bank at {rate}% total interest over {term} hours. Open Banks to approve or decline.')
    return jsonify(success=True,message=f'Loan requested: repay {total:g} in total, due {term} hours after approval. No money has transferred yet.')

def bank_respond():
    conn=db();uid=session['user_id'];d=features.body();loan=conn.execute("SELECT * FROM bank_loans WHERE id=? AND status='pending'",(features.integer(d.get('loan_id'),1),)).fetchone()
    if not loan or uid not in (loan['lender'],loan['borrower']):abort(404)
    action=d.get('action')
    if action=='approve':
        if uid!=loan['lender']:abort(403)
        if not core['sum_levels'](conn,uid,'bank'):raise ValueError('You no longer own a Bank')
        expansion.check_basket(conn,loan['borrower'],{});expansion.check_basket(conn,uid,{'money':loan['principal']})
        expansion.transfer(conn,uid,loan['borrower'],{'money':loan['principal']})
        conn.execute("UPDATE bank_loans SET status='active',due=? WHERE id=?",(now()+loan['term_hours']*3600,loan['id']))
        expansion.note(conn,loan['borrower'],f'Bank loan #{loan["id"]} approved. Received {loan["principal"]}; total repayment {loan["total_due"]:g}.')
    elif action in ('decline','cancel'):conn.execute("UPDATE bank_loans SET status='declined' WHERE id=?",(loan['id'],))
    else:raise ValueError('Choose approve, decline or cancel')
    features.audit(conn,'bank_'+action,loan['borrower'],dict(loan_id=loan['id'],principal=loan['principal']))
    return jsonify(success=True,message='Loan '+action+'d')

def repay(conn,loan,amount):
    borrower=expansion.user(conn,loan['borrower']);lender=expansion.user(conn,loan['lender'])
    if not borrower or not lender:return 0
    amount=min(amount,max(0,loan['total_due']-loan['paid']),borrower['money'])
    if amount<=0:return 0
    conn.execute('UPDATE users SET money=money-? WHERE id=?',(amount,loan['borrower']))
    conn.execute('UPDATE users SET money=money+? WHERE id=?',(amount,loan['lender']))
    conn.execute("UPDATE bank_loans SET paid=paid+?,status=CASE WHEN paid+?>=total_due-.000001 THEN 'paid' ELSE status END WHERE id=?",(amount,amount,loan['id']))
    return amount

def bank_repay():
    conn=db();d=features.body();uid=session['user_id'];loan=conn.execute("SELECT * FROM bank_loans WHERE id=? AND borrower=? AND status IN ('active','overdue')",(features.integer(d.get('loan_id'),1),uid)).fetchone()
    if not loan:abort(404)
    amount=finite(d.get('amount'),.01,2**53-1);paid=repay(conn,loan,amount)
    if not paid:raise ValueError('No money available for repayment')
    return jsonify(success=True,message=f'Repaid {paid:g} money')

def process_loans(conn,timestamp):
    for loan in conn.execute("SELECT * FROM bank_loans WHERE status IN ('active','overdue') AND due<=?",(timestamp,)).fetchall():
        paid=repay(conn,loan,loan['total_due']-loan['paid'])
        if loan['paid']+paid<loan['total_due']-.000001:conn.execute("UPDATE bank_loans SET status='overdue' WHERE id=?",(loan['id'],))
        if loan['status']=='active':expansion.note(conn,loan['borrower'],f'Loan #{loan["id"]} reached its due time. {paid:g} repaid from your balance; any remainder stays due. Interest does not compound.')

def donor_settings():
    conn=db();uid=session['user_id'];u=expansion.user(conn,uid);d=features.body()
    if not u['is_donator']:abort(403)
    color=d.get('name_color','');font=d.get('name_font','default');rgb=d.get('name_rgb',False)
    if not isinstance(color,str) or (color and not re.fullmatch('#[0-9a-fA-F]{6}',color)):raise ValueError('Choose a hex RGB color')
    if font not in FONTS or not isinstance(rgb,bool):raise ValueError('Choose a supported font and RGB toggle')
    conn.execute('UPDATE users SET name_color=?,name_font=?,name_rgb=? WHERE id=?',(color,font,rgb,uid))
    return jsonify(success=True,message='Username style saved')

def donor_tier():
    conn=db();d=features.body();uid=features.integer(d.get('user_id'),1);tier=d.get('tier');u=expansion.user(conn,uid)
    if not u or tier not in TIERS+('None',):raise ValueError('Choose a player and a supporter tier')
    conn.execute('UPDATE users SET is_donator=?,donator_tier=? WHERE id=?',(tier!='None',tier if tier!='None' else 'Supporter',uid))
    features.audit(conn,'donator_tier',uid,dict(tier=tier))
    return jsonify(success=True,message='Cosmetic supporter tier updated')

def name_style(row):
    return {k:row[k] for k in ('is_donator','donator_tier','name_color','name_font','name_rgb','is_moderator')}

def decorate_public(response):
    paths=('/api/online','/api/chat','/api/leaderboard','/api/territories','/api/map/sync')
    if request.path not in paths and not request.path.startswith('/api/territory/'):return response
    if request.method!='GET' or response.status_code!=200 or not response.is_json:return response
    payload=response.get_json()
    items=payload if isinstance(payload,list) else payload.get('messages',payload.get('changed',[])) if isinstance(payload,dict) else []
    if request.path.startswith('/api/territory/') and isinstance(payload,dict):items=[payload]
    if not items:return response
    ids={row.get('owner_id') or row.get('uid') or row.get('id') for row in items if isinstance(row,dict)}-{None}
    names={row.get('username') or row.get('owner') or row.get('user') for row in items if isinstance(row,dict)}-{None}
    if not ids and not names:return response
    parts=[];parameters=[]
    if ids:parts.append('id IN ('+','.join('?' for _ in ids)+')');parameters.extend(ids)
    if names:parts.append('username IN ('+','.join('?' for _ in names)+')');parameters.extend(names)
    rows=db().execute('SELECT id,username,is_donator,donator_tier,name_color,name_font,name_rgb,is_moderator FROM users WHERE '+' OR '.join(parts),parameters).fetchall()
    by_id={r['id']:r for r in rows};by_name={r['username']:r for r in rows}
    for item in items:
        if not isinstance(item,dict) or item.get('type')=='spectator':continue
        row=by_id.get(item.get('owner_id') or item.get('uid') or item.get('id')) or by_name.get(item.get('username') or item.get('owner') or item.get('user'))
        if row:item.update(name_style(row))
    response.set_data(json.dumps(payload));return response

def install(namespace):
    global core
    core=namespace;app=core['app'];conn=db()
    try:refresh_catalog(conn)
    finally:conn.close()
    app.before_request(before_catalog)
    app.after_request(decorate_public)
    routes=[('/api/catalog','GET',catalog,None),('/api/admin/catalog','POST',catalog_save,'admin'),
        ('/api/banks','GET',bank_list,'login'),('/api/banks/settings','POST',bank_settings,'login'),('/api/banks/request','POST',bank_request,'login'),
        ('/api/banks/respond','POST',bank_respond,'login'),('/api/banks/repay','POST',bank_repay,'login'),
        ('/api/profile/name_style','POST',donor_settings,'login'),('/api/admin/donator_tier','POST',donor_tier,'admin')]
    for path,method,fn,guard in routes:app.add_url_rule(path,'economy_'+fn.__name__,core['require_'+guard](fn) if guard else fn,methods=[method])
