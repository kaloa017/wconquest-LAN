"""Host controls, private trade discussions and persistent return-to-game summaries."""
import json,time,math
from flask import request,session,jsonify,abort
import features,config
core=None
RESOURCES=('money','food','wood','metal','oil','steel','uranium','gems')

def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=18').fetchone():conn.commit();return
        columns={r['name'] for r in conn.execute('PRAGMA table_info(users)')}
        for key,ddl in [('donated_ore','INTEGER NOT NULL DEFAULT 0'),('name_badge','TEXT NOT NULL DEFAULT ""'),('name_glow','INTEGER NOT NULL DEFAULT 0'),('otp_secret','TEXT NOT NULL DEFAULT ""'),('otp_pending','TEXT NOT NULL DEFAULT ""'),('otp_pending_until','INTEGER NOT NULL DEFAULT 0'),('otp_last_step','INTEGER NOT NULL DEFAULT -1')]:
            if key not in columns:conn.execute(f'ALTER TABLE users ADD COLUMN {key} {ddl}')
        for sql in [
            '''CREATE TABLE IF NOT EXISTS away_earnings(user_id INTEGER PRIMARY KEY,resources TEXT NOT NULL DEFAULT '{}',since INTEGER NOT NULL,until INTEGER NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS trade_discussion(id INTEGER PRIMARY KEY,sender INTEGER NOT NULL,recipient INTEGER NOT NULL,message TEXT NOT NULL,ts INTEGER NOT NULL)''',
            'CREATE INDEX IF NOT EXISTS trade_discussion_pair ON trade_discussion(sender,recipient,id)',
            'CREATE TABLE IF NOT EXISTS war_seen(user_id INTEGER NOT NULL,rel_id INTEGER NOT NULL,PRIMARY KEY(user_id,rel_id))',
            'CREATE TABLE IF NOT EXISTS research_projects(user_id INTEGER PRIMARY KEY,tech TEXT NOT NULL,remaining REAL NOT NULL,total REAL NOT NULL,last_tick INTEGER NOT NULL,speed REAL NOT NULL,paid INTEGER NOT NULL)',
            'CREATE TABLE IF NOT EXISTS megaprojects(user_id INTEGER NOT NULL,project TEXT NOT NULL,level INTEGER NOT NULL DEFAULT 0,ready_at INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,project))'
        ]:conn.execute(sql)
        conn.execute('INSERT INTO schema_migrations VALUES(18,?)',(int(time.time()),));conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

def away():
    conn=core['get_db']();uid=session['user_id']
    if request.method=='POST':
        data=features.body();saved=conn.execute('SELECT since FROM away_earnings WHERE user_id=?',(uid,)).fetchone()
        since=features.integer(data.get('since',saved['since'] if saved else 0),0,int(time.time()))
        if saved and since!=saved['since']:return jsonify(error='Away summary changed; refresh before acknowledging it'),409
        from player_events import claim_away
        claim_away(conn,uid,since)
        return jsonify(success=True)
    core['auto_collect'](uid,conn)
    row=conn.execute('SELECT * FROM away_earnings WHERE user_id=?',(uid,)).fetchone()
    return jsonify(summary={**dict(row),'resources':json.loads(row['resources'])} if row else None,maximum_hours=2)

def donation():
    conn=core['get_db']();d=features.body();uid=features.integer(d.get('user_id'),1)
    u=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not u:abort(404)
    if d.get('confirm') is not True:raise ValueError('Confirm this host-verified donation total')
    amount=d.get('amount_nok')
    if isinstance(amount,bool) or not isinstance(amount,(float,int)) or not math.isfinite(amount) or not 0<=amount<=10000000:raise ValueError('Enter a donation total in NOK')
    ore=round(amount*100);tier=next((key for key,threshold in reversed(list(config.DONATION_TIERS.items())) if ore>=threshold*100),None)
    conn.execute('UPDATE users SET donated_ore=?,is_donator=?,donator_tier=? WHERE id=?',(ore,bool(tier),tier or 'Supporter',uid))
    features.audit(conn,'verified_donation_total',uid,dict(previous_nok=u['donated_ore']/100,total_nok=ore/100,tier=tier))
    return jsonify(success=True,message='Verified donation total saved',tier=tier)

def discussion():
    conn=core['get_db']();uid=session['user_id'];d=features.body() if request.method=='POST' else request.args
    target=features.integer(d.get('to_id'),1)
    if target==uid or not conn.execute('SELECT 1 FROM users WHERE id=? AND is_banned=0',(target,)).fetchone():abort(404)
    if request.method=='POST':
        u=conn.execute('SELECT muted_until FROM users WHERE id=?',(uid,)).fetchone()
        if u['muted_until']>time.time():abort(403,description='You are muted')
        text=d.get('message')
        if not isinstance(text,str) or not 1<=len(text.strip())<=1000 or any(ord(c)<32 and c not in '\n\t' for c in text):raise ValueError('Write a message of 1–1,000 characters')
        conn.execute('INSERT INTO trade_discussion(sender,recipient,message,ts) VALUES(?,?,?,?)',(uid,target,text.strip(),int(time.time())))
        conn.execute('DELETE FROM trade_discussion WHERE ((sender=? AND recipient=?) OR (sender=? AND recipient=?)) AND id NOT IN (SELECT id FROM trade_discussion WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) ORDER BY id DESC LIMIT 100)',(uid,target,target,uid,uid,target,target,uid))
        core['create_notification'](conn,target,'info',session['username']+' sent a private trade message. Open Trading to discuss.')
    rows=conn.execute('SELECT d.id,d.sender,d.message,d.ts,u.username FROM trade_discussion d JOIN users u ON u.id=d.sender WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) ORDER BY d.id DESC LIMIT 100',(uid,target,target,uid)).fetchall()
    return jsonify(messages=[dict(r) for r in reversed(rows)])

def wars():
    conn=core['get_db']();uid=session['user_id'];fid=core['fac_id'](conn,uid)
    if request.method=='POST':
        rid=features.integer(features.body().get('rel_id'),1)
        if not conn.execute("SELECT 1 FROM faction_rel WHERE id=? AND kind='war' AND b=?",(rid,fid)).fetchone():abort(404)
        conn.execute('INSERT OR IGNORE INTO war_seen VALUES(?,?)',(uid,rid));return jsonify(success=True)
    result=[]
    for row in conn.execute("SELECT r.id,r.a,r.ts,f.name,f.tag,f.army FROM faction_rel r JOIN factions f ON f.id=r.a WHERE r.kind='war' AND r.status='active' AND r.b=? AND NOT EXISTS(SELECT 1 FROM war_seen s WHERE s.user_id=? AND s.rel_id=r.id)",(fid,uid)).fetchall():
        own=conn.execute('SELECT army FROM factions WHERE id=?',(fid,)).fetchone()[0]
        active={f:conn.execute("SELECT COALESCE(SUM(troops),0) FROM campaigns WHERE status='active' AND origin_faction=?",(f,)).fetchone()[0] for f in (fid,row['a'])}
        my_army=own+active[fid];their_army=row['army']+active[row['a']]
        share=my_army/max(1,my_army+their_army)
        result.append(dict(id=row['id'],name=row['name'],tag=row['tag'],strength_share=round(share*100),assessment='Favored' if share>.6 else 'Outnumbered' if share<.4 else 'Roughly even',explanation='This is a troop-strength comparison, not a win probability. Terrain, research, supply, tactics and reinforcements can change the outcome.'))
    return jsonify(wars=result)

def host_control():
    conn=core['get_db']();d=features.body();action=d.get('action');uid=features.integer(d.get('user_id'),1)
    if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():abort(404)
    if d.get('confirm') is not True:raise ValueError('Explicit confirmation required for host controls')
    if action in ('ideology','religion'):
        catalog=core['IDEOLOGIES'] if action=='ideology' else core['RELIGIONS'];key=d.get('key')
        if key not in catalog:raise ValueError('Choose an existing definition')
        core['auto_collect'](uid,conn)
        conn.execute(f'UPDATE users SET {action}=? WHERE id=?',(key,uid))
    elif action=='religion_cooldown':conn.execute('UPDATE users SET religion_ts=0 WHERE id=?',(uid,))
    elif action in ('research_complete','research_cancel'):
        row=conn.execute('SELECT * FROM research_projects WHERE user_id=?',(uid,)).fetchone()
        if not row:raise ValueError('Player has no active research')
        if action=='research_complete':
            from research import tick
            conn.execute('UPDATE research_projects SET remaining=0 WHERE user_id=?',(uid,));tick(conn,uid)
        else:
            conn.execute('UPDATE users SET money=money+? WHERE id=?',(row['paid'],uid));conn.execute('DELETE FROM research_projects WHERE user_id=?',(uid,))
    elif action=='end_campaigns':
        from expansion import finish_campaign
        for row in conn.execute("SELECT * FROM campaigns WHERE status='active' AND (attacker=? OR defender=?)",(uid,uid)).fetchall():finish_campaign(conn,dict(row),'ended','Host ended the offensive; survivors returned')
    elif action=='return_space':
        from space import collect_space
        row=conn.execute('SELECT state FROM space_program WHERE user_id=?',(uid,)).fetchone()
        if not row or row['state']=='earth':raise ValueError('Player has no expedition to return')
        collect_space(conn,uid,force=True);conn.execute("UPDATE space_program SET state='returning',arrival=? WHERE user_id=?",(int(time.time()),uid));collect_space(conn,uid,force=True)
    else:raise ValueError('Unknown host control')
    features.audit(conn,'host_control',uid,dict(action=action,key=d.get('key')))
    return jsonify(success=True,message='Host control applied')

def install(namespace):
    global core
    core=namespace;app=core['app'];original=core['auto_collect']
    def tracked_collect(uid,conn,force=False):
        from activity import state
        stamp=int(time.time());row=state(conn,uid,stamp)
        offline=stamp-row['last_activity']>180 and row['heartbeat']<=stamp-180
        before=conn.execute('SELECT '+','.join(RESOURCES)+' FROM users WHERE id=?',(uid,)).fetchone() if offline else None
        original(uid,conn,force=force)
        if before:
            after=conn.execute('SELECT '+','.join(RESOURCES)+' FROM users WHERE id=?',(uid,)).fetchone()
            gains={key:after[key]-before[key] for key in RESOURCES if after[key]>before[key]+.000001}
            if gains and row['last_activity']>row['away_ack_activity']:
                saved=conn.execute('SELECT * FROM away_earnings WHERE user_id=?',(uid,)).fetchone();resources=json.loads(saved['resources']) if saved else {}
                for key,value in gains.items():resources[key]=resources.get(key,0)+value
                conn.execute('INSERT INTO away_earnings VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET resources=excluded.resources,until=excluded.until',(uid,json.dumps(resources),saved['since'] if saved else row['last_activity'],stamp))
    core['auto_collect']=tracked_collect
    for path,methods,fn,guard in [('/api/away',['GET','POST'],away,'login'),('/api/trade/discussion',['GET','POST'],discussion,'login'),('/api/wars/unseen',['GET','POST'],wars,'login'),('/api/admin/donations',['POST'],donation,'admin'),('/api/admin/control',['POST'],host_control,'admin')]:
        app.add_url_rule(path,'experience_'+fn.__name__,core['require_'+guard](fn),methods=methods)
