"""Visible-page time credited once per account, independent of resource activity."""
import time
from flask import session,request,jsonify
import features
from config import PLAYTIME_HEARTBEAT_GRACE
core=None

def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        columns={row['name'] for row in conn.execute('PRAGMA table_info(player_activity)')}
        for name in ('play_seconds','play_clock'):
            if name not in columns:conn.execute(f'ALTER TABLE player_activity ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
        conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES(17,?)',(int(time.time()),));conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

def record(conn,uid,visible=True,timestamp=None):
    from activity import state
    stamp=int(time.time()) if timestamp is None else timestamp
    row=state(conn,uid,stamp);previous=row['play_clock']
    elapsed=stamp-previous if previous and 0<=stamp-previous<=PLAYTIME_HEARTBEAT_GRACE else 0
    conn.execute('UPDATE player_activity SET play_seconds=play_seconds+?,play_clock=? WHERE user_id=?',(elapsed,stamp if visible else 0,uid))
    return row['play_seconds']+elapsed

def total(row,stamp):
    elapsed=stamp-row['play_clock'] if row['play_clock'] else 0
    return row['play_seconds']+(elapsed if 0<=elapsed<=PLAYTIME_HEARTBEAT_GRACE else 0)

def list_players():
    conn=core['get_db']();stamp=int(time.time());uid=session['user_id']
    page=features.integer(request.args.get('page',1),1,10000);limit=50
    count=conn.execute('SELECT COUNT(*) FROM users WHERE is_banned=0').fetchone()[0]
    rows=conn.execute('''SELECT u.id,u.username,u.color,COALESCE(p.play_seconds,0) play_seconds,COALESCE(p.play_clock,0) play_clock
        FROM users u LEFT JOIN player_activity p ON p.user_id=u.id WHERE u.is_banned=0
        ORDER BY COALESCE(p.play_seconds,0) DESC,u.username LIMIT ? OFFSET ?''',(limit,(page-1)*limit)).fetchall()
    own=conn.execute('SELECT play_seconds,play_clock FROM player_activity WHERE user_id=?',(uid,)).fetchone()
    return jsonify(mine=total(own,stamp) if own else 0,players=[dict(id=r['id'],username=r['username'],color=r['color'],seconds=r['play_seconds']) for r in rows],page=page,pages=max(1,(count+limit-1)//limit))

def install(namespace):
    global core
    core=namespace
    core['app'].add_url_rule('/api/playtime','player_playtime',core['require_login'](list_players),methods=['GET'])
