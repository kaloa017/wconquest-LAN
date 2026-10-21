"""Exact-address game bans and a single public spectator heartbeat."""
import ipaddress
import threading
import time
from flask import request,session,jsonify
import features

core=None
_lock=threading.Lock()
_cache={}

def invalidate():
    with _lock:_cache.clear()

def blocked(ip):
    identity=core['DB_PATH'];now=time.time()
    with _lock:
        cached=_cache.get(identity)
        if not cached or now-cached[0]>=15:
            conn=core['get_db']()
            try:addresses={r['ip']:r['expires_at'] for r in conn.execute('SELECT ip,expires_at FROM ip_bans WHERE expires_at=0 OR expires_at>?',(int(now),))}
            finally:conn.close()
            cached=(now,addresses);_cache[identity]=cached
    return ip in cached[1] and (not cached[1][ip] or cached[1][ip]>now)

def bans():
    conn=core['get_db']();now=int(time.time())
    if request.method=='POST':
        d=features.body()
        try:ip=str(ipaddress.ip_address(str(d.get('ip','')).strip()))
        except ValueError:raise ValueError('Enter an exact IPv4 or IPv6 address')
        if d.get('confirm') is not True:raise ValueError('Confirm the IP restriction')
        if d.get('action')=='remove':
            conn.execute('DELETE FROM ip_bans WHERE ip=?',(ip,))
        elif d.get('action')=='ban':
            if ip==request.remote_addr or ipaddress.ip_address(ip).is_loopback:raise ValueError('You cannot block your current address or localhost')
            reason=str(d.get('reason','')).strip()[:300]
            if not reason:raise ValueError('Enter a moderation reason')
            minutes=features.integer(d.get('minutes',60),0,525600)
            conn.execute('INSERT OR REPLACE INTO ip_bans VALUES(?,?,?,?,?)',(ip,reason,now,now+minutes*60 if minutes else 0,session['user_id']))
        else:raise ValueError('Choose ban or remove')
        features.audit(conn,'ip_restriction_'+d['action'],details={'ip':ip})
        # Cache invalidation happens after the successful request commits.
        from flask import g
        g.ip_bans_changed=True
        return jsonify(success=True,message='IP restriction updated')
    return jsonify(bans=[dict(r) for r in conn.execute('SELECT ip,reason,created_at,expires_at FROM ip_bans WHERE expires_at=0 OR expires_at>? ORDER BY created_at DESC',(now,))])

def snapshot():
    # Dynamic guest refreshes are combined; static map chunks remain cached and
    # are requested separately only when the player explores a new region.
    core['spectate']()
    delta=features.map_sync().get_json()
    online=core['online_users']().get_json()
    fallout=core['fallout_list']().get_json()
    from advertisements import public
    banner=public().get_json()['banner']
    return jsonify(map=delta,online=online,fallout=fallout,advertisement=banner)

def install(namespace):
    global core
    core=namespace;app=core['app']
    app.add_url_rule('/api/admin/ip-bans','ip_bans',core['require_admin'](bans),methods=['GET','POST'])
    app.add_url_rule('/api/spectator/sync','spectator_snapshot',snapshot)
    @app.before_request
    def restrict_ip():
        if request.path=='/' or request.path.startswith('/api/'):
            if blocked(request.remote_addr or ''):return jsonify(error='Access restricted by the host'),403
    app.before_request_funcs[None].remove(restrict_ip)
    app.before_request_funcs[None].insert(0,restrict_ip)
    @app.after_request
    def reset_bans(response):
        from flask import g
        if getattr(g,'ip_bans_changed',False):invalidate()
        return response
