"""Optional authenticator-app TOTP with replay protection and password-confirmed setup."""
import base64,hashlib,hmac,secrets,struct,time,re
from flask import session,jsonify,request
import features
core=None

def code(secret,step):
    key=base64.b32decode(secret+'='*((8-len(secret)%8)%8));digest=hmac.new(key,struct.pack('>Q',step),hashlib.sha1).digest();offset=digest[-1]&15
    return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06d}'

def verify(secret,value,last_step=-1,stamp=None):
    if not isinstance(value,str) or not re.fullmatch(r'\d{6}',value):return None
    step=int(time.time() if stamp is None else stamp)//30
    for candidate in (step-1,step,step+1):
        if candidate>last_step and hmac.compare_digest(code(secret,candidate),value):return candidate
    return None

def settings():
    conn=core['get_db']();uid=session['user_id'];u=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if request.method=='GET':return jsonify(enabled=bool(u['otp_secret']))
    d=features.body()
    if not core['password_matches'](u['password'],d.get('password','')):return jsonify(error='Current password is incorrect'),403
    action=d.get('action')
    if action=='setup':
        if u['otp_secret']:raise ValueError('Two-factor authentication is already enabled')
        secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
        conn.execute('UPDATE users SET otp_pending=?,otp_pending_until=? WHERE id=?',(secret,int(time.time())+600,uid))
        features.audit(conn,'two_factor_setup',uid)
        return jsonify(success=True,secret=secret,message='Add this private key to your authenticator, then confirm a six-digit code. Setup expires in ten minutes.')
    if action=='enable':
        step=verify(u['otp_pending'],d.get('code')) if u['otp_pending'] and u['otp_pending_until']>=time.time() else None
        if step is None:raise ValueError('Invalid or expired authenticator setup code')
        conn.execute('UPDATE users SET otp_secret=otp_pending,otp_pending="",otp_pending_until=0,otp_last_step=?,auth_version=auth_version+1 WHERE id=?',(step,uid))
    elif action=='disable':
        if not u['otp_secret'] or verify(u['otp_secret'],d.get('code'),u['otp_last_step']) is None:raise ValueError('Enter a fresh authenticator code')
        conn.execute('UPDATE users SET otp_secret="",otp_pending="",otp_pending_until=0,otp_last_step=-1,auth_version=auth_version+1 WHERE id=?',(uid,))
    else:raise ValueError('Choose setup, enable or disable')
    session['auth_version']=conn.execute('SELECT auth_version FROM users WHERE id=?',(uid,)).fetchone()[0]
    features.audit(conn,'two_factor_'+action,uid)
    return jsonify(success=True,message='Two-factor authentication '+('enabled' if action=='enable' else 'disabled'))

def install(namespace):
    global core
    core=namespace;app=core['app'];original=app.view_functions['login']
    def login():
        response=original()
        if isinstance(response,tuple) or not response.get_json().get('success'):return response
        conn=core['get_db']();uid=session['user_id'];u=conn.execute('SELECT otp_secret,otp_last_step FROM users WHERE id=?',(uid,)).fetchone()
        if u['otp_secret']:
            step=verify(u['otp_secret'],features.body().get('otp',''),u['otp_last_step'])
            if step is None:
                csrf=session.get('csrf');session.clear();session['csrf']=csrf
                return jsonify(error='Enter a fresh six-digit authenticator code',two_factor_required=True),401
            conn.execute('UPDATE users SET otp_last_step=? WHERE id=?',(step,uid))
        session['issued_at']=int(time.time())
        return response
    app.view_functions['login']=login
    app.add_url_rule('/api/profile/two_factor','two_factor_settings',core['require_login'](settings),methods=['GET','POST'])
