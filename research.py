"""One server-timed research project per country, with lab speed settled incrementally."""
import json,time,math
from flask import request,session,jsonify
import features
from config import RESEARCH_TREE,LAB_SPEED_PER_LEVEL,LAB_MAX_SPEED_BONUS
core=None

def speed(conn,uid):return 1+min(LAB_MAX_SPEED_BONUS,core['sum_levels'](conn,uid,'laboratory')*LAB_SPEED_PER_LEVEL)

def tick(conn,uid,stamp=None):
    stamp=int(time.time()) if stamp is None else stamp
    row=conn.execute('SELECT * FROM research_projects WHERE user_id=?',(uid,)).fetchone()
    if not row:return None
    remaining=max(0,row['remaining']-max(0,stamp-row['last_tick'])*row['speed'])
    if remaining<=0:
        u=conn.execute('SELECT research FROM users WHERE id=?',(uid,)).fetchone()
        if not u:return None
        completed=set(json.loads(u['research'] or '[]'));completed.add(row['tech'])
        conn.execute('UPDATE users SET research=? WHERE id=?',(json.dumps(sorted(completed)),uid))
        conn.execute('DELETE FROM research_projects WHERE user_id=?',(uid,))
        core['create_notification'](conn,uid,'success','Research completed: '+RESEARCH_TREE[row['tech']]['name'])
        return None
    current_speed=speed(conn,uid)
    if stamp!=row['last_tick'] or current_speed!=row['speed']:
        conn.execute('UPDATE research_projects SET remaining=?,last_tick=?,speed=? WHERE user_id=?',(remaining,stamp,current_speed,uid))
    return dict(tech=row['tech'],remaining_seconds=math.ceil(remaining/current_speed),speed=current_speed,progress=1-remaining/row['total'])

def status():
    conn=core['get_db']();uid=session['user_id'];project=tick(conn,uid)
    discount=core['research_discount'](conn,uid)
    return jsonify(research=list(core['user_research'](conn,uid)),tree={key:{**item,'effective_cost':int(item['cost']*(1-discount))} for key,item in RESEARCH_TREE.items()},project=project,speed=speed(conn,uid))

def start():
    conn=core['get_db']();uid=session['user_id'];key=features.body().get('tech');project=tick(conn,uid)
    if project:raise ValueError('Finish your current research project first')
    if not isinstance(key,str) or key not in RESEARCH_TREE:raise ValueError('Unknown technology')
    info=RESEARCH_TREE[key];completed=core['user_research'](conn,uid)
    if key in completed:raise ValueError('Already researched')
    if not set(info['requires'])<=completed:raise ValueError('Complete the connected prerequisite technologies first')
    core['auto_collect'](uid,conn);cost=int(info['cost']*(1-core['research_discount'](conn,uid)))
    u=conn.execute('SELECT money FROM users WHERE id=?',(uid,)).fetchone()
    if u['money']<cost:raise ValueError('Not enough money for this research')
    conn.execute('UPDATE users SET money=money-? WHERE id=?',(cost,uid));duration=info['duration_seconds']
    conn.execute('INSERT INTO research_projects VALUES(?,?,?,?,?,?,?)',(uid,key,duration,duration,int(time.time()),speed(conn,uid),cost))
    return jsonify(success=True,message='Research started: '+info['name'],project=tick(conn,uid))

def install(namespace):
    global core
    core=namespace;app=core['app'];original=core['user_research']
    def completed(conn,uid):
        tick(conn,uid);return original(conn,uid)
    core['user_research']=completed
    app.view_functions['get_research']=core['require_login'](status)
    app.view_functions['unlock_research']=core['require_login'](start)
    @app.before_request
    def settle():
        uid=session.get('user_id')
        if uid and request.path.startswith('/api/'):
            tick(core['get_db'](),uid)
