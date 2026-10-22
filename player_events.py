"""Authoritative event classification, durable presentation claims and inbox history."""
import json,time
from flask import jsonify,session,request
import features

POLICY={
 'capital_lost':1,'city_lost':1,'war_declared':1,'faction_kicked':1,'moderation':1,
 'major_battle':1,'attack':1,'nuclear_strike':1,'rocket_strike':1,
 'territory_lost':2,'battle_started':2,'battle_finished':2,'alliance_invite':2,
 'alliance_accepted':2,'alliance_declined':2,'alliance_broken':2,'faction_ally':2,
 'trade_request':2,'loan_request':2,'merge_request':1,'exchange_offer':2,
 'gift':3,'exchange_result':3,'info':4,'away_summary':4,
}

def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=24').fetchone():conn.commit();return
        columns={r['name'] for r in conn.execute('PRAGMA table_info(notifications)')}
        for name,ddl in [('priority','INTEGER NOT NULL DEFAULT 4'),('event_key','TEXT'),('presented_at','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:conn.execute(f'ALTER TABLE notifications ADD COLUMN {name} {ddl}')
        # Old unread events remain available, without replaying years of toasts.
        conn.execute('UPDATE notifications SET presented_at=?',(int(time.time()),))
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS notification_event_unique ON notifications(user_id,event_key) WHERE event_key IS NOT NULL')
        conn.execute('CREATE INDEX IF NOT EXISTS notification_recipient_read ON notifications(user_id,is_read,id)')
        conn.execute('''CREATE TABLE IF NOT EXISTS away_presentations(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,since INTEGER NOT NULL,claimed_at INTEGER NOT NULL,PRIMARY KEY(user_id,since))''')
        conn.execute('INSERT INTO schema_migrations VALUES(24,?)',(int(time.time()),));conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

def emit(conn,uid,kind,message,data=None,event_key=None):
    conn.execute('INSERT OR IGNORE INTO notifications(user_id,type,message,data,priority,event_key) VALUES(?,?,?,?,?,?)',
                 (uid,kind,message,json.dumps(data or {}),POLICY.get(kind,4),event_key))
    # A bounded per-player feed retains both read and unread messages. Presentation
    # claims live on the retained event, independently of explicit read state.
    conn.execute('DELETE FROM notifications WHERE user_id=? AND id NOT IN (SELECT id FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 500)',(uid,uid))

def serialize(row):
    result=dict(row)
    try:result['data']=json.loads(result['data'] or '{}')
    except (ValueError,TypeError):result['data']={}
    return result

def claim_away(conn,uid,since=None):
    saved=conn.execute('SELECT * FROM away_earnings WHERE user_id=?',(uid,)).fetchone()
    if not saved or since is not None and saved['since']!=since:return None
    stamp=int(time.time());cursor=conn.execute('INSERT OR IGNORE INTO away_presentations VALUES(?,?,?)',(uid,saved['since'],stamp))
    if not cursor.rowcount:return None
    summary={**dict(saved),'resources':json.loads(saved['resources'])}
    emit(conn,uid,'away_summary','While you were away: your recorded earnings are saved here.',{'summary':summary},'away:'+str(saved['since']))
    # A returning heartbeat/login may already have advanced last_activity. Acknowledge
    # the authoritative boundary, never a caller-supplied future timestamp.
    conn.execute('UPDATE player_activity SET away_ack_activity=MAX(away_ack_activity,last_activity) WHERE user_id=?',(uid,))
    conn.execute('DELETE FROM away_earnings WHERE user_id=? AND since=?',(uid,saved['since']))
    conn.execute('DELETE FROM away_presentations WHERE user_id=? AND since NOT IN (SELECT since FROM away_presentations WHERE user_id=? ORDER BY since DESC LIMIT 100)',(uid,uid))
    return summary

def install(core):
    app=core['app'];core['create_notification']=emit
    victory=core['apply_victory']
    def captured(conn,uid,key,terrain,tile,a,b):
        owner=tile['owner_id'] if tile else None
        was_capital=bool(owner and conn.execute('SELECT 1 FROM users WHERE id=? AND capital_key=?',(owner,key)).fetchone())
        result=victory(conn,uid,key,terrain,tile,a,b)
        if owner and owner!=uid:
            from cities import city_index
            kind='capital_lost' if was_capital else 'city_lost' if key in city_index() else 'territory_lost'
            actor=core['uname'](conn,uid);seq=conn.execute('SELECT MAX(seq) FROM map_changes').fetchone()[0]
            emit(conn,owner,kind,f'{actor} captured your '+('capital' if was_capital else 'major-city tile' if kind=='city_lost' else 'territory')+f' at {key}.',dict(actor_id=uid,actor_name=actor,grid_key=key),'capture:'+key+':'+str(seq))
        return result
    core['apply_victory']=captured
    def unread():
        conn=features.db();uid=session['user_id']
        rows=conn.execute('SELECT * FROM notifications WHERE user_id=? AND is_read=0 ORDER BY (presented_at=0) DESC,priority,id DESC LIMIT 100',(uid,)).fetchall()
        return jsonify([serialize(r) for r in rows])
    app.view_functions['get_notifications']=core['require_login'](unread)

    @app.post('/api/notifications/present')
    @core['require_login']
    def present():
        ids=features.body().get('ids')
        if not isinstance(ids,list) or len(ids)>100:raise ValueError('Choose up to 100 event IDs')
        ids=list({features.integer(value,1) for value in ids})
        if not ids:return jsonify(events=[])
        conn=features.db();uid=session['user_id'];marks=','.join('?' for _ in ids)
        rows=conn.execute(f'SELECT * FROM notifications WHERE user_id=? AND id IN ({marks}) AND is_read=0 AND presented_at=0 ORDER BY priority,id',(uid,*ids)).fetchall()
        conn.executemany('UPDATE notifications SET presented_at=? WHERE id=? AND user_id=?',[(int(time.time()),r['id'],uid) for r in rows])
        return jsonify(events=[serialize(r) for r in rows])

    @app.get('/api/notifications/history')
    @core['require_login']
    def history():
        before=features.integer(request.args.get('before','9223372036854775807'),1,9223372036854775807)
        rows=features.db().execute('SELECT * FROM notifications WHERE user_id=? AND id<? ORDER BY id DESC LIMIT 50',(session['user_id'],before)).fetchall()
        return jsonify(events=[serialize(r) for r in rows],next_before=rows[-1]['id'] if len(rows)==50 else None)

    @app.post('/api/away/claim')
    @core['require_login']
    def present_away():
        since=features.integer(features.body().get('since'),0,int(time.time()))
        return jsonify(summary=claim_away(features.db(),session['user_id'],since))
