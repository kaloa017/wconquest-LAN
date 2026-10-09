"""Persistent campaigns, moderation, exchanges, rockets and casino gameplay."""
import json
import math
import secrets
import time
from functools import wraps
from flask import jsonify, request, session, abort
import features
from config import BUILDINGS, ROCKET_COST, ROCKET_RANGE, ROCKET_COOLDOWN, COMBAT_TICK, CASINO_MAX_BET, CAMPAIGN_MAX_TARGETS

core = {}
ASSETS = ('money', 'food', 'wood', 'metal', 'oil', 'steel', 'uranium', 'gems', 'army', 'boats', 'planes', 'nukes', 'rockets')
TACTICS = {'balanced': (1, 1, 1), 'breakthrough': (1.3, 1.35, 1.5), 'careful': (.8, .7, .65)}

def db(): return core['get_db']()
def now(): return int(time.time())
def number(value, low=1, high=2**53-1): return features.integer(value, low, high)
def user(conn, uid): return conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
def note(conn, uid, message): core['create_notification'](conn, uid, 'info', message)

def migrate(get_db):
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=12').fetchone():
            conn.commit(); return
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
        for name, definition in [('is_moderator','INTEGER NOT NULL DEFAULT 0'), ('timeout_until','INTEGER NOT NULL DEFAULT 0'),
                ('timeout_by','TEXT NOT NULL DEFAULT ""'), ('timeout_message','TEXT NOT NULL DEFAULT ""'),
                ('timeout_started','INTEGER NOT NULL DEFAULT 0'), ('rockets','INTEGER NOT NULL DEFAULT 0'),
                ('last_rocket','INTEGER NOT NULL DEFAULT 0'), ('last_casino','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns: conn.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
        statements = [
            '''CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY, attacker INTEGER NOT NULL, defender INTEGER,
                from_key TEXT NOT NULL, target_key TEXT NOT NULL, troops INTEGER NOT NULL, initial_troops INTEGER NOT NULL,
                attack_org REAL DEFAULT 100, defense_org REAL DEFAULT 100, tactic TEXT DEFAULT 'balanced',
                posture TEXT DEFAULT 'hold', status TEXT DEFAULT 'active', started INTEGER, last_tick INTEGER,
                progress REAL DEFAULT 0, supply REAL DEFAULT 1, lost INTEGER DEFAULT 0, summary TEXT DEFAULT '')''',
            "CREATE UNIQUE INDEX IF NOT EXISTS active_front ON campaigns(target_key) WHERE status='active'",
            '''CREATE TABLE IF NOT EXISTS exchanges(id INTEGER PRIMARY KEY, sender INTEGER NOT NULL, recipient INTEGER NOT NULL,
                give_json TEXT NOT NULL, want_json TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS moderation_confirmations(token TEXT PRIMARY KEY, actor INTEGER NOT NULL,
                grid_key TEXT NOT NULL, owner INTEGER, recipient INTEGER NOT NULL, reason TEXT NOT NULL,
                stage INTEGER NOT NULL, expires INTEGER NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS strike_events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                from_key TEXT NOT NULL, target_key TEXT NOT NULL, actor TEXT NOT NULL, ts INTEGER NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS casino_rounds(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL, choice TEXT NOT NULL, roll INTEGER NOT NULL, payout INTEGER NOT NULL, ts INTEGER NOT NULL)'''
        ]
        for statement in statements: conn.execute(statement)
        conn.execute('INSERT INTO schema_migrations VALUES(12,?)', (now(),))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def migrate_orders(get_db):
    """Keep existing battles while adding optional sequential offensive orders."""
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=14').fetchone():
            columns={r['name'] for r in conn.execute('PRAGMA table_info(campaigns)')}
            if 'route_json' not in columns:
                conn.execute("ALTER TABLE campaigns ADD COLUMN route_json TEXT NOT NULL DEFAULT '[]'")
            if 'origin_faction' not in columns:
                conn.execute('ALTER TABLE campaigns ADD COLUMN origin_faction INTEGER')
                conn.execute('UPDATE campaigns SET origin_faction=(SELECT faction_id FROM users WHERE id=campaigns.attacker)')
            conn.execute('CREATE INDEX IF NOT EXISTS campaign_attacker_status ON campaigns(attacker,status,id)')
            conn.execute('CREATE INDEX IF NOT EXISTS campaign_defender_status ON campaigns(defender,status,id)')
            conn.execute('INSERT INTO schema_migrations VALUES(14,?)',(now(),))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

def moderation_guard(fn):
    @wraps(fn)
    @core['require_login']
    def guarded(*args, **kwargs):
        u = user(db(), session['user_id'])
        if not (u['is_admin'] or u['is_moderator']): abort(403)
        return fn(*args, **kwargs)
    return guarded

def timeout_gate():
    if not request.path.startswith('/api/') or not session.get('user_id'): return
    u = user(db(), session['user_id'])
    if u and u['timeout_until'] > now() and request.path not in ('/api/logout', '/api/bootstrap', '/api/moderation/status'):
        return jsonify(error='Your account is timed out.', timeout=timeout_info(u)), 423

def timeout_info(u):
    return dict(until=u['timeout_until'], remaining=max(0,u['timeout_until']-now()), moderator=u['timeout_by'],
                message=u['timeout_message'], duration=max(0,u['timeout_until']-u['timeout_started']))

def moderation_status(): return jsonify(timeout=timeout_info(user(db(),session['user_id'])))

def protect_target(conn, uid):
    actor = user(conn, session['user_id']); target = user(conn, uid)
    if not target: abort(404)
    if uid == actor['id'] or target['is_admin'] or (target['is_moderator'] and not actor['is_admin'] and (actor['is_moderator'] != 1 or target['is_moderator'] == 1)):
        abort(403, description='You cannot moderate yourself or a player of equal or higher rank.')
    return target

def moderation_players():
    return jsonify([dict(r) for r in db().execute('SELECT id,username,is_admin,is_moderator,muted_until,timeout_until FROM users ORDER BY username')])

def moderation_action():
    d=features.body(); conn=db(); uid=number(d.get('user_id')); target=protect_target(conn,uid)
    action=d.get('action'); minutes=number(d.get('minutes',0),0,10080)
    message=d.get('message','')
    if not isinstance(message,str) or not 3<=len(message.strip())<=500: raise ValueError('Provide a reason of 3–500 characters')
    until=now()+minutes*60 if minutes else 0
    if action=='mute': conn.execute('UPDATE users SET muted_until=? WHERE id=?',(until,uid))
    elif action=='timeout':
        conn.execute('UPDATE users SET timeout_until=?,timeout_started=?,timeout_by=?,timeout_message=? WHERE id=?',
                     (until,now(),session['username'],message.strip(),uid))
    else: raise ValueError('Choose mute or timeout')
    features.audit(conn,'moderator_'+action,uid,dict(minutes=minutes,reason=message))
    note(conn,uid,f'{session["username"]}: {action} for {minutes} minutes. {message}')
    return jsonify(success=True,message=f'{action.title()} updated for {target["username"]}')

def set_role():
    conn=db(); d=features.body(); uid=number(d.get('user_id')); target=user(conn,uid)
    if not target or target['is_admin']: raise ValueError('Choose a non-admin player')
    enabled=d.get('enabled')
    if not isinstance(enabled,bool): raise ValueError('Choose enabled or disabled')
    role=d.get('role','senior')
    if role not in ('moderator','senior'): raise ValueError('Choose moderator or senior')
    level=(2 if role=='moderator' else 1) if enabled else 0
    conn.execute('UPDATE users SET is_moderator=? WHERE id=?',(level,uid))
    features.audit(conn,'moderator_role',uid,dict(enabled=enabled,role=role))
    return jsonify(success=True,message='Moderator role updated')

def takeover():
    actor_user=user(db(),session['user_id'])
    if not actor_user['is_admin'] and actor_user['is_moderator'] != 1: abort(403)
    conn=db(); d=features.body(); stage=number(d.get('stage'),1,3); actor=session['user_id']
    conn.execute('DELETE FROM moderation_confirmations WHERE expires<?',(now(),))
    if stage==1:
        key=d.get('grid_key'); core['parse_key'](key)
        tile=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(key,)).fetchone()
        if not tile or not tile['owner_id']: raise ValueError('Select an owned territory')
        protect_target(conn,tile['owner_id'])
        recipient=number(d.get('to_id')); recipient_user=user(conn,recipient)
        if not recipient_user or recipient_user['is_banned'] or recipient==tile['owner_id']: raise ValueError('Choose a different active recipient')
        reason=d.get('reason','')
        if not isinstance(reason,str) or not 5<=len(reason.strip())<=500: raise ValueError('Explain the takeover (5–500 characters)')
        token=secrets.token_urlsafe(32)
        conn.execute('INSERT INTO moderation_confirmations VALUES(?,?,?,?,?,?,1,?)',
                     (token,actor,key,tile['owner_id'],recipient,reason.strip(),now()+120))
        return jsonify(token=token,message=f'Transfer {key} from {core["uname"](conn,tile["owner_id"])} to {recipient_user["username"]}. Buildings stay with the tile. Confirm this exact transfer.')
    confirmation=conn.execute('SELECT * FROM moderation_confirmations WHERE token=? AND actor=? AND expires>=?',(d.get('token'),actor,now())).fetchone()
    if not confirmation or confirmation['stage']!=stage-1 or d.get('confirm') is not True: raise ValueError('Confirmation expired or out of sequence; start again')
    if stage==2:
        conn.execute('UPDATE moderation_confirmations SET stage=2 WHERE token=?',(confirmation['token'],))
        return jsonify(token=confirmation['token'],message='Final confirmation: this immediately changes ownership and records your name and reason in the audit log.')
    protect_target(conn,confirmation['owner'])
    tile=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(confirmation['grid_key'],)).fetchone()
    if not tile or tile['owner_id']!=confirmation['owner']: raise ValueError('Ownership changed; start again')
    if not user(conn,confirmation['recipient']) or user(conn,confirmation['recipient'])['is_banned']: raise ValueError('Recipient is unavailable')
    settle_tile_campaigns(conn,confirmation['grid_key'],'Ownership changed by moderator')
    conn.execute('UPDATE territories SET owner_id=? WHERE grid_key=?',(confirmation['recipient'],confirmation['grid_key']))
    conn.execute('UPDATE users SET capital_key=NULL WHERE capital_key=?',(confirmation['grid_key'],))
    features.audit(conn,'moderator_takeover',confirmation['owner'],dict(confirmation))
    for uid in (confirmation['owner'],confirmation['recipient']): note(conn,uid,f'{session["username"]} transferred {confirmation["grid_key"]}. Reason: {confirmation["reason"]}')
    conn.execute('DELETE FROM moderation_confirmations WHERE token=?',(confirmation['token'],))
    return jsonify(success=True,message='Territory transferred')

def war_score(conn,uid,oid):
    relation=core['war_between'](conn,uid,oid)
    if relation:
        column='score_a' if relation['a']==core['fac_id'](conn,uid) else 'score_b'
        conn.execute(f'UPDATE faction_rel SET {column}={column}+1 WHERE id=?',(relation['id'],))

def end_war():
    conn=db(); d=features.body(); fid=core['fac_id'](conn,session['user_id'])
    relation=conn.execute("SELECT * FROM faction_rel WHERE id=? AND kind='war' AND status='active' AND (a=? OR b=?)",(number(d.get('rel_id')),fid,fid)).fetchone()
    if not relation: abort(404)
    action=d.get('action','peace')
    if action not in ('peace','surrender'): raise ValueError('Choose peace or surrender')
    conn.execute("UPDATE faction_rel SET status='ended' WHERE id=?",(relation['id'],))
    for campaign in conn.execute("SELECT * FROM campaigns WHERE status='active'").fetchall():
        if {core['fac_id'](conn,campaign['attacker']),core['fac_id'](conn,campaign['defender']) if campaign['defender'] else None}=={relation['a'],relation['b']}:
            finish_campaign(conn,campaign,'ended','War ended; troops returned')
    core['announce'](conn,f'{session["username"]} ended the faction war by {action}. Captured land stays with its current owner.')
    features.audit(conn,'war_'+action,None,dict(relation=relation['id']))
    return jsonify(success=True,message='War ended. Surviving committed troops returned; ownership retained.')

def start_campaign():
    conn=db(); d=features.body(); uid=session['user_id']; fk=d.get('from_key'); tk=d.get('target_key')
    core['parse_key'](fk); core['parse_key'](tk)
    if fk==tk or core['cell_distance'](fk,tk)>1: raise ValueError('Choose an adjacent land target')
    source=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(fk,)).fetchone()
    if not source or source['owner_id'] not in core['group_ids'](conn,uid): abort(403)
    error=core['_target_checks'](conn,uid,tk)
    if error: raise ValueError(error)
    route=d.get('target_keys',[tk])
    if not isinstance(route,list) or not 1<=len(route)<=CAMPAIGN_MAX_TARGETS or any(not isinstance(key,str) for key in route):raise ValueError('Plan between 1 and 64 adjacent targets')
    if route[0]!=tk or len(set(route))!=len(route) or fk in route:raise ValueError('Choose different targets starting with the selected tile')
    previous=fk
    for key in route:
        core['parse_key'](key)
        if core['cell_distance'](previous,key)>1:raise ValueError('Each planned target must touch the previous tile')
        error=core['_target_checks'](conn,uid,key)
        if error:raise ValueError(error)
        previous=key
    if conn.execute("SELECT 1 FROM campaigns WHERE target_key=? AND status='active'",(tk,)).fetchone(): raise ValueError('An offensive is already fighting for this tile')
    troops=number(d.get('troops')); tactic=d.get('tactic','balanced')
    if tactic not in TACTICS: raise ValueError('Unknown tactic')
    if core['pool_get'](conn,uid,'army')<troops: raise ValueError('Not enough available troops')
    travel_cost=core['military_travel_cost']('land',troops)
    if not core['can_afford'](user(conn,uid),travel_cost):raise ValueError('Not enough money and oil to move this force: '+', '.join(f'{v:,} {k}' for k,v in travel_cost.items()))
    core['pay'](conn,uid,travel_cost)
    core['pool_add'](conn,uid,'army',-troops)
    target=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(tk,)).fetchone(); defender=target['owner_id'] if target else None
    cur=conn.execute('INSERT INTO campaigns(attacker,defender,from_key,target_key,troops,initial_troops,tactic,started,last_tick,route_json,origin_faction) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (uid,defender,fk,tk,troops,troops,tactic,now(),now(),json.dumps(route[1:]),core['fac_id'](conn,uid)))
    if defender: note(conn,defender,f'{session["username"]} started an offensive at {tk}. Open Operations to choose a defensive stance.')
    return jsonify(success=True,campaign_id=cur.lastrowid,message='Offensive started. Manage tactics, organization and retreat in Operations.')

def finish_campaign(conn,campaign,status,message):
    if campaign['troops']:
        # Refund a committed force without counting it as new faction contributions.
        fid=campaign['origin_faction']
        if fid and not conn.execute('SELECT 1 FROM factions WHERE id=?',(fid,)).fetchone():fid=None
        if fid: conn.execute('UPDATE factions SET army=army+? WHERE id=?',(campaign['troops'],fid))
        elif user(conn,campaign['attacker']): conn.execute('UPDATE users SET army=army+? WHERE id=?',(campaign['troops'],campaign['attacker']))
    conn.execute("UPDATE campaigns SET status=?,summary=?,route_json='[]' WHERE id=?",(status,message,campaign['id']))
    if user(conn,campaign['attacker']): note(conn,campaign['attacker'],message)
    if campaign['defender'] and user(conn,campaign['defender']): note(conn,campaign['defender'],message)

def settle_tile_campaigns(conn,key,message):
    for campaign in conn.execute("SELECT * FROM campaigns WHERE status='active' AND (target_key=? OR from_key=?)",(key,key)).fetchall(): finish_campaign(conn,campaign,'ended',message)

def tick_campaigns(conn, timestamp=None):
    timestamp=now() if timestamp is None else timestamp
    for original in conn.execute("SELECT * FROM campaigns WHERE status='active' AND last_tick<=?",(timestamp-COMBAT_TICK,)).fetchall():
        c=dict(original); attacker=user(conn,c['attacker']); target=conn.execute('SELECT * FROM territories WHERE grid_key=?',(c['target_key'],)).fetchone()
        source=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(c['from_key'],)).fetchone()
        if not attacker or attacker['is_banned'] or attacker['timeout_until']>timestamp or (c['defender'] and not user(conn,c['defender'])) or (target['owner_id'] if target else None)!=c['defender'] or core['fallout_active'](conn,c['target_key']):
            finish_campaign(conn,c,'ended','Offensive ended because a participant or territory became unavailable'); continue
        if c['defender'] and core['attack_block'](conn,c['attacker'],c['defender']):
            finish_campaign(conn,c,'ended','Diplomacy ended the offensive'); continue
        # One bounded tick after downtime avoids silently consuming hours of troops.
        r=core['resolve_battle'](conn,c['attacker'],attacker['username'],c['target_key'],c['troops'],'land',c['from_key'],dry=True)
        gl,gg=core['parse_key'](c['target_key']); ids=core['group_ids'](conn,c['attacker'])
        adjacent=sum(1 for key in core['adj_keys'](gl,gg) if (row:=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(key,)).fetchone()) and row['owner_id'] in ids)
        supply=1 if source and source['owner_id'] in ids else .25
        food=max(1,math.ceil(c['troops']*.02*TACTICS[c['tactic']][2]))
        if attacker['food']<food: supply*=.4
        else: conn.execute('UPDATE users SET food=food-? WHERE id=?',(food,c['attacker']))
        width={'mountains':45,'forest':70,'city':60}.get(r['terrain'],100)
        effective=min(c['troops'],width)+max(0,c['troops']-width)*.25
        attack=r['A']*effective/max(1,c['troops'])*TACTICS[c['tactic']][0]*supply*(.5+c['attack_org']/200)*(1+min(.3,max(0,adjacent-1)*.1))
        defense=r['D']*(1.2 if c['posture']=='entrench' else .9 if c['posture']=='counterattack' else 1)
        ratio=attack/max(1,defense)
        c['attack_org']=max(0,c['attack_org']-max(2,9/max(.2,ratio))*TACTICS[c['tactic']][1]*(1.3 if c['posture']=='counterattack' else 1))
        c['defense_org']=max(0,c['defense_org']-max(2,min(30,9*ratio)))
        loss=min(c['troops'],max(1,math.ceil(c['troops']*.015/max(.4,ratio)*TACTICS[c['tactic']][1])))
        c['troops']-=loss; c['lost']+=loss
        if c['defender']: core['pool_add'](conn,c['defender'],'army',-min(core['pool_get'](conn,c['defender'],'army'),max(1,int(r['def_force']*.02*min(3,ratio)))))
        c['progress']=min(100,100-c['defense_org']); c['supply']=supply
        conn.execute('UPDATE campaigns SET troops=?,lost=?,attack_org=?,defense_org=?,progress=?,supply=?,last_tick=? WHERE id=?',
                     (c['troops'],c['lost'],c['attack_org'],c['defense_org'],c['progress'],supply,timestamp,c['id']))
        if c['troops']<=0 or c['attack_org']<=0 or c['defense_org']<=0:
            victory=c['troops']>0 and c['attack_org']>0 and c['defense_org']<=0
            halted=''
            if victory:
                core['apply_victory'](conn,c['attacker'],c['target_key'],r['terrain'],target,gl,gg)
                if c['defender']: war_score(conn,c['attacker'],c['defender'])
                route=json.loads(c['route_json'])
                if route:
                    next_key=route[0]
                    blocked=core['_target_checks'](conn,c['attacker'],next_key)
                    busy=conn.execute("SELECT 1 FROM campaigns WHERE target_key=? AND status='active' AND id!=?",(next_key,c['id'])).fetchone()
                    travel_cost=core['military_travel_cost']('land',c['troops'])
                    if not blocked and not core['can_afford'](user(conn,c['attacker']),travel_cost):blocked='not enough money and oil for troop travel'
                    if not blocked and not busy:
                        core['pay'](conn,c['attacker'],travel_cost)
                        next_tile=conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(next_key,)).fetchone()
                        defender=next_tile['owner_id'] if next_tile else None
                        conn.execute('UPDATE campaigns SET from_key=?,target_key=?,defender=?,attack_org=?,defense_org=100,posture="hold",progress=0,route_json=? WHERE id=?',
                            (c['target_key'],next_key,defender,min(100,c['attack_org']+15),json.dumps(route[1:]),c['id']))
                        note(conn,c['attacker'],f'Captured {c["target_key"]}; {c["troops"]:,} survivors advancing to {next_key}.')
                        if defender:note(conn,defender,f'{attacker["username"]} is advancing on {next_key}. Choose a stance in Operations.')
                        core['award_achievements'](conn,c['attacker'])
                        continue
                    halted=' Queued advance stopped: '+(blocked or 'another offensive occupies the next tile')+'.'
            status='victory' if victory else 'retreated'; message=f'{status.title()} at {c["target_key"]}: {c["lost"]} lost, {c["troops"]} returned.'
            message+=halted
            core['morale_update'](conn,c['attacker'],victory)
            conn.execute('INSERT INTO battle_log(attacker,defender,grid_key,result,mode,details) VALUES(?,?,?,?,?,?)',
                         (attacker['username'],core['uname'](conn,c['defender']) if c['defender'] else 'wilderness',c['target_key'],'victory' if victory else 'defeat','land',message))
            finish_campaign(conn,c,status,message); core['award_achievements'](conn,c['attacker'])
    conn.execute("DELETE FROM campaigns WHERE status!='active' AND id NOT IN (SELECT id FROM campaigns ORDER BY id DESC LIMIT 500)")

def campaigns():
    conn=db();uid=session['user_id']
    if not conn.in_transaction:conn.execute('BEGIN')
    rows=conn.execute("SELECT * FROM campaigns WHERE status='active' AND (attacker=? OR defender=?) ORDER BY id DESC",(uid,uid)).fetchall()
    rows+=conn.execute("SELECT * FROM campaigns WHERE status!='active' AND (attacker=? OR defender=?) ORDER BY id DESC LIMIT 20",(uid,uid)).fetchall()
    result=[]
    for row in rows:
        item=dict(row);route=json.loads(item.pop('route_json'))
        item['targets_remaining']=route if item['attacker']==uid else []
        result.append(item)
    return jsonify(campaigns=result,tick_seconds=COMBAT_TICK)

def campaign_order():
    conn=db(); d=features.body(); uid=session['user_id']; c=conn.execute("SELECT * FROM campaigns WHERE id=? AND status='active'",(number(d.get('campaign_id')),)).fetchone()
    if not c: abort(404)
    ids=core['group_ids'](conn,uid); action=d.get('action')
    if action in ('retreat','tactic'):
        if c['attacker']!=uid: abort(403)
        if action=='retreat': finish_campaign(conn,c,'retreated','Commander ordered a retreat; surviving troops returned')
        else:
            if d.get('tactic') not in TACTICS: raise ValueError('Choose a tactic')
            conn.execute('UPDATE campaigns SET tactic=? WHERE id=?',(d['tactic'],c['id']))
    elif action=='posture':
        if c['defender']!=uid: abort(403)
        if d.get('posture') not in ('hold','entrench','counterattack'): raise ValueError('Choose a defensive stance')
        conn.execute('UPDATE campaigns SET posture=? WHERE id=?',(d['posture'],c['id']))
    else: raise ValueError('Unknown command')
    return jsonify(success=True,message='Orders updated')

def basket(value):
    if not isinstance(value,dict) or len(value)>len(ASSETS)+1: raise ValueError('Invalid item list')
    result={}
    for key,amount in value.items():
        if key=='territories':
            if not isinstance(amount,list) or len(amount)>50 or any(not isinstance(k,str) for k in amount) or len(set(amount))!=len(amount): raise ValueError('Choose up to 50 different territories')
            for tile in amount: core['parse_key'](tile)
            if amount: result[key]=amount
        elif key in ASSETS:
            amount=number(amount,0,10**9)
            if amount: result[key]=amount
        else: raise ValueError('Unknown transferable item')
    return result

def check_basket(conn,uid,items):
    u=user(conn,uid)
    if not u or u['is_banned'] or u['timeout_until']>now(): raise ValueError('A participant is unavailable')
    for key,amount in items.items():
        if key=='territories':
            for tile in amount:
                if not conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id=?',(tile,uid)).fetchone(): raise ValueError('A territory is no longer owned by its sender')
                if conn.execute("SELECT 1 FROM campaigns WHERE status='active' AND (from_key=? OR target_key=?)",(tile,tile)).fetchone(): raise ValueError('End the offensive before transferring this territory')
        elif key=='army' and u['faction_id']:
            contribution=conn.execute('SELECT army FROM faction_contributions WHERE user_id=?',(uid,)).fetchone()
            total=conn.execute('SELECT SUM(army) FROM faction_contributions WHERE faction_id=?',(u['faction_id'],)).fetchone()[0] or 1
            available=int(core['pool_get'](conn,uid,'army')*(contribution[0] if contribution else 0)/total)
            if available<amount: raise ValueError('You can send only your proportional share of the faction army')
        elif u[key]<amount: raise ValueError('Insufficient personally owned '+key)

def transfer(conn,sender,recipient,items):
    for key,amount in items.items():
        if key=='territories':
            for tile in amount:
                conn.execute('UPDATE territories SET owner_id=? WHERE grid_key=?',(recipient,tile))
                conn.execute('UPDATE users SET capital_key=NULL WHERE id=? AND capital_key=?',(sender,tile))
        elif key=='army':
            u=user(conn,sender); fid=u['faction_id']
            if fid:
                pool=core['pool_get'](conn,sender,'army'); total=conn.execute('SELECT SUM(army) FROM faction_contributions WHERE faction_id=?',(fid,)).fetchone()[0] or 0
                debit=math.ceil(amount*total/max(1,pool))
                conn.execute('UPDATE faction_contributions SET army=MAX(0,army-?) WHERE user_id=?',(debit,sender))
            core['pool_add'](conn,sender,'army',-amount); core['pool_add'](conn,recipient,'army',amount)
        else:
            conn.execute(f'UPDATE users SET {key}={key}-? WHERE id=?',(amount,sender))
            conn.execute(f'UPDATE users SET {key}={key}+? WHERE id=?',(amount,recipient))

def exchange_list():
    conn=db(); uid=session['user_id']
    rows=conn.execute('SELECT e.*,a.username sender_name,b.username recipient_name FROM exchanges e JOIN users a ON a.id=e.sender JOIN users b ON b.id=e.recipient WHERE sender=? OR recipient=? ORDER BY e.id DESC LIMIT 60',(uid,uid))
    return jsonify(assets=ASSETS,players=[dict(r) for r in conn.execute('SELECT id,username FROM users WHERE id!=? AND is_banned=0 ORDER BY username',(uid,))],
        offers=[{**dict(r),'give':json.loads(r['give_json']),'want':json.loads(r['want_json'])} for r in rows])

def exchange_send():
    conn=db(); uid=session['user_id']; d=features.body(); recipient=number(d.get('to_id'))
    if recipient==uid: raise ValueError('Choose another player')
    give=basket(d.get('give',{})); want=basket(d.get('want',{}))
    if not give: raise ValueError('Choose at least one item to send')
    check_basket(conn,uid,give); check_basket(conn,recipient,{})
    if conn.execute("SELECT COUNT(*) FROM exchanges WHERE sender=? AND status='pending'",(uid,)).fetchone()[0]>=30: raise ValueError('Cancel an old offer first (30 pending offers maximum)')
    status='pending' if want else 'completed'
    if not want: transfer(conn,uid,recipient,give)
    conn.execute('INSERT INTO exchanges(sender,recipient,give_json,want_json,status,created) VALUES(?,?,?,?,?,?)',(uid,recipient,json.dumps(give),json.dumps(want),status,now()))
    note(conn,recipient,f'{session["username"]} sent you '+('an exchange offer. Open Trading to review it.' if want else 'a gift: '+json.dumps(give)))
    return jsonify(success=True,message='Offer sent; items transfer when accepted' if want else 'Gift delivered')

def exchange_respond():
    conn=db(); d=features.body(); uid=session['user_id']; offer=conn.execute("SELECT * FROM exchanges WHERE id=? AND status='pending'",(number(d.get('offer_id')),)).fetchone()
    if not offer or uid not in (offer['sender'],offer['recipient']): abort(404)
    action=d.get('action')
    if action=='accept':
        if uid!=offer['recipient']: abort(403)
        give=json.loads(offer['give_json']); want=json.loads(offer['want_json'])
        check_basket(conn,offer['sender'],give); check_basket(conn,uid,want)
        transfer(conn,offer['sender'],uid,give); transfer(conn,uid,offer['sender'],want); status='completed'
    elif action in ('decline','cancel'): status='cancelled'
    else: raise ValueError('Unknown response')
    conn.execute('UPDATE exchanges SET status=? WHERE id=?',(status,offer['id']))
    note(conn,offer['sender'],f'Exchange #{offer["id"]}: {status}')
    return jsonify(success=True,message='Exchange '+status)

def trade_propose():
    """Keep recurring trade contracts compatible while allowing gifts and units."""
    conn=db(); d=features.body(); uid=session['user_id']; recipient=number(d.get('to_id'))
    give=basket({d.get('give_res'):d.get('give_amt')})
    want=basket({d.get('get_res','money'):d.get('get_amt',0)})
    if not give or recipient==uid: raise ValueError('Choose items and another player')
    check_basket(conn,uid,give); check_basket(conn,recipient,{})
    cur=conn.execute("INSERT INTO trades(from_id,to_id,give_res,give_amt,get_res,get_amt,status) VALUES(?,?,?,?,?,?,'pending')",
        (uid,recipient,d['give_res'],d['give_amt'],d.get('get_res','money'),d.get('get_amt',0)))
    core['notify_actions'](conn,recipient,'trade_request',f'{session["username"]} offers {d["give_amt"]} {d["give_res"]} for {d.get("get_amt",0)} {d.get("get_res","money")} every ten minutes.',
        [{'label':'Accept','path':'/api/trade/respond','body':{'trade_id':cur.lastrowid,'accept':True},'cls':'btn-success'},
         {'label':'Decline','path':'/api/trade/respond','body':{'trade_id':cur.lastrowid,'accept':False},'cls':'btn-danger'}])
    return jsonify(success=True,message='Recurring offer sent')

def run_trades(conn,uid):
    timestamp=now()
    for deal in conn.execute("SELECT * FROM trades WHERE status='active' AND (from_id=? OR to_id=?)",(uid,uid)).fetchall():
        last=deal['last_run'] or timestamp; count=min(6,(timestamp-last)//600)
        if not deal['last_run']: conn.execute('UPDATE trades SET last_run=? WHERE id=?',(timestamp,deal['id']))
        for _ in range(count):
            try:
                give=basket({deal['give_res']:deal['give_amt']}); want=basket({deal['get_res']:deal['get_amt']})
                check_basket(conn,deal['from_id'],give); check_basket(conn,deal['to_id'],want)
            except ValueError: break
            transfer(conn,deal['from_id'],deal['to_id'],give); transfer(conn,deal['to_id'],deal['from_id'],want)
        if count: conn.execute('UPDATE trades SET last_run=? WHERE id=?',(last+count*600,deal['id']))

def rocket_build():
    conn=db(); uid=session['user_id']; amount=number(features.body().get('amount',1),1,2**53-1)
    if not core['group_levels'](conn,uid,'rocket_pad'): raise ValueError('Build a Rocket Pad first')
    cost={k:v*amount for k,v in ROCKET_COST.items()}
    if not core['can_afford'](user(conn,uid),cost): raise ValueError('Need '+core['fmt_cost'](cost))
    core['pay'](conn,uid,cost); conn.execute('UPDATE users SET rockets=rockets+? WHERE id=?',(amount,uid))
    return jsonify(success=True,message=f'Built {amount} rocket(s)')

def rocket_launch():
    conn=db(); uid=session['user_id']; d=features.body(); fk=d.get('from_key'); tk=d.get('target_key')
    core['parse_key'](fk); core['parse_key'](tk); u=user(conn,uid)
    ids=core['group_ids'](conn,uid)
    source=conn.execute('SELECT t.owner_id FROM territories t JOIN buildings b ON b.grid_key=t.grid_key WHERE t.grid_key=? AND b.type="rocket_pad"',(fk,)).fetchone()
    if not source or source[0] not in ids: raise ValueError('Launch from a friendly Rocket Pad')
    if core['cell_distance'](fk,tk)>ROCKET_RANGE: raise ValueError(f'Rocket range is {ROCKET_RANGE} cells')
    target=conn.execute('SELECT * FROM territories WHERE grid_key=? AND owner_id IS NOT NULL',(tk,)).fetchone()
    if not target or target['owner_id'] in ids: raise ValueError('Choose an enemy owned territory')
    error=core['attack_block'](conn,uid,target['owner_id'])
    if error: raise ValueError(error)
    if u['rockets']<1: raise ValueError('Build a rocket first')
    if now()-u['last_rocket']<ROCKET_COOLDOWN: raise ValueError('Rocket Pad is reloading')
    from geography import islands_in_radius
    a,b=core['parse_key'](tk);radius=2
    keys=[f'{a+x},{b+y}' for x in range(-radius,radius+1) for y in range(-radius,radius+1) if x*x+y*y<=radius*radius and -473<=a+x<=472 and -1000<=b+y<=999]
    keys+=islands_in_radius(a,b,radius);marks=','.join('?' for _ in keys)
    error=core['blast_attack_block'](conn,uid,keys)
    if error: raise ValueError(error)
    victims=conn.execute(f'SELECT grid_key,owner_id FROM territories WHERE grid_key IN ({marks}) AND owner_id IS NOT NULL',keys).fetchall()
    for campaign in conn.execute(f"SELECT * FROM campaigns WHERE status='active' AND (from_key IN ({marks}) OR target_key IN ({marks}))",keys+keys).fetchall():
        finish_campaign(conn,campaign,'ended','Rocket strike cleared the battlefield; survivors returned')
    owners={r['owner_id'] for r in victims}
    for owner in owners:
        damage=min(core['pool_get'](conn,owner,'army'),max(1,int(core['pool_get'](conn,owner,'army')*.05)))
        core['pool_add'](conn,owner,'army',-damage)
        note(conn,owner,f'{session["username"]} launched a rocket at {tk}. Radius 2: land and buildings cleared, {damage} troops lost. Land can be claimed immediately unless older fallout remains.')
    conn.execute(f'UPDATE territories SET owner_id=NULL,garrison=0,boats=0,planes=0 WHERE grid_key IN ({marks})',keys)
    conn.execute(f'DELETE FROM buildings WHERE grid_key IN ({marks})',keys)
    conn.execute(f'UPDATE users SET capital_key=NULL WHERE capital_key IN ({marks})',keys)
    conn.execute('UPDATE users SET rockets=rockets-1,last_rocket=? WHERE id=?',(now(),uid))
    record_strike(conn,'rocket',fk,tk)
    conn.execute('INSERT INTO battle_log(attacker,defender,grid_key,result,mode,details) VALUES(?,?,?,?,?,?)',
        (session['username'],', '.join(core['uname'](conn,o) for o in owners),tk,'victory','rocket',f'Radius 2, {len(victims)} owned tiles cleared; no new fallout'))
    return jsonify(success=True,radius=2,message=f'Rocket hit: {len(victims)} owned tiles cleared in a 2-cell radius. No new fallout; reclaim available land immediately.')

def record_strike(conn,kind,fk,tk):
    conn.execute('INSERT INTO strike_events(kind,from_key,target_key,actor,ts) VALUES(?,?,?,?,?)',(kind,fk,tk,session['username'],now()))
    conn.execute('DELETE FROM strike_events WHERE id<(SELECT COALESCE(MAX(id),0)-200 FROM strike_events)')

def strike_events():
    since=number(request.args.get('since','0'),0)
    return jsonify(events=[dict(r) for r in db().execute('SELECT * FROM strike_events WHERE id>? AND ts>? ORDER BY id',(since,now()-90))])

def casino_play():
    conn=db(); uid=session['user_id']; d=features.body(); key=d.get('grid_key'); bet=number(d.get('bet'),1,CASINO_MAX_BET); choice=d.get('choice')
    if choice not in ('low','high','seven'): raise ValueError('Choose low, high or seven')
    casino=conn.execute('SELECT b.level FROM buildings b JOIN territories t ON b.grid_key=t.grid_key WHERE b.grid_key=? AND b.type="casino" AND t.owner_id=?',(key,uid)).fetchone()
    if not casino: raise ValueError('Build and own a Casino on the selected tile')
    if bet>min(CASINO_MAX_BET,casino[0]*1000): raise ValueError('Bet limit is 1,000 per casino level')
    u=user(conn,uid)
    if u['money']<bet: raise ValueError('Not enough in-game money')
    if now()-u['last_casino']<3: raise ValueError('Wait three seconds between rounds')
    dice=[secrets.randbelow(6)+1,secrets.randbelow(6)+1]; roll=sum(dice)
    won=(choice=='low' and roll<7) or (choice=='high' and roll>7) or (choice=='seven' and roll==7)
    payout=bet*(5 if choice=='seven' else 2) if won else 0
    conn.execute('UPDATE users SET money=money-?+?,last_casino=? WHERE id=?',(bet,payout,now(),uid))
    conn.execute('INSERT INTO casino_rounds(user_id,bet,choice,roll,payout,ts) VALUES(?,?,?,?,?,?)',(uid,bet,choice,roll,payout,now()))
    conn.execute('DELETE FROM casino_rounds WHERE id<(SELECT COALESCE(MAX(id),0)-5000 FROM casino_rounds)')
    return jsonify(success=True,dice=dice,payout=payout,message=f'Rolled {dice[0]} + {dice[1]} = {roll}. '+(f'Returned {payout} money (including stake).' if payout else f'Lost {bet} money.'))

def me_details(conn,u,uid):
    out=features.me_details(conn,u,uid)
    out.update({k:u[k] for k in ('is_moderator','rockets')})
    from economy import name_style
    out.update(name_style(u))
    out['building_counts']={r['type']:{'count':r['n'],'levels':r['levels']} for r in conn.execute('SELECT b.type,COUNT(*) n,SUM(b.level) levels FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE t.owner_id=? GROUP BY b.type',(uid,))}
    return out

def install(namespace):
    global core
    core=namespace; app=core['app']; core['war_score']=war_score; core['me_extra']=me_details; core['run_trades']=run_trades
    app.before_request(timeout_gate)
    routes=[('/api/moderation/status','GET',moderation_status,'login'),('/api/moderation/players','GET',moderation_players,'mod'),
        ('/api/moderation/action','POST',moderation_action,'mod'),('/api/moderation/takeover','POST',takeover,'mod'),
        ('/api/admin/moderator','POST',set_role,'admin'),('/api/campaigns','GET',campaigns,'login'),('/api/campaigns/order','POST',campaign_order,'login'),
        ('/api/exchanges','GET',exchange_list,'login'),('/api/exchanges/send','POST',exchange_send,'login'),('/api/exchanges/respond','POST',exchange_respond,'login'),
        ('/api/rockets/build','POST',rocket_build,'login'),('/api/rockets/launch','POST',rocket_launch,'login'),('/api/strikes','GET',strike_events,None),
        ('/api/casino/play','POST',casino_play,'login')]
    for path,method,fn,guard in routes:
        wrapped=moderation_guard(fn) if guard=='mod' else core['require_'+guard](fn) if guard else fn
        app.add_url_rule(path,'expansion_'+fn.__name__,wrapped,methods=[method])
    app.view_functions['attack']=core['require_login'](start_campaign)
    app.view_functions['war_end']=core['require_login'](end_war)
    app.view_functions['trade_propose']=core['require_login'](trade_propose)
    old_nuke=app.view_functions['nuke_launch']
    @wraps(old_nuke)
    def nuke_with_event():
        response=app.make_response(old_nuke())
        if response.status_code<400:
            d=features.body(); record_strike(db(),'nuke',d['from_key'],d['target_key'])
        return response
    app.view_functions['nuke_launch']=nuke_with_event
