"""
World Conquest v4 — Full-Featured Multiplayer Strategy Game
Run:  pip install flask && python app.py
Open: http://localhost:5000
Admin: admin / admin123
Note: Username 'Kasper' (any case) auto-gets admin on registration
"""

from flask import Flask, request, jsonify, session, send_file
import sqlite3, hashlib, random, time, os, json, math
import urllib.request, threading, queue

# ── Spectator tracking ────────────────────────────────────────────────────────
_spectators = {}   # ip -> {flag, country, last_seen}
_geo_cache  = {}   # ip -> {flag, country}  — persists for process lifetime
_geo_queue  = queue.Queue()   # IPs to geo-lookup, processed by one background thread

def _country_flag(code):
    if not code or len(code) != 2: return '🌐'
    try: return chr(0x1F1E6+ord(code[0].upper())-65)+chr(0x1F1E6+ord(code[1].upper())-65)
    except: return '🌐'

def _geo_worker():
    """Single long-lived thread that processes geo lookups from the queue."""
    while True:
        try:
            ip = _geo_queue.get(timeout=60)
            if ip in _geo_cache:
                _geo_queue.task_done(); continue
            if ip in ('127.0.0.1', '::1', ''):
                _geo_cache[ip] = {'flag':'🖥','country':'Localhost','city':''}
                _geo_queue.task_done(); continue
            try:
                url = f'http://ip-api.com/json/{ip}?fields=countryCode,country,city,status'
                with urllib.request.urlopen(url, timeout=4) as r:
                    data = json.loads(r.read())
                if data.get('status') == 'success':
                    _geo_cache[ip] = {'flag':_country_flag(data['countryCode']), 'country':data.get('country','?'), 'city':data.get('city','')}
                else:
                    _geo_cache[ip] = {'flag':'🌐','country':'Unknown'}
            except:
                _geo_cache[ip] = {'flag':'🌐','country':'Unknown'}
            _geo_queue.task_done()
        except queue.Empty:
            continue
        except Exception:
            try: _geo_queue.task_done()
            except: pass

# Start one persistent worker thread (not a new thread per request)
_geo_thread = threading.Thread(target=_geo_worker, daemon=True)
_geo_thread.start()

def _touch_spectator(ip):
    """Record a spectator visit. Geo lookup is async via queue."""
    geo = _geo_cache.get(ip, {'flag':'🌐','country':'?'})
    _spectators[ip] = {**geo, 'last_seen': time.time()}
    if ip not in _geo_cache:
        try: _geo_queue.put_nowait(ip)
        except queue.Full: pass


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'wc_v3_secret_xK9m_2024_!@#')

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'game.db'))

# ── Game Constants ────────────────────────────────────────────────────────────
GRID            = 0.18     # degrees per cell (~20 km)
TROOP_COST      = 8        # money per troop
BOAT_COST       = 800      # money per boat (single-use overseas landing)
PLANE_COST      = 1200     # money per plane (single-use overseas strike)
AUTO_COLLECT_CD = 10       # seconds between auto-accruals per territory
MAX_ACCUM_MINS  = 120      # max offline accrual cap (2hrs)
WIN_THRESHOLD   = 150      # territories to win a round
WIN_COUNTDOWN   = 45       # seconds before game resets after win
CLAIM_COST      = 25       # base claim cost (scales with territory count)
BOAT_RANGE      = 9999        # max cells for naval attack
PLANE_RANGE_DEF = 100        # default plane range (cells)
PLANE_RANGE_BLZ = 120        # plane range with blitzkrieg

AUTO_ADMIN_NAMES = {'Kasper'}
SELL_RATES = {'food': 2, 'wood': 4, 'metal': 6, 'oil': 10}

TERRAIN_RES = {
    'plains':    ('food',   9),
    'forest':    ('wood',   12),
    'mountains': ('metal',  9),
    'desert':    ('money',  7),
    'tundra':    ('metal',  5),
    'city':      ('money',  18),
    'oil':       ('oil',    14),
}

POP_BASE  = {'city':80000,'plains':3000,'forest':1200,'mountains':800,'desert':300,'tundra':150,'oil':900}
POP_RANGE = {'city':420000,'plains':17000,'forest':8000,'mountains':3200,'desert':1700,'tundra':850,'oil':6100}

RANKS = [
    (0,   '🪓', 'Settler'),
    (3,   '⚔',  'Warrior'),
    (10,  '🛡', 'Commander'),
    (25,  '🏰', 'Warlord'),
    (60,  '👑', 'Emperor'),
    (150, '🌍', 'Conqueror'),
]

RESEARCH_TREE = {
    'agri':      {'name':'Agriculture',      'icon':'🌾','cost':100,'branch':'economy', 'requires':[],           'desc':'+25% food & wood yield'},
    'trade':     {'name':'Trade Routes',     'icon':'💹','cost':150,'branch':'economy', 'requires':['agri'],     'desc':'+15% money yield'},
    'industry':  {'name':'Industrialization','icon':'⚙','cost':250,'branch':'economy', 'requires':['trade'],    'desc':'+25% metal & oil yield'},
    'iron':      {'name':'Iron Weapons',     'icon':'⚔','cost':100,'branch':'military','requires':[],           'desc':'+20% attack strength'},
    'castle':    {'name':'Castle Walls',     'icon':'🏰','cost':100,'branch':'military','requires':[],           'desc':'+30% defense bonus'},
    'gunpowder': {'name':'Gunpowder',        'icon':'💥','cost':250,'branch':'military','requires':['iron'],     'desc':'+30% attack, -20% troop cost'},
    'shipyard':  {'name':'Shipbuilding',     'icon':'⚓','cost':200,'branch':'naval',   'requires':[],           'desc':'Unlocks Boats (cross-water attacks)'},
    'airforce':  {'name':'Air Force',        'icon':'✈','cost':400,'branch':'naval',   'requires':['shipyard'], 'desc':'Unlocks Planes (long-range attacks)'},
    'blitz':     {'name':'Blitzkrieg',       'icon':'⚡','cost':600,'branch':'naval',   'requires':['airforce'], 'desc':'Planes range +3, +20% power'},
}

PLAYER_COLORS = [
    '#e74c3c','#3498db','#2ecc71','#9b59b6','#e67e22','#1abc9c',
    '#e91e63','#00bcd4','#ff5722','#8bc34a','#ff9800','#f06292',
    '#4db6ac','#aed581','#ba68c8','#d35400','#16a085','#8e44ad',
    '#c0392b','#27ae60',
]

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

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

    # Seed admin
    ph = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute('''INSERT OR IGNORE INTO users
                 (username,password,is_admin,food,wood,metal,oil,money,color)
                 VALUES (?,?,1,9999,9999,9999,9999,99999,'#ffd700')''', ('admin', ph))

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
    if abs(lat) > 65:      return 'tundra'
    elif abs(lat) > 55:    opts=['tundra','tundra','forest','mountains','plains']
    elif abs(lat) > 40:    opts=['plains','plains','forest','forest','mountains','city']
    elif abs(lat) > 20:    opts=['plains','desert','desert','mountains','city','oil','forest']
    else:                  opts=['forest','forest','forest','plains','desert','city','oil']
    return opts[h % len(opts)]

def get_population(terrain, glat, glng):
    h = simple_hash(glat, glng)
    return POP_BASE[terrain] + (h % POP_RANGE[terrain])

def parse_key(k):
    p = k.split(','); return int(p[0]), int(p[1])

def adj_keys(gl, gg):
    return [f"{gl+dl},{gg+dg}" for dl in (-1,0,1) for dg in (-1,0,1) if dl or dg]

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
    return hashlib.sha256(pw.encode()).hexdigest()

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

def auto_collect(uid, conn):
    now = int(time.time())
    rsch = user_research(conn, uid)
    rows = conn.execute(
        'SELECT t.grid_key,t.terrain,t.last_collected,b.type bt,b.level bl FROM territories t '
        'LEFT JOIN buildings b ON b.grid_key=t.grid_key WHERE t.owner_id=?', (uid,)).fetchall()
    ev = ev_type(conn); fb = faction_bonus(conn, uid)
    gm = float(get_setting(conn, 'income_mult', 1) or 1)
    totals = {'food':0.,'wood':0.,'metal':0.,'oil':0.,'money':0.}
    troops = 0.; updated = []
    for row in rows:
        elapsed = now - (row['last_collected'] or 0)
        if elapsed < AUTO_COLLECT_CD: continue
        rt, rate = TERRAIN_RES[row['terrain']]
        minutes  = min(elapsed/60., MAX_ACCUM_MINS)
        m = res_mult(rt, rsch) * fb * gm
        if 'banking' in rsch and rt == 'money': m *= 1.10 / 1.0
        if ev == 'gold_rush' and rt == 'money': m *= 1.5
        if ev == 'harvest' and rt in ('food', 'wood'): m *= 1.5
        if ev == 'mining' and rt in ('metal', 'oil'): m *= 1.5
        if row['bt'] == 'workshop': m *= 1 + 0.25*row['bl']
        totals[rt] += rate * m * minutes
        if row['bt'] == 'market': totals['money'] += 6*row['bl']*minutes*gm
        if row['bt'] == 'barracks': troops += 3*row['bl']*minutes
        updated.append(row['grid_key'])
    if updated:
        for k in updated:
            conn.execute('UPDATE territories SET last_collected=? WHERE grid_key=?',(now,k))
        sets = ','.join(f'{r}={r}+?' for r in totals)
        conn.execute(f'UPDATE users SET {sets} WHERE id=?',list(totals.values())+[uid])
        if troops >= 1:
            cap = army_cap(conn, uid, rsch)
            conn.execute('UPDATE users SET army=MIN(?,army+?) WHERE id=? AND army<?', (cap, int(troops), uid, cap))

# ── Win-condition check ───────────────────────────────────────────────────────

def check_win(uid, conn):
    """Win when a single player reaches WIN_THRESHOLD territories."""
    existing = get_setting(conn,'winner_id')
    if existing: return False
    # Find the player with the most territories
    leader = conn.execute('''
        SELECT u.id, u.username, COUNT(t.id) tc FROM users u
        JOIN territories t ON t.owner_id=u.id
        WHERE u.is_banned=0
        GROUP BY u.id
        ORDER BY tc DESC LIMIT 1
    ''').fetchone()
    if not leader or leader['tc'] < WIN_THRESHOLD:
        return False
    set_setting(conn,'winner_id', leader['id'])
    set_setting(conn,'winner_name', leader['username'])
    set_setting(conn,'win_time', int(time.time()))
    return True

def do_game_reset(conn):
    conn.execute('UPDATE territories SET owner_id=NULL,garrison=0,boats=0,planes=0')
    conn.execute('DELETE FROM buildings'); conn.execute('DELETE FROM achievements WHERE 0')
    conn.execute('UPDATE users SET army=10,boats=0,planes=0,morale=50')
    conn.execute('UPDATE users SET food=100,wood=100,metal=100,oil=25,money=200,research=\'[]\'')
    conn.execute("DELETE FROM game_settings WHERE key IN ('winner_id','winner_name','win_time')")
    conn.execute('DELETE FROM battle_log')
    conn.execute("INSERT OR IGNORE INTO announcements (message,author) VALUES ('🔄 A new round has started! Claim territories and conquer the world.','System')")

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
    is_admin = 1 if un.lower() in AUTO_ADMIN_NAMES else 0
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
        'army': u['army'], 'army_cap': army_cap(conn_me, uid, set(rsch)), 'boats': u['boats'], 'planes': u['planes'],
        'morale': u['morale'], 'wins': u['wins'], 'losses': u['losses'],
        'daily_ready': u['last_daily'] != int(time.time()//86400), 'daily_streak': u['daily_streak'],
        'faction': fac, 'event': ev_me, 'weather_slot': cur_slot(),
        'troop_cost': troop_cost2(conn_me, set(rsch)), 'claim_cost': claim_cost_for(tc, set(rsch)),
        'boat_range': boat_range(conn_me, uid, set(rsch)), 'plane_range': plane_range(set(rsch)),
        'uni_discount': min(30, 8*sum_levels(conn_me, uid, 'university')),
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
    if u['password'] != ph(curr):
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
    if len(new)<3 or len(new)>20: return jsonify({'error':'Username must be 3–20 characters'}),400
    conn = get_db()
    u = conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if u['password'] != ph(pw):
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
    if u['password'] != ph(pw):
        conn.close()
        return jsonify({'error':'Incorrect password'}),401
    conn.execute('UPDATE users SET reset_pin=? WHERE id=?',(pin, session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Recovery PIN set!'})

# ── Online players ────────────────────────────────────────────────────────────

@app.route('/api/spectate', methods=['POST'])
def spectate():
    """Called by guests to register their presence on the map."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
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
    for ip, s in list(_spectators.items()):
        if now - s['last_seen'] < 180:
            guests.append({'username': f"{s['flag']} {ip}", 'color':'#607090',
                           'is_admin':False,'territories':0,'type':'spectator',
                           'flag': s['flag'], 'country': s.get('country','?'),
                           'city': s.get('city',''), 'ip': ip})
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
    have = round(u[rt])
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
    disc = min(0.30, 0.08*sum_levels(conn, session['user_id'], 'university'))
    info = {**info, 'cost': int(info['cost']*(1-disc))}
    if round(u['money']) < info['cost']:
        conn.close()
        return jsonify({'error':f'Need {info["cost"]}💰, have {round(u["money"])}💰'}),400
    rsch.add(tech)
    conn.execute('UPDATE users SET research=?,money=money-? WHERE id=?',
                 (json.dumps(list(rsch)), info['cost'], session['user_id']))
    award_achievements(conn, session['user_id'])
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':f'Researched {info["name"]}!'})

# ── Territories ───────────────────────────────────────────────────────────────

def _army_map(conn):
    rows = conn.execute('SELECT u.id,u.army,(SELECT COUNT(*) FROM territories WHERE owner_id=u.id) n FROM users u').fetchall()
    return {r['id']: (r['army'], max(1, r['n'])) for r in rows}

@app.route('/api/territories')
def get_territories():
    conn = get_db(); am = _army_map(conn)
    rows = conn.execute('''
        SELECT t.grid_key,t.owner_id,t.terrain,t.population,u.username,u.color,u.faction_id,
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
                    'building':r['bt'],'blevel':r['bl'],'tag':r['ftag']})
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
    out.update({'coastal': coastal, 'water': water, 'weather': wx})
    conn.close(); return jsonify(out)

@app.route('/api/territory/claim', methods=['POST'])
@require_login
def claim_territory():
    d  = request.json or {}
    gk = d.get('grid_key','').strip()
    if not gk: return jsonify({'error':'grid_key required'}),400
    try: gl, gg = parse_key(gk)
    except: return jsonify({'error':'Invalid grid_key'}),400

    conn = get_db()
    ingest_water(conn, d.get('water'))
    if is_water(conn, gk):
        conn.commit(); conn.close(); return jsonify({'error':'You cannot claim open water'}),400
    existing = conn.execute('SELECT owner_id FROM territories WHERE grid_key=?',(gk,)).fetchone()
    if existing and existing['owner_id']:
        conn.close(); return jsonify({'error':'Territory already owned'}),409

    # Claim cost check (1000 if player owns 300+ territories, else 30)
    mc = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?',(session['user_id'],)).fetchone()['c']
    cost = claim_cost_for(mc, user_research(conn, session['user_id']))
    user_money = conn.execute('SELECT money FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if round(user_money['money']) < cost:
        conn.close(); return jsonify({'error':f'Need {cost}💰 to claim (you have {round(user_money["money"])}💰)'}),400

    if mc > 0:
        ak = adj_keys(gl, gg)
        owned_adj = conn.execute(
            f'SELECT COUNT(*) c FROM territories WHERE owner_id=? AND grid_key IN ({",".join("?"*len(ak))})',
            [session['user_id']]+ak
        ).fetchone()['c']
        if owned_adj == 0:
            conn.close(); return jsonify({'error':'Must be adjacent to one of your territories'}),400

    terrain = get_terrain(gl, gg)
    pop     = get_population(terrain, gl, gg)
    now     = int(time.time())
    if existing:
        conn.execute('UPDATE territories SET owner_id=?,garrison=0,boats=0,planes=0,population=?,last_collected=? WHERE grid_key=?',
                     (session['user_id'],pop,now,gk))
    else:
        conn.execute('INSERT INTO territories (grid_key,owner_id,terrain,garrison,boats,planes,population,last_collected) VALUES (?,?,?,0,0,0,?,?)',
                     (gk,session['user_id'],terrain,pop,now))

    conn.execute('UPDATE users SET money=money-? WHERE id=?',(cost,session['user_id']))
    check_win(session['user_id'], conn)
    award_achievements(conn, session['user_id'])
    conn.commit(); conn.close()
    return jsonify({'success':True,'terrain':terrain,'population':pop,'message':f'Territory claimed! ({terrain})','cost':cost})

# ══════════════════════════════════════════════════════════════════════════════
#  v4 — national army, modifiers, buildings, factions, chat, events, daily, quests
# ══════════════════════════════════════════════════════════════════════════════

BOAT_COST_M, BOAT_COST_W, BOAT_CAP = 250, 20, 12      # money, wood, troops carried
PLANE_COST_M, PLANE_COST_X, PLANE_COST_O, PLANE_POWER = 700, 40, 30, 8
BOAT_RANGE_BASE, PLANE_RANGE_BASE = 4, 5
FACTION_COST = 500
CHAT_COOLDOWN = 1.5

TERRAIN_DEF = {'mountains':1.35,'forest':1.2,'city':1.25,'plains':1.0,'desert':0.95,'tundra':1.1,'oil':1.05}

# weather — deterministic per 10-minute slot + region, so server & clients agree with zero network load
WEATHER_TABLE = {
    'polar':    [('clear',30),('snow',40),('fog',15),('storm',15)],
    'temperate':[('clear',45),('rain',25),('fog',12),('snow',10),('storm',8)],
    'tropical': [('clear',40),('rain',30),('storm',20),('fog',10)],
}
WEATHER_FX = {  # attacker land multiplier, air multiplier
    'clear':(1.00,1.00),'rain':(0.93,0.90),'fog':(0.95,0.75),'snow':(0.88,0.85),'storm':(0.82,0.60),
}
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

BUILDINGS = {
  'barracks':  {'name':'Barracks',  'icon':'🏕','desc':'+3 troops/min per level','cost':{'money':150,'wood':60,'metal':30}},
  'fort':      {'name':'Fortress',  'icon':'🏯','desc':'+25% defense on this tile per level','cost':{'money':200,'metal':80}},
  'market':    {'name':'Market',    'icon':'🏪','desc':'+6💰/min per level','cost':{'money':180,'wood':40}},
  'workshop':  {'name':'Workshop',  'icon':'🔨','desc':'+25% yield of this tile per level','cost':{'money':200,'wood':50,'metal':40}},
  'port':      {'name':'Port',      'icon':'⚓','desc':'Boats launch from here (coastal only). Lv2+ = +1 range','cost':{'money':250,'wood':100},'needs':'shipyard','coastal':True},
  'airport':   {'name':'Airport',   'icon':'🛫','desc':'Planes launch from here. Lv2+ = +1 range','cost':{'money':500,'metal':120,'oil':40},'needs':'airforce'},
  'university':{'name':'University','icon':'🎓','desc':'-8% research cost per level (max -30% total)','cost':{'money':300,'wood':60,'metal':40}},
  'hospital':  {'name':'Hospital',  'icon':'🏥','desc':'-10% battle casualties per level (max -30% total)','cost':{'money':250,'wood':50}},
}
BUILD_MAX_LEVEL = 3
def build_cost(btype, level):  # cost to build level (level = new level, 1..3)
    mult = {1:1,2:2.2,3:4.5}[level]
    return {k:int(v*mult) for k,v in BUILDINGS[btype]['cost'].items()}

RESEARCH_TREE.update({
  'tactics':   {'name':'Tactics',       'icon':'🧠','cost':180,'branch':'military','requires':['iron'],      'desc':'Morale never drops below 30; +5% attack'},
  'medicine':  {'name':'Field Medicine','icon':'⚕','cost':200,'branch':'military','requires':['castle'],    'desc':'-25% casualties'},
  'logistics': {'name':'Logistics',     'icon':'📦','cost':220,'branch':'military','requires':['iron'],      'desc':'+25% army capacity'},
  'espionage': {'name':'Espionage',     'icon':'🕵','cost':260,'branch':'military','requires':['tactics'],   'desc':'See exact enemy defense & modifiers'},
  'engineering':{'name':'Engineering',  'icon':'🏗','cost':200,'branch':'economy', 'requires':['trade'],     'desc':'-20% building costs'},
  'banking':   {'name':'Banking',       'icon':'🏦','cost':300,'branch':'economy', 'requires':['trade'],     'desc':'-20% claim cost, +10% money'},
  'navigation':{'name':'Navigation',    'icon':'🧭','cost':260,'branch':'naval',   'requires':['shipyard'],  'desc':'Boat range +2, boats carry +4 troops'},
  'jets':      {'name':'Jet Engines',   'icon':'🛩','cost':500,'branch':'naval',   'requires':['airforce'],  'desc':'Plane range +2'},
  'radar':     {'name':'Radar',         'icon':'📡','cost':350,'branch':'naval',   'requires':['airforce'],  'desc':'-30% damage from air strikes against you'},
})

EVENTS = {
  'gold_rush': {'name':'Gold Rush','icon':'🪙','desc':'Money yield +50%'},
  'harvest':   {'name':'Bumper Harvest','icon':'🌾','desc':'Food & wood yield +50%'},
  'mining':    {'name':'Mining Boom','icon':'⛏','desc':'Metal & oil yield +50%'},
  'conscription':{'name':'Conscription Drive','icon':'📯','desc':'Troops cost -40%'},
  'war_fever': {'name':'War Fever','icon':'🔥','desc':'All attacks +15% stronger'},
  'cold_snap': {'name':'Cold Snap','icon':'🧊','desc':'All attacks -12% weaker'},
}
EVENT_LEN, EVENT_GAP = 1800, 600

ACHIEVEMENTS = {
  'first_blood':{'name':'First Blood','icon':'🩸','desc':'Win a battle','reward':100},
  'wins_10':    {'name':'Veteran','icon':'🎖','desc':'Win 10 battles','reward':300},
  'wins_50':    {'name':'Warmonger','icon':'☠','desc':'Win 50 battles','reward':1000},
  'land_10':    {'name':'Landowner','icon':'🏡','desc':'Own 10 territories','reward':200},
  'land_30':    {'name':'Duke','icon':'🏰','desc':'Own 30 territories','reward':600},
  'land_75':    {'name':'Emperor','icon':'👑','desc':'Own 75 territories','reward':2000},
  'builder':    {'name':'Builder','icon':'🏗','desc':'Own 5 buildings','reward':300},
  'scholar':    {'name':'Scholar','icon':'📚','desc':'Research 6 technologies','reward':400},
  'admiral':    {'name':'Admiral','icon':'🚢','desc':'Win a naval landing','reward':400},
  'ace':        {'name':'Ace','icon':'✈','desc':'Win an air strike','reward':500},
  'rich':       {'name':'Tycoon','icon':'💎','desc':'Hold 10,000💰','reward':500},
  'faction':    {'name':'Team Player','icon':'🚩','desc':'Join a faction','reward':150},
  'chatty':     {'name':'Diplomat','icon':'💬','desc':'Send 10 chat messages','reward':100},
  'daily_7':    {'name':'Loyal','icon':'📅','desc':'7-day login streak','reward':500},
}

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

def army_cap(conn, uid, rsch=None):
    rsch = rsch if rsch is not None else user_research(conn, uid)
    n = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?', (uid,)).fetchone()['c']
    cap = 60 + 30*n + 40*sum_levels(conn, uid, 'barracks')
    return int(cap * (1.25 if 'logistics' in rsch else 1.0))

def casualty_mult(conn, uid, rsch):
    m = 1.0
    if 'medicine' in rsch: m *= 0.75
    m *= 1 - min(0.30, 0.10*sum_levels(conn, uid, 'hospital'))
    return m

def troop_cost2(conn, rsch):
    c = TROOP_COST
    if 'gunpowder' in rsch: c = c*0.75
    if ev_type(conn) == 'conscription': c *= 0.6
    c *= float(get_setting(conn, 'troop_cost_mult', 1) or 1)
    return max(1, int(round(c)))

def claim_cost_for(mc, rsch):
    cost = 1200 if mc>=200 else 400 if mc>=100 else 150 if mc>=50 else 80 if mc>=20 else 40 if mc>=8 else CLAIM_COST
    return int(cost*0.8) if 'banking' in rsch else cost

def boat_range(conn, uid, rsch):
    return BOAT_RANGE_BASE + (2 if 'navigation' in rsch else 0)
def plane_range(rsch):
    return PLANE_RANGE_DEF + (3 if 'blitz' in rsch else 0) + (2 if 'jets' in rsch else 0)

def can_afford(u, cost): return all(round(u[k]) >= v for k, v in cost.items())
def pay(conn, uid, cost):
    for k, v in cost.items(): conn.execute(f'UPDATE users SET {k}={k}-? WHERE id=?', (v, uid))
def fmt_cost(cost): return ' '.join(f'{v}{ {"money":"💰","wood":"🌲","metal":"⚙","oil":"🛢","food":"🌾"}[k]}' for k, v in cost.items())

def defense_of(conn, owner_id, gk, terrain):
    """Defending force at one tile: share of the owner's national army + militia, with modifiers."""
    if not owner_id:
        return {'base': 3 + (random.Random(simple_hash(*parse_key(gk))).randint(0, 4)), 'mods': [], 'mult': 1.0, 'owner_army': 0}
    row = conn.execute('SELECT army,research FROM users WHERE id=?', (owner_id,)).fetchone()
    n = max(1, conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?', (owner_id,)).fetchone()['c'])
    rs = set(json.loads(row['research'] or '[]'))
    base = row['army'] / (n ** 0.55) + 3        # +3 militia per tile
    mods = []; mult = 1.0
    x = def_bonus(rs); mods.append(('Home ground' + (' + Castle Walls' if 'castle' in rs else ''), x)); mult *= x
    x = TERRAIN_DEF.get(terrain, 1.0)
    if x != 1.0: mods.append((f'Terrain ({terrain})', x)); mult *= x
    b = conn.execute('SELECT level FROM buildings WHERE grid_key=? AND type="fort"', (gk,)).fetchone()
    if b: x = 1 + 0.25*b['level']; mods.append((f'Fortress Lv{b["level"]}', x)); mult *= x
    return {'base': base, 'mods': mods, 'mult': mult, 'owner_army': row['army']}

def attack_mods(conn, uid, rsch, kind, tgl, tgg, rng=None):
    """List of (label, multiplier) for the attacker."""
    mods = []
    if 'iron' in rsch: mods.append(('Iron Weapons', 1.2))
    if 'gunpowder' in rsch: mods.append(('Gunpowder', 1.3))
    if 'tactics' in rsch: mods.append(('Tactics', 1.05))
    if kind == 'air' and 'blitz' in rsch: mods.append(('Blitzkrieg', 1.2))
    if kind == 'naval' and 'navigation' in rsch: mods.append(('Navigation', 1.1))
    w = weather_for(cur_slot(), tgl, tgg)
    wf = WEATHER_FX[w][1 if kind == 'air' else 0]
    if wf != 1.0: mods.append((f'Weather ({w})', wf))
    u = conn.execute('SELECT morale FROM users WHERE id=?', (uid,)).fetchone()
    morale = u['morale'] if u else 50
    if 'tactics' in rsch: morale = max(30, morale)
    mm = 0.90 + 0.25*(morale/100.0)
    mods.append((f'Morale ({morale})', round(mm, 3)))
    e = ev_type(conn)
    if e == 'war_fever': mods.append(('War Fever', 1.15))
    if e == 'cold_snap': mods.append(('Cold Snap', 0.88))
    fb = faction_bonus(conn, uid)
    if fb > 1.0: mods.append(('Faction unity', round(1 + (fb-1)/2, 3)))
    if kind == 'naval': mods.append(('Amphibious landing', 0.9))
    return mods, w

def prod(mods):
    p = 1.0
    for _, m in mods: p *= m
    return p

def resolve_battle(conn, uid, uname, target_key, force, kind, from_key, carried_units=0, dry=False):
    """Core combat. `force` = raw attacking strength (troops, or boat/plane power). Returns dict."""
    tgl, tgg = parse_key(target_key)
    tt = conn.execute('SELECT * FROM territories WHERE grid_key=?', (target_key,)).fetchone()
    terrain = tt['terrain'] if tt else get_terrain(tgl, tgg)
    def_oid = tt['owner_id'] if tt else None
    rsch = user_research(conn, uid)
    amods, weather = attack_mods(conn, uid, rsch, kind, tgl, tgg)
    d = defense_of(conn, def_oid, target_key, terrain)
    dmods = list(d['mods'])
    if kind == 'air' and def_oid:
        drs = user_research(conn, def_oid)
        if 'radar' in drs: dmods.append(('Radar', 1.3))
    A = force * prod(amods); D = d['base'] * prod(dmods)
    # luck: ±8% each side
    ra = 1.0 if dry else random.uniform(0.92, 1.08); rd = 1.0 if dry else random.uniform(0.92, 1.08)
    A *= ra; D *= rd
    odds = A / (A + D) if (A + D) > 0 else 1
    return {'A': A, 'D': D, 'odds': odds, 'weather': weather, 'terrain': terrain, 'def_oid': def_oid,
            'def_force': d['base'], 'amods': amods, 'dmods': dmods, 'tt': tt, 'rsch': rsch,
            'owner_army': d['owner_army']}

def apply_victory(conn, uid, tk, terrain, tt, tgl, tgg):
    pop = tt['population'] if tt else get_population(terrain, tgl, tgg)
    now = int(time.time())
    if tt:
        conn.execute('UPDATE territories SET owner_id=?,garrison=0,boats=0,planes=0,last_collected=? WHERE grid_key=?', (uid, now, tk))
        conn.execute('DELETE FROM buildings WHERE grid_key=? AND random()%3=0', (tk,))  # some buildings burn down
    else:
        conn.execute('INSERT INTO territories (grid_key,owner_id,terrain,garrison,boats,planes,population,last_collected) VALUES (?,?,?,0,0,0,?,?)',
                     (tk, uid, terrain, pop, now))

def morale_update(conn, uid, win):
    conn.execute('UPDATE users SET morale=MAX(5,MIN(100,morale+?)),wins=wins+?,losses=losses+? WHERE id=?',
                 (8 if win else -12, 1 if win else 0, 0 if win else 1, uid))

def battle_response(res, extra=None):
    d = {'success': True, 'attacker_wins': res['win'], 'result': 'victory' if res['win'] else 'defeat', 'message': res['msg'],
         'breakdown': {'attack': round(res['A'], 1), 'defense': round(res['D'], 1), 'weather': res['weather'],
                       'atk_mods': [[a, round(b, 2)] for a, b in res['amods']], 'def_mods': [[a, round(b, 2)] for a, b in res['dmods']]}}
    if extra: d.update(extra)
    return jsonify(d)

def do_assault(conn, uid, uname, fk, tk, force, kind, units_label, committed_troops, fleet_back=0.0):
    """Shared assault flow for land / naval / air. Troops & fleet already validated."""
    tgl, tgg = parse_key(tk)
    r = resolve_battle(conn, uid, uname, tk, force, kind, fk)
    rsch = r['rsch']; cm = casualty_mult(conn, uid, rsch)
    win = r['A'] > r['D']
    def_name = 'wilderness'
    if r['def_oid']:
        du = conn.execute('SELECT username FROM users WHERE id=?', (r['def_oid'],)).fetchone()
        def_name = du['username'] if du else 'unknown'
    ratio = r['D'] / max(r['A'], 0.01)
    if win:
        loss_frac = min(0.8, (0.12 + 0.55*min(1.0, ratio)) * cm)
        lost = min(committed_troops - 1, int(committed_troops*loss_frac)) if committed_troops > 1 else 0
        survivors = max(1, committed_troops - lost) if committed_troops else 0
        conn.execute('UPDATE users SET army=army+? WHERE id=?', (survivors, uid))
        apply_victory(conn, uid, tk, r['terrain'], r['tt'], tgl, tgg)
        if r['def_oid']:
            dl = int(r['owner_army'] * min(0.25, 0.04 + 0.05*(r['A']/max(r['D'], 1))))
            conn.execute('UPDATE users SET army=MAX(0,army-?) WHERE id=?', (dl, r['def_oid']))
        msg = f'Victory! Took {def_name}\'s tile. Lost {lost}, {survivors} troops hold the line.'
        res_lost = lost
    else:
        lost = committed_troops
        # survivors of a failed assault: a few retreat
        retreat = int(committed_troops * max(0.0, 0.25 - 0.2*min(1.0, ratio-1)) * (2-cm)) if committed_troops else 0
        retreat = max(0, min(committed_troops-1, retreat)) if committed_troops > 1 else 0
        conn.execute('UPDATE users SET army=army+? WHERE id=?', (retreat, uid))
        lost = committed_troops - retreat
        if r['def_oid']:
            dl = int(r['owner_army'] * min(0.12, 0.02 + 0.04*(r['A']/max(r['D'], 1))))
            conn.execute('UPDATE users SET army=MAX(0,army-?) WHERE id=?', (dl, r['def_oid']))
        msg = f'Defeat! {def_name} held. {lost} troops lost, {retreat} retreated.'
        res_lost = lost
    morale_update(conn, uid, win)
    conn.execute('INSERT INTO battle_log (attacker,defender,grid_key,result,mode,details) VALUES (?,?,?,?,?,?)',
                 (uname, def_name, tk, 'victory' if win else 'defeat', kind,
                  f'{units_label}: {round(r["A"])} vs {round(r["D"])} · {r["weather"]} · {r["terrain"]}'))
    if r['def_oid']:
        create_notification(conn, r['def_oid'], 'attack',
            f'⚔ {uname} {"captured" if win else "attacked"} your {r["terrain"]} tile ({tk}) by {kind} — {"you lost it!" if win else "you held!"}')
    if win: check_win(uid, conn)
    r.update({'win': win, 'msg': msg, 'lost': res_lost})
    return r

# ── Troops / army ───────────────────────────────────────────────────────────
@app.route('/api/troops/build', methods=['POST'])
@require_login
def build_troops():
    d = request.json or {}; uid = session['user_id']
    am = max(1, min(int(d.get('amount', 1)), 500))
    conn = get_db()
    rsch = user_research(conn, uid)
    cap = army_cap(conn, uid, rsch)
    u = conn.execute('SELECT money,army FROM users WHERE id=?', (uid,)).fetchone()
    am = min(am, cap - u['army'])
    if am <= 0:
        conn.close(); return jsonify({'error': f'Army at capacity ({u["army"]}/{cap}). Claim land or build Barracks to raise it.'}), 400
    cost = am * troop_cost2(conn, rsch)
    if round(u['money']) < cost:
        conn.close(); return jsonify({'error': f'Need {cost}💰, have {round(u["money"])}💰'}), 400
    conn.execute('UPDATE users SET money=money-?,army=army+? WHERE id=?', (cost, am, uid))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Recruited {am} troops for {cost}💰'})

@app.route('/api/troops/move', methods=['POST'])
@require_login
def move_troops():   # kept for compatibility: the army is national now
    return jsonify({'error': 'Your army is now one national force — no need to move troops!'}), 400

@app.route('/api/combat/preview', methods=['POST'])
@require_login
def combat_preview():
    d = request.json or {}; uid = session['user_id']
    tk = d.get('target_key', ''); kind = d.get('kind', 'land'); n = max(1, int(d.get('amount', 1)))
    try: parse_key(tk)
    except Exception: return jsonify({'error': 'bad key'}), 400
    conn = get_db()
    force = n if kind == 'land' else n*(BOAT_CAP + (4 if 'navigation' in user_research(conn, uid) else 0)) if kind == 'naval' else n*PLANE_POWER
    r = resolve_battle(conn, uid, session['username'], tk, force, kind, d.get('from_key', ''), dry=True)
    rs = r['rsch']; spy = 'espionage' in rs
    out = {'odds': round(r['odds']*100), 'weather': r['weather'], 'attack': round(r['A'], 1),
           'atk_mods': [[a, round(b, 2)] for a, b in r['amods']]}
    if spy or not r['def_oid']:
        out.update({'defense': round(r['D'], 1), 'def_mods': [[a, round(b, 2)] for a, b in r['dmods']]})
    else:  # fuzzy intel without espionage
        out.update({'defense_est': [int(r['D']*0.7), int(r['D']*1.3)], 'odds': None})
        out['odds_est'] = [round(100*r['A']/(r['A']+r['D']*1.3)), round(100*r['A']/(r['A']+r['D']*0.7))]
    conn.close(); return jsonify(out)

@app.route('/api/attack', methods=['POST'])
@require_login
def attack():
    d = request.json or {}; uid = session['user_id']
    fk = d.get('from_key', '').strip(); tk = d.get('target_key', '').strip()
    sent = max(1, int(d.get('troops', 1)))
    try:
        fl, fg = parse_key(fk); tl, tg = parse_key(tk)
        if fk == tk or max(abs(fl-tl), abs(fg-tg)) > 1: return jsonify({'error': 'Target must be adjacent to your attacking tile'}), 400
    except Exception: return jsonify({'error': 'Invalid keys'}), 400
    conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id=?', (fk, uid)).fetchone():
            conn.rollback(); conn.close(); return jsonify({'error': 'You do not own the attacking territory'}), 403
        if is_water(conn, tk):
            conn.rollback(); conn.close(); return jsonify({'error': 'That is open water. You need ships.'}), 400
        u = conn.execute('SELECT army FROM users WHERE id=?', (uid,)).fetchone()
        if u['army'] < sent:
            conn.rollback(); conn.close(); return jsonify({'error': f'Only {u["army"]} troops in your army'}), 400
        tt = conn.execute('SELECT owner_id FROM territories WHERE grid_key=?', (tk,)).fetchone()
        if tt and tt['owner_id'] == uid: conn.rollback(); conn.close(); return jsonify({'error': 'Cannot attack your own territory'}), 400
        if tt and tt['owner_id'] and are_allied(uid, tt['owner_id'], conn):
            conn.rollback(); conn.close(); return jsonify({'error': '🤝 Cannot attack an ally or faction mate!'}), 400
        conn.execute('UPDATE users SET army=army-? WHERE id=?', (sent, uid))
        r = do_assault(conn, uid, session['username'], fk, tk, sent, 'land', f'{sent} troops', sent)
        ach = award_achievements(conn, uid)
        conn.commit(); conn.close()
        return battle_response(r, {'achievements': ach})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({'error': f'Battle failed: {e}'}), 500

# ── Boats ───────────────────────────────────────────────────────────────────
@app.route('/api/boats/build', methods=['POST'])
@require_login
def build_boats():
    d = request.json or {}; uid = session['user_id']
    am = max(1, min(int(d.get('amount', 1)), 50)); conn = get_db()
    if 'shipyard' not in user_research(conn, uid):
        conn.close(); return jsonify({'error': 'Research Shipbuilding first'}), 400
    if sum_levels(conn, uid, 'port') == 0:
        conn.close(); return jsonify({'error': 'You need a Port (on a coastal tile) to build boats'}), 400
    cost = {'money': am*BOAT_COST_M, 'wood': am*BOAT_COST_W}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost); conn.execute('UPDATE users SET boats=boats+? WHERE id=?', (am, uid))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Built {am} boat(s) for {fmt_cost(cost)}'})

@app.route('/api/boats/attack', methods=['POST'])
@require_login
def boats_attack():
    d = request.json or {}; uid = session['user_id']
    fk = d.get('from_key', '').strip(); tk = d.get('target_key', '').strip()
    n = max(1, int(d.get('boats', 1)))
    conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    def bail(msg, code=400): conn.rollback(); conn.close(); return jsonify({'error': msg}), code
    try:
        ingest_water(conn, d.get('water'))
        b = conn.execute('SELECT level FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE b.grid_key=? AND b.type="port" AND t.owner_id=?', (fk, uid)).fetchone()
        if not b: return bail('Boats must launch from one of your Ports')
        if not is_coastal(conn, fk): return bail('This port is not on the coast — boats need water')
        rsch = user_research(conn, uid)
        if cell_distance(fk, tk) <= 1: return bail('Target is adjacent — use a land attack')
        if is_water(conn, tk): return bail('You can\'t land on open water')
        if not is_coastal(conn, tk): return bail('Landing site isn\'t on a coast (or coast unscouted) — pick a coastal tile')
        u = conn.execute('SELECT boats,army FROM users WHERE id=?', (uid,)).fetchone()
        if u['boats'] < n: return bail(f'You only have {u["boats"]} boat(s)')
        cap = BOAT_CAP + (4 if 'navigation' in rsch else 0)
        troops = min(u['army'], n*cap)
        if troops < 1: return bail('No troops available to load')
        tt = conn.execute('SELECT owner_id FROM territories WHERE grid_key=?', (tk,)).fetchone()
        if tt and tt['owner_id'] == uid: return bail('Cannot attack your own territory')
        if tt and tt['owner_id'] and are_allied(uid, tt['owner_id'], conn): return bail('🤝 Cannot attack an ally or faction mate!')
        conn.execute('UPDATE users SET army=army-?,boats=boats-? WHERE id=?', (troops, n, uid))
        r = do_assault(conn, uid, session['username'], fk, tk, troops, 'naval', f'{n} boats/{troops} troops', troops)
        back = 0
        if r['win']:
            back = max(0, int(round(n*0.8)))
            conn.execute('UPDATE users SET boats=boats+? WHERE id=?', (back, uid))
        ach = award_achievements(conn, uid)
        conn.commit(); conn.close()
        return battle_response(r, {'boats_back': back, 'troops_loaded': troops, 'achievements': ach})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({'error': f'Naval operation failed: {e}'}), 500

# ── Planes ──────────────────────────────────────────────────────────────────
@app.route('/api/planes/build', methods=['POST'])
@require_login
def build_planes():
    d = request.json or {}; uid = session['user_id']
    am = max(1, min(int(d.get('amount', 1)), 30)); conn = get_db()
    if 'airforce' not in user_research(conn, uid):
        conn.close(); return jsonify({'error': 'Research Air Force first'}), 400
    if sum_levels(conn, uid, 'airport') == 0:
        conn.close(); return jsonify({'error': 'You need an Airport to build planes'}), 400
    cost = {'money': am*PLANE_COST_M, 'metal': am*PLANE_COST_X, 'oil': am*PLANE_COST_O}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost); conn.execute('UPDATE users SET planes=planes+? WHERE id=?', (am, uid))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Built {am} plane(s) for {fmt_cost(cost)}'})

@app.route('/api/planes/attack', methods=['POST'])
@require_login
def planes_attack():
    d = request.json or {}; uid = session['user_id']
    fk = d.get('from_key', '').strip(); tk = d.get('target_key', '').strip()
    n = max(1, int(d.get('planes', 1)))
    conn = get_db(); conn.execute('BEGIN IMMEDIATE')
    def bail(msg, code=400): conn.rollback(); conn.close(); return jsonify({'error': msg}), code
    try:
        ingest_water(conn, d.get('water'))
        b = conn.execute('SELECT level FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE b.grid_key=? AND b.type="airport" AND t.owner_id=?', (fk, uid)).fetchone()
        if not b: return bail('Planes must take off from one of your Airports')
        rsch = user_research(conn, uid)
        rng = plane_range(rsch) + (b['level']-1)
        dist = cell_distance(fk, tk)
        if dist <= 1: return bail('Target is adjacent — use a land attack')
        if dist > rng: return bail(f'Out of range ({dist} > {rng} cells). Build an airport closer.')
        if is_water(conn, tk): return bail('Nothing to capture over open water')
        u = conn.execute('SELECT planes,army FROM users WHERE id=?', (uid,)).fetchone()
        if u['planes'] < n: return bail(f'You only have {u["planes"]} plane(s)')
        paras = min(u['army'], n*5)
        if paras < 1: return bail('No paratroopers available')
        tt = conn.execute('SELECT owner_id FROM territories WHERE grid_key=?', (tk,)).fetchone()
        if tt and tt['owner_id'] == uid: return bail('Cannot attack your own territory')
        if tt and tt['owner_id'] and are_allied(uid, tt['owner_id'], conn): return bail('🤝 Cannot attack an ally or faction mate!')
        conn.execute('UPDATE users SET army=army-?,planes=planes-? WHERE id=?', (paras, n, uid))
        force = n*PLANE_POWER * (min(1.0, paras/(n*5)) * 0.5 + 0.5)
        r = do_assault(conn, uid, session['username'], fk, tk, force, 'air', f'{n} planes/{paras} paras', paras)
        back = int(round(n*0.7)) if r['win'] else int(n*0.2)
        conn.execute('UPDATE users SET planes=planes+? WHERE id=?', (back, uid))
        ach = award_achievements(conn, uid)
        conn.commit(); conn.close()
        return battle_response(r, {'planes_back': back, 'achievements': ach})
    except Exception as e:
        conn.rollback(); conn.close(); return jsonify({'error': f'Air strike failed: {e}'}), 500

# ── Buildings ───────────────────────────────────────────────────────────────
@app.route('/api/building/build', methods=['POST'])
@require_login
def building_build():
    d = request.json or {}; uid = session['user_id']
    gk = d.get('grid_key', ''); bt = d.get('type', '')
    if bt not in BUILDINGS: return jsonify({'error': 'Unknown building'}), 400
    conn = get_db()
    ingest_water(conn, d.get('water'))
    t = conn.execute('SELECT 1 FROM territories WHERE grid_key=? AND owner_id=?', (gk, uid)).fetchone()
    if not t: conn.close(); return jsonify({'error': 'You do not own this territory'}), 403
    info = BUILDINGS[bt]; rsch = user_research(conn, uid)
    if info.get('needs') and info['needs'] not in rsch:
        conn.close(); return jsonify({'error': f'Requires research: {RESEARCH_TREE[info["needs"]]["name"]}'}), 400
    cur = conn.execute('SELECT * FROM buildings WHERE grid_key=?', (gk,)).fetchone()
    if cur and cur['type'] != bt: conn.close(); return jsonify({'error': 'Tile already has a different building — demolish it first'}), 400
    if info.get('coastal') and not is_coastal(conn, gk):
        conn.close(); return jsonify({'error': 'Ports can only be built on the coast'}), 400
    lvl = (cur['level'] if cur else 0) + 1
    if lvl > BUILD_MAX_LEVEL: conn.close(); return jsonify({'error': 'Already max level'}), 400
    cost = build_cost(bt, lvl)
    if 'engineering' in rsch: cost = {k: int(v*0.8) for k, v in cost.items()}
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not can_afford(u, cost): conn.close(); return jsonify({'error': f'Need {fmt_cost(cost)}'}), 400
    pay(conn, uid, cost)
    if cur: conn.execute('UPDATE buildings SET level=? WHERE grid_key=?', (lvl, gk))
    else: conn.execute('INSERT INTO buildings(grid_key,type,level) VALUES(?,?,1)', (gk, bt))
    ach = award_achievements(conn, uid)
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'{info["name"]} {"upgraded to Lv"+str(lvl) if cur else "built"} ({fmt_cost(cost)})', 'achievements': ach})

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

# ── Faction ─────────────────────────────────────────────────────────────────
def faction_dict(conn, f):
    mem = conn.execute('SELECT u.id,u.username,u.color,(SELECT COUNT(*) FROM territories WHERE owner_id=u.id) tc FROM users u WHERE u.faction_id=? ORDER BY tc DESC', (f['id'],)).fetchall()
    return {'id': f['id'], 'name': f['name'], 'tag': f['tag'], 'leader_id': f['leader_id'], 'treasury': round(f['treasury']),
            'members': [{'id': m['id'], 'username': m['username'], 'color': m['color'], 'territories': m['tc']} for m in mem],
            'territories': sum(m['tc'] for m in mem), 'bonus_pct': round(min(15, 2*(len(mem)-1)))}

@app.route('/api/faction/list')
@require_login
def faction_list():
    conn = get_db()
    rows = conn.execute('SELECT f.*,(SELECT COUNT(*) FROM users WHERE faction_id=f.id) mc,'
        '(SELECT COUNT(*) FROM territories t JOIN users u ON u.id=t.owner_id WHERE u.faction_id=f.id) tc FROM factions f ORDER BY tc DESC').fetchall()
    out = [{'id': r['id'], 'name': r['name'], 'tag': r['tag'], 'members': r['mc'], 'territories': r['tc']} for r in rows]
    conn.close(); return jsonify(out)

@app.route('/api/faction/info')
@require_login
def faction_info():
    conn = get_db()
    u = conn.execute('SELECT faction_id FROM users WHERE id=?', (session['user_id'],)).fetchone()
    f = conn.execute('SELECT * FROM factions WHERE id=?', (u['faction_id'],)).fetchone() if u['faction_id'] else None
    out = faction_dict(conn, f) if f else None
    if out: out['rally_ready_in'] = max(0, int(get_setting(conn, f'rally_{f["id"]}', 0) or 0) - int(time.time()))
    conn.close(); return jsonify({'faction': out})

@app.route('/api/faction/create', methods=['POST'])
@require_login
def faction_create():
    d = request.json or {}; uid = session['user_id']
    name = (d.get('name') or '').strip(); tag = (d.get('tag') or '').strip().upper()
    if not (3 <= len(name) <= 24) or not (2 <= len(tag) <= 4) or not tag.isalnum():
        return jsonify({'error': 'Name 3–24 chars, tag 2–4 letters/digits'}), 400
    conn = get_db(); u = conn.execute('SELECT money,faction_id FROM users WHERE id=?', (uid,)).fetchone()
    if u['faction_id']: conn.close(); return jsonify({'error': 'Leave your faction first'}), 400
    if round(u['money']) < FACTION_COST: conn.close(); return jsonify({'error': f'Founding a faction costs {FACTION_COST}💰'}), 400
    try:
        cur = conn.execute('INSERT INTO factions(name,tag,leader_id) VALUES(?,?,?)', (name, tag, uid))
    except sqlite3.IntegrityError:
        conn.close(); return jsonify({'error': 'Name or tag already taken'}), 409
    conn.execute('UPDATE users SET money=money-?,faction_id=? WHERE id=?', (FACTION_COST, cur.lastrowid, uid))
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Faction [{tag}] {name} founded!', 'achievements': ach})

@app.route('/api/faction/join', methods=['POST'])
@require_login
def faction_join():
    uid = session['user_id']; fid = int((request.json or {}).get('faction_id', 0)); conn = get_db()
    u = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    if u['faction_id']: conn.close(); return jsonify({'error': 'Leave your faction first'}), 400
    f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
    if not f: conn.close(); return jsonify({'error': 'Faction not found'}), 404
    if faction_members(conn, fid) >= 12: conn.close(); return jsonify({'error': 'Faction is full (12)'}), 400
    conn.execute('UPDATE users SET faction_id=? WHERE id=?', (fid, uid))
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Joined [{f["tag"]}] {f["name"]}', 'achievements': ach})

def _leave(conn, uid):
    u = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    fid = u['faction_id']
    if not fid: return
    conn.execute('UPDATE users SET faction_id=NULL WHERE id=?', (uid,))
    f = conn.execute('SELECT * FROM factions WHERE id=?', (fid,)).fetchone()
    if f and f['leader_id'] == uid:
        nxt = conn.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id LIMIT 1', (fid,)).fetchone()
        if nxt: conn.execute('UPDATE factions SET leader_id=? WHERE id=?', (nxt['id'], fid))
        else: conn.execute('DELETE FROM factions WHERE id=?', (fid,))

@app.route('/api/faction/leave', methods=['POST'])
@require_login
def faction_leave():
    conn = get_db(); _leave(conn, session['user_id']); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'You left the faction'})

@app.route('/api/faction/kick', methods=['POST'])
@require_login
def faction_kick():
    uid = session['user_id']; tid = int((request.json or {}).get('user_id', 0)); conn = get_db()
    me_ = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    f = conn.execute('SELECT * FROM factions WHERE id=?', (me_['faction_id'],)).fetchone() if me_['faction_id'] else None
    if not f or f['leader_id'] != uid: conn.close(); return jsonify({'error': 'Only the leader can kick'}), 403
    if tid == uid: conn.close(); return jsonify({'error': 'Use Leave instead'}), 400
    conn.execute('UPDATE users SET faction_id=NULL WHERE id=? AND faction_id=?', (tid, f['id']))
    create_notification(conn, tid, 'info', f'You were removed from [{f["tag"]}] {f["name"]}')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Member removed'})

@app.route('/api/faction/donate', methods=['POST'])
@require_login
def faction_donate():
    uid = session['user_id']; am = int((request.json or {}).get('amount', 0)); conn = get_db()
    u = conn.execute('SELECT money,faction_id FROM users WHERE id=?', (uid,)).fetchone()
    if not u['faction_id']: conn.close(); return jsonify({'error': 'Not in a faction'}), 400
    if am < 1 or round(u['money']) < am: conn.close(); return jsonify({'error': 'Invalid amount'}), 400
    conn.execute('UPDATE users SET money=money-? WHERE id=?', (am, uid))
    conn.execute('UPDATE factions SET treasury=treasury+? WHERE id=?', (am, u['faction_id']))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Donated {am}💰 to the treasury'})

@app.route('/api/faction/rally', methods=['POST'])
@require_login
def faction_rally():
    uid = session['user_id']; conn = get_db()
    me_ = conn.execute('SELECT faction_id FROM users WHERE id=?', (uid,)).fetchone()
    f = conn.execute('SELECT * FROM factions WHERE id=?', (me_['faction_id'],)).fetchone() if me_['faction_id'] else None
    if not f or f['leader_id'] != uid: conn.close(); return jsonify({'error': 'Only the leader can call a rally'}), 403
    if f['treasury'] < 1500: conn.close(); return jsonify({'error': 'Rally costs 1500💰 from the treasury'}), 400
    nxt = int(get_setting(conn, f'rally_{f["id"]}', 0) or 0)
    if nxt > time.time(): conn.close(); return jsonify({'error': f'Rally on cooldown ({int(nxt-time.time())//60} min)'}), 400
    conn.execute('UPDATE factions SET treasury=treasury-1500 WHERE id=?', (f['id'],))
    conn.execute('UPDATE users SET morale=100 WHERE faction_id=?', (f['id'],))
    set_setting(conn, f'rally_{f["id"]}', int(time.time()) + 3600)
    for m in conn.execute('SELECT id FROM users WHERE faction_id=?', (f['id'],)).fetchall():
        create_notification(conn, m['id'], 'info', f'📯 [{f["tag"]}] rally! Your morale is at maximum.')
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': 'Rally called — every member is at 100 morale!'})

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
    if since: rows = conn.execute('SELECT * FROM chat WHERE channel=? AND id>? ORDER BY id LIMIT 100', (key, since)).fetchall()
    else: rows = list(reversed(conn.execute('SELECT * FROM chat WHERE channel=? ORDER BY id DESC LIMIT 60', (key,)).fetchall()))
    conn.close()
    msgs = [{'id': r['id'], 'user': r['username'], 'color': r['color'], 'text': r['message'], 'ts': r['ts'], 'uid': r['user_id']} for r in rows]
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
    conn.execute('INSERT INTO chat(channel,user_id,username,color,message,ts) VALUES(?,?,?,?,?,?)', (key, uid, u['username'], u['color'], text, int(time.time())))
    conn.execute('UPDATE users SET chat_count=chat_count+1 WHERE id=?', (uid,))
    conn.execute('DELETE FROM chat WHERE id < (SELECT MAX(id)-1500 FROM chat)')
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'achievements': ach})

# ── Daily bonus & achievements ──────────────────────────────────────────────
def award_achievements(conn, uid):
    u = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    tc = conn.execute('SELECT COUNT(*) c FROM territories WHERE owner_id=?', (uid,)).fetchone()['c']
    nb = conn.execute('SELECT COUNT(*) c FROM buildings b JOIN territories t ON t.grid_key=b.grid_key WHERE t.owner_id=?', (uid,)).fetchone()['c']
    nr = len(json.loads(u['research'] or '[]'))
    last = conn.execute("SELECT mode FROM battle_log WHERE attacker=? AND result='victory' ORDER BY id DESC LIMIT 1", (u['username'],)).fetchone()
    have = {r['key'] for r in conn.execute('SELECT key FROM achievements WHERE user_id=?', (uid,))}
    checks = {'first_blood': u['wins'] >= 1, 'wins_10': u['wins'] >= 10, 'wins_50': u['wins'] >= 50, 'land_10': tc >= 10,
              'land_30': tc >= 30, 'land_75': tc >= 75, 'builder': nb >= 5, 'scholar': nr >= 6,
              'admiral': bool(last and last['mode'] == 'naval'), 'ace': bool(last and last['mode'] == 'air'),
              'rich': u['money'] >= 10000, 'faction': bool(u['faction_id']), 'chatty': u['chat_count'] >= 10,
              'daily_7': u['daily_streak'] >= 7}
    new = []
    for k, ok in checks.items():
        if ok and k not in have:
            conn.execute('INSERT OR IGNORE INTO achievements(user_id,key,ts) VALUES(?,?,?)', (uid, k, int(time.time())))
            conn.execute('UPDATE users SET money=money+? WHERE id=?', (ACHIEVEMENTS[k]['reward'], uid))
            create_notification(conn, uid, 'info', f'🏅 Achievement: {ACHIEVEMENTS[k]["name"]} (+{ACHIEVEMENTS[k]["reward"]}💰)')
            new.append({'key': k, **ACHIEVEMENTS[k]})
    return new

@app.route('/api/achievements')
@require_login
def achievements_list():
    conn = get_db(); have = {r['key'] for r in conn.execute('SELECT key FROM achievements WHERE user_id=?', (session['user_id'],))}
    conn.close()
    return jsonify([{'key': k, **v, 'done': k in have} for k, v in ACHIEVEMENTS.items()])

@app.route('/api/daily/claim', methods=['POST'])
@require_login
def daily_claim():
    uid = session['user_id']; day = int(time.time() // 86400); conn = get_db()
    u = conn.execute('SELECT last_daily,daily_streak FROM users WHERE id=?', (uid,)).fetchone()
    if u['last_daily'] == day: conn.close(); return jsonify({'error': 'Already claimed today — come back tomorrow!'}), 400
    streak = (u['daily_streak'] + 1) if u['last_daily'] == day-1 else 1
    s = min(streak, 7); money = 100 + 50*s; extra = {'food': 30*s, 'wood': 30*s, 'metal': 15*s, 'oil': 8*s}
    conn.execute('UPDATE users SET last_daily=?,daily_streak=?,money=money+?,food=food+?,wood=wood+?,metal=metal+?,oil=oil+?,army=army+? WHERE id=?',
                 (day, streak, money, extra['food'], extra['wood'], extra['metal'], extra['oil'], 2*s, uid))
    ach = award_achievements(conn, uid); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Day {streak} reward: {money}💰 + supplies + {2*s} troops!', 'achievements': ach})

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

@app.route('/api/admin/set_setting', methods=['POST'])
@require_admin
def admin_set_setting():
    d = request.json or {}; k = d.get('key')
    if k not in ('income_mult', 'troop_cost_mult', 'events_enabled'): return jsonify({'error': 'Bad key'}), 400
    v = d.get('value'); 
    if k != 'events_enabled':
        try: v = max(0.1, min(float(v), 20))
        except Exception: return jsonify({'error': 'Bad value'}), 400
    conn = get_db(); set_setting(conn, k, v); conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'{k} = {v}'})

@app.route('/api/admin/give_resource', methods=['POST'])
@require_admin
def admin_give_resource():
    d = request.json or {}; r = d.get('resource'); 
    if r not in ('money', 'food', 'wood', 'metal', 'oil', 'army', 'boats', 'planes'): return jsonify({'error': 'Bad resource'}), 400
    conn = get_db(); conn.execute(f'UPDATE users SET {r}=MAX(0,{r}+?) WHERE id=?', (int(d.get('amount', 0)), int(d.get('user_id', 0))))
    conn.commit(); conn.close(); return jsonify({'success': True, 'message': f'Gave {d.get("amount")} {r}'})

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
    conn.execute('UPDATE users SET faction_id=NULL WHERE faction_id=?', (fid,)); conn.execute('DELETE FROM factions WHERE id=?', (fid,))
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
    if round(sender['money']) < amount:
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
        SELECT u.username,u.color,u.is_admin,
               COUNT(t.id) territories,
               COALESCE(SUM(t.population),0) total_pop, u.money, u.army, u.wins, f.tag
        FROM users u LEFT JOIN territories t ON t.owner_id=u.id LEFT JOIN factions f ON f.id=u.faction_id
        WHERE u.is_banned=0
        GROUP BY u.id ORDER BY territories DESC LIMIT 20
    ''').fetchall()
    conn.close()
    result = []
    for r in rows:
        rank = get_rank(r['territories'])
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

# ── Game status (win condition) ───────────────────────────────────────────────

@app.route('/api/game/status')
def game_status():
    conn = get_db()
    wid   = get_setting(conn,'winner_id')
    wname = get_setting(conn,'winner_name')
    wtime = get_setting(conn,'win_time')
    if wid and wtime:
        elapsed = time.time() - float(wtime)
        if elapsed >= WIN_COUNTDOWN:
            do_game_reset(conn); conn.commit(); conn.close()
            return jsonify({'status':'reset','message':'A new round has started!'})
        conn.close()
        return jsonify({'status':'winner','winner':wname,
                        'reset_in': WIN_COUNTDOWN-int(elapsed),
                        'threshold': WIN_THRESHOLD})
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
    return jsonify({'status':'playing','threshold':WIN_THRESHOLD,'leader':leader_info,'event':ev,'next_weather_in':600-int(time.time()%600)})

# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/api/admin/users')
@require_admin
def admin_users():
    conn = get_db()
    rows = conn.execute('''
        SELECT u.id,u.username,u.is_admin,u.is_banned,u.created_at,u.money,u.color,u.last_seen,
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
    if not new or len(new)<3 or len(new)>20:
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

init_db(); migrate_v4()

if __name__ == '__main__':
    print("\n" + "="*56)
    print("  ⚔   World Conquest v3")
    print("="*56)
    print("  URL     :  http://localhost:5000")
    print("  Admin   :  admin / admin123")
    print("  Auto-mod:  Register as 'Kasper' for admin")
    print(f"  Win at  :  {WIN_THRESHOLD} territories")
    print("="*56 + "\n")
    port = int(os.environ.get('PORT', 5000))
    # use_reloader=False avoids multiprocessing semaphore leaks in dev
    app.run(debug=os.environ.get('DEBUG') == '1', host='0.0.0.0', port=port, use_reloader=False)
