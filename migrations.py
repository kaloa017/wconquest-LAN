"""Idempotent v6 upgrade, with a consistent pre-upgrade SQLite backup."""
import sqlite3, time
from contextlib import closing
from pathlib import Path
from config import FACTION_COLORS

def backup_before_upgrade(path):
    p=Path(path)
    if not p.exists(): return
    with closing(sqlite3.connect(path)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
            if conn.execute('SELECT 1 FROM schema_migrations WHERE version=10').fetchone(): return
        backup=p.parent/'backups'/f'{p.stem}-before-v10-{time.time_ns()}.db'
        backup.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(backup)) as dest: conn.backup(dest)

def migrate_v6(get_db):
    c=get_db(); c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,ts INTEGER)')
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=6').fetchone(): c.close();return
    c.execute('BEGIN IMMEDIATE')
    for table, additions in {
        'users': [('auth_version','INTEGER DEFAULT 0'),('religion','TEXT'),('religion_ts','INTEGER DEFAULT 0'),
                  ('display_faction_colors','INTEGER DEFAULT 1'),('share_boats','INTEGER DEFAULT 0'),('share_planes','INTEGER DEFAULT 0'),
                  ('last_seen_version','TEXT DEFAULT ""'),('music_volume','REAL DEFAULT .25'),('music_muted','INTEGER DEFAULT 0'),
                  ('recovery_hash','TEXT'),('reset_code_hash','TEXT'),('reset_code_until','INTEGER DEFAULT 0'),('stock_trade_ts','INTEGER DEFAULT 0')],
        'factions':[('color_slot','INTEGER')], 'chat':[('admin_actor','TEXT')]
    }.items():
        existing={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
        for col,ddl in additions:
            if col not in existing: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
    # Existing fleets are redistributed deterministically, retaining every unit.
    for f in c.execute('SELECT * FROM factions ORDER BY id').fetchall():
        ids=[r['id'] for r in c.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id',(f['id'],))]
        for kind in ('boats','planes'):
            if ids:
                q,r=divmod(f[kind] or 0,len(ids))
                for i,uid in enumerate(ids): c.execute(f'UPDATE users SET {kind}={kind}+? WHERE id=?',(q+(i<r),uid))
                c.execute(f'UPDATE factions SET {kind}=0 WHERE id=?',(f['id'],))
    # Preserve legacy excess factions; block new creation until fewer than eight.
    for slot,f in enumerate(c.execute('SELECT id FROM factions ORDER BY id').fetchall()):
        if slot<8:
            c.execute('UPDATE factions SET color_slot=?,color=? WHERE id=?',(slot,FACTION_COLORS[slot],f['id']))
            c.execute('UPDATE users SET color=? WHERE faction_id=?',(FACTION_COLORS[slot],f['id']))
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS faction_color_unique ON factions(color_slot) WHERE color_slot IS NOT NULL')
    cols={r['name'] for r in c.execute('PRAGMA table_info(wonders)')}
    if 'grid_key' not in cols:
        c.execute('ALTER TABLE wonders RENAME TO wonders_v5')
        c.execute('CREATE TABLE wonders(key TEXT,owner_id INTEGER,ts INTEGER,grid_key TEXT,PRIMARY KEY(key,owner_id))')
        c.execute('INSERT INTO wonders(key,owner_id,ts) SELECT key,owner_id,ts FROM wonders_v5')
        c.execute('DROP TABLE wonders_v5')
    script='''
      CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,ts INTEGER,actor_id INTEGER,actor TEXT,action TEXT,target_id INTEGER,ip TEXT,details TEXT);
      CREATE TABLE IF NOT EXISTS request_stats(client TEXT PRIMARY KEY,user_id INTEGER,ip TEXT,peer_ip TEXT,requests INTEGER DEFAULT 0,last_seen INTEGER);
      CREATE TABLE IF NOT EXISTS faction_contributions(user_id INTEGER PRIMARY KEY,faction_id INTEGER,army INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS map_changes(seq INTEGER PRIMARY KEY AUTOINCREMENT,grid_key TEXT);
      CREATE TABLE IF NOT EXISTS map_epoch(id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER DEFAULT 0);
      INSERT OR IGNORE INTO map_epoch(id,value) VALUES(1,0);
      CREATE TABLE IF NOT EXISTS stock_prices(symbol TEXT PRIMARY KEY,kind TEXT,target_id INTEGER,price REAL,anchor REAL,last_tick INTEGER);
      CREATE TABLE IF NOT EXISTS stock_history(symbol TEXT,ts INTEGER,price REAL,PRIMARY KEY(symbol,ts));
      CREATE TABLE IF NOT EXISTS stock_holdings(user_id INTEGER,symbol TEXT,quantity INTEGER,cost_basis REAL,PRIMARY KEY(user_id,symbol));
      CREATE TABLE IF NOT EXISTS stock_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,symbol TEXT,side TEXT,quantity INTEGER,price REAL,fee REAL,ts INTEGER);
      CREATE TABLE IF NOT EXISTS scheduler_state(id INTEGER PRIMARY KEY CHECK(id=1),next_tick INTEGER);
      CREATE TABLE IF NOT EXISTS eva_deployments(user_id INTEGER PRIMARY KEY,grid_key TEXT,image TEXT);
      INSERT OR IGNORE INTO scheduler_state VALUES(1,0);
      CREATE INDEX IF NOT EXISTS territory_owner ON territories(owner_id);
      CREATE INDEX IF NOT EXISTS users_faction ON users(faction_id);
      CREATE INDEX IF NOT EXISTS notifications_unread ON notifications(user_id,is_read,id);
      CREATE INDEX IF NOT EXISTS trades_active ON trades(status,last_run);
      CREATE INDEX IF NOT EXISTS faction_requests_user ON faction_requests(user_id,faction_id);
      CREATE INDEX IF NOT EXISTS stock_history_lookup ON stock_history(symbol,ts);
      CREATE TRIGGER IF NOT EXISTS tile_insert AFTER INSERT ON territories BEGIN INSERT INTO map_changes(grid_key) VALUES(NEW.grid_key); END;
      CREATE TRIGGER IF NOT EXISTS tile_update AFTER UPDATE OF owner_id,terrain,population,invested ON territories BEGIN INSERT INTO map_changes(grid_key) VALUES(NEW.grid_key); END;
      CREATE TRIGGER IF NOT EXISTS tile_delete AFTER DELETE ON territories BEGIN INSERT INTO map_changes(grid_key) VALUES(OLD.grid_key); END;
      CREATE TRIGGER IF NOT EXISTS building_insert AFTER INSERT ON buildings BEGIN INSERT INTO map_changes(grid_key) VALUES(NEW.grid_key); END;
      CREATE TRIGGER IF NOT EXISTS building_update AFTER UPDATE ON buildings BEGIN INSERT INTO map_changes(grid_key) VALUES(NEW.grid_key); END;
      CREATE TRIGGER IF NOT EXISTS building_delete AFTER DELETE ON buildings BEGIN INSERT INTO map_changes(grid_key) VALUES(OLD.grid_key); END;
      CREATE TRIGGER IF NOT EXISTS user_map_update AFTER UPDATE OF army,color,base_color,username,faction_id,capital_key ON users BEGIN INSERT INTO map_changes(grid_key) SELECT grid_key FROM territories WHERE owner_id=NEW.id; END;
      CREATE TRIGGER IF NOT EXISTS faction_map_update AFTER UPDATE OF army,color ON factions BEGIN INSERT INTO map_changes(grid_key) SELECT t.grid_key FROM territories t JOIN users u ON u.id=t.owner_id WHERE u.faction_id=NEW.id; END;
    '''
    # executescript implicitly commits; execute complete statements to keep the migration atomic.
    statement=''
    for line in script.splitlines(True):
        statement+=line
        if sqlite3.complete_statement(statement):c.execute(statement);statement=''
    for f in c.execute('SELECT id,army FROM factions').fetchall():
        ids=[r['id'] for r in c.execute('SELECT id FROM users WHERE faction_id=? ORDER BY id',(f['id'],))]
        if ids:
            q,r=divmod(f['army'] or 0,len(ids))
            for i,uid in enumerate(ids): c.execute('INSERT OR IGNORE INTO faction_contributions VALUES(?,?,?)',(uid,f['id'],q+(i<r)))
    # Disable only the known default credential; retain the account and its save.
    import hashlib
    from werkzeug.security import generate_password_hash
    for row in c.execute('SELECT id,reset_pin FROM users WHERE reset_pin IS NOT NULL').fetchall():
        if row['reset_pin']:c.execute('UPDATE users SET recovery_hash=?,reset_pin=NULL WHERE id=?',(generate_password_hash(row['reset_pin']),row['id']))
    c.execute('UPDATE users SET password="!reset-required",auth_version=auth_version+1 WHERE username="admin" COLLATE NOCASE AND password=?',(hashlib.sha256(b'admin123').hexdigest(),))
    c.execute('INSERT INTO schema_migrations VALUES(6,?)',(int(time.time()),)); c.commit();c.close()

def migrate_v7(get_db):
    """Add supporter cosmetics; reset old throttles once, retaining later choices."""
    import json
    c=get_db()
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=7').fetchone():c.close();return
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM schema_migrations WHERE version=7').fetchone():c.commit();return
        columns={r['name'] for r in c.execute('PRAGMA table_info(users)')}
        for name,ddl in [('is_donator','INTEGER NOT NULL DEFAULT 0'),('donator_title','TEXT NOT NULL DEFAULT "Supporter"')]:
            if name not in columns:c.execute(f'ALTER TABLE users ADD COLUMN {name} {ddl}')
        c.execute('INSERT OR REPLACE INTO game_settings(key,value) VALUES(?,?)',('rate_limits',json.dumps({'requests':0,'auth':0,'chat':0,'trades':0})))
        # Client pixel sampling used to persist inaccurate coastlines. Owned
        # territory remains intact; new land checks use the bundled raster.
        c.execute('DELETE FROM water_cells')
        c.execute('INSERT INTO schema_migrations VALUES(7,?)',(int(time.time()),))
        c.commit()
    except Exception:
        c.rollback();raise
    finally:c.close()

def migrate_v8(get_db):
    c=get_db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM schema_migrations WHERE version=8').fetchone():c.commit();return
        if 'rank_override' not in {r['name'] for r in c.execute('PRAGMA table_info(users)')}:c.execute('ALTER TABLE users ADD COLUMN rank_override TEXT')
        # Wonder modifiers already apply to the country. Retain ownership while
        # removing the old placement requirement from existing records.
        c.execute('UPDATE wonders SET grid_key=NULL')
        c.execute('INSERT INTO schema_migrations VALUES(8,?)',(int(time.time()),));c.commit()
    except Exception:c.rollback();raise
    finally:c.close()


def migrate_v9(get_db):
    """Split the legacy cosmetic unlock without removing any paid-for access."""
    c=get_db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM schema_migrations WHERE version=9').fetchone():c.commit();return
        for row in c.execute('SELECT owner_id,ts FROM wonders WHERE key="eva"').fetchall():
            for key in ('eva_00','eva_01','eva_02'):
                c.execute('INSERT OR IGNORE INTO wonders(key,owner_id,ts,grid_key) VALUES(?,?,?,NULL)',(key,row['owner_id'],row['ts']))
        c.execute('DELETE FROM wonders WHERE key="eva"')
        c.execute('INSERT INTO schema_migrations VALUES(9,?)',(int(time.time()),));c.commit()
    except Exception:c.rollback();raise
    finally:c.close()


def migrate_v10(get_db):
    c=get_db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM schema_migrations WHERE version=10').fetchone():c.commit();return
        columns={r['name'] for r in c.execute('PRAGMA table_info(users)')}
        for name,ddl in [('ideas_banned','INTEGER NOT NULL DEFAULT 0'),('idea_last_sent','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:c.execute(f'ALTER TABLE users ADD COLUMN {name} {ddl}')
        c.execute('INSERT INTO schema_migrations VALUES(10,?)',(int(time.time()),));c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
