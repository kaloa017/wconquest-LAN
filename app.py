"""
World Conquest v6 — Persistent Multiplayer Strategy Game
Run:  pip install -r requirements.txt && python app.py
Open: http://localhost:5055
Host setup: python manage.py create-admin --username USERNAME
"""

from flask import Flask, request, jsonify, session, send_file
from config import *
from runtime import connect_db, initialize_security
from werkzeug.security import generate_password_hash, check_password_hash
import hmac
import sqlite3, hashlib, random, time, os, json, math
import urllib.request, threading, queue

# ── Spectator tracking ────────────────────────────────────────────────────────
_spectators = {}   # ip -> {flag, country, last_seen}
_geo_cache  = {}   # ip -> {flag, country}  — persists for process lifetime
_geo_queue  = queue.Queue(maxsize=MAX_TRACKED_CLIENTS)   # IPs to geo-lookup, processed by one background thread

_spectator_lock = threading.RLock()
_geo_pending = set()

def _country_flag(code):
    if not code or len(code) != 2: return '🌐'
    try: return chr(0x1F1E6+ord(code[0].upper())-65)+chr(0x1F1E6+ord(code[1].upper())-65)
    except: return '🌐'

def _geo_worker():
    """Bounded, deduplicated lookups; shared dictionaries are lock protected."""
    while True:
        ip = _geo_queue.get()
        try:
            if ip in ('127.0.0.1', '::1', ''):
                geo = {'flag':'🖥','country':'Localhost','city':''}
            else:
                try:
                    url = f'http://ip-api.com/json/{ip}?fields=countryCode,country,city,status'
                    with urllib.request.urlopen(url, timeout=4) as r:data = json.loads(r.read())
                    geo = {'flag':_country_flag(data['countryCode']), 'country':data.get('country','?'), 'city':data.get('city','')} if data.get('status') == 'success' else {'flag':'🌐','country':'Unknown'}
                except Exception:geo = {'flag':'🌐','country':'Unknown'}
            with _spectator_lock:
                _geo_cache[ip] = geo
                while len(_geo_cache)>MAX_TRACKED_CLIENTS:_geo_cache.pop(next(iter(_geo_cache)))
        finally:
            with _spectator_lock:_geo_pending.discard(ip)
            _geo_queue.task_done()

_geo_thread = threading.Thread(target=_geo_worker, daemon=True)
_geo_thread.start()

def _touch_spectator(ip):
    """Record presence and enqueue at most one pending lookup per IP."""
    with _spectator_lock:
        if ip not in _spectators:
            while len(_spectators)>=MAX_TRACKED_CLIENTS:_spectators.pop(next(iter(_spectators)))
        geo = _geo_cache.get(ip, {'flag':'🌐','country':'?'})
        _spectators[ip] = {**geo, 'last_seen':time.time()}
        if os.getenv('ENABLE_IP_GEOLOOKUP')=='1' and ip not in _geo_cache and ip not in _geo_pending:
            try:_geo_queue.put_nowait(ip);_geo_pending.add(ip)
            except queue.Full:pass

app = Flask(__name__)
initialize_security(app)

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'game.db'))

# ── Game Constants ────────────────────────────────────────────────────────────

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return connect_db(DB_PATH)

def init_db():
    conn = get_db(); c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT UNIQUE NOT NULL COLLATE NOCASE,
        password    TEXT NOT NULL,
        is_admin    INTEGER DEFAULT 0,
        is_banned   INTEGER DEFAULT 0,
        reset_pin   TEXT DEFAULT NULL,
        research    TEXT DEFAULT '[]',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
        last_seen   INTEGER DEFAULT 0,
        last_claim  INTEGER DEFAULT 0,
        food        REAL DEFAULT 100,
        wood        REAL DEFAULT 100,
        metal       REAL DEFAULT 100,
        oil         REAL DEFAULT 25,
        money       REAL DEFAULT 200,
        color       TEXT DEFAULT '#e74c3c'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS territories (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        grid_key       TEXT UNIQUE NOT NULL,
        owner_id       INTEGER REFERENCES users(id),
        terrain        TEXT NOT NULL,
        garrison       INTEGER DEFAULT 0,
        boats          INTEGER DEFAULT 0,
        planes         INTEGER DEFAULT 0,
        population     INTEGER DEFAULT 0,
        last_collected INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        message    TEXT NOT NULL,
        image_url  TEXT DEFAULT NULL,
        author     TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS battle_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        attacker   TEXT NOT NULL,
        defender   TEXT NOT NULL,
        grid_key   TEXT NOT NULL,
        result     TEXT NOT NULL,
        mode       TEXT DEFAULT 'land',
        details    TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS game_settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id),
        type       TEXT NOT NULL,
        message    TEXT NOT NULL,
        data       TEXT DEFAULT '{}',
        is_read    INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS alliances (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER NOT NULL REFERENCES users(id),
        target_id    INTEGER NOT NULL REFERENCES users(id),
        status       TEXT DEFAULT 'pending',
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(requester_id, target_id)
    )''')

    c.execute('''INSERT OR IGNORE INTO announcements (id,message,author)
                 VALUES (1,'🌍 Welcome to World Conquest! Claim your first territory to begin.','System')''')

    conn.commit(); conn.close()

# ── Pure helpers ──────────────────────────────────────────────────────────────

def simple_hash(glat, glng):
    s = f"{glat},{glng}"; h = 0
    for ch in s: h = (h*31 + ord(ch)) % 10007
    return h

def get_terrain(glat, glng):
    h = simple_hash(glat, glng); lat = glat * GRID
    if lat <= -60 or abs(lat) > 65: return 'tundra'
    elif abs(lat) > 55:    opts=['tundra','tundra','forest','mountains','plains']
    elif abs(lat) > 40:    opts=['plains','plains','forest','forest','mountains','city']
    elif abs(lat) > 20:    opts=['plains','desert','desert','mountains','city','oil','forest']
    else:                  opts=['tropical','tropical','forest','plains','desert','city','oil']
    return opts[h % len(opts)]

def get_population(terrain, glat, glng):
    h = simple_hash(glat, glng)
    return POP_BASE[terrain] + (h % POP_RANGE[terrain])

def parse_key(k):
    if isinstance(k,str) and k.startswith('island:'):
        from geography import island_grid
        return island_grid(k)
    if not isinstance(k, str) or not re.fullmatch(r'-?\d+,-?\d+', k): raise ValueError('Invalid grid key')
    a, b = map(int, k.split(','))
    if k != f'{a},{b}' or not (-473 <= a <= 472 and -1000 <= b <= 999): raise ValueError('Grid outside world bounds')
    return a, b

def adj_keys(gl, gg):
    from geography import island_neighbors
    return [f"{gl+dl},{gg+dg}" for dl in (-1,0,1) for dg in (-1,0,1) if dl or dg]+island_neighbors(gl,gg)

def cell_distance(k1, k2):
    """Chebyshev distance between two grid keys."""
    a, b = parse_key(k1); c, d = parse_key(k2)
    return max(abs(a-c), abs(b-d))

def get_rank(tc):
    r = RANKS[0]
    for threshold, icon, name in RANKS:
        if tc >= threshold: r = (threshold, icon, name)
    return {'icon': r[1], 'name': r[2]}

def ph(pw):
    return generate_password_hash(pw)

def password_matches(stored, password):
    if stored and len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
        return hmac.compare_digest(stored, hashlib.sha256(password.encode()).hexdigest())
    return bool(stored and check_password_hash(stored, password))

def get_setting(conn, key, default=None):
    row = conn.execute('SELECT value FROM game_settings WHERE key=?',(key,)).fetchone()
    return row['value'] if row else default

def set_setting(conn, key, value):
    conn.execute('INSERT OR REPLACE INTO game_settings(key,value) VALUES(?,?)',(key,str(value)))

def are_allied(uid1, uid2, conn):
    """Return True if uid1 and uid2 have an active alliance."""
    row = conn.execute(
        "SELECT 1 FROM alliances WHERE status='active' AND "
        "((requester_id=? AND target_id=?) OR (requester_id=? AND target_id=?))",
        (uid1, uid2, uid2, uid1)
    ).fetchone()
    if row is not None: return True
    f = conn.execute('SELECT 1 FROM users a JOIN users b ON a.faction_id=b.faction_id '
                     'WHERE a.id=? AND b.id=? AND a.faction_id IS NOT NULL', (uid1, uid2)).fetchone()
    return f is not None

def create_notification(conn, user_id, ntype, message, data=None):
    conn.execute(
        'INSERT INTO notifications (user_id, type, message, data) VALUES (?,?,?,?)',
        (user_id, ntype, message, json.dumps(data or {}))
    )

# ── Research helpers ───────────────────────────────────────────────────────────

def user_research(conn, uid):
    row = conn.execute('SELECT research FROM users WHERE id=?',(uid,)).fetchone()
    try: return set(json.loads(row['research'] or '[]'))
    except: return set()

def res_mult(res_type, research):
    m = 1.0
    if res_type in ('food','wood') and 'agri' in research: m *= 1.25
    if res_type == 'money' and 'trade' in research: m *= 1.15
    if res_type in ('metal','oil') and 'industry' in research: m *= 1.25
    return m

def atk_mult(research):
    m = 1.0
    if 'iron' in research: m *= 1.20
    if 'gunpowder' in research: m *= 1.30
    return m

def def_bonus(research):
    b = 1.25
    if 'castle' in research: b *= 1.30
    return b

def troop_cost(research):
    c = TROOP_COST
    if 'gunpowder' in research: c = max(1, int(c * 0.75))  # 25% discount
    return c

# ── Banning / auth ────────────────────────────────────────────────────────────

def touch_last_seen(uid):
    try:
        conn = get_db()
        conn.execute('UPDATE users SET last_seen=? WHERE id=?',(int(time.time()),uid))
        conn.commit(); conn.close()
    except: pass

def require_login(f):
    from functools import wraps
    @wraps(f)
    def wrap(*a, **kw):
        if 'user_id' not in session:
            return jsonify({'error':'Not authenticated'}),401
        conn = get_db()
        u = conn.execute('SELECT is_banned FROM users WHERE id=?',(session['user_id'],)).fetchone()
        conn.close()
        if not u:
            session.clear()
            return jsonify({'error':'Account not found'}),401
        if u['is_banned']:
            session.clear()
            return jsonify({'error':'🚫 Your account has been banned'}),403
        touch_last_seen(session['user_id'])
        return f(*a, **kw)
    return wrap

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def wrap(*a, **kw):
        if 'user_id' not in session:
            return jsonify({'error':'Not authenticated'}),401
        conn = get_db()
        u = conn.execute('SELECT is_admin,is_banned FROM users WHERE id=?',(session['user_id'],)).fetchone()
        conn.close()
        if not u or u['is_banned']:
            session.clear()
            return jsonify({'error':'Banned or not found'}),403
        if not u['is_admin']:
            return jsonify({'error':'Admin required'}),403
        touch_last_seen(session['user_id'])
        return f(*a, **kw)
    return wrap

# ── Auto resource collection ──────────────────────────────────────────────────

# ── Static ────────────────────────────────────────────────────────────────────

@app.route('/')
def index(): return send_file('index.html')

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    d  = request.json or {}
    un = d.get('username','').strip()
    pw = d.get('password','')
    pin= d.get('reset_pin','').strip()
    if not un or not pw: return jsonify({'error':'Username and password required'}),400
    if len(un)<3 or len(un)>20: return jsonify({'error':'Username must be 3–20 characters'}),400
    if len(pw)<4: return jsonify({'error':'Password must be at least 4 characters'}),400
    if pin and (not pin.isdigit() or len(pin)<4 or len(pin)>8):
        return jsonify({'error':'Reset PIN must be 4–8 digits'}),400
    is_admin = 0
    color    = random.choice(PLAYER_COLORS)
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username,password,color,is_admin,reset_pin) VALUES (?,?,?,?,?)',
            (un, ph(pw), color, is_admin, pin or None)
        )
        conn.commit(); conn.close()
        msg = '✅ Account created!'
        if is_admin: msg += ' Admin privileges granted.'
        return jsonify({'success':True,'message':msg,'is_admin':bool(is_admin)})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error':'Username already taken — each name can only be registered once.'}),409

@app.route('/api/login', methods=['POST'])
def login():
    d  = request.json or {}
    un = d.get('username','')
    pw = d.get('password','')
    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE username=? COLLATE NOCASE AND password=?',(un, ph(pw))
    ).fetchone()
    conn.close()
    if not user: return jsonify({'error':'Invalid username or password'}),401
    if user['is_banned']:
        return jsonify({'error':'🚫 This account has been banned'}),403
    session['user_id']  = user['id']
    session['username'] = user['username']
    touch_last_seen(user['id'])
    return jsonify({'success':True,'user':{
        'id':user['id'],'username':user['username'],
        'is_admin':bool(user['is_admin']),'color':user['color']
    }})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success':True})

@app.route('/api/forgot_password', methods=['POST'])
def forgot_password():
    d   = request.json or {}
    un  = d.get('username','').strip()
    pin = d.get('reset_pin','').strip()
    pw  = d.get('new_password','')
    if not un or not pin or not pw:
        return jsonify({'error':'Username, PIN, and new password required'}),400
    if len(pw)<4:
        return jsonify({'error':'Password must be at least 4 characters'}),400
    conn = get_db()
    user = conn.execute(
        'SELECT id,reset_pin FROM users WHERE username=? COLLATE NOCASE',(un,)
    ).fetchone()
    if not user or not user['reset_pin']:
        conn.close()
        return jsonify({'error':'No reset PIN set for this account. Contact an admin.'}),404
    if user['reset_pin'] != pin:
        conn.close()
        return jsonify({'error':'Incorrect PIN'}),401
    conn.execute('UPDATE users SET password=? WHERE id=?',(ph(pw), user['id']))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Password reset successfully!'})

@app.route('/api/me')
@require_login
def me():
    conn = get_db()
    auto_collect(session['user_id'], conn); conn.commit()
    u  = conn.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
    tc = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?',(session['user_id'],)).fetchone()['c']
    pop= conn.execute('SELECT COALESCE(SUM(population),0) p FROM territories WHERE owner_id=?',(session['user_id'],)).fetchone()['p']
    rsch = list(json.loads(u['research'] or '[]'))
    rank = get_rank(tc)
    claim_ready_in = 0
    # Fetch active/pending alliances
    uid = session['user_id']
    ally_rows = conn.execute('''
        SELECT a.id, a.status,
               r.id r_id, r.username r_name, r.color r_color,
               t.id t_id, t.username t_name, t.color t_color
        FROM alliances a
        JOIN users r ON a.requester_id=r.id
        JOIN users t ON a.target_id=t.id
        WHERE (a.requester_id=? OR a.target_id=?) AND a.status IN ('active','pending')
    ''', (uid, uid)).fetchall()
    alliances = []
    for row in ally_rows:
        is_req    = (row['r_id'] == uid)
        ally_id   = row['t_id']    if is_req else row['r_id']
        ally_name = row['t_name']  if is_req else row['r_name']
        ally_col  = row['t_color'] if is_req else row['r_color']
        alliances.append({'id': row['id'], 'status': row['status'],
                          'ally_id': ally_id, 'ally_name': ally_name,
                          'ally_color': ally_col, 'is_requester': is_req})
    fac = None
    if u['faction_id']:
        f = conn.execute('SELECT id,name,tag,leader_id FROM factions WHERE id=?', (u['faction_id'],)).fetchone()
        if f: fac = {'id': f['id'], 'name': f['name'], 'tag': f['tag'], 'is_leader': f['leader_id'] == uid}
    conn_me = conn; ev_me = current_event(conn)
    conn.commit()
    resp = jsonify({
        'id':u['id'],'username':u['username'],
        'is_admin':bool(u['is_admin']),'color':u['color'],
        'food':round(u['food']),'wood':round(u['wood']),
        'metal':round(u['metal']),'oil':round(u['oil']),'money':round(u['money']),
        'territory_count':tc,'population':int(pop),
        'research':rsch,'rank':rank,
        'has_pin':bool(u['reset_pin']),
        'claim_ready_in': claim_ready_in,
        'alliances': alliances,
        'army': pool_get(conn_me, uid, 'army'), 'army_cap': None, 'boats': pool_get(conn_me, uid, 'boats'), 'planes': pool_get(conn_me, uid, 'planes'),
        'morale': u['morale'], 'wins': u['wins'], 'losses': u['losses'],
        'daily_ready': u['last_daily'] != int(time.time()//86400), 'daily_streak': u['daily_streak'],
        'event': ev_me, 'weather_slot': cur_slot(),
        'claim_cost': claim_price(conn_me, uid, 'plains')['money'],
        'boat_range': boat_range(conn_me, uid, set(rsch)), 'plane_range': plane_range(set(rsch)),
        'troop_cost': troop_cost_for(conn_me, uid, set(rsch)), **me_extra(conn_me, u, uid),
    })
    conn.close()
    return resp

# ── Profile ───────────────────────────────────────────────────────────────────

@app.route('/api/profile/change_password', methods=['POST'])
@require_login
def change_password():
    d    = request.json or {}
    curr = d.get('current_password','')
    new  = d.get('new_password','')
    if not curr or not new: return jsonify({'error':'Both passwords required'}),400
    if len(new)<4: return jsonify({'error':'New password must be at least 4 characters'}),400
    conn = get_db()
    u = conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if not password_matches(u['password'], curr):
        conn.close()
        return jsonify({'error':'Current password is incorrect'}),401
    conn.execute('UPDATE users SET password=? WHERE id=?',(ph(new), session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Password changed successfully!'})

@app.route('/api/profile/change_username', methods=['POST'])
@require_login
def change_username():
    d   = request.json or {}
    new = d.get('new_username','').strip()
    pw  = d.get('password','')
    if not new or not pw: return jsonify({'error':'New username and password required'}),400
    if not re.fullmatch(r'[\w .-]{3,20}', new): return jsonify({'error':'Username must be 3–20 characters'}),400
    conn = get_db()
    u = conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if not password_matches(u['password'], pw):
        conn.close()
        return jsonify({'error':'Incorrect password'}),401
    # Block auto-admin names for other users
    if new.lower() in AUTO_ADMIN_NAMES:
        existing = conn.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE',(new,)).fetchone()
        if existing and existing['id'] != session['user_id']:
            conn.close()
            return jsonify({'error':'Username taken'}),409
    try:
        conn.execute('UPDATE users SET username=? WHERE id=?',(new, session['user_id']))
        conn.commit(); conn.close()
        session['username'] = new
        return jsonify({'success':True,'message':f'Username changed to {new}!'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error':'Username already taken'}),409

@app.route('/api/profile/set_pin', methods=['POST'])
@require_login
def set_pin():
    d   = request.json or {}
    pin = d.get('pin','').strip()
    pw  = d.get('password','')
    if not pin or not pw: return jsonify({'error':'PIN and password required'}),400
    if not pin.isdigit() or len(pin)<4 or len(pin)>8:
        return jsonify({'error':'PIN must be 4–8 digits'}),400
    conn = get_db()
    u = conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if not password_matches(u['password'], pw):
        conn.close()
        return jsonify({'error':'Incorrect password'}),401
    conn.execute('UPDATE users SET reset_pin=? WHERE id=?',(pin, session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Recovery PIN set!'})

# ── Online players ────────────────────────────────────────────────────────────

@app.route('/api/spectate', methods=['POST'])
def spectate():
    """Called by guests to register their presence on the map."""
    ip = request.remote_addr or ''
    if ip:
        _touch_spectator(ip)  # fast: just dict update, geo is queued async
    return jsonify({'success': True})

@app.route('/api/online')
def online_users():
    cutoff = int(time.time()) - 180
    conn = get_db()
    rows = conn.execute('''
        SELECT u.username,u.color,u.is_admin,COUNT(t.id) territories
        FROM users u LEFT JOIN territories t ON t.owner_id=u.id
        WHERE u.last_seen>? AND u.is_banned=0
        GROUP BY u.id ORDER BY u.last_seen DESC
    ''',(cutoff,)).fetchall()
    conn.close()
    players = [{'username':r['username'],'color':r['color'],
                'is_admin':bool(r['is_admin']),'territories':r['territories'],
                'type':'player'} for r in rows]
    # Add active spectators (last 3 min, not logged-in players)
    player_ips = set()  # we don't track player IPs, just avoid double-count
    now = time.time()
    guests = []
    with _spectator_lock:spectators=list(_spectators.items())
    for ip, s in spectators:
        if now - s['last_seen'] < 180:
            guests.append({'username': f"{s['flag']} Guest", 'color':'#607090',
                           'is_admin':False,'territories':0,'type':'spectator',
                           'flag': s['flag'], 'country': s.get('country','?'),
                           'city': s.get('city','')})
    return jsonify(players + guests)

# ── Sell resources ────────────────────────────────────────────────────────────

@app.route('/api/resources/sell', methods=['POST'])
@require_login
def sell_resources():
    d  = request.json or {}
    rt = d.get('resource','')
    am = max(1, int(d.get('amount',1)))
    if rt not in SELL_RATES: return jsonify({'error':'Invalid resource'}),400
    conn = get_db()
    u = conn.execute(f'SELECT {rt} FROM users WHERE id=?',(session['user_id'],)).fetchone()
    have = int(u[rt])
    if have < am:
        conn.close()
        return jsonify({'error':f'Not enough {rt}. Have {have}, need {am}'}),400
    earned = am * SELL_RATES[rt]
    conn.execute(f'UPDATE users SET {rt}={rt}-?,money=money+? WHERE id=?',(am,earned,session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success':True,'earned':earned,'message':f'Sold {am} {rt} for {earned}💰'})

# ── Research ──────────────────────────────────────────────────────────────────

@app.route('/api/research')
@require_login
def get_research():
    conn = get_db()
    rsch = user_research(conn, session['user_id'])
    conn.close()
    return jsonify({'research': list(rsch), 'tree': RESEARCH_TREE})

@app.route('/api/research/unlock', methods=['POST'])
@require_login
def unlock_research():
    d    = request.json or {}
    tech = d.get('tech','')
    if tech not in RESEARCH_TREE:
        return jsonify({'error':'Unknown technology'}),400
    info = RESEARCH_TREE[tech]
    conn = get_db()
    rsch = user_research(conn, session['user_id'])
    if tech in rsch:
        conn.close()
        return jsonify({'error':'Already researched'}),400
    for req in info['requires']:
        if req not in rsch:
            conn.close()
            return jsonify({'error':f'Requires {RESEARCH_TREE[req]["name"]} first'}),400
    u = conn.execute('SELECT money FROM users WHERE id=?',(session['user_id'],)).fetchone()
    disc = research_discount(conn, session['user_id'])
    info = {**info, 'cost': int(info['cost']*(1-disc))}
    if u['money'] < info['cost']:
        conn.close()
        return jsonify({'error':f'Need {info["cost"]}💰, have {round(u["money"])}💰'}),400
    rsch.add(tech)
    conn.execute('UPDATE users SET research=?,money=money-? WHERE id=?',
                 (json.dumps(list(rsch)), info['cost'], session['user_id']))
    award_achievements(conn, session['user_id'])
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':f'Researched {info["name"]}!'})

# ── Territories ───────────────────────────────────────────────────────────────

@app.route('/api/territories')
def get_territories():
    conn = get_db(); am = _army_map(conn)
    rows = conn.execute('''
        SELECT t.grid_key,t.owner_id,t.terrain,t.population,u.username,u.color,u.faction_id,u.capital_key,
               b.type bt,b.level bl,f.tag ftag
        FROM territories t LEFT JOIN users u ON t.owner_id=u.id
        LEFT JOIN buildings b ON b.grid_key=t.grid_key LEFT JOIN factions f ON f.id=u.faction_id
        WHERE t.owner_id IS NOT NULL
    ''').fetchall()
    water = [r['grid_key'] for r in conn.execute('SELECT grid_key FROM water_cells WHERE is_water=1')]
    conn.close()
    out = []
    for r in rows:
        a, n = am.get(r['owner_id'], (0, 1))
        out.append({'grid_key':r['grid_key'],'owner_id':r['owner_id'],'owner':r['username'],'color':r['color'] or '#888',
                    'terrain':r['terrain'],'garrison':int(a/(n**0.55)+3),'boats':0,'planes':0,'population':r['population'],
                    'building':r['bt'],'blevel':r['bl'],'tag':r['ftag'],'capital':r['capital_key']==r['grid_key']})
    resp = jsonify(out); return resp

@app.route('/api/water/all')
def water_all():
    conn = get_db(); w = [r['grid_key'] for r in conn.execute('SELECT grid_key FROM water_cells WHERE is_water=1')]; conn.close()
    return jsonify(w)

@app.route('/api/territory/<path:grid_key>')
def territory_detail(grid_key):
    conn = get_db()
    row  = conn.execute('''
        SELECT t.*,u.username,u.color,b.type bt,b.level bl FROM territories t
        LEFT JOIN users u ON t.owner_id=u.id LEFT JOIN buildings b ON b.grid_key=t.grid_key WHERE t.grid_key=?
    ''',(grid_key,)).fetchone()
    try: gl, gg = parse_key(grid_key)
    except Exception: conn.close(); return jsonify({'error':'Invalid grid key'}),400
    coastal = is_coastal(conn, grid_key); water = is_water(conn, grid_key)
    wx = weather_for(cur_slot(), gl, gg)
    if row:
        d = defense_of(conn, row['owner_id'], grid_key, row['terrain']) if row['owner_id'] else None
        out = {'grid_key':row['grid_key'],'owner_id':row['owner_id'],'owner':row['username'],'color':row['color'],
               'terrain':row['terrain'],'garrison':int(d['base']) if d else 0,'boats':0,'planes':0,'population':row['population'],
               'last_collected':row['last_collected'],'building':row['bt'],'blevel':row['bl']}
    else:
        terrain = get_terrain(gl, gg)
        out = {'grid_key':grid_key,'owner_id':None,'owner':None,'terrain':terrain,'garrison':0,'boats':0,'planes':0,
               'population':get_population(terrain, gl, gg),'last_collected':0,'building':None,'blevel':None}
    out.update({'coastal': coastal, 'water': water, 'weather': wx, **detail_extra(conn, grid_key, row)})
    if grid_key.startswith('island:'):
        from geography import island_feature
        from features import island_legacy_owner
        out.update(island_name=island_feature(grid_key)['properties']['name'],legacy_tile=island_legacy_owner(conn,grid_key))
    conn.close(); return jsonify(out)

# ══════════════════════════════════════════════════════════════════════════════
#  v4 — national army, modifiers, buildings, factions, chat, events, daily, quests
# ══════════════════════════════════════════════════════════════════════════════

# weather — deterministic per 10-minute slot + region, so server & clients agree with zero network load

def weather_for(slot, gl, gg):
    lat = abs(gl*GRID)
    band = 'polar' if lat > 55 else 'temperate' if lat > 25 else 'tropical'
    rx, ry = gl//25, gg//25
    h = ((slot*73856093) ^ (rx*19349663) ^ (ry*83492791)) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1274126177) & 0xFFFFFFFF
    h = (h ^ (h >> 16)) % 100
    acc = 0
    for name, w in WEATHER_TABLE[band]:
        acc += w
        if h < acc: return name
    return 'clear'
def cur_slot(): return int(time.time() // 600)

def migrate_v4():
    conn = get_db(); c = conn.cursor()
    def cols(t): return {r['name'] for r in c.execute(f'PRAGMA table_info({t})')}
    ucols = cols('users')
    fresh_army = 'army' not in ucols
    for name, ddl in [('army','INTEGER DEFAULT 10'),('boats','INTEGER DEFAULT 0'),('planes','INTEGER DEFAULT 0'),
                      ('morale','INTEGER DEFAULT 50'),('streak','INTEGER DEFAULT 0'),('wins','INTEGER DEFAULT 0'),
                      ('losses','INTEGER DEFAULT 0'),('faction_id','INTEGER DEFAULT NULL'),('muted_until','INTEGER DEFAULT 0'),
                      ('last_daily','INTEGER DEFAULT 0'),('daily_streak','INTEGER DEFAULT 0'),('chat_count','INTEGER DEFAULT 0')]:
        if name not in ucols: c.execute(f'ALTER TABLE users ADD COLUMN {name} {ddl}')
    if fresh_army:  # carry old per-tile forces into the new national pools
        c.execute('UPDATE users SET army=10+COALESCE((SELECT SUM(garrison) FROM territories WHERE owner_id=users.id),0),'
                  'boats=COALESCE((SELECT SUM(boats) FROM territories WHERE owner_id=users.id),0)/3,'
                  'planes=COALESCE((SELECT SUM(planes) FROM territories WHERE owner_id=users.id),0)/2')
    c.executescript('''
      CREATE TABLE IF NOT EXISTS buildings(grid_key TEXT PRIMARY KEY, type TEXT NOT NULL, level INTEGER DEFAULT 1);
      CREATE TABLE IF NOT EXISTS water_cells(grid_key TEXT PRIMARY KEY, is_water INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS factions(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE,
        tag TEXT UNIQUE NOT NULL COLLATE NOCASE, leader_id INTEGER, treasury REAL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, user_id INTEGER,
        username TEXT, color TEXT, message TEXT NOT NULL, ts INTEGER);
      CREATE INDEX IF NOT EXISTS chat_ch ON chat(channel,id);
      CREATE TABLE IF NOT EXISTS achievements(user_id INTEGER, key TEXT, ts INTEGER, PRIMARY KEY(user_id,key));
    ''')
    conn.commit(); conn.close()

# ── helpers ──────────────────────────────────────────────────────────────────
def ingest_water(conn, water):
    """Client reports which cells are open water (first report wins; admin can override)."""
    if not isinstance(water, dict): return
    for k, v in list(water.items())[:60]:
        try: parse_key(k)
        except Exception: continue
        conn.execute('INSERT OR IGNORE INTO water_cells(grid_key,is_water) VALUES(?,?)', (k, 1 if v else 0))

def is_water(conn, k):
    r = conn.execute('SELECT is_water FROM water_cells WHERE grid_key=?', (k,)).fetchone()
    return bool(r and r['is_water'])

def is_coastal(conn, k):
    gl, gg = parse_key(k); ak = adj_keys(gl, gg)
    r = conn.execute(f'SELECT 1 FROM water_cells WHERE is_water=1 AND grid_key IN ({",".join("?"*len(ak))}) LIMIT 1', ak).fetchone()
    return r is not None

def current_event(conn):
    raw = get_setting(conn, 'event')
    now = int(time.time())
    ev = None
    if raw:
        try: ev = json.loads(raw)
        except Exception: ev = None
    if ev and ev.get('until', 0) > now: return ev
    # Event creation belongs to serialized gameplay/scheduler transactions.
    from flask import has_request_context
    if has_request_context() and request.method=='GET' and not conn.in_transaction:return None
    nxt = int(get_setting(conn, 'event_next', 0) or 0)
    if ev and ev.get('until', 0) <= now and nxt < ev['until'] + EVENT_GAP:
        nxt = ev['until'] + EVENT_GAP; set_setting(conn, 'event_next', nxt)
    if now >= nxt and get_setting(conn, 'events_enabled', '1') == '1':
        t = random.choice(list(EVENTS))
        ev = {'type': t, 'until': now + EVENT_LEN, **EVENTS[t]}
        set_setting(conn, 'event', json.dumps(ev)); set_setting(conn, 'event_next', now + EVENT_LEN + EVENT_GAP)
        return ev
    return None

def ev_type(conn):
    e = current_event(conn); return e['type'] if e else None

def faction_members(conn, fid):
    return conn.execute('SELECT COUNT(*) c FROM users WHERE faction_id=?', (fid,)).fetchone()['c'] if fid else 0

def faction_bonus(conn, uid):
    r = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    if not r or not r['faction_id']: return 1.0
    return 1.0 + min(0.15, 0.02*(faction_members(conn, r['faction_id'])-1))

def sum_levels(conn, uid, btype):
    r = conn.execute('SELECT COALESCE(SUM(b.level),0) s FROM buildings b JOIN territories t ON t.grid_key=b.grid_key '
                     'WHERE t.owner_id=? AND b.type=?', (uid, btype)).fetchone()
    return r['s']

def claim_cost_for(mc, rsch):
    cost = 1200 if mc>=200 else 400 if mc>=100 else 150 if mc>=50 else 80 if mc>=20 else 40 if mc>=8 else CLAIM_COST
    return int(cost*0.8) if 'banking' in rsch else cost

def boat_range(conn, uid, rsch):
    return BOAT_RANGE_BASE + (2 if 'navigation' in rsch else 0)
def plane_range(rsch):
    return PLANE_RANGE_BASE + sum(value for tech,value in PLANE_RANGE_BONUSES.items() if tech in rsch)

def pay(conn, uid, cost):
    for k, v in cost.items(): conn.execute(f'UPDATE users SET {k}={k}-? WHERE id=?', (v, uid))

def prod(mods):
    p = 1.0
    for _, m in mods: p *= m
    return p

def battle_response(res, extra=None):
    d = {'success': True, 'attacker_wins': res['win'], 'result': 'victory' if res['win'] else 'defeat', 'message': res['msg'],
         'breakdown': {'attack': round(res['A'], 1), 'defense': round(res['D'], 1), 'weather': res['weather'],
                       'atk_mods': [[a, round(b, 2)] for a, b in res['amods']], 'def_mods': [[a, round(b, 2)] for a, b in res['dmods']]}}
    if extra: d.update(extra)
    return jsonify(d)

# ── Troops / army ───────────────────────────────────────────────────────────
@app.route('/api/troops/move', methods=['POST'])
@require_login
def move_troops():   # kept for compatibility: the army is national now
    return jsonify({'error': 'Your army is now one national force — no need to move troops!'}), 400

# ── Boats ───────────────────────────────────────────────────────────────────
# ── Planes ──────────────────────────────────────────────────────────────────
# ── Buildings ───────────────────────────────────────────────────────────────
@app.route('/api/building/demolish', methods=['POST'])
@require_login
def building_demolish():
    gk = (request.json or {}).get('grid_key', ''); conn = get_db()
    if not conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id=?', (gk, session['user_id'])).fetchone():
        conn.close(); return jsonify({'error': 'Not your territory'}), 403
    conn.execute('DELETE FROM buildings WHERE grid_key=?', (gk,)); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Building demolished'})

@app.route('/api/buildings')
def buildings_info():
    return jsonify({k: {**v, 'costs': [build_cost(k, i) for i in (1, 2, 3)]} for k, v in BUILDINGS.items()})

# ── Water report (client-detected coast) ────────────────────────────────────
@app.route('/api/water/report', methods=['POST'])
@require_login
def water_report():
    conn = get_db(); ingest_water(conn, (request.json or {}).get('water')); conn.commit(); conn.close()
    return jsonify({'success': True})

# ── Chat ────────────────────────────────────────────────────────────────────
def _channel(conn, uid, ch):
    if ch == 'global': return 'global'
    u = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    return f'f:{u["faction_id"]}' if u and u['faction_id'] else None

@app.route('/api/chat')
@require_login
def chat_get():
    ch = request.args.get('channel', 'global'); since = int(request.args.get('since', 0) or 0)
    conn = get_db(); key = _channel(conn, session['user_id'], ch)
    if not key: conn.close(); return jsonify({'messages': [], 'last_id': since, 'error': 'No faction'})
    if since: rows = conn.execute('SELECT c.*,u.is_donator,u.donator_title FROM chat c LEFT JOIN users u ON u.id=c.user_id WHERE c.channel=? AND c.id>? ORDER BY c.id LIMIT 100', (key, since)).fetchall()
    else: rows = list(reversed(conn.execute('SELECT c.*,u.is_donator,u.donator_title FROM chat c LEFT JOIN users u ON u.id=c.user_id WHERE c.channel=? ORDER BY c.id DESC LIMIT 60', (key,)).fetchall()))
    conn.close()
    msgs = [{'id': r['id'], 'user': r['username'], 'color': r['color'], 'text': r['message'], 'ts': r['ts'], 'uid': r['user_id'], 'edited': r['edited'],'is_donator':bool(r['is_donator']),'donator_title':r['donator_title']} for r in rows]
    return jsonify({'messages': msgs, 'last_id': msgs[-1]['id'] if msgs else since})

_last_chat = {}
@app.route('/api/chat/send', methods=['POST'])
@require_login
def chat_send():
    d = request.json or {}; uid = session['user_id']
    text = ' '.join((d.get('message') or '').split())[:200]
    if not text: return jsonify({'error': 'Empty message'}), 400
    if time.time() - _last_chat.get(uid, 0) < CHAT_COOLDOWN: return jsonify({'error': 'Slow down a little'}), 429
    conn = get_db(); u = conn.execute('SELECT username,color,muted_until FROM users WHERE id=?', (uid,)).fetchone()
    if u['muted_until'] > time.time(): conn.close(); return jsonify({'error': f'You are muted for {int((u["muted_until"]-time.time())//60)+1} more min'}), 403
    key = _channel(conn, uid, d.get('channel', 'global'))
    if not key: conn.close(); return jsonify({'error': 'Join a faction first'}), 400
    _last_chat[uid] = time.time()
    while len(_last_chat) > MAX_TRACKED_CLIENTS: _last_chat.pop(next(iter(_last_chat)))
    conn.execute('INSERT INTO chat(channel,user_id,username,color,message,ts) VALUES(?,?,?,?,?,?)', (key, uid, u['username'], u['color'], text, int(time.time())))
    conn.execute('UPDATE users SET chat_count=chat_count+1 WHERE id=?', (uid,))
    conn.execute('DELETE FROM chat WHERE id < (SELECT MAX(id)-1500 FROM chat)')
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'achievements': ach})

# ── Daily bonus & achievements ──────────────────────────────────────────────

@app.route('/api/achievements')
@require_login
def achievements_list():
    conn = get_db(); have = {r['key'] for r in conn.execute('SELECT key FROM achievements WHERE user_id=?', (session['user_id'],))}
    conn.close()
    return jsonify([{'key': k, **v, 'done': k in have} for k, v in ACHIEVEMENTS.items()])

@app.route('/api/weather')
def weather_api():  # optional helper: same as client's local computation
    lat = float(request.args.get('lat', 0)); lng = float(request.args.get('lng', 0))
    gl, gg = math.floor(lat/GRID), math.floor(lng/GRID)
    return jsonify({'weather': weather_for(cur_slot(), gl, gg), 'next_change_in': 600 - int(time.time() % 600)})

# ── Admin extras ────────────────────────────────────────────────────────────
@app.route('/api/admin/stats')
@require_admin
def admin_stats():
    conn = get_db(); q = lambda s: conn.execute(s).fetchone()[0]
    out = {'users': q('SELECT COUNT(*) FROM users'), 'territories': q('SELECT COUNT(*) FROM territories WHERE owner_id IS NOT NULL'),
           'battles': q('SELECT COUNT(*) FROM battle_log'), 'factions': q('SELECT COUNT(*) FROM factions'),
           'chat_msgs': q('SELECT COUNT(*) FROM chat'), 'buildings': q('SELECT COUNT(*) FROM buildings'),
           'total_army': q('SELECT COALESCE(SUM(army),0) FROM users'), 'event': current_event(conn),
           'settings': {'income_mult': get_setting(conn, 'income_mult', 1), 'troop_cost_mult': get_setting(conn, 'troop_cost_mult', 1),
                        'events_enabled': get_setting(conn, 'events_enabled', '1')}}
    conn.close(); return jsonify(out)

@app.route('/api/admin/event', methods=['POST'])
@require_admin
def admin_event():
    d = request.json or {}; conn = get_db(); t = d.get('type')
    if t == 'none':
        set_setting(conn, 'event', ''); set_setting(conn, 'event_next', int(time.time()) + EVENT_GAP)
    elif t in EVENTS:
        mins = max(1, min(int(d.get('minutes', 30)), 720))
        set_setting(conn, 'event', json.dumps({'type': t, 'until': int(time.time()) + mins*60, **EVENTS[t]}))
    else: conn.close(); return jsonify({'error': 'Unknown event'}), 400
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Event updated'})

@app.route('/api/admin/mute', methods=['POST'])
@require_admin
def admin_mute():
    d = request.json or {}; mins = max(0, min(int(d.get('minutes', 10)), 10080)); conn = get_db()
    conn.execute('UPDATE users SET muted_until=? WHERE id=?', (int(time.time()) + mins*60 if mins else 0, int(d.get('user_id', 0))))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Muted' if mins else 'Unmuted'})

@app.route('/api/admin/chat_delete', methods=['POST'])
@require_admin
def admin_chat_delete():
    d = request.json or {}; conn = get_db()
    if d.get('all'): conn.execute('DELETE FROM chat')
    else: conn.execute('DELETE FROM chat WHERE id=?', (int(d.get('id', 0)),))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Chat cleaned'})

@app.route('/api/admin/factions')
@require_admin
def admin_factions():
    conn = get_db(); rows = conn.execute('SELECT * FROM factions').fetchall()
    out = [faction_dict(conn, f) for f in rows]; conn.close(); return jsonify(out)

@app.route('/api/admin/disband_faction', methods=['POST'])
@require_admin
def admin_disband():
    fid = int((request.json or {}).get('faction_id', 0)); conn = get_db()
    if not conn.execute('SELECT 1 FROM factions WHERE id=?',(fid,)).fetchone():conn.close();return jsonify(error='Faction not found'),404
    for member in conn.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id',(fid,)).fetchall():_leave_faction(conn,member['id'])
    conn.execute('DELETE FROM factions WHERE id=?',(fid,))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Faction disbanded'})

@app.route('/api/admin/set_water', methods=['POST'])
@require_admin
def admin_set_water():
    d = request.json or {}; conn = get_db()
    conn.execute('INSERT OR REPLACE INTO water_cells(grid_key,is_water) VALUES(?,?)', (d.get('grid_key', ''), 1 if d.get('water') else 0))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Cell updated'})

@app.route('/api/admin/give_territory', methods=['POST'])
@require_admin
def admin_give_territory():
    d = request.json or {}; gk = d.get('grid_key', ''); uid = int(d.get('user_id', 0))
    try: gl, gg = parse_key(gk)
    except Exception: return jsonify({'error': 'Bad key'}), 400
    terr = get_terrain(gl, gg); conn = get_db()
    if conn.execute('SELECT 1 FROM territories WHERE grid_key=?', (gk,)).fetchone():
        conn.execute('UPDATE territories SET owner_id=? WHERE grid_key=?', (uid, gk))
    else:
        conn.execute('INSERT INTO territories(grid_key,owner_id,terrain,garrison,population,last_collected) VALUES(?,?,?,0,?,?)',
                     (gk, uid, terr, get_population(terr, gl, gg), int(time.time())))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Territory assigned'})

# ── Notifications ─────────────────────────────────────────────────────────────

@app.route('/api/notifications')
@require_login
def get_notifications():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM notifications WHERE user_id=? AND is_read=0 ORDER BY created_at DESC LIMIT 30',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return jsonify([{**dict(r), 'data': json.loads(r['data'] or '{}')} for r in rows])

@app.route('/api/notifications/dismiss', methods=['POST'])
@require_login
def dismiss_notification():
    d   = request.json or {}
    nid = d.get('id')
    conn = get_db()
    conn.execute('UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?', (nid, session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/notifications/dismiss_all', methods=['POST'])
@require_login
def dismiss_all_notifications():
    conn = get_db()
    conn.execute('UPDATE notifications SET is_read=1 WHERE user_id=?', (session['user_id'],))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── Gift ──────────────────────────────────────────────────────────────────────

@app.route('/api/gift/send', methods=['POST'])
@require_login
def gift_money():
    d           = request.json or {}
    to_username = d.get('to_username', '').strip()
    try:        amount = max(1, int(d.get('amount', 0)))
    except:     return jsonify({'error': 'Invalid amount'}), 400
    if amount > 1_000_000: return jsonify({'error': 'Amount too large'}), 400
    conn = get_db()
    recipient = conn.execute(
        'SELECT id, username FROM users WHERE username=? COLLATE NOCASE AND is_banned=0', (to_username,)
    ).fetchone()
    if not recipient:
        conn.close(); return jsonify({'error': 'Player not found'}), 404
    if recipient['id'] == session['user_id']:
        conn.close(); return jsonify({'error': 'Cannot gift yourself'}), 400
    sender = conn.execute('SELECT username, money FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if sender['money'] < amount:
        conn.close(); return jsonify({'error': f'Not enough money (have {round(sender["money"])}💰)'}), 400
    conn.execute('UPDATE users SET money=money-? WHERE id=?', (amount, session['user_id']))
    conn.execute('UPDATE users SET money=money+? WHERE id=?', (amount, recipient['id']))
    create_notification(conn, recipient['id'], 'gift',
                        f'💰 {sender["username"]} gifted you {amount:,}💰!',
                        {'from': sender['username'], 'amount': amount})
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Gifted {amount:,}💰 to {recipient["username"]}!'})

# ── Alliance ──────────────────────────────────────────────────────────────────

@app.route('/api/alliance/invite', methods=['POST'])
@require_login
def alliance_invite():
    d               = request.json or {}
    target_username = d.get('username', '').strip()
    conn = get_db()
    target = conn.execute(
        'SELECT id, username FROM users WHERE username=? COLLATE NOCASE AND is_banned=0', (target_username,)
    ).fetchone()
    if not target:
        conn.close(); return jsonify({'error': 'Player not found'}), 404
    if target['id'] == session['user_id']:
        conn.close(); return jsonify({'error': 'Cannot invite yourself'}), 400
    existing = conn.execute(
        'SELECT * FROM alliances WHERE (requester_id=? AND target_id=?) OR (requester_id=? AND target_id=?)',
        (session['user_id'], target['id'], target['id'], session['user_id'])
    ).fetchone()
    if existing:
        if existing['status'] == 'active':
            conn.close(); return jsonify({'error': 'Already allied with this player'}), 400
        if existing['status'] == 'pending':
            conn.close(); return jsonify({'error': 'Alliance invite already pending'}), 400
        conn.execute('DELETE FROM alliances WHERE id=?', (existing['id'],))
    sender = conn.execute('SELECT username FROM users WHERE id=?', (session['user_id'],)).fetchone()
    cur    = conn.execute(
        'INSERT INTO alliances (requester_id, target_id, status) VALUES (?,?,?)',
        (session['user_id'], target['id'], 'pending')
    )
    aid = cur.lastrowid
    create_notification(conn, target['id'], 'alliance_invite',
                        f'🤝 {sender["username"]} wants to form an alliance with you!',
                        {'from': sender['username'], 'from_id': session['user_id'], 'alliance_id': aid})
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Alliance invite sent to {target["username"]}!'})

@app.route('/api/alliance/respond', methods=['POST'])
@require_login
def alliance_respond():
    d          = request.json or {}
    alliance_id= d.get('alliance_id')
    accept     = bool(d.get('accept', False))
    conn = get_db()
    alliance = conn.execute(
        "SELECT * FROM alliances WHERE id=? AND target_id=? AND status='pending'",
        (alliance_id, session['user_id'])
    ).fetchone()
    if not alliance:
        conn.close(); return jsonify({'error': 'Invite not found or already responded'}), 404
    me        = conn.execute('SELECT username FROM users WHERE id=?', (session['user_id'],)).fetchone()
    requester = conn.execute('SELECT username FROM users WHERE id=?', (alliance['requester_id'],)).fetchone()
    if accept:
        conn.execute("UPDATE alliances SET status='active' WHERE id=?", (alliance_id,))
        create_notification(conn, alliance['requester_id'], 'alliance_accepted',
                            f'🤝 {me["username"]} accepted your alliance!',
                            {'from': me['username'], 'from_id': session['user_id'], 'alliance_id': alliance_id})
        msg = f'Alliance formed with {requester["username"]}!'
    else:
        conn.execute("UPDATE alliances SET status='declined' WHERE id=?", (alliance_id,))
        create_notification(conn, alliance['requester_id'], 'alliance_declined',
                            f'❌ {me["username"]} declined your alliance invite.',
                            {'from': me['username']})
        msg = f'Declined alliance with {requester["username"]}.'
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': msg})

@app.route('/api/alliance/list')
@require_login
def list_alliances():
    conn = get_db()
    uid  = session['user_id']
    rows = conn.execute('''
        SELECT a.id, a.status, a.created_at,
               r.id r_id, r.username r_name, r.color r_color,
               t.id t_id, t.username t_name, t.color t_color
        FROM alliances a
        JOIN users r ON a.requester_id=r.id
        JOIN users t ON a.target_id=t.id
        WHERE (a.requester_id=? OR a.target_id=?) AND a.status IN ('active','pending')
        ORDER BY a.created_at DESC
    ''', (uid, uid)).fetchall()
    conn.close()
    result = []
    for row in rows:
        is_req    = (row['r_id'] == uid)
        ally_id   = row['t_id']   if is_req else row['r_id']
        ally_name = row['t_name'] if is_req else row['r_name']
        ally_col  = row['t_color']if is_req else row['r_color']
        result.append({
            'id': row['id'], 'status': row['status'],
            'ally_id': ally_id, 'ally_name': ally_name, 'ally_color': ally_col,
            'is_requester': is_req, 'created_at': row['created_at'],
        })
    return jsonify(result)

@app.route('/api/alliance/break', methods=['POST'])
@require_login
def break_alliance():
    d   = request.json or {}
    aid = d.get('alliance_id')
    conn = get_db()
    alliance = conn.execute(
        "SELECT * FROM alliances WHERE id=? AND status='active' AND (requester_id=? OR target_id=?)",
        (aid, session['user_id'], session['user_id'])
    ).fetchone()
    if not alliance:
        conn.close(); return jsonify({'error': 'Alliance not found'}), 404
    me       = conn.execute('SELECT username FROM users WHERE id=?', (session['user_id'],)).fetchone()
    other_id = alliance['target_id'] if alliance['requester_id'] == session['user_id'] else alliance['requester_id']
    conn.execute('DELETE FROM alliances WHERE id=?', (aid,))
    create_notification(conn, other_id, 'alliance_broken',
                        f'💔 {me["username"]} dissolved your alliance.',
                        {'from': me['username']})
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Alliance dissolved.'})

@app.route('/api/alliance/cancel', methods=['POST'])
@require_login
def cancel_alliance_invite():
    d   = request.json or {}
    aid = d.get('alliance_id')
    conn = get_db()
    alliance = conn.execute(
        "SELECT * FROM alliances WHERE id=? AND requester_id=? AND status='pending'",
        (aid, session['user_id'])
    ).fetchone()
    if not alliance:
        conn.close(); return jsonify({'error': 'Pending invite not found'}), 404
    conn.execute('DELETE FROM alliances WHERE id=?', (aid,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Invite cancelled.'})

# ── Leaderboard / battle log / announcements ──────────────────────────────────

@app.route('/api/leaderboard')
def leaderboard():
    conn = get_db()
    rows = conn.execute('''
        SELECT u.username,u.color,u.is_admin,u.is_donator,u.donator_title,u.rank_override,
               COUNT(t.id) territories,
               COALESCE(SUM(t.population),0) total_pop, u.id, u.money, u.army, u.wins, f.tag
        FROM users u LEFT JOIN territories t ON t.owner_id=u.id LEFT JOIN factions f ON f.id=u.faction_id
        WHERE u.is_banned=0
        GROUP BY u.id ORDER BY territories DESC LIMIT 20
    ''').fetchall()
    conn.close()
    result = []
    for r in rows:
        rank = get_rank(r['territories'])
        if r['rank_override']:
            custom=next((entry for entry in RANKS if entry[2]==r['rank_override']),None)
            if custom:rank={'icon':custom[1],'name':custom[2]}
        result.append({**dict(r),'rank':rank})
    return jsonify(result)

@app.route('/api/battle_log')
@require_login
def battle_log():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM battle_log WHERE attacker=? OR defender=? ORDER BY created_at DESC LIMIT 30',
        (session['username'],session['username'])
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/battle_log/all')
def battle_log_all():
    conn = get_db()
    rows = conn.execute('SELECT * FROM battle_log ORDER BY created_at DESC LIMIT 30').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/announcements')
def get_announcements():
    conn = get_db()
    rows = conn.execute('SELECT * FROM announcements ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Game status (leader and world event) ───────────────────────────────────────────────

@app.route('/api/game/status')
def game_status():
    conn = get_db()
    ev = current_event(conn); conn.commit()
    conn.close()
    # Check current leader
    conn2 = get_db()
    leader = conn2.execute('''
        SELECT u.username, COUNT(t.id) tc FROM users u
        LEFT JOIN territories t ON t.owner_id=u.id
        WHERE u.is_banned=0 GROUP BY u.id ORDER BY tc DESC LIMIT 1
    ''').fetchone()
    conn2.close()
    leader_info = {'name':leader['username'],'count':leader['tc']} if leader else None
    return jsonify({'status':'playing','leader':leader_info,'event':ev,'next_weather_in':600-int(time.time()%600)})

# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/api/admin/users')
@require_admin
def admin_users():
    conn = get_db()
    rows = conn.execute('''
        SELECT u.id,u.username,u.is_admin,u.is_donator,u.donator_title,u.rank_override,u.ideas_banned,u.is_banned,u.created_at,u.money,u.color,u.last_seen,
               COUNT(t.id) territory_count, COALESCE(SUM(t.population),0) total_pop
        FROM users u LEFT JOIN territories t ON t.owner_id=u.id
        GROUP BY u.id ORDER BY u.created_at DESC
    ''').fetchall()
    conn.close()
    now = int(time.time())
    return jsonify([{**dict(r),'online':(now-(r['last_seen'] or 0))<180} for r in rows])

@app.route('/api/admin/ban', methods=['POST'])
@require_admin
def admin_ban():
    d = request.json or {}
    uid = d.get('user_id'); ban = 1 if d.get('ban',True) else 0
    conn = get_db()
    # Prevent banning self or other admins
    target = conn.execute('SELECT is_admin,username FROM users WHERE id=?',(uid,)).fetchone()
    if not target:
        conn.close(); return jsonify({'error':'User not found'}),404
    if target['is_admin'] and target['username'].lower()=='admin':
        conn.close(); return jsonify({'error':'Cannot ban the main admin'}),403
    conn.execute('UPDATE users SET is_banned=? WHERE id=?',(ban,uid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/change_username', methods=['POST'])
@require_admin
def admin_change_username():
    d   = request.json or {}
    uid = d.get('user_id')
    new = d.get('new_username','').strip()
    if not new or not re.fullmatch(r'[\w .-]{3,20}', new):
        return jsonify({'error':'Username must be 3–20 characters'}),400
    conn = get_db()
    try:
        conn.execute('UPDATE users SET username=? WHERE id=?',(new,uid))
        conn.commit(); conn.close()
        return jsonify({'success':True,'message':f'Username changed to {new}'})
    except sqlite3.IntegrityError:
        conn.close(); return jsonify({'error':'Username already taken'}),409

@app.route('/api/admin/reset_password', methods=['POST'])
@require_admin
def admin_reset_password():
    d   = request.json or {}
    uid = d.get('user_id')
    new = d.get('new_password','')
    if not new or len(new)<4:
        return jsonify({'error':'Password must be at least 4 characters'}),400
    conn = get_db()
    conn.execute('UPDATE users SET password=? WHERE id=?',(ph(new),uid))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Password reset successfully'})

@app.route('/api/admin/promote', methods=['POST'])
@require_admin
def admin_promote():
    d   = request.json or {}
    uid = d.get('user_id'); val = 1 if d.get('promote',True) else 0
    conn = get_db()
    conn.execute('UPDATE users SET is_admin=? WHERE id=?',(val,uid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/give_money', methods=['POST'])
@require_admin
def admin_give_money():
    d      = request.json or {}
    uid    = d.get('user_id')
    try:   amount = max(1, int(d.get('amount', 0)))
    except: return jsonify({'error': 'Invalid amount'}), 400
    conn = get_db()
    target = conn.execute('SELECT username FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        conn.close(); return jsonify({'error': 'User not found'}), 404
    conn.execute('UPDATE users SET money=money+? WHERE id=?', (amount, uid))
    create_notification(conn, uid, 'gift',
                        f'💰 Admin granted you {amount:,}💰!',
                        {'from': 'Admin', 'amount': amount})
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Gave {amount:,}💰 to {target["username"]}'})

@app.route('/api/admin/announce', methods=['POST'])
@require_admin
def admin_announce():
    d   = request.json or {}
    msg = d.get('message','').strip()
    img = d.get('image_url','').strip() or None
    if not msg: return jsonify({'error':'Message required'}),400
    conn = get_db()
    cur  = conn.execute('INSERT INTO announcements (message,image_url,author) VALUES (?,?,?)',
                        (msg, img, session['username']))
    aid  = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({'success':True,'id':aid})

@app.route('/api/admin/delete_announcement', methods=['POST'])
@require_admin
def admin_del_ann():
    d = request.json or {}
    aid = d.get('id')
    conn = get_db()
    conn.execute('DELETE FROM announcements WHERE id=?',(aid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/remove_territories', methods=['POST'])
@require_admin
def admin_remove_territories():
    d = request.json or {}; uid = d.get('user_id')
    conn = get_db()
    conn.execute('UPDATE territories SET owner_id=NULL,garrison=0,boats=0,planes=0 WHERE owner_id=?',(uid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/reset_game', methods=['POST'])
@require_admin
def admin_reset_game():
    conn = get_db(); do_game_reset(conn); conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Game has been reset!'})

# ── DB backup (admin) ────────────────────────────────────────────────────────

@app.route('/api/admin/export_db')
@require_admin
def export_db():
    import io
    conn = get_db()
    buf = io.BytesIO()
    for chunk in conn.iterdump():
        buf.write((chunk + '\n').encode())
    conn.close(); buf.seek(0)
    from flask import send_file as _sf
    return _sf(buf, as_attachment=True, download_name='world_conquest_backup.sql', mimetype='text/plain')

# ── Run ───────────────────────────────────────────────────────────────────────

import re
# ══════════════════════════════════════════════════════════════════════════════
#  v5 — faction pools/research/wars, embassies, trade, wonders, ideologies, nukes, merges…
# ══════════════════════════════════════════════════════════════════════════════

def build_cost(btype, level):
    mult = BUILD_LEVEL_MULTIPLIERS[level]
    return {k: int(v*mult) for k, v in BUILDINGS[btype]['cost'].items()}
def fmt_cost(cost): return ' '.join(f'{v}{RES_EMOJI[k]}' for k, v in cost.items())

def migrate_v5():
    conn = get_db(); c = conn.cursor()
    def cols(t): return {r['name'] for r in c.execute(f'PRAGMA table_info({t})')}
    u = cols('users')
    for n, d in [('base_color','TEXT'),('ideology','TEXT'),('ideology_ts','INTEGER DEFAULT 0'),('capital_key','TEXT'),('capital_ts','INTEGER DEFAULT 0'),
                 ('steel','REAL DEFAULT 0'),('uranium','REAL DEFAULT 0'),('gems','REAL DEFAULT 0'),('nukes','INTEGER DEFAULT 0'),
                 ('konami','INTEGER DEFAULT 0'),('last_nuke','INTEGER DEFAULT 0')]:
        if n not in u: c.execute(f'ALTER TABLE users ADD COLUMN {n} {d}')
    c.execute('UPDATE users SET base_color=color WHERE base_color IS NULL')
    t = cols('territories')
    if 'invested' not in t:
        c.execute('ALTER TABLE territories ADD COLUMN invested REAL DEFAULT 25')
    if 'edited' not in cols('chat'): c.execute('ALTER TABLE chat ADD COLUMN edited INTEGER DEFAULT 0')
    f = cols('factions'); fresh = 'army' not in f
    for n, d in [('color','TEXT'),('mode',"TEXT DEFAULT 'open'"),('army','INTEGER DEFAULT 0'),('boats','INTEGER DEFAULT 0'),
                 ('planes','INTEGER DEFAULT 0'),('last_tick','INTEGER DEFAULT 0'),('descr','TEXT DEFAULT ""')]:
        if n not in f: c.execute(f'ALTER TABLE factions ADD COLUMN {n} {d}')
    if fresh:
        for k in POOLS:
            c.execute(f'UPDATE factions SET {k}=COALESCE((SELECT SUM({k}) FROM users WHERE faction_id=factions.id),0)')
        c.execute('UPDATE factions SET color=(SELECT color FROM users WHERE id=factions.leader_id) WHERE color IS NULL')
        c.execute('UPDATE users SET color=(SELECT color FROM factions WHERE id=users.faction_id) WHERE faction_id IS NOT NULL')
    c.executescript('''
      CREATE TABLE IF NOT EXISTS faction_research(faction_id INTEGER, tech TEXT, PRIMARY KEY(faction_id,tech));
      CREATE TABLE IF NOT EXISTS faction_rel(id INTEGER PRIMARY KEY AUTOINCREMENT, a INTEGER, b INTEGER, kind TEXT, status TEXT, ts INTEGER, score_a INTEGER DEFAULT 0, score_b INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS faction_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, faction_id INTEGER, user_id INTEGER, message TEXT, ts INTEGER);
      CREATE TABLE IF NOT EXISTS faction_bans(faction_id INTEGER, user_id INTEGER, until INTEGER, PRIMARY KEY(faction_id,user_id));
      CREATE TABLE IF NOT EXISTS fallout(grid_key TEXT PRIMARY KEY, until INTEGER, reason TEXT);
      CREATE TABLE IF NOT EXISTS embassies(host_id INTEGER, owner_id INTEGER, ts INTEGER, PRIMARY KEY(host_id,owner_id));
      CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER, give_res TEXT, give_amt INTEGER, get_res TEXT, get_amt INTEGER, status TEXT, last_run INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS loans(id INTEGER PRIMARY KEY AUTOINCREMENT, lender_id INTEGER, borrower_id INTEGER, unit TEXT, amount INTEGER, message TEXT, status TEXT, ts INTEGER);
      CREATE TABLE IF NOT EXISTS wonders(key TEXT PRIMARY KEY, owner_id INTEGER, ts INTEGER);
      CREATE TABLE IF NOT EXISTS merges(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER, status TEXT, ts INTEGER);
    ''')
    conn.commit(); conn.close()

# ── groups / pools ───────────────────────────────────────────────────────────
def _in(ids): return ','.join('?'*len(ids))
def fac_id(conn, uid):
    r = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    return r['faction_id'] if r else None
def group_ids(conn, uid):
    f = fac_id(conn, uid)
    return [x['id'] for x in conn.execute('SELECT id FROM users WHERE faction_id=?', (f,))] if f else [uid]
def group_levels(conn, uid, btype):
    ids = group_ids(conn, uid)
    return conn.execute(f'SELECT COALESCE(SUM(b.level),0) s FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE t.owner_id IN ({_in(ids)}) AND b.type=?', ids+[btype]).fetchone()['s']
def pool_get(conn, uid, kind):
    assert kind in POOLS
    r = conn.execute(f'SELECT faction_id,{kind} v FROM users WHERE id=?', (uid,)).fetchone()
    if not r: return 0
    if r['faction_id']:
        f = conn.execute(f'SELECT {kind} v FROM factions WHERE id=?', (r['faction_id'],)).fetchone()
        if f: return f['v']
    return r['v']
def pool_add(conn, uid, kind, d):
    assert kind in POOLS
    f = fac_id(conn, uid)
    if f: conn.execute(f'UPDATE factions SET {kind}=MAX(0,{kind}+?) WHERE id=?', (int(d), f))
    else: conn.execute(f'UPDATE users SET {kind}=MAX(0,{kind}+?) WHERE id=?', (int(d), uid))
def ftechs(conn, uid):
    f = fac_id(conn, uid)
    return {x['tech'] for x in conn.execute('SELECT tech FROM faction_research WHERE faction_id=?', (f,))} if f else set()
def ideo(conn, uid):
    r = conn.execute('SELECT ideology FROM users WHERE id=?', (uid,)).fetchone()
    return IDEOLOGIES.get(r['ideology'] if r else None, {})
def my_wonders(conn, uid): return {r['key'] for r in conn.execute('SELECT key FROM wonders WHERE owner_id=?', (uid,))}
def army_cap(conn, uid, rsch=None): return 10**9
def fallout_active(conn, k):
    r = conn.execute('SELECT until FROM fallout WHERE grid_key=?', (k,)).fetchone()
    return bool(r and r['until'] > time.time())
def announce(conn, msg): conn.execute("INSERT INTO announcements(message,author) VALUES(?, 'System')", (msg,))
def notify_actions(conn, uid, ntype, msg, actions):
    create_notification(conn, uid, ntype, msg, {'actions': actions})
def uname(conn, uid):
    r = conn.execute('SELECT username FROM users WHERE id=?', (uid,)).fetchone(); return r['username'] if r else '?'
def leader_of(conn, fid):
    r = conn.execute('SELECT leader_id FROM factions WHERE id=?', (fid,)).fetchone(); return r['leader_id'] if r else None

# ── economy ──────────────────────────────────────────────────────────────────
def yield_ctx(conn, uid):
    rs = user_research(conn, uid); ft = ftechs(conn, uid); ide = ideo(conn, uid); w = my_wonders(conn, uid)
    base = faction_bonus(conn, uid) * float(get_setting(conn, 'income_mult', 1) or 1) * ide.get('yield', 1.0)
    if 'f_unity' in ft: base *= 1.05
    for key in w: base *= WONDERS.get(key, {}).get('yield', 1)
    base *= religion_for(conn, uid).get('yield', 1)
    return {'rs': rs, 'ft': ft, 'ide': ide, 'w': w, 'ev': ev_type(conn), 'base': base, 'religion': religion_for(conn, uid)}
def res_mult2(rt, c):
    rs = c['rs']; m = c['base'] * c.get('religion', {}).get(rt, 1); ev = c['ev']
    if rt == 'food': m *= (1.25 if 'agri' in rs else 1) * (1.2 if 'irrigation' in rs else 1) * (1.5 if ev == 'harvest' else 1)
    if rt == 'wood': m *= (1.25 if 'agri' in rs else 1) * (1.5 if ev == 'harvest' else 1)
    if rt == 'money':
        m *= (1.15 if 'trade' in rs else 1) * (1.10 if 'banking' in rs else 1) * (1.10 if 'global_trade' in rs else 1)
        m *= c['ide'].get('money', 1.0) * math.prod(WONDERS.get(k, {}).get('money', 1) for k in c['w']) * (1.5 if ev == 'gold_rush' else 1)
    if rt == 'metal': m *= (1.25 if 'industry' in rs else 1) * (1.2 if 'metallurgy' in rs else 1) * (1.15 if 'mining' in rs else 1) * (1.5 if ev == 'mining' else 1)
    if rt == 'oil': m *= (1.25 if 'industry' in rs else 1) * (1.2 if 'refining' in rs else 1) * (1.5 if ev == 'mining' else 1)
    return m
def tile_yield(c, terrain, bt, bl):
    rt, rate = TERRAIN_RES[terrain]; bl = bl or 0
    info = BUILDINGS.get(bt, {})
    m = res_mult2(rt, c) * (1 + info.get('yield_per_level', 0)*bl)
    out = {rt: rate*m}
    for resource, amount in info.get('production', {}).items():
        out[resource] = out.get(resource, 0) + amount*bl*res_mult2(resource, c)
    return out
def income_rates(conn, uid):
    c = yield_ctx(conn, uid); rates = {k: 0.0 for k in RATE_VAL}; troops = 0
    for r in conn.execute('SELECT t.terrain,b.type bt,b.level bl FROM territories t LEFT JOIN buildings b ON b.grid_key=t.grid_key WHERE t.owner_id=?', (uid,)):
        for k, v in tile_yield(c, r['terrain'], r['bt'], r['bl']).items(): rates[k] += v
        troops += BUILDINGS.get(r['bt'], {}).get('troops_per_level', 0)*(r['bl'] or 0)
    return rates, troops, c
def claim_price(conn, uid, terrain):
    mc = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?', (uid,)).fetchone()['c']
    if mc == 0: return {'money': CLAIM_COST}
    rates, _, c = income_rates(conn, uid)
    inc = sum(rates[k]*RATE_VAL[k] for k in rates)
    rt, rate = TERRAIN_RES[terrain]
    price = (CLAIM_COST + CLAIM_TILE_FACTOR*rate*RATE_VAL[rt] + CLAIM_INCOME_FACTOR*inc) * c['ide'].get('claim', 1.0) * c['religion'].get('claim', 1) * (0.8 if 'banking' in c['rs'] else 1.0)
    price = max(CLAIM_COST, int(price))
    cost = {'money': price, 'wood': max(1, int(price*CLAIM_WOOD_RATIO/4)), 'food': max(1, int(price*CLAIM_FOOD_RATIO/2))}
    if mc >= 15: cost['metal'] = max(1, int(price*CLAIM_METAL_RATIO/6))
    return cost
def cost_value(cost): return sum(v*RATE_VAL.get(k, 1) for k, v in cost.items())
def research_discount(conn, uid):
    c = yield_ctx(conn, uid); d = min(0.30, 0.08*sum_levels(conn, uid, 'university'))
    if 'scientific' in c['rs']: d += 0.10
    if 'f_academy' in c['ft']: d += 0.10
    d += sum(WONDERS.get(k, {}).get('research_discount', 0) for k in c['w'])
    d += 1 - religion_for(conn, uid).get('research', 1)
    d += 1 - c['ide'].get('research', 1.0)
    return min(0.7, d)

def troop_cost2(conn, rsch):
    return troop_cost_for(conn, None, rsch)
def troop_cost_for(conn, uid, rsch):
    c = TROOP_COST
    if 'gunpowder' in rsch: c *= 0.75
    if 'logistics' in rsch: c *= 0.9
    if 'conscription' in rsch: c *= 0.85
    if uid:
        if 'f_logi' in ftechs(conn, uid): c *= 0.9
        c *= ideo(conn, uid).get('troop', 1.0)
    if ev_type(conn) == 'conscription': c *= 0.6
    c *= float(get_setting(conn, 'troop_cost_mult', 1) or 1)
    return max(1, int(round(c)))

def casualty_mult(conn, uid, rsch):
    m = 1.0
    if 'medicine' in rsch: m *= 0.75
    if 'f_medic' in ftechs(conn, uid): m *= 0.85
    m *= ideo(conn, uid).get('casualty', 1.0) * religion_for(conn, uid).get('casualty', 1)
    m *= 1 - min(0.30, 0.10*sum_levels(conn, uid, 'hospital'))
    return m

def auto_collect(uid, conn):
    now = int(time.time()); c = yield_ctx(conn, uid)
    rows = conn.execute('SELECT t.grid_key,t.terrain,t.last_collected,b.type bt,b.level bl FROM territories t LEFT JOIN buildings b ON b.grid_key=t.grid_key WHERE t.owner_id=?', (uid,)).fetchall()
    totals = {k: 0.0 for k in RATE_VAL}; troops = 0.0; upd = []; plants = []
    for r in rows:
        el = now - (r['last_collected'] or 0)
        if el < AUTO_COLLECT_CD: continue
        mins = min(el/60., MAX_ACCUM_MINS)
        for k, v in tile_yield(c, r['terrain'], r['bt'], r['bl']).items(): totals[k] += v*mins
        if r['bt'] == 'barracks': troops += 3*r['bl']*mins
        if r['bt'] == 'nuclear_plant': plants.append((r['grid_key'], r['bl'], mins))
        upd.append(r['grid_key'])
    if upd:
        for k in upd: conn.execute('UPDATE territories SET last_collected=? WHERE grid_key=?', (now, k))
        sets = ','.join(f'{r}={r}+?' for r in totals)
        conn.execute(f'UPDATE users SET {sets} WHERE id=?', list(totals.values())+[uid])
        if troops >= 1: pool_add(conn, uid, 'army', int(troops))
        for gk, bl, mins in plants:
            if random.random() < 1 - (1 - NUCLEAR_MELTDOWN_P*bl)**mins: meltdown(conn, gk)
    run_trades(conn, uid)
    f = fac_id(conn, uid)
    if f: faction_tick(conn, f)

def devastate(conn, gl, gg, R, until, reason):
    from geography import islands_in_radius
    keys = [f'{gl+a},{gg+b}' for a in range(-R, R+1) for b in range(-R, R+1) if a*a+b*b <= R*R and -473<=gl+a<=472 and -1000<=gg+b<=999]
    keys += islands_in_radius(gl,gg,R)
    q = _in(keys)
    rows = conn.execute(f'SELECT grid_key,owner_id FROM territories WHERE owner_id IS NOT NULL AND grid_key IN ({q})', keys).fetchall()
    owners = {}
    for r in rows: owners[r['owner_id']] = owners.get(r['owner_id'], 0) + 1
    conn.execute(f'UPDATE territories SET owner_id=NULL,garrison=0 WHERE grid_key IN ({q})', keys)
    conn.execute(f'DELETE FROM buildings WHERE grid_key IN ({q})', keys)
    conn.execute(f'UPDATE users SET capital_key=NULL WHERE capital_key IN ({q})', keys)
    conn.executemany('INSERT OR REPLACE INTO fallout(grid_key,until,reason) VALUES(?,?,?)', [(k, until, reason) for k in keys])
    return owners, len(keys)

def meltdown(conn, gk):
    gl, gg = parse_key(gk); R = random.randint(3, 6)
    owners, n = devastate(conn, gl, gg, R, int(time.time()) + FALLOUT_DURATION, 'meltdown')
    announce(conn, f'☢ NUCLEAR MELTDOWN near {gl*GRID:.1f}°, {gg*GRID:.1f}°! A reactor exploded — a {R}-tile radius is uninhabitable forever.')
    for o, cnt in owners.items(): create_notification(conn, o, 'info', f'☢ A nuclear plant melted down! You lost {cnt} tiles to three days of fallout.')

# ── trades ────────────────────────────────────────────────────────────────────
def run_trades(conn, uid):
    now = int(time.time())
    for t in conn.execute("SELECT * FROM trades WHERE status='active' AND (from_id=? OR to_id=?)", (uid, uid)).fetchall():
        last = t['last_run'] or now
        n = min(6, (now - last)//600)
        if n <= 0:
            if not t['last_run']: conn.execute('UPDATE trades SET last_run=? WHERE id=?', (now, t['id']))
            continue
        for _ in range(n):
            a = conn.execute(f'SELECT {t["give_res"]} v FROM users WHERE id=?', (t['from_id'],)).fetchone()
            b = conn.execute(f'SELECT {t["get_res"]} v FROM users WHERE id=?', (t['to_id'],)).fetchone()
            if not a or not b or a['v'] < t['give_amt'] or b['v'] < t['get_amt']: break
            conn.execute(f'UPDATE users SET {t["give_res"]}={t["give_res"]}-? WHERE id=?', (t['give_amt'], t['from_id']))
            conn.execute(f'UPDATE users SET {t["give_res"]}={t["give_res"]}+? WHERE id=?', (t['give_amt'], t['to_id']))
            conn.execute(f'UPDATE users SET {t["get_res"]}={t["get_res"]}-? WHERE id=?', (t['get_amt'], t['to_id']))
            conn.execute(f'UPDATE users SET {t["get_res"]}={t["get_res"]}+? WHERE id=?', (t['get_amt'], t['from_id']))
        conn.execute('UPDATE trades SET last_run=? WHERE id=?', (last + n*600, t['id']))

# ── faction treasury / relations ──────────────────────────────────────────────
def faction_tick(conn, fid):
    f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
    if not f: return
    now = int(time.time())
    if not f['last_tick']: conn.execute('UPDATE factions SET last_tick=? WHERE id=?', (now, fid)); return
    n = min(144, (now - f['last_tick'])//600)
    if n <= 0: return
    rate = 0.015 if conn.execute("SELECT 1 FROM faction_research WHERE faction_id=? AND tech='f_bank'", (fid,)).fetchone() else 0.01
    t = f['treasury']; paid = 0.0
    for _ in range(n): p = t*rate; t -= p; paid += p
    mem = [x['id'] for x in conn.execute('SELECT id FROM users WHERE faction_id=?', (fid,))]
    if mem and paid > 0: conn.execute(f'UPDATE users SET money=money+? WHERE id IN ({_in(mem)})', [paid/len(mem)] + mem)
    conn.execute('UPDATE factions SET treasury=?,last_tick=? WHERE id=?', (t, f['last_tick'] + n*600, fid))

def rel_between(conn, fa, fb, kind=None, status='active'):
    if not fa or not fb or fa == fb: return None
    q = 'SELECT * FROM faction_rel WHERE status=? AND ((a=? AND b=?) OR (a=? AND b=?))'; p = [status, fa, fb, fb, fa]
    if kind: q += ' AND kind=?'; p.append(kind)
    return conn.execute(q, p).fetchone()
def war_between(conn, u1, u2): return rel_between(conn, fac_id(conn, u1), fac_id(conn, u2), 'war')
def attack_block(conn, uid, oid):
    if not oid: return None
    if are_allied(uid, oid, conn): return '🤝 Cannot attack an ally or faction mate!'
    fa, fb = fac_id(conn, uid), fac_id(conn, oid)
    if fa and fb and rel_between(conn, fa, fb, 'ally'): return '🤝 Your factions are allied!'
    if not war_between(conn, uid, oid): return '⚔ Declare war through your faction before attacking this player.'
    return None

def blast_attack_block(conn, uid, keys):
    """Check every affected country before spending weapons or damaging tiles."""
    for row in conn.execute(f'SELECT DISTINCT owner_id FROM territories WHERE owner_id IS NOT NULL AND grid_key IN ({_in(keys)})', keys):
        if row['owner_id'] != uid:
            error = attack_block(conn, uid, row['owner_id'])
            if error: return error
    return None
def war_score(conn, uid, oid):
    r = war_between(conn, uid, oid)
    if not r: return
    fa = fac_id(conn, uid); col = 'score_a' if r['a'] == fa else 'score_b'
    conn.execute(f'UPDATE faction_rel SET {col}={col}+1 WHERE id=?', (r['id'],))
    r2 = conn.execute('SELECT * FROM faction_rel WHERE id=?', (r['id'],)).fetchone()
    if r2[col] >= 25:
        loser = r['b'] if r['a'] == fa else r['a']
        lt = conn.execute('SELECT treasury FROM factions WHERE id=?', (loser,)).fetchone()['treasury']
        spoil = lt*0.2
        conn.execute('UPDATE factions SET treasury=treasury-? WHERE id=?', (spoil, loser)); conn.execute('UPDATE factions SET treasury=treasury+? WHERE id=?', (spoil, fa))
        conn.execute("UPDATE faction_rel SET status='ended' WHERE id=?", (r['id'],))
        wn = conn.execute('SELECT name FROM factions WHERE id=?', (fa,)).fetchone()['name']; ln = conn.execute('SELECT name FROM factions WHERE id=?', (loser,)).fetchone()['name']
        announce(conn, f'🏁 {wn} has WON the war against {ln} and plundered {int(spoil)}💰 from their treasury!')

def morale_update(conn, uid, win):
    bonus = 4 if (win and 'propaganda' in user_research(conn, uid)) else 0
    conn.execute('UPDATE users SET morale=MAX(5,MIN(100,morale+?)),wins=wins+?,losses=losses+? WHERE id=?',
                 ((8 + bonus) if win else -12, 1 if win else 0, 0 if win else 1, uid))

# ── combat core (v5) ─────────────────────────────────────────────────────────
def defense_of(conn, owner_id, gk, terrain):
    if not owner_id:
        return {'base': 3 + random.Random(simple_hash(*parse_key(gk))).randint(0, 4), 'mods': [], 'mult': 1.0, 'owner_army': 0}
    army = pool_get(conn, owner_id, 'army')
    ids = group_ids(conn, owner_id)
    n = max(1, conn.execute(f'SELECT COUNT(*) c FROM territories WHERE owner_id IN ({_in(ids)})', ids).fetchone()['c'])
    rs = user_research(conn, owner_id); ft = ftechs(conn, owner_id); ide = ideo(conn, owner_id); w = my_wonders(conn, owner_id)
    base = army / (n ** 0.55) + 3
    mods = []; x = def_bonus(rs); mods.append(('Home ground' + (' + Castle Walls' if 'castle' in rs else ''), x))
    def add(label, v):
        if v != 1.0: mods.append((label, v))
    add(f'Terrain ({terrain})', TERRAIN_DEF.get(terrain, 1.0))
    if 'masonry' in rs: add('Masonry', 1.15)
    b = conn.execute('SELECT level FROM buildings WHERE grid_key=? AND type="fort"', (gk,)).fetchone()
    if b: add(f'Fortress Lv{b["level"]}', 1 + (0.32 if 'fortification' in rs else 0.25)*b['level'])
    if 'f_bulwark' in ft: add('Bulwark', 1.08)
    for key in w: add(WONDERS.get(key, {}).get('name', key), WONDERS.get(key, {}).get('def', 1))
    add('Religion', religion_for(conn, owner_id).get('def', 1))
    add('Radar stations', 1 + min(.09, BUILDINGS['radar_station']['def_per_level']*sum_levels(conn, owner_id, 'radar_station')))
    add('Ideology', ide.get('def', 1.0))
    cap = conn.execute('SELECT 1 FROM users WHERE id=? AND capital_key=?', (owner_id, gk)).fetchone()
    if cap: add('Capital', 1.15)
    mult = 1.0
    for _, m in mods: mult *= m
    return {'base': base, 'mods': mods, 'mult': mult, 'owner_army': army}

def attack_mods(conn, uid, rsch, kind, tgl, tgg, def_oid=None):
    mods = []; ft = ftechs(conn, uid); ide = ideo(conn, uid); w = my_wonders(conn, uid)
    if 'iron' in rsch: mods.append(('Iron Weapons', 1.2))
    if 'gunpowder' in rsch: mods.append(('Gunpowder', 1.3))
    if 'tactics' in rsch: mods.append(('Tactics', 1.05))
    if 'cavalry' in rsch and kind == 'land': mods.append(('Cavalry', 1.08))
    if 'artillery' in rsch and kind == 'land': mods.append(('Artillery', 1.12))
    if kind == 'air' and 'blitz' in rsch: mods.append(('Blitzkrieg', 1.2))
    if kind == 'air' and 'stealth' in rsch: mods.append(('Stealth', 1.25))
    if kind == 'air' and 'f_air' in ft: mods.append(('Joint Air Command', 1.2))
    if kind == 'naval' and 'navigation' in rsch: mods.append(('Navigation', 1.1))
    if 'f_warcry' in ft: mods.append(('War Cry', 1.06))
    for key in w:
        if WONDERS.get(key, {}).get('atk'): mods.append((WONDERS[key]['name'], WONDERS[key]['atk']))
    religion = religion_for(conn, uid)
    if religion: mods.append(('Religion: '+religion['name'], religion['atk']))
    if ide.get('atk'): mods.append(('Ideology', ide['atk']))
    wx = weather_for(cur_slot(), tgl, tgg)
    wf = WEATHER_FX[wx][1 if kind == 'air' else 0]
    if wf != 1.0: mods.append((f'Weather ({wx})', wf))
    morale = conn.execute('SELECT morale FROM users WHERE id=?', (uid,)).fetchone()['morale']
    floor = max(30 if 'tactics' in rsch else 0, ide.get('floor', 0), max([WONDERS.get(k, {}).get('floor', 0) for k in w] or [0]))
    morale = max(morale, floor)
    mods.append((f'Morale ({morale})', round(0.90 + 0.25*(morale/100.0), 3)))
    e = ev_type(conn)
    if e == 'war_fever': mods.append(('War Fever', 1.15))
    if e == 'cold_snap': mods.append(('Cold Snap', 0.88))
    fb = faction_bonus(conn, uid)
    if fb > 1.0: mods.append(('Faction unity', round(1 + (fb-1)/2, 3)))
    if def_oid and war_between(conn, uid, def_oid): mods.append(('Faction war', 1.10))
    if kind == 'naval': mods.append(('Amphibious landing', 0.9))
    return mods, wx

def resolve_battle(conn, uid, uname_, target_key, force, kind, from_key, carried_units=0, dry=False):
    tgl, tgg = parse_key(target_key)
    tt = conn.execute('SELECT * FROM territories WHERE grid_key=?', (target_key,)).fetchone()
    terrain = tt['terrain'] if tt else get_terrain(tgl, tgg)
    def_oid = tt['owner_id'] if tt else None
    rsch = user_research(conn, uid)
    amods, weather = attack_mods(conn, uid, rsch, kind, tgl, tgg, def_oid)
    d = defense_of(conn, def_oid, target_key, terrain); dmods = list(d['mods'])
    if kind == 'air' and def_oid and 'radar' in user_research(conn, def_oid): dmods.append(('Radar', 1.3))
    A = force; D = d['base']
    for _, m in amods: A *= m
    for _, m in dmods: D *= m
    if not dry: A *= random.uniform(0.92, 1.08); D *= random.uniform(0.92, 1.08)
    return {'A': A, 'D': D, 'odds': A/(A+D) if A+D > 0 else 1, 'weather': weather, 'terrain': terrain, 'def_oid': def_oid,
            'def_force': d['base'], 'amods': amods, 'dmods': dmods, 'tt': tt, 'rsch': rsch, 'owner_army': d['owner_army']}

def apply_victory(conn, uid, tk, terrain, tt, tgl, tgg):
    pop = tt['population'] if tt else get_population(terrain, tgl, tgg); now = int(time.time())
    if tt:
        conn.execute('UPDATE territories SET owner_id=?,garrison=0,boats=0,planes=0,last_collected=?,invested=25 WHERE grid_key=?', (uid, now, tk))
        conn.execute('DELETE FROM buildings WHERE grid_key=? AND random()%3=0', (tk,))
    else:
        conn.execute('INSERT INTO territories (grid_key,owner_id,terrain,garrison,boats,planes,population,last_collected,invested) VALUES (?,?,?,0,0,0,?,?,25)', (tk, uid, terrain, pop, now))
    conn.execute('UPDATE users SET capital_key=NULL WHERE capital_key=? AND id!=?', (tk, uid))

def do_assault(conn, uid, uname_, fk, tk, force, kind, units_label, committed_troops, fleet_back=0.0):
    tgl, tgg = parse_key(tk)
    r = resolve_battle(conn, uid, uname_, tk, force, kind, fk)
    rsch = r['rsch']; cm = casualty_mult(conn, uid, rsch); win = r['A'] > r['D']
    def_name = 'wilderness'
    if r['def_oid']: def_name = uname(conn, r['def_oid'])
    ratio = r['D'] / max(r['A'], 0.01)
    if win:
        lost = min(committed_troops-1, int(committed_troops*min(0.8, (0.12 + 0.55*min(1.0, ratio))*cm))) if committed_troops > 1 else 0
        survivors = max(1, committed_troops - lost) if committed_troops else 0
        pool_add(conn, uid, 'army', survivors)
        apply_victory(conn, uid, tk, r['terrain'], r['tt'], tgl, tgg)
        if r['def_oid']:
            pool_add(conn, r['def_oid'], 'army', -int(r['owner_army']*min(0.25, 0.04 + 0.05*(r['A']/max(r['D'], 1)))))
            war_score(conn, uid, r['def_oid'])
        msg = f"Victory! Took {def_name}'s tile. Lost {lost}, {survivors} troops hold the line."
    else:
        retreat = int(committed_troops*max(0.0, 0.25 - 0.2*min(1.0, ratio-1))*(2-cm)) if committed_troops else 0
        retreat = max(0, min(committed_troops-1, retreat)) if committed_troops > 1 else 0
        pool_add(conn, uid, 'army', retreat); lost = committed_troops - retreat
        if r['def_oid']: pool_add(conn, r['def_oid'], 'army', -int(r['owner_army']*min(0.12, 0.02 + 0.04*(r['A']/max(r['D'], 1)))))
        msg = f'Defeat! {def_name} held. {lost} troops lost, {retreat} retreated.'
    morale_update(conn, uid, win)
    conn.execute('INSERT INTO battle_log (attacker,defender,grid_key,result,mode,details) VALUES (?,?,?,?,?,?)',
                 (uname_, def_name, tk, 'victory' if win else 'defeat', kind, f'{units_label}: {round(r["A"])} vs {round(r["D"])} · {r["weather"]} · {r["terrain"]}'))
    if r['def_oid']:
        create_notification(conn, r['def_oid'], 'attack', f'⚔ {uname_} {"captured" if win else "attacked"} your {r["terrain"]} tile ({tk}) by {kind} — {"you lost it!" if win else "you held!"}')
    r.update({'win': win, 'msg': msg, 'lost': lost}); return r

def do_game_reset(conn):
    conn.execute('UPDATE territories SET owner_id=NULL,garrison=0,boats=0,planes=0')
    for t in ('bank_loans', 'bank_offers', 'campaigns', 'exchanges', 'moderation_confirmations', 'strike_events', 'casino_rounds', 'buildings', 'fallout', 'embassies', 'trades', 'loans', 'wonders', 'faction_rel', 'faction_research', 'faction_requests', 'merges','stock_prices','stock_history','stock_holdings','stock_transactions','eva_deployments','faction_contributions'):
        conn.execute(f'DELETE FROM {t}')
    conn.execute('UPDATE users SET army=CASE WHEN faction_id IS NULL THEN 10 ELSE 0 END,boats=0,planes=0,morale=50,steel=0,uranium=0,gems=0,nukes=0,rockets=0,capital_key=NULL')
    conn.execute('UPDATE factions SET army=10,boats=0,planes=0,treasury=0')
    for faction in conn.execute('SELECT id FROM factions').fetchall():
        members=[r['id'] for r in conn.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id',(faction['id'],))]
        if members:
            q,r=divmod(10,len(members))
            conn.executemany('INSERT INTO faction_contributions VALUES(?,?,?)',[(uid,faction['id'],q+(i<r)) for i,uid in enumerate(members)])
    conn.execute("UPDATE users SET food=100,wood=100,metal=100,oil=25,money=200,research='[]'")
    conn.execute("DELETE FROM game_settings WHERE key IN ('winner_id','winner_name','win_time')")
    conn.execute('DELETE FROM battle_log')
    conn.execute("INSERT OR IGNORE INTO announcements (message,author) VALUES ('🌍 A new round has started! Claim territories and conquer the world!','System')")

def _army_map(conn):
    out = {}
    for r in conn.execute('SELECT id,faction_id FROM users'):
        ids = group_ids(conn, r['id']) if r['faction_id'] else [r['id']]
        n = conn.execute(f'SELECT COUNT(*) c FROM territories WHERE owner_id IN ({_in(ids)})', ids).fetchone()['c']
        out[r['id']] = (pool_get(conn, r['id'], 'army'), max(1, n))
    return out

def award_achievements(conn, uid):
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    tc = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?', (uid,)).fetchone()['c']
    nb = conn.execute('SELECT COUNT(*) c FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE t.owner_id=?', (uid,)).fetchone()['c']
    nr = len(json.loads(u['research'] or '[]'))
    last = conn.execute("SELECT mode FROM battle_log WHERE attacker=? AND result='victory' ORDER BY id DESC LIMIT 1", (u['username'],)).fetchone()
    nukes = conn.execute("SELECT COUNT(*) c FROM battle_log WHERE attacker=? AND mode='nuke'", (u['username'],)).fetchone()['c']
    wonder = conn.execute('SELECT COUNT(*) c FROM wonders WHERE owner_id=?', (uid,)).fetchone()['c']
    emb = conn.execute('SELECT COUNT(*) c FROM embassies WHERE owner_id=?', (uid,)).fetchone()['c']
    trd = conn.execute("SELECT COUNT(*) c FROM trades WHERE status='active' AND (from_id=? OR to_id=?)", (uid, uid)).fetchone()['c']
    have = {r['key'] for r in conn.execute('SELECT key FROM achievements WHERE user_id=?', (uid,))}
    m = u['money']
    checks = {'first_blood': u['wins'] >= 1, 'wins_10': u['wins'] >= 10, 'wins_50': u['wins'] >= 50, 'wins_100': u['wins'] >= 100,
              'land_10': tc >= 10, 'land_30': tc >= 30, 'land_75': tc >= 75, 'land_150': tc >= 150, 'builder': nb >= 5, 'builder_20': nb >= 20,
              'scholar': nr >= 6, 'scholar_15': nr >= 15, 'scholar_25': nr >= 25, 'admiral': bool(last and last['mode'] == 'naval'),
              'ace': bool(last and last['mode'] == 'air'), 'rich': m >= 10000, 'rich_100k': m >= 100000, 'rich_1m': m >= 1000000,
              'faction': bool(u['faction_id']), 'chatty': u['chat_count'] >= 10, 'chat_100': u['chat_count'] >= 100,
              'daily_7': u['daily_streak'] >= 7, 'daily_30': u['daily_streak'] >= 30, 'capital': bool(u['capital_key']),
              'ideology': bool(u['ideology']), 'embassy': emb > 0, 'trader': trd > 0, 'wonder': wonder > 0, 'nuke': nukes > 0,
              'war_hero': False}
    new = []
    for k, ok in checks.items():
        if ok and k not in have and k in ACHIEVEMENTS:
            conn.execute('INSERT OR IGNORE INTO achievements(user_id,key,ts) VALUES(?,?,?)', (uid, k, int(time.time())))
            conn.execute('UPDATE users SET money=money+? WHERE id=?', (ACHIEVEMENTS[k]['reward'], uid))
            create_notification(conn, uid, 'info', f'🏅 Achievement: {ACHIEVEMENTS[k]["name"]} (+{ACHIEVEMENTS[k]["reward"]}💰)')
            new.append({'key': k, **ACHIEVEMENTS[k]})
    return new

def can_afford(u, cost): return all(u[k] >= v for k, v in cost.items())

def ingest_and_check_target(conn, tk):
    if is_water(conn, tk): return 'That is open water.'
    if fallout_active(conn, tk): return '☢ That land is irradiated and uninhabitable.'
    return None

# ── ROUTES: combat ────────────────────────────────────────────────────────────
@app.route('/api/troops/build', methods=['POST'])
@require_login
def build_troops():
    d = request.json or {}; uid = session['user_id']
    am = int(d.get('amount', 1)); conn = get_db()
    rsch = user_research(conn, uid); cost = am * troop_cost_for(conn, uid, rsch)
    u = conn.execute('SELECT money FROM users WHERE id=?', (uid,)).fetchone()
    if u['money'] < cost:
        conn.close(); return jsonify({'error': f'Need {cost}💰, have {round(u["money"])}💰'}), 400
    conn.execute('UPDATE users SET money=money-? WHERE id=?', (cost, uid)); pool_add(conn, uid, 'army', am)
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Recruited {am} troops for {cost}💰'})

@app.route('/api/combat/preview', methods=['POST'])
@require_login
def combat_preview():
    d = request.json or {}; uid = session['user_id']
    tk = d.get('target_key', ''); kind = d.get('kind', 'land'); n = max(1, int(d.get('amount', 1)))
    try: parse_key(tk)
    except Exception: return jsonify({'error': 'bad key'}), 400
    conn = get_db(); rs = user_research(conn, uid)
    cap = BOAT_CAP + (4 if 'navigation' in rs else 0)
    force = n if kind == 'land' else n*cap if kind == 'naval' else n*PLANE_POWER
    r = resolve_battle(conn, uid, session['username'], tk, force, kind, d.get('from_key', ''), dry=True)
    spy = 'espionage' in rs or 'f_spy' in ftechs(conn, uid)
    out = {'odds': round(r['odds']*100), 'weather': r['weather'], 'attack': round(r['A'], 1), 'atk_mods': [[a, round(b, 2)] for a, b in r['amods']]}
    blk = attack_block(conn, uid, r['def_oid'])
    if blk: out['blocked'] = blk
    if kind == 'naval' and d.get('from_key'):
        try: out['voyage'] = voyage_cost(conn, uid, d['from_key'], tk, n)
        except Exception: pass
    if spy or not r['def_oid']:
        out.update({'defense': round(r['D'], 1), 'def_mods': [[a, round(b, 2)] for a, b in r['dmods']]})
    else:
        out.update({'defense_est': [int(r['D']*0.7), int(r['D']*1.3)], 'odds': None,
                    'odds_est': [round(100*r['A']/(r['A']+r['D']*1.3)), round(100*r['A']/(r['A']+r['D']*0.7))]})
    conn.close(); return jsonify(out)

def voyage_cost(conn, uid, fk, tk, boats):
    dist = cell_distance(fk, tk); rs = user_research(conn, uid)
    f = 1.0
    if 'shipping' in rs: f *= 0.75
    if 'f_navy' in ftechs(conn, uid): f *= 0.75
    return {'money': int(boats*dist*VOYAGE_MONEY*f), 'wood': round(boats*dist*VOYAGE_WOOD*f,2), 'cells': dist}

def _target_checks(conn, uid, tk):
    msg = ingest_and_check_target(conn, tk)
    if msg: return msg
    tt = conn.execute('SELECT owner_id FROM territories WHERE grid_key=?', (tk,)).fetchone()
    if tt and tt['owner_id'] == uid: return 'Cannot attack your own territory'
    if tt and tt['owner_id']: return attack_block(conn, uid, tt['owner_id'])
    return None

@app.route('/api/attack', methods=['POST'])
@require_login
def attack():
    d = request.json or {}; uid = session['user_id']
    fk = d.get('from_key', '').strip(); tk = d.get('target_key', '').strip(); sent = max(1, int(d.get('troops', 1)))
    try:
        fl, fg = parse_key(fk); tl, tg = parse_key(tk)
        if fk == tk or max(abs(fl-tl), abs(fg-tg)) > 1: return jsonify({'error': 'Target must be adjacent to your attacking tile'}), 400
    except Exception: return jsonify({'error': 'Invalid keys'}), 400
    conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    def bail(m, c=400): conn.rollback(); conn.close(); return jsonify({'error': m}), c
    try:
        ids = group_ids(conn, uid)
        if not conn.execute(f'SELECT 1 FROM territories WHERE grid_key=? AND owner_id IN ({_in(ids)})', [fk]+ids).fetchone(): return bail('You do not own the attacking territory', 403)
        m = _target_checks(conn, uid, tk)
        if m: return bail(m)
        have = pool_get(conn, uid, 'army')
        if have < sent: return bail(f'Only {have} troops in your army')
        pool_add(conn, uid, 'army', -sent)
        r = do_assault(conn, uid, session['username'], fk, tk, sent, 'land', f'{sent} troops', sent)
        ach = award_achievements(conn, uid); conn.commit(); conn.close()
        return battle_response(r, {'achievements': ach})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({'error': f'Battle failed: {e}'}), 500

@app.route('/api/boats/build', methods=['POST'])
@require_login
def build_boats():
    d = request.json or {}; uid = session['user_id']; am = int(d.get('amount', 1)); conn = get_db()
    if 'shipyard' not in user_research(conn, uid): conn.close(); return jsonify({'error': 'Research Shipbuilding first'}), 400
    if group_levels(conn, uid, 'port') == 0: conn.close(); return jsonify({'error': 'You (or your faction) need a Port to build boats'}), 400
    cost = {'money': am*BOAT_COST_M, 'wood': am*BOAT_COST_W}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost); pool_add(conn, uid, 'boats', am); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Built {am} boat(s) for {fmt_cost(cost)}'})

@app.route('/api/boats/attack', methods=['POST'])
@require_login
def boats_attack():
    d = request.json or {}; uid = session['user_id']
    fk = d.get('from_key', '').strip(); tk = d.get('target_key', '').strip(); n = max(1, int(d.get('boats', 1)))
    conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    def bail(m, c=400): conn.rollback(); conn.close(); return jsonify({'error': m}), c
    try:
        ingest_water(conn, d.get('water')); ids = group_ids(conn, uid)
        b = conn.execute(f'SELECT 1 FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE b.grid_key=? AND b.type="port" AND t.owner_id IN ({_in(ids)})', [fk]+ids).fetchone()
        if not b: return bail('Boats must launch from a Port (yours or a faction mate\'s)')
        if not is_coastal(conn, fk): return bail('This port is not on the coast — boats need water')
        if cell_distance(fk, tk) <= 1: return bail('Target is adjacent — use a land attack')
        if not is_coastal(conn, tk): return bail('Landing site must be on a coast (no port needed there)')
        m = _target_checks(conn, uid, tk)
        if m: return bail(m)
        rsch = user_research(conn, uid)
        if pool_get(conn, uid, 'boats') < n: return bail(f'You only have {pool_get(conn, uid, "boats")} boat(s)')
        troops = min(pool_get(conn, uid, 'army'), n*(BOAT_CAP + (4 if 'navigation' in rsch else 0)))
        if troops < 1: return bail('No troops available to load')
        vc = voyage_cost(conn, uid, fk, tk, n); cost = {'money': vc['money'], 'wood': vc['wood']}
        u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not can_afford(u, cost): return bail(f'Voyage of {vc["cells"]} cells costs {fmt_cost(cost)}')
        pay(conn, uid, cost); pool_add(conn, uid, 'army', -troops); pool_add(conn, uid, 'boats', -n)
        r = do_assault(conn, uid, session['username'], fk, tk, troops, 'naval', f'{n} boats/{troops} troops', troops)
        back = int(round(n*BOAT_SURVIVAL)) if r['win'] else 0
        if back: pool_add(conn, uid, 'boats', back)
        ach = award_achievements(conn, uid); conn.commit(); conn.close()
        return battle_response(r, {'boats_back': back, 'troops_loaded': troops, 'voyage': vc, 'achievements': ach})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({'error': f'Naval operation failed: {e}'}), 500

@app.route('/api/planes/build', methods=['POST'])
@require_login
def build_planes():
    d = request.json or {}; uid = session['user_id']; am = int(d.get('amount', 1)); conn = get_db()
    if 'airforce' not in user_research(conn, uid): conn.close(); return jsonify({'error': 'Research Air Force first'}), 400
    if group_levels(conn, uid, 'airport') == 0: conn.close(); return jsonify({'error': 'You (or your faction) need an Airport'}), 400
    cost = {'money': am*PLANE_COST_M, 'metal': am*PLANE_COST_X, 'oil': am*PLANE_COST_O}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost); pool_add(conn, uid, 'planes', am); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Built {am} plane(s) for {fmt_cost(cost)}'})

@app.route('/api/planes/attack', methods=['POST'])
@require_login
def planes_attack():
    d = request.json or {}; uid = session['user_id']
    fk = d.get('from_key', '').strip(); tk = d.get('target_key', '').strip(); n = max(1, int(d.get('planes', 1)))
    conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    def bail(m, c=400): conn.rollback(); conn.close(); return jsonify({'error': m}), c
    try:
        ids = group_ids(conn, uid)
        b = conn.execute(f'SELECT b.level FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE b.grid_key=? AND b.type="airport" AND t.owner_id IN ({_in(ids)})', [fk]+ids).fetchone()
        if not b: return bail('Planes must take off from an Airport (yours or a faction mate\'s)')
        rsch = user_research(conn, uid); rng = plane_range(rsch) + (b['level']-1); dist = cell_distance(fk, tk)
        if dist <= 1: return bail('Target is adjacent — use a land attack')
        if dist > rng: return bail(f'Out of range ({dist} > {rng} cells). Build an airport closer.')
        m = _target_checks(conn, uid, tk)
        if m: return bail(m)
        if pool_get(conn, uid, 'planes') < n: return bail(f'You only have {pool_get(conn, uid, "planes")} plane(s)')
        paras = min(pool_get(conn, uid, 'army'), n*PLANE_TROOP_CAPACITY)
        if paras < 1: return bail('No paratroopers available')
        pool_add(conn, uid, 'army', -paras); pool_add(conn, uid, 'planes', -n)
        force = n*PLANE_POWER*(min(1.0, paras/(n*PLANE_TROOP_CAPACITY))*0.5 + 0.5)
        r = do_assault(conn, uid, session['username'], fk, tk, force, 'air', f'{n} planes/{paras} paras', paras)
        back = int(round(n*PLANE_VICTORY_SURVIVAL)) if r['win'] else int(n*PLANE_DEFEAT_SURVIVAL)
        if back: pool_add(conn, uid, 'planes', back)
        ach = award_achievements(conn, uid); conn.commit(); conn.close()
        return battle_response(r, {'planes_back': back, 'achievements': ach})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({'error': f'Air strike failed: {e}'}), 500

# ── claim / sell / abandon / capital ─────────────────────────────────────────
@app.route('/api/territory/claim', methods=['POST'])
@require_login
def claim_territory():
    d = request.json or {}; uid = session['user_id']; gk = d.get('grid_key', '').strip()
    try: gl, gg = parse_key(gk)
    except Exception: return jsonify({'error': 'Invalid grid_key'}), 400
    conn = get_db(); ingest_water(conn, d.get('water'))
    def bail(m, c=400): conn.commit(); conn.close(); return jsonify({'error': m}), c
    if is_water(conn, gk): return bail('You cannot claim open water')
    if fallout_active(conn, gk): return bail('☢ Irradiated land — nobody can live here')
    ex = conn.execute('SELECT owner_id FROM territories WHERE grid_key=?', (gk,)).fetchone()
    if ex and ex['owner_id']: return bail('Already owned — attack it!')
    mine = conn.execute('SELECT grid_key FROM territories WHERE owner_id=?', (uid,)).fetchall()
    if mine and not any(max(abs(gl - parse_key(m['grid_key'])[0]), abs(gg - parse_key(m['grid_key'])[1])) <= 1 for m in mine) and not any(True for _ in []):
        # allow expanding next to faction mates too
        ids = group_ids(conn, uid); near = conn.execute(f'SELECT grid_key FROM territories WHERE owner_id IN ({_in(ids)})', ids).fetchall()
        if not any(max(abs(gl - parse_key(m['grid_key'])[0]), abs(gg - parse_key(m['grid_key'])[1])) <= 1 for m in near):
            return bail('Must be adjacent to your territory (or a faction mate\'s)')
    terrain = get_terrain(gl, gg); cost = claim_price(conn, uid, terrain)
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): return bail(f'Need {fmt_cost(cost)}')
    pay(conn, uid, cost); now = int(time.time()); inv = cost_value(cost)
    if ex: conn.execute('UPDATE territories SET owner_id=?,garrison=0,boats=0,planes=0,population=?,last_collected=?,invested=? WHERE grid_key=?', (uid, get_population(terrain, gl, gg), now, inv, gk))
    else: conn.execute('INSERT INTO territories (grid_key,owner_id,terrain,garrison,boats,planes,population,last_collected,invested) VALUES (?,?,?,0,0,0,?,?,?)', (gk, uid, terrain, get_population(terrain, gl, gg), now, inv))
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'terrain': terrain, 'message': f'Claimed {terrain} for {fmt_cost(cost)}', 'achievements': ach})

@app.route('/api/territory/sell', methods=['POST'])
@require_login
def territory_sell():
    uid = session['user_id']; gk = (request.json or {}).get('grid_key', ''); conn = get_db()
    t = conn.execute('SELECT invested FROM territories WHERE grid_key=? AND owner_id=?', (gk, uid)).fetchone()
    if not t: conn.close(); return jsonify({'error': 'Not your territory'}), 403
    refund = int((t['invested'] or 0)*TILE_REFUND)
    conn.execute('UPDATE territories SET owner_id=NULL,garrison=0 WHERE grid_key=?', (gk,)); conn.execute('DELETE FROM buildings WHERE grid_key=?', (gk,))
    conn.execute('UPDATE users SET money=money+?,capital_key=CASE WHEN capital_key=? THEN NULL ELSE capital_key END WHERE id=?', (refund, gk, uid))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Sold tile for {refund}💰 (50% of your investment)'})

@app.route('/api/territory/abandon_all', methods=['POST'])
@require_login
def territory_abandon_all():
    d = request.json or {}; uid = session['user_id']; conn = get_db()
    if d.get('confirm') != 'DELETE ALL MY TERRITORIES': conn.close(); return jsonify({'error': 'Confirmation text did not match'}), 400
    u = conn.execute('SELECT password FROM users WHERE id=?', (uid,)).fetchone()
    if not u or not password_matches(u['password'], d.get('password', '')): conn.close(); return jsonify({'error': 'Wrong password'}), 403
    keys = [r['grid_key'] for r in conn.execute('SELECT grid_key FROM territories WHERE owner_id=?', (uid,))]
    for i in range(0, len(keys), 500):
        ch = keys[i:i+500]; conn.execute(f'DELETE FROM buildings WHERE grid_key IN ({_in(ch)})', ch)
    conn.execute('UPDATE territories SET owner_id=NULL,garrison=0 WHERE owner_id=?', (uid,)); conn.execute('UPDATE users SET capital_key=NULL WHERE id=?', (uid,))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Abandoned {len(keys)} territories. Pick a new place on the map!'})

@app.route('/api/capital/set', methods=['POST'])
@require_login
def capital_set():
    uid = session['user_id']; gk = (request.json or {}).get('grid_key', ''); conn = get_db()
    if not conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id=?', (gk, uid)).fetchone(): conn.close(); return jsonify({'error': 'Not your territory'}), 403
    u = conn.execute('SELECT capital_key,capital_ts FROM users WHERE id=?', (uid,)).fetchone()
    if u['capital_key'] and time.time() - (u['capital_ts'] or 0) < 86400: conn.close(); return jsonify({'error': 'You can move your capital once per day'}), 400
    conn.execute('UPDATE users SET capital_key=?,capital_ts=? WHERE id=?', (gk, int(time.time()), uid))
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': '⭐ Capital established! +15% defense there; embassies will gather here.', 'achievements': ach})

# ── buildings ─────────────────────────────────────────────────────────────────
@app.route('/api/building/build', methods=['POST'])
@require_login
def building_build():
    d = request.json or {}; uid = session['user_id']; gk = d.get('grid_key', ''); bt = d.get('type', '')
    if bt not in BUILDINGS: return jsonify({'error': 'Unknown building'}), 400
    conn = get_db(); ingest_water(conn, d.get('water'))
    t = conn.execute('SELECT terrain FROM territories WHERE grid_key=? AND owner_id=?', (gk, uid)).fetchone()
    if not t: conn.close(); return jsonify({'error': 'You do not own this territory'}), 403
    info = BUILDINGS[bt]; rsch = user_research(conn, uid)
    if info.get('needs') and info['needs'] not in rsch: conn.close(); return jsonify({'error': f'Requires research: {RESEARCH_TREE[info["needs"]]["name"]}'}), 400
    if info.get('terrain') and t['terrain'] not in info['terrain']: conn.close(); return jsonify({'error': f'Needs terrain: {", ".join(info["terrain"])}'}), 400
    cur = conn.execute('SELECT * FROM buildings WHERE grid_key=?', (gk,)).fetchone()
    if cur and cur['type'] != bt: conn.close(); return jsonify({'error': 'Tile already has a different building — demolish it first'}), 400
    if info.get('coastal') and not is_coastal(conn, gk): conn.close(); return jsonify({'error': 'Ports can only be built on the coast'}), 400
    lvl = (cur['level'] if cur else 0) + 1
    if lvl > BUILD_MAX_LEVEL: conn.close(); return jsonify({'error': 'Already max level'}), 400
    cost = build_cost(bt, lvl)
    if 'engineering' in rsch: cost = {k: int(v*ENGINEERING_DISCOUNT) for k, v in cost.items()}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost)
    if cur: conn.execute('UPDATE buildings SET level=? WHERE grid_key=?', (lvl, gk))
    else: conn.execute('INSERT INTO buildings(grid_key,type,level) VALUES(?,?,1)', (gk, bt))
    conn.execute('UPDATE territories SET invested=invested+? WHERE grid_key=?', (cost_value(cost), gk))
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'{info["name"]} {"upgraded to Lv"+str(lvl) if cur else "built"} ({fmt_cost(cost)})', 'achievements': ach})

@app.route('/api/daily/claim', methods=['POST'])
@require_login
def daily_claim():
    uid = session['user_id']; day = int(time.time() // 86400); conn = get_db()
    u = conn.execute('SELECT last_daily,daily_streak FROM users WHERE id=?', (uid,)).fetchone()
    if u['last_daily'] == day: conn.close(); return jsonify({'error': 'Already claimed today — come back tomorrow!'}), 400
    streak = (u['daily_streak'] + 1) if u['last_daily'] == day-1 else 1; s = min(streak, 7)
    conn.execute('UPDATE users SET last_daily=?,daily_streak=?,money=money+?,food=food+?,wood=wood+?,metal=metal+?,oil=oil+? WHERE id=?',
                 (day, streak, 100+50*s, 30*s, 30*s, 15*s, 8*s, uid))
    pool_add(conn, uid, 'army', 2*s); ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Day {streak} reward: {100+50*s}💰 + supplies + {2*s} troops!', 'achievements': ach})

@app.route('/api/resources/sell_all', methods=['POST'])
@require_login
def sell_all():
    uid = session['user_id']; only = (request.json or {}).get('resource'); conn = get_db(); total = 0; sold = {}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    for r, rate in SELL_RATES.items():
        if only and r != only: continue
        have = int(u[r])
        if have > 0: total += have*rate; sold[r] = have; conn.execute(f'UPDATE users SET {r}={r}-? WHERE id=?', (have, uid))
    conn.execute('UPDATE users SET money=money+? WHERE id=?', (total, uid)); ach = award_achievements(conn, uid); conn.commit(); conn.close()
    if not sold: return jsonify({'error': 'Nothing to sell'}), 400
    return jsonify({'success': True, 'earned': total, 'message': f'Sold everything for {total}💰', 'achievements': ach})

@app.route('/api/income')
@require_login
def income_api():
    uid = session['user_id']; mins = max(1, min(int(request.args.get('minutes', 60)), 10080)); conn = get_db()
    rates, troops, c = income_rates(conn, uid); n = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?', (uid,)).fetchone()['c']
    mults = [('Faction bonus', faction_bonus(conn, uid)), ('Global x', float(get_setting(conn, 'income_mult', 1) or 1))]
    if c['ide'].get('yield'): mults.append(('Ideology', c['ide']['yield']))
    if c['ev'] in ('gold_rush','harvest','mining'): mults.append((f'Event: {c["ev"]}', 1.5))
    conn.close()
    return jsonify({'minutes': mins, 'tiles': n, 'rates': {k: round(v, 2) for k, v in rates.items()},
                    'totals': {k: round(v*mins, 1) for k, v in rates.items()}, 'troops_per_min': troops,
                    'value_per_min': round(sum(rates[k]*RATE_VAL[k] for k in rates), 1), 'mults': [[a, round(b, 2)] for a, b in mults if b != 1]})

@app.route('/api/profile/color', methods=['POST'])
@require_login
def profile_color():
    col = (request.json or {}).get('color', '')
    if not re.match(r'^#[0-9a-fA-F]{6}$', col): return jsonify({'error': 'Pick a valid #RRGGBB color'}), 400
    conn = get_db(); uid = session['user_id']; conn.execute('UPDATE users SET base_color=? WHERE id=?', (col, uid))
    if not fac_id(conn, uid): conn.execute('UPDATE users SET color=? WHERE id=?', (col, uid))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Color updated' + (' (your faction color is used while you are in a faction)' if fac_id(get_db(), uid) else '')})

# ── FACTIONS (pooled army/fleet, research, wars, settings) ───────────────────
def faction_dict(conn, f):
    mem = conn.execute('SELECT u.id,u.username,u.color,(SELECT COUNT(*) FROM territories WHERE owner_id=u.id) tc,'
                       '(SELECT COALESCE(SUM(population),0) FROM territories WHERE owner_id=u.id) pop FROM users u WHERE u.faction_id=? ORDER BY tc DESC', (f['id'],)).fetchall()
    techs = [x['tech'] for x in conn.execute('SELECT tech FROM faction_research WHERE faction_id=?', (f['id'],))]
    rels = []
    for r in conn.execute("SELECT * FROM faction_rel WHERE status IN ('active','pending') AND (a=? OR b=?)", (f['id'], f['id'])):
        other = r['b'] if r['a'] == f['id'] else r['a']; o = conn.execute('SELECT name,tag FROM factions WHERE id=?', (other,)).fetchone()
        if not o: continue
        mine, theirs = (r['score_a'], r['score_b']) if r['a'] == f['id'] else (r['score_b'], r['score_a'])
        rels.append({'id': r['id'], 'kind': r['kind'], 'status': r['status'], 'other_id': other, 'other': o['name'], 'tag': o['tag'], 'mine': mine, 'theirs': theirs,
                     'incoming': r['b'] == f['id'] and r['status'] == 'pending', 'since': r['ts']})
    return {'id': f['id'], 'name': f['name'], 'tag': f['tag'], 'color': f['color'], 'mode': f['mode'], 'descr': f['descr'] or '', 'leader_id': f['leader_id'],
            'treasury': round(f['treasury']), 'army': f['army'], 'boats': f['boats'], 'planes': f['planes'],
            'members': [{'id': m['id'], 'username': m['username'], 'color': m['color'], 'territories': m['tc'], 'pop': m['pop']} for m in mem],
            'territories': sum(m['tc'] for m in mem), 'population': sum(m['pop'] for m in mem), 'bonus_pct': round(min(15, 2*(len(mem)-1))),
            'techs': techs, 'rels': rels, 'rate': 1.5 if 'f_bank' in techs else 1.0}

def _join_faction(conn, uid, fid):
    u = conn.execute('SELECT army,boats,planes FROM users WHERE id=?', (uid,)).fetchone(); f = conn.execute('SELECT color FROM factions WHERE id=?', (fid,)).fetchone()
    for k in POOLS: conn.execute(f'UPDATE factions SET {k}={k}+? WHERE id=?', (u[k], fid))
    conn.execute('UPDATE users SET army=0,boats=0,planes=0,faction_id=?,color=? WHERE id=?', (fid, f['color'], uid))
    conn.execute('DELETE FROM faction_requests WHERE user_id=?', (uid,))

def _leave_faction(conn, uid, ban=False):
    fid = fac_id(conn, uid)
    if not fid: return
    n = max(1, faction_members(conn, fid)); f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
    for k in POOLS:
        share = f[k]//n; conn.execute(f'UPDATE factions SET {k}={k}-? WHERE id=?', (share, fid)); conn.execute(f'UPDATE users SET {k}=? WHERE id=?', (share, uid))
    conn.execute('UPDATE users SET faction_id=NULL,color=COALESCE(base_color,color) WHERE id=?', (uid,))
    if ban: conn.execute('INSERT OR REPLACE INTO faction_bans(faction_id,user_id,until) VALUES(?,?,?)', (fid, uid, (int(time.time())//86400 + 1)*86400))
    if f['leader_id'] == uid:
        nxt = conn.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id LIMIT 1', (fid,)).fetchone()
        if nxt: conn.execute('UPDATE factions SET leader_id=? WHERE id=?', (nxt['id'], fid))
        else:
            for t in ('factions', 'faction_research', 'faction_requests', 'faction_bans'): conn.execute(f'DELETE FROM {t} WHERE {"id" if t=="factions" else "faction_id"}=?', (fid,))
            conn.execute('DELETE FROM faction_rel WHERE a=? OR b=?', (fid, fid))

def _my_fac(conn, uid, leader=False):
    fid = fac_id(conn, uid)
    f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone() if fid else None
    if not f: return None, ('You are not in a faction', 400)
    if leader and f['leader_id'] != uid: return None, ('Only the faction leader can do that', 403)
    return f, None

@app.route('/api/faction/list')
@require_login
def faction_list():
    conn = get_db()
    rows = conn.execute('SELECT f.*,(SELECT COUNT(*) FROM users WHERE faction_id=f.id) mc,(SELECT COUNT(*) FROM territories t JOIN users u ON u.id=t.owner_id WHERE u.faction_id=f.id) tc FROM factions f ORDER BY tc DESC').fetchall()
    out = [{'id': r['id'], 'name': r['name'], 'tag': r['tag'], 'members': r['mc'], 'territories': r['tc'], 'mode': r['mode'], 'color': r['color'], 'descr': r['descr'] or ''} for r in rows]
    conn.close(); return jsonify(out)

@app.route('/api/faction/info')
@require_login
def faction_info():
    uid = session['user_id']; conn = get_db(); fid = fac_id(conn, uid)
    f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone() if fid else None
    out = None
    if f:
        faction_tick(conn, fid); conn.commit(); f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
        out = faction_dict(conn, f); out['rally_ready_in'] = max(0, int(get_setting(conn, f'rally_{fid}', 0) or 0) - int(time.time()))
        out['catalog'] = FACTION_TECH
        if f['leader_id'] == uid:
            out['requests'] = [{'id': r['id'], 'user_id': r['user_id'], 'username': uname(conn, r['user_id']), 'message': r['message']} for r in conn.execute('SELECT * FROM faction_requests WHERE faction_id=?', (fid,))]
    unlocked = conn.execute('SELECT konami FROM users WHERE id=?', (uid,)).fetchone()['konami']
    conn.close(); return jsonify({'faction': out, 'konami': bool(unlocked)})

@app.route('/api/faction/create', methods=['POST'])
@require_login
def faction_create():
    d = request.json or {}; uid = session['user_id']
    name = (d.get('name') or '').strip(); tag = (d.get('tag') or '').strip().upper()
    if not (3 <= len(name) <= 24) or not (2 <= len(tag) <= 4) or not tag.isalnum(): return jsonify({'error': 'Name 3–24 chars, tag 2–4 letters/digits'}), 400
    conn = get_db(); u = conn.execute('SELECT money,faction_id,color,base_color FROM users WHERE id=?', (uid,)).fetchone()
    if u['faction_id']: conn.close(); return jsonify({'error': 'Leave your faction first'}), 400
    if u['money'] < FACTION_COST: conn.close(); return jsonify({'error': f'Founding a faction costs {FACTION_COST}💰'}), 400
    try: cur = conn.execute('INSERT INTO factions(name,tag,leader_id,color,last_tick) VALUES(?,?,?,?,?)', (name, tag, uid, u['base_color'] or u['color'], int(time.time())))
    except sqlite3.IntegrityError: conn.close(); return jsonify({'error': 'Name or tag already taken'}), 409
    conn.execute('UPDATE users SET money=money-? WHERE id=?', (FACTION_COST, uid)); _join_faction(conn, uid, cur.lastrowid)
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Faction [{tag}] {name} founded!', 'achievements': ach})

@app.route('/api/faction/join', methods=['POST'])
@require_login
def faction_join():
    d = request.json or {}; uid = session['user_id']; fid = int(d.get('faction_id', 0)); conn = get_db()
    if fac_id(conn, uid): conn.close(); return jsonify({'error': 'Leave your faction first'}), 400
    f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
    if not f: conn.close(); return jsonify({'error': 'Faction not found'}), 404
    ban = conn.execute('SELECT until FROM faction_bans WHERE faction_id=? AND user_id=?', (fid, uid)).fetchone()
    if ban and ban['until'] > time.time(): conn.close(); return jsonify({'error': f'You were kicked — you can try again in {int((ban["until"]-time.time())//3600)+1}h'}), 403
    if faction_members(conn, fid) >= 12: conn.close(); return jsonify({'error': 'Faction is full (12)'}), 400
    if f['mode'] == 'closed': conn.close(); return jsonify({'error': '🔒 This faction is closed'}), 403
    if f['mode'] == 'invite':
        if conn.execute('SELECT 1 FROM faction_requests WHERE faction_id=? AND user_id=?', (fid, uid)).fetchone(): conn.close(); return jsonify({'error': 'You already asked to join'}), 400
        conn.execute('INSERT INTO faction_requests(faction_id,user_id,message,ts) VALUES(?,?,?,?)', (fid, uid, (d.get('message') or '')[:140], int(time.time())))
        create_notification(conn, f['leader_id'], 'info', f'🚩 {session["username"]} asks to join [{f["tag"]}] — see the Faction tab.')
        conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Request sent to the faction leader'})
    _join_faction(conn, uid, fid); ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Joined [{f["tag"]}] {f["name"]}', 'achievements': ach})

@app.route('/api/faction/request_respond', methods=['POST'])
@require_login
def faction_request_respond():
    d = request.json or {}; uid = session['user_id']; conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    r = conn.execute('SELECT * FROM faction_requests WHERE id=? AND faction_id=?', (int(d.get('request_id', 0)), f['id'])).fetchone()
    if not r: conn.close(); return jsonify({'error': 'Request not found'}), 404
    conn.execute('DELETE FROM faction_requests WHERE id=?', (r['id'],))
    if d.get('accept'):
        if fac_id(conn, r['user_id']): conn.close(); return jsonify({'error': 'They already joined another faction'}), 400
        if faction_members(conn, f['id']) >= 12: conn.close(); return jsonify({'error': 'Faction is full'}), 400
        _join_faction(conn, r['user_id'], f['id']); create_notification(conn, r['user_id'], 'info', f'✅ You were accepted into [{f["tag"]}] {f["name"]}!'); award_achievements(conn, r['user_id'])
    else: create_notification(conn, r['user_id'], 'info', f'❌ [{f["tag"]}] declined your join request.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Done'})

@app.route('/api/faction/leave', methods=['POST'])
@require_login
def faction_leave():
    conn = get_db(); _leave_faction(conn, session['user_id']); conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'You left the faction (you took your share of the army and fleet)'})

@app.route('/api/faction/kick', methods=['POST'])
@require_login
def faction_kick():
    uid = session['user_id']; tid = int((request.json or {}).get('user_id', 0)); conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    if tid == uid or fac_id(conn, tid) != f['id']: conn.close(); return jsonify({'error': 'Invalid member'}), 400
    _leave_faction(conn, tid, ban=True); create_notification(conn, tid, 'info', f'You were kicked from [{f["tag"]}]. You can rejoin tomorrow.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Member kicked (banned until tomorrow)'})

@app.route('/api/faction/donate', methods=['POST'])
@require_login
def faction_donate():
    uid = session['user_id']; am = int((request.json or {}).get('amount', 0)); conn = get_db(); f, err = _my_fac(conn, uid)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    u = conn.execute('SELECT money FROM users WHERE id=?', (uid,)).fetchone()
    if am < 1 or u['money'] < am: conn.close(); return jsonify({'error': 'Invalid amount'}), 400
    conn.execute('UPDATE users SET money=money-? WHERE id=?', (am, uid)); conn.execute('UPDATE factions SET treasury=treasury+? WHERE id=?', (am, f['id']))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Donated {am}💰. Every 10 min 1% of the treasury is paid out to all members, and the leader can buy faction research with it.'})

@app.route('/api/faction/settings', methods=['POST'])
@require_login
def faction_settings():
    d = request.json or {}; uid = session['user_id']; conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    mode = d.get('mode', f['mode']); col = d.get('color', f['color']); desc = (d.get('descr', f['descr']) or '')[:140]
    if mode not in ('open', 'invite', 'closed'): conn.close(); return jsonify({'error': 'Bad mode'}), 400
    if not re.match(r'^#[0-9a-fA-F]{6}$', col or ''): conn.close(); return jsonify({'error': 'Bad color'}), 400
    conn.execute('UPDATE factions SET mode=?,color=?,descr=? WHERE id=?', (mode, col, desc, f['id'])); conn.execute('UPDATE users SET color=? WHERE faction_id=?', (col, f['id']))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Faction settings saved'})

@app.route('/api/faction/rally', methods=['POST'])
@require_login
def faction_rally():
    uid = session['user_id']; conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    if f['treasury'] < RALLY_COST: conn.close(); return jsonify({'error': 'Rally costs 1500💰 from the treasury'}), 400
    nxt = int(get_setting(conn, f'rally_{f["id"]}', 0) or 0)
    if nxt > time.time(): conn.close(); return jsonify({'error': f'Rally on cooldown ({int(nxt-time.time())//60} min)'}), 400
    conn.execute('UPDATE factions SET treasury=treasury-? WHERE id=?', (RALLY_COST,f['id'])); conn.execute('UPDATE users SET morale=100 WHERE faction_id=?', (f['id'],))
    set_setting(conn, f'rally_{f["id"]}', int(time.time()) + RALLY_COOLDOWN)
    for m in conn.execute('SELECT id FROM users WHERE faction_id=?', (f['id'],)).fetchall(): create_notification(conn, m['id'], 'info', f'📯 [{f["tag"]}] rally! Your morale is at maximum.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Rally called — every member is at 100 morale!'})

@app.route('/api/faction/research', methods=['POST'])
@require_login
def faction_research():
    uid = session['user_id']; tech = (request.json or {}).get('tech'); conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    if tech not in FACTION_TECH: conn.close(); return jsonify({'error': 'Unknown tech'}), 400
    if conn.execute('SELECT 1 FROM faction_research WHERE faction_id=? AND tech=?', (f['id'], tech)).fetchone(): conn.close(); return jsonify({'error': 'Already researched'}), 400
    cost = FACTION_TECH[tech]['cost']
    if f['treasury'] < cost: conn.close(); return jsonify({'error': f'Treasury needs {cost}💰'}), 400
    conn.execute('UPDATE factions SET treasury=treasury-? WHERE id=?', (cost, f['id'])); conn.execute('INSERT INTO faction_research VALUES(?,?)', (f['id'], tech))
    for m in conn.execute('SELECT id FROM users WHERE faction_id=?', (f['id'],)).fetchall(): create_notification(conn, m['id'], 'info', f'🔬 Faction research complete: {FACTION_TECH[tech]["name"]}!')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Faction researched {FACTION_TECH[tech]["name"]} — all members benefit!'})

def _notify_faction(conn, fid, msg):
    for m in conn.execute('SELECT id FROM users WHERE faction_id=?', (fid,)).fetchall(): create_notification(conn, m['id'], 'info', msg)

@app.route('/api/faction/war/declare', methods=['POST'])
@require_login
def war_declare():
    uid = session['user_id']; tid = int((request.json or {}).get('faction_id', 0)); conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    t = conn.execute('SELECT * FROM factions WHERE id=?', (tid,)).fetchone()
    if not t or tid == f['id']: conn.close(); return jsonify({'error': 'Invalid target faction'}), 400
    if rel_between(conn, f['id'], tid, status='active'): conn.close(); return jsonify({'error': 'You already have a treaty or war with them — end it first'}), 400
    conn.execute("INSERT INTO faction_rel(a,b,kind,status,ts) VALUES(?,?,'war','active',?)", (f['id'], tid, int(time.time())))
    announce(conn, f'⚔ WAR! [{f["tag"]}] {f["name"]} has declared war on [{t["tag"]}] {t["name"]}!')
    _notify_faction(conn, tid, f'⚔ [{f["tag"]}] declared WAR on your faction! No time or capture limit. Either side can end the war or surrender.'); _notify_faction(conn, f['id'], f'⚔ We are at war with [{t["tag"]}]! No time or capture limit. Either side can end the war or surrender.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'War declared on {t["name"]}!'})

@app.route('/api/faction/war/end', methods=['POST'])
@require_login
def war_end():
    uid = session['user_id']; rid = int((request.json or {}).get('rel_id', 0)); conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    r = conn.execute("SELECT * FROM faction_rel WHERE id=? AND kind='war' AND status='active' AND (a=? OR b=?)", (rid, f['id'], f['id'])).fetchone()
    if not r: conn.close(); return jsonify({'error': 'No such war'}), 404
    other = r['b'] if r['a'] == f['id'] else r['a']; mine = r['score_a'] if r['a'] == f['id'] else r['score_b']; theirs = r['score_b'] if r['a'] == f['id'] else r['score_a']
    if time.time() - r['ts'] < 86400 and mine >= theirs: conn.close(); return jsonify({'error': 'A war lasts at least 24h unless you are losing — you can surrender if behind'}), 400
    pay_ = 0
    if mine < theirs:
        pay_ = f['treasury']*0.15; conn.execute('UPDATE factions SET treasury=treasury-? WHERE id=?', (pay_, f['id'])); conn.execute('UPDATE factions SET treasury=treasury+? WHERE id=?', (pay_, other))
    conn.execute("UPDATE faction_rel SET status='ended' WHERE id=?", (rid,))
    announce(conn, f'🕊 [{f["tag"]}] ended the war ({mine}–{theirs}).'); _notify_faction(conn, other, f'🕊 [{f["tag"]}] ended the war.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'War ended{" — you paid "+str(int(pay_))+"💰 reparations" if pay_ else ""}'})

@app.route('/api/faction/ally/propose', methods=['POST'])
@require_login
def ally_propose():
    uid = session['user_id']; tid = int((request.json or {}).get('faction_id', 0)); conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    t = conn.execute('SELECT * FROM factions WHERE id=?', (tid,)).fetchone()
    if not t or tid == f['id']: conn.close(); return jsonify({'error': 'Invalid faction'}), 400
    if rel_between(conn, f['id'], tid, status='active') or rel_between(conn, f['id'], tid, status='pending'): conn.close(); return jsonify({'error': 'There is already a relation/proposal'}), 400
    cur = conn.execute("INSERT INTO faction_rel(a,b,kind,status,ts) VALUES(?,?,'ally','pending',?)", (f['id'], tid, int(time.time())))
    notify_actions(conn, t['leader_id'], 'faction_ally', f'🤝 [{f["tag"]}] {f["name"]} proposes a faction alliance.',
        [{'label': '✓ Accept', 'path': '/api/faction/rel/respond', 'body': {'rel_id': cur.lastrowid, 'accept': True}, 'cls': 'btn-success'}, {'label': '✕ Decline', 'path': '/api/faction/rel/respond', 'body': {'rel_id': cur.lastrowid, 'accept': False}, 'cls': 'btn-danger'}])
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Alliance proposed to their leader'})

@app.route('/api/faction/rel/respond', methods=['POST'])
@require_login
def rel_respond():
    d = request.json or {}; uid = session['user_id']; conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    r = conn.execute("SELECT * FROM faction_rel WHERE id=? AND b=? AND status='pending'", (int(d.get('rel_id', 0)), f['id'])).fetchone()
    if not r: conn.close(); return jsonify({'error': 'Proposal not found'}), 404
    conn.execute('UPDATE faction_rel SET status=? WHERE id=?', ('active' if d.get('accept') else 'declined', r['id']))
    ally = conn.execute('SELECT * FROM factions WHERE id=?', (r['a'],)).fetchone()
    if d.get('accept'): announce(conn, f'🤝 [{ally["tag"]}] and [{f["tag"]}] are now allied!'); _notify_faction(conn, r['a'], f'🤝 [{f["tag"]}] accepted the alliance.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Alliance formed' if d.get('accept') else 'Declined'})

@app.route('/api/faction/rel/break', methods=['POST'])
@require_login
def rel_break():
    uid = session['user_id']; rid = int((request.json or {}).get('rel_id', 0)); conn = get_db(); f, err = _my_fac(conn, uid, True)
    if err: conn.close(); return jsonify({'error': err[0]}), err[1]
    conn.execute("UPDATE faction_rel SET status='ended' WHERE id=? AND kind='ally' AND (a=? OR b=?)", (rid, f['id'], f['id'])); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Alliance ended'})

# ── Ideology / wonders ───────────────────────────────────────────────────────
@app.route('/api/ideology/set', methods=['POST'])
@require_login
def ideology_set():
    uid = session['user_id']; k = (request.json or {}).get('id'); conn = get_db()
    if k not in IDEOLOGIES: conn.close(); return jsonify({'error': 'Unknown ideology'}), 400
    u = conn.execute('SELECT ideology,ideology_ts,money FROM users WHERE id=?', (uid,)).fetchone()
    if u['ideology'] == k: conn.close(); return jsonify({'error': 'Already your ideology'}), 400
    cost = 0
    if u['ideology']:
        if time.time() - (u['ideology_ts'] or 0) < 86400: conn.close(); return jsonify({'error': 'You can change ideology once per 24h'}), 400
        cost = IDEOLOGY_CHANGE_COST
        if u['money'] < cost: conn.close(); return jsonify({'error': 'A revolution costs 2000💰'}), 400
    conn.execute('UPDATE users SET ideology=?,ideology_ts=?,money=money-? WHERE id=?', (k, int(time.time()), cost, uid))
    ach = award_achievements(conn, uid); conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'{IDEOLOGIES[k]["name"]} adopted!', 'achievements': ach})

@app.route('/api/wonders')
@require_login
def wonders_list():
    conn = get_db(); own = {r['key']: r['owner_id'] for r in conn.execute('SELECT key,owner_id FROM wonders')}
    out = [{'key': k, **v, 'owner_id': own.get(k), 'owner': uname(conn, own[k]) if k in own else None} for k, v in WONDERS.items()]
    conn.close(); return jsonify(out)

@app.route('/api/wonders/buy', methods=['POST'])
@require_login
def wonders_buy():
    uid = session['user_id']; k = (request.json or {}).get('key'); conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    if k not in WONDERS: conn.rollback(); conn.close(); return jsonify({'error': 'Unknown wonder'}), 400
    if conn.execute('SELECT 1 FROM wonders WHERE key=?', (k,)).fetchone(): conn.rollback(); conn.close(); return jsonify({'error': 'Someone already built it!'}), 400
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone(); cost = WONDERS[k]['cost']
    if not can_afford(u, cost): conn.rollback(); conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost); conn.execute('INSERT INTO wonders VALUES(?,?,?)', (k, uid, int(time.time())))
    announce(conn, f'{WONDERS[k]["icon"]} {u["username"]} has completed the {WONDERS[k]["name"]}!'); ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'{WONDERS[k]["name"]} built!', 'achievements': ach})

# ── Embassies / trade / loans ────────────────────────────────────────────────
@app.route('/api/embassy/build', methods=['POST'])
@require_login
def embassy_build():
    uid = session['user_id']; hid = int((request.json or {}).get('host_id', 0)); conn = get_db()
    if 'diplomacy' not in user_research(conn, uid): conn.close(); return jsonify({'error': 'Research Diplomacy first'}), 400
    h = conn.execute('SELECT capital_key,username FROM users WHERE id=?', (hid,)).fetchone()
    if hid == uid or not h: conn.close(); return jsonify({'error': 'Invalid country'}), 400
    if not h['capital_key']: conn.close(); return jsonify({'error': f'{h["username"]} has no capital yet'}), 400
    if conn.execute('SELECT 1 FROM embassies WHERE host_id=? AND owner_id=?', (hid, uid)).fetchone(): conn.close(); return jsonify({'error': 'You already have an embassy there'}), 400
    if conn.execute('SELECT money FROM users WHERE id=?', (uid,)).fetchone()['money'] < EMBASSY_COST: conn.close(); return jsonify({'error': 'An embassy costs 400💰'}), 400
    conn.execute('UPDATE users SET money=money-? WHERE id=?', (EMBASSY_COST,uid)); conn.execute('INSERT INTO embassies VALUES(?,?,?)', (hid, uid, int(time.time())))
    create_notification(conn, hid, 'info', f'🏳 {session["username"]} opened an embassy in your capital.'); ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Embassy opened in {h["username"]}\'s capital', 'achievements': ach})

def trade_ok(conn, a, b):
    if fac_id(conn, a) and fac_id(conn, a) == fac_id(conn, b): return True
    return bool(conn.execute('SELECT 1 FROM embassies WHERE (host_id=? AND owner_id=?) OR (host_id=? AND owner_id=?)', (a, b, b, a)).fetchone())

@app.route('/api/embassy/list')
@require_login
def embassy_list():
    uid = session['user_id']; conn = get_db()
    o = [{'host_id': r['host_id'], 'name': uname(conn, r['host_id'])} for r in conn.execute('SELECT host_id FROM embassies WHERE owner_id=?', (uid,))]
    h = [{'owner_id': r['owner_id'], 'name': uname(conn, r['owner_id'])} for r in conn.execute('SELECT owner_id FROM embassies WHERE host_id=?', (uid,))]
    trades = []
    for t in conn.execute("SELECT * FROM trades WHERE status IN ('active','pending') AND (from_id=? OR to_id=?)", (uid, uid)):
        trades.append({**dict(t), 'from_name': uname(conn, t['from_id']), 'to_name': uname(conn, t['to_id'])})
    loans = []
    for l in conn.execute("SELECT * FROM loans WHERE status IN ('active','pending') AND (lender_id=? OR borrower_id=?)", (uid, uid)):
        loans.append({**dict(l), 'lender': uname(conn, l['lender_id']), 'borrower': uname(conn, l['borrower_id'])})
    conn.close(); return jsonify({'owned': o, 'hosted': h, 'trades': trades, 'loans': loans})

@app.route('/api/trade/propose', methods=['POST'])
@require_login
def trade_propose():
    d = request.json or {}; uid = session['user_id']; to = int(d.get('to_id', 0)); gr, tr = d.get('give_res'), d.get('get_res')
    ga, ta = int(d.get('give_amt', 0)), int(d.get('get_amt', 0)); ok = set(RATE_VAL)
    if gr not in ok or tr not in ok or gr == tr or not (1 <= ga <= 10**6) or not (1 <= ta <= 10**6) or to == uid: return jsonify({'error': 'Invalid trade'}), 400
    conn = get_db()
    if not conn.execute('SELECT 1 FROM users WHERE id=?', (to,)).fetchone(): conn.close(); return jsonify({'error': 'Unknown player'}), 400
    if not trade_ok(conn, uid, to): conn.close(); return jsonify({'error': 'You need an embassy with them (or be in the same faction) to trade'}), 400
    cur = conn.execute("INSERT INTO trades(from_id,to_id,give_res,give_amt,get_res,get_amt,status) VALUES(?,?,?,?,?,?,'pending')", (uid, to, gr, ga, tr, ta))
    notify_actions(conn, to, 'trade_request', f'⚖ {session["username"]} offers: they send {ga}{RES_EMOJI[gr]} and you send {ta}{RES_EMOJI[tr]} every 10 min.',
        [{'label': '✓ Accept', 'path': '/api/trade/respond', 'body': {'trade_id': cur.lastrowid, 'accept': True}, 'cls': 'btn-success'}, {'label': '✕ Decline', 'path': '/api/trade/respond', 'body': {'trade_id': cur.lastrowid, 'accept': False}, 'cls': 'btn-danger'}])
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Trade offer sent'})

@app.route('/api/trade/respond', methods=['POST'])
@require_login
def trade_respond():
    d = request.json or {}; uid = session['user_id']; conn = get_db()
    t = conn.execute("SELECT * FROM trades WHERE id=? AND to_id=? AND status='pending'", (int(d.get('trade_id', 0)), uid)).fetchone()
    if not t: conn.close(); return jsonify({'error': 'Offer not found'}), 404
    conn.execute('UPDATE trades SET status=?,last_run=? WHERE id=?', ('active' if d.get('accept') else 'declined', int(time.time()), t['id']))
    create_notification(conn, t['from_id'], 'info', f'⚖ {session["username"]} {"accepted" if d.get("accept") else "declined"} your trade offer.')
    award_achievements(conn, t['from_id']); award_achievements(conn, uid); conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Trade deal active' if d.get('accept') else 'Declined'})

@app.route('/api/trade/cancel', methods=['POST'])
@require_login
def trade_cancel():
    uid = session['user_id']; conn = get_db()
    conn.execute("UPDATE trades SET status='cancelled' WHERE id=? AND (from_id=? OR to_id=?)", (int((request.json or {}).get('trade_id', 0)), uid, uid)); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Trade cancelled'})

@app.route('/api/loan/request', methods=['POST'])
@require_login
def loan_request():
    d = request.json or {}; uid = session['user_id']; to = int(d.get('to_id', 0)); unit = d.get('unit'); amt = int(d.get('amount', 0)); conn = get_db()
    if unit not in ('boats', 'planes') or amt < 1 or to == uid: conn.close(); return jsonify({'error': 'Invalid request'}), 400
    if not conn.execute('SELECT 1 FROM users WHERE id=?', (to,)).fetchone(): conn.close(); return jsonify({'error': 'Unknown player'}), 400
    cur = conn.execute("INSERT INTO loans(lender_id,borrower_id,unit,amount,message,status,ts) VALUES(?,?,?,?,?,'pending',?)", (to, uid, unit, amt, (d.get('message') or '')[:200], int(time.time())))
    msg = f'🚢 {session["username"]} asks to borrow {amt} {unit}.' + (f' "{(d.get("message") or "")[:200]}"' if d.get('message') else '')
    notify_actions(conn, to, 'loan_request', msg, [{'label': '✓ Lend', 'path': '/api/loan/respond', 'body': {'loan_id': cur.lastrowid, 'accept': True}, 'cls': 'btn-success'}, {'label': '✕ Deny', 'path': '/api/loan/respond', 'body': {'loan_id': cur.lastrowid, 'accept': False}, 'cls': 'btn-danger'}])
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Request sent'})

@app.route('/api/loan/respond', methods=['POST'])
@require_login
def loan_respond():
    d = request.json or {}; uid = session['user_id']; conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    l = conn.execute("SELECT * FROM loans WHERE id=? AND lender_id=? AND status='pending'", (int(d.get('loan_id', 0)), uid)).fetchone()
    if not l: conn.rollback(); conn.close(); return jsonify({'error': 'Request not found'}), 404
    if d.get('accept'):
        owned = conn.execute(f'SELECT {l["unit"]} FROM users WHERE id=?', (uid,)).fetchone()[0]
        if owned < l['amount']: conn.rollback(); conn.close(); return jsonify({'error': f'You personally own only {owned} {l["unit"]}'}), 400
        conn.execute(f'UPDATE users SET {l["unit"]}={l["unit"]}-? WHERE id=?', (l['amount'], uid)); pool_add(conn, l['borrower_id'], l['unit'], l['amount']); conn.execute("UPDATE loans SET status='active' WHERE id=?", (l['id'],))
    else: conn.execute("UPDATE loans SET status='denied' WHERE id=?", (l['id'],))
    create_notification(conn, l['borrower_id'], 'info', f'🚢 {session["username"]} {"lent you" if d.get("accept") else "denied your request for"} {l["amount"]} {l["unit"]}.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Lent!' if d.get('accept') else 'Denied'})

@app.route('/api/loan/return', methods=['POST'])
@require_login
def loan_return():
    uid = session['user_id']; conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    l = conn.execute("SELECT * FROM loans WHERE id=? AND (borrower_id=? OR lender_id=?) AND status='active'", (int((request.json or {}).get('loan_id', 0)), uid, uid)).fetchone()
    if not l: conn.rollback(); conn.close(); return jsonify({'error': 'Loan not found'}), 404
    owned = conn.execute(f'SELECT {l["unit"]} FROM users WHERE id=?', (l['borrower_id'],)).fetchone()
    back = min(l['amount'], owned[0] if owned else 0)
    conn.execute(f'UPDATE users SET {l["unit"]}={l["unit"]}-? WHERE id=?', (back, l['borrower_id'])); pool_add(conn, l['lender_id'], l['unit'], back); conn.execute("UPDATE loans SET status='returned' WHERE id=?", (l['id'],))
    create_notification(conn, l['lender_id'], 'info', f'🚢 {uname(conn, l["borrower_id"])} returned {back}/{l["amount"]} {l["unit"]}.'); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Returned {back} {l["unit"]}'})

# ── Nukes & fallout ──────────────────────────────────────────────────────────
def nuke_cost(conn): return int(float(get_setting(conn, 'nuke_cost', NUKE_MONEY) or NUKE_MONEY))

@app.route('/api/nuke/build', methods=['POST'])
@require_login
def nuke_build():
    d = request.json or {}; uid = session['user_id']; conn = get_db(); rs = user_research(conn, uid)
    for t in ('nuclear_physics', 'rocketry', 'manhattan'):
        if t not in rs: conn.close(); return jsonify({'error': f'Requires research: {RESEARCH_TREE[t]["name"]}'}), 400
    for b in ('uranium_mine', 'enrichment', 'nuclear_plant'):
        if group_levels(conn, uid, b) == 0: conn.close(); return jsonify({'error': f'You need a {BUILDINGS[b]["name"]}'}), 400
    cost = nuke_cost(conn); u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    extra = {'uranium': NUKE_URANIUM, 'steel': NUKE_STEEL}
    if not can_afford(u, extra): conn.close(); return jsonify({'error': f'Need {fmt_cost(extra)} as well'}), 400
    if d.get('from_treasury'):
        f, err = _my_fac(conn, uid, True)
        if err or f['treasury'] < cost: conn.close(); return jsonify({'error': 'Leader-only, and the treasury needs ' + f'{cost:,}💰'}), 400
        conn.execute('UPDATE factions SET treasury=treasury-? WHERE id=?', (cost, f['id']))
    else:
        if u['money'] < cost: conn.close(); return jsonify({'error': f'A nuclear warhead costs {cost:,}💰'}), 400
        conn.execute('UPDATE users SET money=money-? WHERE id=?', (cost, uid))
    pay(conn, uid, extra); conn.execute('UPDATE users SET nukes=nukes+1 WHERE id=?', (uid,)); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': '☢ A nuclear warhead has been assembled.'})

@app.route('/api/nuke/launch', methods=['POST'])
@require_login
def nuke_launch():
    d = request.json or {}; uid = session['user_id']; fk, tk = d.get('from_key', ''), d.get('target_key', ''); conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    def bail(m): conn.rollback(); conn.close(); return jsonify({'error': m}), 400
    try: tl, tg = parse_key(tk); parse_key(fk)
    except Exception: return bail('Bad keys')
    ids = group_ids(conn, uid)
    if not conn.execute(f'SELECT 1 FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE b.grid_key=? AND b.type="silo" AND t.owner_id IN ({_in(ids)})', [fk]+ids).fetchone(): return bail('Launch from a Missile Silo')
    u = conn.execute('SELECT nukes,last_nuke FROM users WHERE id=?', (uid,)).fetchone()
    if u['nukes'] < 1: return bail('You have no nuclear warheads')
    if time.time() - (u['last_nuke'] or 0) < NUKE_COOLDOWN: return bail(f'Silo reloading ({int((NUKE_COOLDOWN-(time.time()-u["last_nuke"]))//60)+1} min)')
    if cell_distance(fk, tk) > NUKE_RANGE: return bail(f'Out of range ({NUKE_RANGE} cells)')
    R = random.randint(NUKE_RADIUS_MIN, NUKE_RADIUS_MAX)
    from geography import islands_in_radius
    keys = [f'{tl+a},{tg+b}' for a in range(-R, R+1) for b in range(-R, R+1) if a*a+b*b <= R*R and -473<=tl+a<=472 and -1000<=tg+b<=999]
    keys += islands_in_radius(tl, tg, R)
    blocked = blast_attack_block(conn, uid, keys)
    if blocked: return bail(blocked)
    owners, n = devastate(conn, tl, tg, R, int(time.time()) + FALLOUT_DURATION, 'nuke')
    conn.execute('UPDATE users SET nukes=nukes-1,last_nuke=? WHERE id=?', (int(time.time()), uid)); seen = set()
    for o, cnt in owners.items():
        g = fac_id(conn, o) or ('u', o)
        if g not in seen:
            seen.add(g); pool_add(conn, o, 'army', -int(pool_get(conn, o, 'army')*0.4))
        conn.execute('UPDATE users SET morale=MAX(5,morale-30),money=money*0.9 WHERE id=?', (o,))
        create_notification(conn, o, 'attack', f'☢ {session["username"]} NUKED you! {cnt} tiles vaporised, army -40%, morale shattered, money -10%.')
    conn.execute('INSERT INTO battle_log (attacker,defender,grid_key,result,mode,details) VALUES (?,?,?,?,?,?)', (session['username'], ', '.join(uname(conn, o) for o in owners) or 'nobody', tk, 'victory', 'nuke', f'radius {R}, {n} cells'))
    announce(conn, f'☢ {session["username"]} launched a nuclear missile! Radius {R} around {tl*GRID:.1f}°, {tg*GRID:.1f}° destroyed; {sum(owners.values())} territories vaporised.')
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'☢ Detonation! Radius {R}: {sum(owners.values())} territories lost by {len(owners)} countr{"y" if len(owners)==1 else "ies"}.', 'radius': R, 'achievements': ach})

@app.route('/api/fallout')
def fallout_list():
    conn = get_db(); rows = [r['grid_key'] for r in conn.execute('SELECT grid_key FROM fallout WHERE until>?', (int(time.time()),))]; conn.close(); return jsonify(rows)

@app.route('/api/world')
def world_info():
    conn = get_db(); r = conn.execute('SELECT COALESCE(SUM(population),0) p,COUNT(*) c FROM territories WHERE owner_id IS NOT NULL').fetchone(); conn.close()
    return jsonify({'population': r['p'], 'territories': r['c']})

# ── Konami / merge ───────────────────────────────────────────────────────────
@app.route('/api/konami', methods=['POST'])
@require_login
def konami():
    conn = get_db(); conn.execute('UPDATE users SET konami=1 WHERE id=?', (session['user_id'],)); conn.commit(); conn.close(); return jsonify({'success': True})

@app.route('/api/merge/request', methods=['POST'])
@require_login
def merge_request():
    uid = session['user_id']; name = ((request.json or {}).get('username') or '').strip(); conn = get_db()
    if not conn.execute('SELECT konami FROM users WHERE id=?', (uid,)).fetchone()['konami']: conn.close(); return jsonify({'error': '???'}), 403
    t = conn.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE', (name,)).fetchone()
    if not t or t['id'] == uid: conn.close(); return jsonify({'error': 'Player not found'}), 404
    cur = conn.execute("INSERT INTO merges(from_id,to_id,status,ts) VALUES(?,?,'pending',?)", (uid, t['id'], int(time.time())))
    notify_actions(conn, t['id'], 'merge_request', f'🧬 {session["username"]} proposes to MERGE your countries into one (your account would be absorbed into theirs — territories, resources, research, everything).',
        [{'label': '✓ Merge', 'path': '/api/merge/respond', 'body': {'merge_id': cur.lastrowid, 'accept': True}, 'cls': 'btn-success'}, {'label': '✕ No', 'path': '/api/merge/respond', 'body': {'merge_id': cur.lastrowid, 'accept': False}, 'cls': 'btn-danger'}])
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Merge proposal sent'})

def do_merge(conn, keep, gone):
    _leave_faction(conn, gone); g = conn.execute('SELECT * FROM users WHERE id=?', (gone,)).fetchone(); k = conn.execute('SELECT * FROM users WHERE id=?', (keep,)).fetchone()
    cols = ['money', 'food', 'wood', 'metal', 'oil', 'steel', 'uranium', 'gems', 'nukes', 'wins', 'losses', 'chat_count']
    conn.execute('UPDATE users SET ' + ','.join(f'{c}={c}+?' for c in cols) + ' WHERE id=?', [g[c] for c in cols] + [keep])
    for p in POOLS: pool_add(conn, keep, p, g[p])
    rs = sorted(set(json.loads(k['research'] or '[]')) | set(json.loads(g['research'] or '[]'))); conn.execute('UPDATE users SET research=? WHERE id=?', (json.dumps(rs), keep))
    conn.execute('UPDATE territories SET owner_id=? WHERE owner_id=?', (keep, gone))
    conn.execute('UPDATE OR IGNORE embassies SET owner_id=? WHERE owner_id=?', (keep, gone)); conn.execute('UPDATE OR IGNORE embassies SET host_id=? WHERE host_id=?', (keep, gone))
    conn.execute('DELETE FROM embassies WHERE owner_id=? OR host_id=? OR owner_id=host_id', (gone, gone))
    conn.execute('UPDATE OR IGNORE achievements SET user_id=? WHERE user_id=?', (keep, gone)); conn.execute('DELETE FROM achievements WHERE user_id=?', (gone,))
    conn.execute('UPDATE OR IGNORE wonders SET owner_id=? WHERE owner_id=?', (keep, gone)); conn.execute('DELETE FROM wonders WHERE owner_id=?', (gone,))
    conn.execute('DELETE FROM faction_contributions WHERE user_id=?', (gone,))
    for h in conn.execute('SELECT * FROM stock_holdings WHERE user_id=?', (gone,)).fetchall():
        conn.execute('INSERT INTO stock_holdings VALUES(?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET quantity=quantity+excluded.quantity,cost_basis=cost_basis+excluded.cost_basis', (keep,h['symbol'],h['quantity'],h['cost_basis']))
    conn.execute('DELETE FROM stock_holdings WHERE user_id=?', (gone,))
    conn.execute("UPDATE trades SET status='cancelled' WHERE from_id=? OR to_id=?", (gone, gone)); conn.execute("UPDATE loans SET status='returned' WHERE lender_id=? OR borrower_id=?", (gone, gone))
    for t in ('notifications', 'alliances'):
        col = 'user_id' if t == 'notifications' else None
        if col: conn.execute(f'DELETE FROM {t} WHERE {col}=?', (gone,))
    try: conn.execute('DELETE FROM alliances WHERE requester_id=? OR target_id=?', (gone, gone))
    except Exception: pass
    conn.execute("UPDATE merges SET status='cancelled' WHERE status='pending' AND (from_id=? OR to_id=?)",(gone,gone))
    conn.execute('DELETE FROM faction_requests WHERE user_id=?', (gone,)); conn.execute('DELETE FROM users WHERE id=?', (gone,))
    create_notification(conn, keep, 'info', f'🧬 {g["username"]} merged into your country!'); announce(conn, f'🧬 {g["username"]} and {k["username"]} merged into one nation!')

@app.route('/api/merge/respond', methods=['POST'])
@require_login
def merge_respond():
    d = request.json or {}; uid = session['user_id']; conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    m = conn.execute("SELECT * FROM merges WHERE id=? AND to_id=? AND status='pending'", (int(d.get('merge_id', 0)), uid)).fetchone()
    if not m: conn.rollback(); conn.close(); return jsonify({'error': 'Proposal not found'}), 404
    if d.get('accept') and not conn.execute('SELECT 1 FROM users WHERE id=? AND is_banned=0',(m['from_id'],)).fetchone():conn.rollback();conn.close();return jsonify(error='The inviting country is no longer available'),409
    conn.execute('UPDATE merges SET status=? WHERE id=?', ('done' if d.get('accept') else 'declined', m['id']))
    if d.get('accept'):
        try: do_merge(conn, m['from_id'], uid)
        except Exception as e: conn.rollback(); conn.close(); return jsonify({'error': f'Merge failed: {e}'}), 500
        session.clear()
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Merged! Log in with the other account from now on.' if d.get('accept') else 'Declined'})

# ── admin extras (v5) ────────────────────────────────────────────────────────
@app.route('/api/admin/chat_edit', methods=['POST'])
@require_admin
def admin_chat_edit():
    d = request.json or {}; conn = get_db(); conn.execute('UPDATE chat SET message=?,edited=1 WHERE id=?', ((d.get('text') or '')[:200], int(d.get('id', 0)))); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Message edited'})

@app.route('/api/admin/chat_as', methods=['POST'])
@require_admin
def admin_chat_as():
    d = request.json or {}; conn = get_db(); u = conn.execute('SELECT id,username,color FROM users WHERE id=?', (int(d.get('user_id', 0)),)).fetchone()
    text = ' '.join((d.get('message') or '').split())[:200]
    if not u or not text: conn.close(); return jsonify({'error': 'Pick a user and type something'}), 400
    ch = _channel(conn, u['id'], d.get('channel', 'global'))
    if not ch: conn.close(); return jsonify({'error': 'That user has no faction'}), 400
    conn.execute('INSERT INTO chat(channel,user_id,username,color,message,ts) VALUES(?,?,?,?,?,?)', (ch, u['id'], u['username'], u['color'], text, int(time.time()))); conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/clear_fallout', methods=['POST'])
@require_admin
def admin_clear_fallout():
    gk = (request.json or {}).get('grid_key'); conn = get_db()
    if gk: conn.execute('DELETE FROM fallout WHERE grid_key=?', (gk,))
    else: conn.execute('DELETE FROM fallout')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Fallout cleared'})

@app.route('/api/admin/give_resource', methods=['POST'])
@require_admin
def admin_give_resource():
    d = request.json or {}; r = d.get('resource'); uid = int(d.get('user_id', 0)); am = int(d.get('amount', 0)); conn = get_db()
    if r in POOLS: pool_add(conn, uid, r, am)
    elif r in ('money', 'food', 'wood', 'metal', 'oil', 'steel', 'uranium', 'gems', 'nukes'): conn.execute(f'UPDATE users SET {r}=MAX(0,{r}+?) WHERE id=?', (am, uid))
    else: conn.close(); return jsonify({'error': 'Bad resource'}), 400
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Gave {am} {r}'})

@app.route('/api/admin/set_setting', methods=['POST'])
@require_admin
def admin_set_setting():
    d = request.json or {}; k = d.get('key')
    if k not in ('income_mult', 'troop_cost_mult', 'events_enabled', 'nuke_cost'): return jsonify({'error': 'Bad key'}), 400
    v = d.get('value')
    if k != 'events_enabled':
        try:
            if isinstance(v,bool) or not math.isfinite(float(v)): raise ValueError()
        except (ValueError,TypeError,OverflowError): return jsonify({'error': 'Setting must be a finite number'}), 400
    elif str(v) not in ('0','1'):return jsonify({'error': 'Choose 0 or 1 for events'}),400
    if k == 'nuke_cost':
        try: v = max(0, int(float(v)))
        except Exception: return jsonify({'error': 'Bad value'}), 400
    elif k != 'events_enabled':
        try: v = max(0.1, min(float(v), 20))
        except Exception: return jsonify({'error': 'Bad value'}), 400
    conn = get_db(); set_setting(conn, k, v); conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'{k} = {v}'})

def me_extra(conn, u, uid):
    f = None; fid = u['faction_id']
    if fid:
        fr = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
        if fr: f = {'id': fr['id'], 'name': fr['name'], 'tag': fr['tag'], 'is_leader': fr['leader_id'] == uid, 'color': fr['color'], 'mode': fr['mode'], 'techs': [x['tech'] for x in conn.execute('SELECT tech FROM faction_research WHERE faction_id=?', (fid,))]}
    pop = conn.execute('SELECT COALESCE(SUM(population),0) p FROM territories WHERE owner_id=?', (uid,)).fetchone()['p']
    return {'steel': round(u['steel']), 'uranium': round(u['uranium']), 'gems': round(u['gems']), 'nukes': u['nukes'], 'ideology': u['ideology'],
            'capital_key': u['capital_key'], 'konami': bool(u['konami']), 'faction': f, 'population': pop, 'base_color': u['base_color'] or u['color'],
            'ideology_cooldown': max(0, int((u['ideology_ts'] or 0) + 86400 - time.time())) if u['ideology'] else 0,
            'wonders': sorted(my_wonders(conn, uid)), 'nuke_cost': nuke_cost(conn), 'uni_discount': round(research_discount(conn, uid)*100)}

def detail_extra(conn, grid_key, row):
    out = {'fallout': fallout_active(conn, grid_key)}
    if row and row['owner_id']:
        c = conn.execute('SELECT capital_key FROM users WHERE id=?', (row['owner_id'],)).fetchone()
        out['capital'] = bool(c and c['capital_key'] == grid_key); out['invested'] = round(row['invested'] or 0)
    uid = session.get('user_id')
    if uid and (not row or not row['owner_id']):
        try:
            gl, gg = parse_key(grid_key); out['claim'] = claim_price(conn, uid, row['terrain'] if row else get_terrain(gl, gg))
        except Exception: pass
    return out

from features import install_features, religion_for
from migrations import migrate_v6, migrate_v7, migrate_v8, migrate_v9, migrate_v10, migrate_v11, backup_before_upgrade
from expansion import migrate as migrate_v12
from economy import migrate as migrate_v13
backup_before_upgrade(DB_PATH)
init_db(); migrate_v4(); migrate_v5(); migrate_v6(get_db); migrate_v7(get_db); migrate_v8(get_db); migrate_v9(get_db); migrate_v10(get_db); migrate_v11(get_db); migrate_v12(get_db); migrate_v13(get_db)
install_features(globals())

if __name__ == '__main__':
    from waitress import serve
    print('World Conquest: production server. See README.md for host setup.')
    serve(app, host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', 5055)), threads=4)
