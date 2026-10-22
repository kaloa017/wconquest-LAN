"""One shared UTC-day claim: projected weekly cash or a stable three-resource bundle."""
import hashlib,hmac,random,time,math
from flask import jsonify,session,request
import features

def offer(core,conn,uid):
    user=conn.execute('SELECT last_daily,daily_streak FROM users WHERE id=?',(uid,)).fetchone()
    day=int(time.time()//86400);streak=user['daily_streak']+1 if user['last_daily']==day-1 else 1;scale=min(streak,7)
    rates,_,_=core['income_rates'](conn,uid)
    from space import income,unlocked
    if unlocked(conn,uid):
        for resource,value in income(conn,uid).items():rates[resource]=rates.get(resource,0)+value
    key=core['app'].secret_key;key=key.encode() if isinstance(key,str) else key
    seed=hmac.new(key,f'daily:{uid}:{day}'.encode(),hashlib.sha256).digest()
    chosen=random.Random(seed).sample(['food','wood','metal','oil','steel','uranium','gems'],3)
    minimum={'food':30,'wood':30,'metal':15,'oil':8,'steel':5,'uranium':1,'gems':1}
    def amount(resource,floor):
        value=rates.get(resource,0)*10080*.1
        if not math.isfinite(value):raise ValueError('Income is unavailable; ask the host to check production settings')
        return max(floor,int(value))
    return dict(day=day,ready=user['last_daily']!=day,streak=streak if user['last_daily']!=day else user['daily_streak'],
        money=amount('money',100+50*scale),resources={r:amount(r,minimum[r]*scale) for r in chosen},troops=2*scale,
        basis='10% of seven days at current per-minute production (1,008 minutes). This is a projection, not recorded weekly earnings. Starter minimums apply.',resets_at=(day+1)*86400)

def install(core):
    app=core['app']
    @app.get('/api/daily')
    @core['require_login']
    def daily_offer():return jsonify(offer(core,features.db(),session['user_id']))

    def claim():
        conn=features.db();uid=session['user_id'];choice=features.body().get('choice','money')
        if choice not in ('money','resources'):raise ValueError('Choose money or resources')
        data=offer(core,conn,uid)
        if not data['ready']:return jsonify(error='Already claimed today — come back after the daily reset'),400
        rewards={'money':data['money']} if choice=='money' else data['resources']
        conn.execute('UPDATE users SET last_daily=?,daily_streak=? WHERE id=?',(data['day'],data['streak'],uid))
        for resource,amount in rewards.items():conn.execute(f'UPDATE users SET {resource}={resource}+? WHERE id=?',(amount,uid))
        core['pool_add'](conn,uid,'army',data['troops'])
        achievements=core['award_achievements'](conn,uid)
        return jsonify(success=True,rewards=rewards,message='Daily reward: '+core['fmt_cost'](rewards)+f" + {data['troops']} troops",achievements=achievements)
    app.view_functions['daily_claim']=core['require_login'](claim)
