"""Private late-game expeditions and bounded, timestamp-based orbital income."""
import json
import time
from flask import jsonify, session, request
import features
from config import (SPACE_BUSINESSES, SPACE_PLANETS, SPACE_GRID_SIZE, SPACE_CARGO_CAPACITY,
    SPACE_IRIDIUM_PRICE, SPACE_MINE_COST, SPACE_MINE_MAX_LEVEL, SPACE_RESOURCE_RATES,
    SPACE_COLLECTION_INTERVAL, MAX_ACCUM_MINS)

core = {}


def migrate(get_db):
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone():
            conn.commit();return
        for statement in [
            """CREATE TABLE IF NOT EXISTS space_program(user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'earth',planet TEXT,arrival INTEGER NOT NULL DEFAULT 0,
                collected INTEGER NOT NULL,last_mined INTEGER NOT NULL,cargo TEXT NOT NULL DEFAULT '{}',
                visited TEXT NOT NULL DEFAULT '[]',tutorial_seen INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS space_businesses(user_id INTEGER NOT NULL,business TEXT NOT NULL,
                quantity INTEGER NOT NULL,PRIMARY KEY(user_id,business))""",
            """CREATE TABLE IF NOT EXISTS planet_tiles(user_id INTEGER NOT NULL,planet TEXT NOT NULL,
                x INTEGER NOT NULL,y INTEGER NOT NULL,level INTEGER NOT NULL,
                PRIMARY KEY(user_id,planet,x,y))"""
        ]:conn.execute(statement)
        conn.execute('INSERT INTO schema_migrations VALUES(15,?)',(int(time.time()),))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()


def db():return core['get_db']()


def agency_level(conn, uid):return core['sum_levels'](conn, uid, 'space_agency')


def unlocked(conn, uid):
    return 'spaceflight' in core['user_research'](conn, uid) and agency_level(conn, uid)>0


def ensure_program(conn, uid, timestamp):
    conn.execute('INSERT OR IGNORE INTO space_program(user_id,collected,last_mined) VALUES(?,?,?)',(uid,timestamp,timestamp))
    return dict(conn.execute('SELECT * FROM space_program WHERE user_id=?',(uid,)).fetchone())


def resource_at(planet, x, y):
    # Same deterministic map for every player, independent of Python hash seeds.
    offset=list(SPACE_PLANETS).index(planet)
    return ('steel','gems','uranium','iridium')[(x*7+y*11+offset)%4]


def income(conn, uid):
    totals={}
    for row in conn.execute('SELECT business,quantity FROM space_businesses WHERE user_id=?',(uid,)):
        for key,rate in SPACE_BUSINESSES[row['business']]['production'].items():
            totals[key]=totals.get(key,0)+rate*row['quantity']
    return totals


def collect_space(conn, uid, timestamp=None, force=False):
    timestamp=int(time.time()) if timestamp is None else timestamp
    row=conn.execute('SELECT * FROM space_program WHERE user_id=?',(uid,)).fetchone()
    if not row:return
    program=dict(row)
    elapsed=timestamp-program['collected']
    interval=0 if force else SPACE_COLLECTION_INTERVAL
    if elapsed>0 and elapsed>=interval:
        minutes=min(MAX_ACCUM_MINS,elapsed/60)
        # Removing an agency pauses orbital income, without accumulating a backlog.
        if unlocked(conn,uid):
            for key,rate in income(conn,uid).items():
                conn.execute(f'UPDATE users SET {key}={key}+? WHERE id=?',(rate*minutes,uid))
        conn.execute('UPDATE space_program SET collected=? WHERE user_id=?',(timestamp,uid))
    if program['state']=='outbound' and timestamp>=program['arrival']:
        conn.execute("UPDATE space_program SET state='surface',last_mined=? WHERE user_id=?",(timestamp,uid))
        core['create_notification'](conn,uid,'info','Arrived at '+SPACE_PLANETS[program['planet']]['name']+'. Open Space to explore your personal map.')
    elif program['state']=='returning' and timestamp>=program['arrival']:
        cargo=json.loads(program['cargo']);visited=json.loads(program['visited'])
        for key,amount in cargo.items():
            if key=='iridium':conn.execute('UPDATE users SET money=money+? WHERE id=?',(amount*SPACE_IRIDIUM_PRICE,uid))
            else:conn.execute(f'UPDATE users SET {key}={key}+? WHERE id=?',(amount,uid))
        if program['planet'] not in visited:visited.append(program['planet'])
        conn.execute("UPDATE space_program SET state='earth',planet=NULL,arrival=0,cargo='{}',visited=?,last_mined=? WHERE user_id=?",(json.dumps(visited),timestamp,uid))
        core['create_notification'](conn,uid,'info',f'Returned to Earth. Cargo delivered; iridium sold for {cargo.get("iridium",0)*SPACE_IRIDIUM_PRICE:,.0f} money.')
    elif program['state']=='surface' and timestamp>program['last_mined'] and timestamp-program['last_mined']>=interval:
        cargo=json.loads(program['cargo']);production={}
        for tile in conn.execute('SELECT x,y,level FROM planet_tiles WHERE user_id=? AND planet=?',(uid,program['planet'])):
            key=resource_at(program['planet'],tile['x'],tile['y'])
            production[key]=production.get(key,0)+SPACE_RESOURCE_RATES[key]*tile['level']*SPACE_PLANETS[program['planet']]['yield_multiplier']
        minutes=min(MAX_ACCUM_MINS,(timestamp-program['last_mined'])/60)
        total=sum(production.values())*minutes
        available=max(0,SPACE_CARGO_CAPACITY-sum(cargo.values()))
        scale=min(1,available/total) if total else 0
        for key,rate in production.items():cargo[key]=cargo.get(key,0)+rate*minutes*scale
        conn.execute('UPDATE space_program SET cargo=?,last_mined=? WHERE user_id=?',(json.dumps(cargo),timestamp,uid))


def require_program(conn, uid):
    if not unlocked(conn,uid):raise ValueError('Research Spaceflight and build your own Space Agency first')
    return ensure_program(conn,uid,int(time.time()))


def status():
    conn=db();uid=session['user_id'];enabled=unlocked(conn,uid)
    if enabled:ensure_program(conn,uid,int(time.time()))
    collect_space(conn,uid)
    row=conn.execute('SELECT * FROM space_program WHERE user_id=?',(uid,)).fetchone()
    program=dict(row) if row else None
    if program:
        for key in ('cargo','visited'):program[key]=json.loads(program[key])
        program['remaining_seconds']=max(0,program['arrival']-int(time.time()))
    level=agency_level(conn,uid);visited=program['visited'] if program else []
    planets=[]
    for key,definition in SPACE_PLANETS.items():
        reason=''
        if definition['previous'] and definition['previous'] not in visited:reason='Return from '+SPACE_PLANETS[definition['previous']]['name']+' first'
        elif level<definition['agency_level']:reason=f'Need {definition["agency_level"]} Space Agency levels'
        planets.append(dict(key=key,**definition,available=enabled and not reason,lock_reason=reason))
    holdings={r['business']:r['quantity'] for r in conn.execute('SELECT * FROM space_businesses WHERE user_id=?',(uid,))}
    tiles=[]
    if program and program['planet']:
        built={(r['x'],r['y']):r['level'] for r in conn.execute('SELECT * FROM planet_tiles WHERE user_id=? AND planet=?',(uid,program['planet']))}
        for y in range(SPACE_GRID_SIZE):
            for x in range(SPACE_GRID_SIZE):
                level=built.get((x,y),0);resource=resource_at(program['planet'],x,y)
                adjacent=not built and (x,y)==(SPACE_GRID_SIZE//2,SPACE_GRID_SIZE//2) or any((x+dx,y+dy) in built for dx,dy in ((0,1),(1,0),(0,-1),(-1,0)))
                cost={k:v*2**level for k,v in SPACE_MINE_COST.items()}
                tiles.append(dict(x=x,y=y,resource=resource,level=level,can_build=bool(adjacent or level),cost=cost,
                    rate=SPACE_RESOURCE_RATES[resource]*max(1,level)*SPACE_PLANETS[program['planet']]['yield_multiplier']))
    return jsonify(unlocked=enabled,program=program,planets=planets,tiles=tiles,businesses=SPACE_BUSINESSES,holdings=holdings,
        income=income(conn,uid) if enabled else {},grid_size=SPACE_GRID_SIZE,cargo_capacity=SPACE_CARGO_CAPACITY,
        iridium_price=SPACE_IRIDIUM_PRICE,mine_max_level=SPACE_MINE_MAX_LEVEL,
        tutorial_required=bool(enabled and program and not program['tutorial_seen']))


def buy_business():
    conn=db();uid=session['user_id'];d=features.body();require_program(conn,uid);collect_space(conn,uid,force=True)
    key=d.get('business')
    if not isinstance(key,str) or key not in SPACE_BUSINESSES:raise ValueError('Unknown orbital business')
    quantity=features.integer(d.get('quantity'),1,2**53-1)
    held=conn.execute('SELECT quantity FROM space_businesses WHERE user_id=? AND business=?',(uid,key)).fetchone()
    if quantity+(held[0] if held else 0)>2**53-1:raise ValueError('Quantity exceeds safe numeric precision')
    cost={k:v*quantity for k,v in SPACE_BUSINESSES[key]['cost'].items()}
    user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not core['can_afford'](user,cost):raise ValueError('Need '+core['fmt_cost'](cost))
    core['pay'](conn,uid,cost)
    conn.execute('INSERT INTO space_businesses VALUES(?,?,?) ON CONFLICT(user_id,business) DO UPDATE SET quantity=quantity+excluded.quantity',(uid,key,quantity))
    return jsonify(success=True,message=f'Purchased {quantity:,} '+SPACE_BUSINESSES[key]['name'])


def depart():
    conn=db();uid=session['user_id'];d=features.body();program=require_program(conn,uid);collect_space(conn,uid,force=True)
    program=dict(conn.execute('SELECT * FROM space_program WHERE user_id=?',(uid,)).fetchone())
    key=d.get('planet')
    if not isinstance(key,str) or key not in SPACE_PLANETS:raise ValueError('Choose a planet')
    if program['state']!='earth':raise ValueError('Return to Earth before another expedition')
    planet=SPACE_PLANETS[key]
    if planet['previous'] and planet['previous'] not in json.loads(program['visited']):raise ValueError('Return from the previous planet first')
    if agency_level(conn,uid)<planet['agency_level']:raise ValueError('Upgrade your Space Agency first')
    cost={}
    for leg in ('outbound','return'):
        for resource,amount in planet[leg].items():cost[resource]=cost.get(resource,0)+amount
    user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not core['can_afford'](user,cost):raise ValueError('Round trip requires '+core['fmt_cost'](cost))
    core['pay'](conn,uid,cost);stamp=int(time.time())
    conn.execute("UPDATE space_program SET state='outbound',planet=?,arrival=?,cargo='{}',last_mined=? WHERE user_id=?",(key,stamp+planet['travel_seconds'],stamp,uid))
    return jsonify(success=True,message='Departed for '+planet['name']+'. Both travel legs are paid; open Space for arrival progress.')


def build_mine():
    conn=db();uid=session['user_id'];d=features.body();collect_space(conn,uid,force=True)
    program=conn.execute('SELECT * FROM space_program WHERE user_id=?',(uid,)).fetchone()
    if not program or program['state']!='surface':raise ValueError('Land on a planet to build mines')
    x=features.integer(d.get('x'),0,SPACE_GRID_SIZE-1);y=features.integer(d.get('y'),0,SPACE_GRID_SIZE-1)
    rows=conn.execute('SELECT x,y,level FROM planet_tiles WHERE user_id=? AND planet=?',(uid,program['planet'])).fetchall()
    built={(r['x'],r['y']):r['level'] for r in rows};level=built.get((x,y),0)
    if not level and not (not built and (x,y)==(SPACE_GRID_SIZE//2,SPACE_GRID_SIZE//2)) and not any((x+dx,y+dy) in built for dx,dy in ((0,1),(1,0),(0,-1),(-1,0))):raise ValueError('Start at the landing tile, then expand to neighboring tiles')
    if level>=SPACE_MINE_MAX_LEVEL:raise ValueError('Mine is already at its highest tier')
    cost={k:v*2**level for k,v in SPACE_MINE_COST.items()};user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not core['can_afford'](user,cost):raise ValueError('Need '+core['fmt_cost'](cost))
    core['pay'](conn,uid,cost)
    conn.execute('INSERT INTO planet_tiles VALUES(?,?,?,?,?) ON CONFLICT(user_id,planet,x,y) DO UPDATE SET level=excluded.level',(uid,program['planet'],x,y,level+1))
    return jsonify(success=True,message=f'Mine built at {x+1}, {y+1}. Mining runs while you are on the surface.')


def return_home():
    conn=db();uid=session['user_id'];collect_space(conn,uid,force=True)
    program=conn.execute('SELECT * FROM space_program WHERE user_id=?',(uid,)).fetchone()
    if not program or program['state']!='surface':raise ValueError('Land on a planet before returning')
    conn.execute("UPDATE space_program SET state='returning',arrival=?,last_mined=? WHERE user_id=?",(int(time.time())+SPACE_PLANETS[program['planet']]['travel_seconds'],int(time.time()),uid))
    return jsonify(success=True,message='Returning to Earth. Travel is prepaid; cargo is delivered once on arrival.')


def tutorial_seen():
    conn=db();uid=session['user_id'];require_program(conn,uid)
    conn.execute('UPDATE space_program SET tutorial_seen=1 WHERE user_id=?',(uid,))
    return jsonify(success=True)


def install(namespace):
    global core
    core=namespace;app=core['app'];original=core['auto_collect']
    def auto_collect(uid,conn):
        original(uid,conn);collect_space(conn,uid)
    core['auto_collect']=auto_collect
    @app.after_request
    def include_orbital_income(response):
        uid=session.get('user_id')
        if request.path!='/api/income' or response.status_code!=200 or not uid:return response
        conn=db()
        if not unlocked(conn,uid):return response
        payload=response.get_json();rates=income(conn,uid)
        payload['orbital_rates']=rates
        for key,rate in rates.items():
            payload['rates'][key]=payload['rates'].get(key,0)+rate
            payload['totals'][key]=payload['totals'].get(key,0)+rate*payload['minutes']
            payload['value_per_min']+=rate*core['RATE_VAL'][key]
        response.set_data(json.dumps(payload));return response
    for path,method,fn in [('/api/space','GET',status),('/api/space/business','POST',buy_business),('/api/space/depart','POST',depart),
            ('/api/space/mine','POST',build_mine),('/api/space/return','POST',return_home),('/api/space/tutorial/seen','POST',tutorial_seen)]:
        app.add_url_rule(path,'space_'+fn.__name__,core['require_login'](fn),methods=[method])
