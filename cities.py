"""Offline city geography and capital districts. All effects are server-authoritative."""
import json,time
from functools import lru_cache
from pathlib import Path
from flask import jsonify,request,session,send_file
import features

ROOT=Path(__file__).resolve().parent
MAX_LEVEL=10
DISTRICTS={
 'civic_center':dict(name='Capital civic centre',icon='🏛',desc='+15% capital production per level.',cost={'money':25000,'wood':1500,'metal':500},production_bonus=.15),
 'royal_treasury':dict(name='Sovereign treasury',icon='🏦',desc='+1,800 money/min per level before tile multipliers.',cost={'money':100000,'metal':1500,'steel':200},production={'money':1800}),
 'military_academy':dict(name='Grand military academy',icon='🎖',desc='+60 troops/min per level before tile multipliers.',cost={'money':150000,'metal':3000,'steel':500},troops=60),
 'capital_industry':dict(name='Strategic industrial district',icon='🏭',desc='+180 metal and +60 steel/min per level before tile multipliers.',cost={'money':500000,'metal':5000,'steel':2000},production={'metal':180,'steel':60}),
 'command_bunker':dict(name='National command bunker',icon='🛡',desc='+12% local defense per level, added to district defense.',cost={'money':250000,'metal':5000,'steel':1500},defense=.12),
 'imperial_guard':dict(name='Capital guard headquarters',icon='⚔',desc='+30 troops/min and +6% local defense per level.',cost={'money':300000,'food':5000,'steel':1000},troops=30,defense=.06),
}

@lru_cache(maxsize=1)
def catalog():
    data=json.loads((ROOT/'data/major-cities.json').read_text(encoding='utf-8'))
    if data['grid']!=features.GRID:raise RuntimeError('Rebuild the city registry for this grid size')
    return data

@lru_cache(maxsize=1)
def city_index():
    out={}
    for city in catalog()['cities']:
        if city['playable']:out.setdefault(city['grid_key'],[]).append(city)
    return out

def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=23').fetchone():conn.commit();return
        conn.execute('''CREATE TABLE IF NOT EXISTS capital_districts(grid_key TEXT NOT NULL,type TEXT NOT NULL,level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 10),PRIMARY KEY(grid_key,type))''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS capital_district_territory_deleted AFTER DELETE ON territories BEGIN DELETE FROM capital_districts WHERE grid_key=OLD.grid_key; END''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS capital_district_abandoned AFTER UPDATE OF owner_id ON territories WHEN NEW.owner_id IS NULL BEGIN DELETE FROM capital_districts WHERE grid_key=NEW.grid_key; END''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS capital_district_changed AFTER INSERT ON capital_districts BEGIN INSERT INTO map_changes(grid_key) VALUES(NEW.grid_key); END''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS capital_district_upgraded AFTER UPDATE ON capital_districts BEGIN INSERT INTO map_changes(grid_key) VALUES(NEW.grid_key); END''')
        conn.execute('INSERT INTO schema_migrations VALUES(23,?)',(int(time.time()),));conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

def capital_context(conn,uid):
    row=conn.execute('SELECT u.capital_key FROM users u JOIN territories t ON t.grid_key=u.capital_key AND t.owner_id=u.id WHERE u.id=?',(uid,)).fetchone()
    key=row[0] if row else None
    return {'key':key,'districts':{r['type']:r['level'] for r in conn.execute('SELECT type,level FROM capital_districts WHERE grid_key=?',(key,))} if key else {}}

def bonuses(key,capital=None):
    city=key in city_index();active=bool(key and capital and key==capital['key']);levels=capital['districts'] if active else {}
    production=(1.5 if city else 1)*(2 if active else 1)*(1+sum(DISTRICTS.get(k,{}).get('production_bonus',0)*v for k,v in levels.items()))
    recruitment=(1.5 if city else 1)*(2 if active else 1)
    defense=(1.25 if city else 1)*(1.75 if active else 1)*(1+sum(DISTRICTS.get(k,{}).get('defense',0)*v for k,v in levels.items()))
    return dict(production=production,recruitment=recruitment,defense=defense,base_troops=12 if active else 0,districts=levels)

def production(context,key):return bonuses(key,context.get('capital'))

def troops(context,key,bt,bl,buildings):
    b=production(context,key)
    amount=buildings.get(bt,{}).get('troops_per_level',0)*(bl or 0)+b['base_troops']
    amount+=sum(DISTRICTS.get(k,{}).get('troops',0)*v for k,v in b['districts'].items())
    return amount*b['recruitment']

def district_cost(kind,level):return {key:round(value*2.3**(level-1)) for key,value in DISTRICTS[kind]['cost'].items()}

def install(core):
    app=core['app']
    @app.get('/api/cities')
    def city_catalog():
        return send_file(ROOT/'data/major-cities.json',mimetype='application/json',max_age=86400,conditional=True)

    @app.get('/api/cities.csv')
    def city_csv():
        return send_file(ROOT/'data/major-cities.csv',mimetype='text/csv',as_attachment=True,download_name='world-conquest-major-cities.csv',max_age=86400,conditional=True)

    @app.get('/api/capital')
    @core['require_login']
    def capital_status():
        conn=features.db();uid=session['user_id'];capital=capital_context(conn,uid);key=capital['key']
        owned={r[0] for r in conn.execute('SELECT grid_key FROM territories WHERE owner_id=?',(uid,))}
        city_tiles=owned & city_index().keys()
        return jsonify(grid_key=key,bonuses=bonuses(key,capital),cities=city_index().get(key,[]),max_level=MAX_LEVEL,
            owned_city_tiles=len(city_tiles),owned_cities=sum(len(city_index()[k]) for k in city_tiles),
            districts=[dict(key=k,**d,level=capital['districts'].get(k,0),next_cost=district_cost(k,capital['districts'].get(k,0)+1) if capital['districts'].get(k,0)<MAX_LEVEL else None) for k,d in DISTRICTS.items()],
            move_cooldown=max(0,int(conn.execute('SELECT capital_ts FROM users WHERE id=?',(uid,)).fetchone()[0]+86400-time.time())) if key else 0)

    @app.post('/api/capital/district')
    @core['require_login']
    def upgrade_district():
        data=features.body();kind=data.get('type');key=data.get('grid_key')
        if not isinstance(kind,str) or kind not in DISTRICTS:raise ValueError('Choose a capital district')
        conn=features.db();uid=session['user_id'];capital=capital_context(conn,uid)
        if not key or key!=capital['key']:return jsonify(error='Choose your current, owned capital'),403
        # Settle at old rates before applying an upgrade. Existing request transactions
        # serialize concurrent upgrades, affordability and deductions.
        core['auto_collect'](uid,conn,force=True)
        if capital_context(conn,uid)['key']!=key:return jsonify(error='Your capital changed during production settlement; refresh'),409
        level=capital['districts'].get(kind,0)
        if level>=MAX_LEVEL:raise ValueError('District is already at maximum level')
        cost=district_cost(kind,level+1);user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not core['can_afford'](user,cost):return jsonify(error='Need '+core['fmt_cost'](cost)),400
        core['pay'](conn,uid,cost)
        conn.execute('INSERT INTO capital_districts VALUES(?,?,1) ON CONFLICT(grid_key,type) DO UPDATE SET level=level+1',(key,kind))
        return jsonify(success=True,message=f"{DISTRICTS[kind]['name']} upgraded to level {level+1}")
