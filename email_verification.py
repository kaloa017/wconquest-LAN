"""Optional Brevo verification with bounded sending and private durable delivery.

Passwords remain required. Quota-only password fallback is an explicit host
setting; provider/network failures never silently turn off authentication.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime,timezone
from flask import request,session,jsonify
from cryptography.fernet import Fernet
import features

core=None
DEFAULT=dict(enabled=False,daily_limit=250,quota_fallback=True,subject='Your World Conquest code',
    heading='Welcome to World Conquest',intro='Enter this code in the game to verify your email and sign in.',
    footer='If you did not request this code, you can ignore this email.',accent='#d8b66a')

def state(conn):
    try:saved=json.loads(core['get_setting'](conn,'email_verification','{}'))
    except (ValueError,TypeError):saved={}
    return {**DEFAULT,**saved}

def configured():return bool(os.getenv('BREVO_API_KEY') and os.getenv('EMAIL_FROM'))
def day():return datetime.now(timezone.utc).strftime('%Y-%m-%d')
def used(conn):
    row=conn.execute('SELECT used FROM email_budget WHERE day=?',(day(),)).fetchone()
    return row[0] if row else 0
def available(conn,s=None):
    s=s or state(conn)
    return s['enabled'] and configured() and used(conn)<s['daily_limit']
def normalized(value):
    if not isinstance(value,str) or len(value)>254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}",value.strip()):raise ValueError('Enter a valid email address')
    return value.strip().lower()
def cipher():
    secret=core['app'].secret_key
    if isinstance(secret,str):secret=secret.encode()
    return Fernet(base64.urlsafe_b64encode(hmac.new(secret,b'world-conquest-email-outbox',hashlib.sha256).digest()))
def digest(value):
    secret=core['app'].secret_key
    if isinstance(secret,str):secret=secret.encode()
    return hmac.new(secret,value.encode(),hashlib.sha256).hexdigest()
def limited(conn,key,seconds,maximum):
    slot=int(time.time())//seconds;key=digest(key)
    row=conn.execute('SELECT window,count FROM email_request_limits WHERE key=?',(key,)).fetchone()
    count=row['count']+1 if row and row['window']==slot else 1
    conn.execute('INSERT OR REPLACE INTO email_request_limits VALUES(?,?,?,?)',(key,slot,count,int(time.time())+seconds*2))
    return count>maximum

def consume(conn,user,email,value):
    row=conn.execute('SELECT * FROM email_challenges WHERE user_id=?',(user['id'],)).fetchone()
    if not row or row['email']!=email or row['expires_at']<=time.time() or row['auth_version']!=user['auth_version']:return False,'The code has expired. Request a new code.'
    if row['attempts']>=5:return False,'Too many incorrect codes. Request a new code after the cooldown.'
    conn.execute('UPDATE email_challenges SET attempts=attempts+1 WHERE user_id=?',(user['id'],))
    expected=digest(f"{user['id']}:{email}:{value}:{user['auth_version']}")
    if not isinstance(value,str) or not re.fullmatch(r'\d{8}',value) or not hmac.compare_digest(row['code_hash'],expected):return False,'Incorrect verification code.'
    conn.execute('DELETE FROM email_challenges WHERE user_id=?',(user['id'],))
    conn.execute("UPDATE email_outbox SET status='cancelled',payload='' WHERE user_id=? AND status IN ('queued','sending')",(user['id'],))
    conn.execute('UPDATE account_emails SET verified_at=? WHERE user_id=? AND email=?',(int(time.time()),user['id'],email))
    return True,''

def enqueue(conn,user,email,resend=False):
    s=state(conn);now=int(time.time())
    if not s['enabled'] or not configured():return dict(error='Email sending is not configured by the host.')
    previous=conn.execute('SELECT * FROM email_challenges WHERE user_id=?',(user['id'],)).fetchone()
    if previous and previous['email']==email and previous['expires_at']>now and previous['auth_version']==user['auth_version']:
        if not resend:return dict(email_required=True,message='Enter your eight-digit email code.',retry_after=max(0,60-(now-previous['created_at'])))
        if now-previous['created_at']<60:return dict(error='Please wait before requesting another email.',email_required=True,retry_after=60-(now-previous['created_at']))
    if used(conn)>=s['daily_limit']:return dict(error='The daily email allowance is exhausted.',quota_exhausted=True)
    # Enforced in the database transaction, so simultaneous requests cannot race.
    for key,seconds,maximum in [(f'user:{user["id"]}',86400,10),(f'email:{email}',86400,10),(f'ip:{request.remote_addr}',3600,60)]:
        if limited(conn,key,seconds,maximum):return dict(error='Email request limit reached. Please try again later.',email_required=True)
    code=f'{secrets.randbelow(100000000):08d}'
    conn.execute('INSERT OR REPLACE INTO email_challenges VALUES(?,?,?,?,0,?,?)',(user['id'],email,digest(f"{user['id']}:{email}:{code}:{user['auth_version']}"),now+600,now,user['auth_version']))
    conn.execute("UPDATE email_outbox SET status='cancelled',payload='' WHERE user_id=? AND status IN ('queued','sending')",(user['id'],))
    payload=cipher().encrypt(json.dumps(dict(code=code,username=user['username'],settings=s)).encode()).decode()
    conn.execute('INSERT INTO email_outbox(user_id,recipient,subject,payload,created_at,expires_at) VALUES(?,?,?,?,?,?)',(user['id'],email,s['subject'],payload,now,now+600))
    conn.execute('INSERT INTO email_budget(day,used) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET used=used+1',(day(),))
    features.audit(conn,'verification_email_queued',user['id'])
    return dict(email_required=True,message='A verification email is queued. Enter its eight-digit code.',retry_after=60)

def login_challenge(conn,user,data):
    s=state(conn)
    if not s['enabled'] or not configured():return None
    row=conn.execute('SELECT * FROM account_emails WHERE user_id=?',(user['id'],)).fetchone()
    if not row:return None
    if data.get('email_code'):
        ok,message=consume(conn,user,row['email'],data['email_code'])
        return None if ok else jsonify(error=message,email_required=True)
    if used(conn)>=s['daily_limit'] and s['quota_fallback']:
        # TOTP, passwords and account bans still apply in the normal login path.
        features.audit(conn,'email_quota_password_fallback',user['id'])
        from flask import g
        g.email_quota_fallback=True
        return None
    return jsonify(**enqueue(conn,user,row['email'],data.get('resend_email') is True))

def account():
    conn=core['get_db']();uid=session['user_id'];s=state(conn)
    row=conn.execute('SELECT email,verified_at FROM account_emails WHERE user_id=?',(uid,)).fetchone()
    if request.method=='GET':return jsonify(available=bool(s['enabled'] and configured()),email=dict(row) if row else None,quota_exhausted=used(conn)>=s['daily_limit'],quota_fallback=s['quota_fallback'])
    d=features.body();user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if d.get('action')=='verify':
        if not row:raise ValueError('Add an email first')
        ok,message=consume(conn,user,row['email'],d.get('code',''))
        if not ok:return jsonify(error=message)
        return jsonify(success=True,message='Email verified. Future logins use a code while sending is available.')
    if not core['password_matches'](user['password'],d.get('password','')):return jsonify(error='Current password is incorrect'),403
    email=normalized(d.get('email',row['email'] if row else ''))
    if not available(conn,s):return jsonify(error='Email sending is unavailable or today’s allowance is exhausted. Try again later.')
    if row and row['email']!=email and row['verified_at']:
        # Confirm the old mailbox before replacing a verified recovery address.
        ok,message=consume(conn,user,row['email'],d.get('old_code',''))
        if not ok:return jsonify(error='Verify your current email code before changing address. '+message)
    result=enqueue(conn,user,email,d.get('resend') is True)
    if result.get('error'):return jsonify(**result)
    conn.execute('INSERT INTO account_emails(user_id,email) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,verified_at=CASE WHEN email=excluded.email THEN verified_at ELSE 0 END',(uid,email))
    return jsonify(**result)

def admin():
    conn=core['get_db']();s=state(conn)
    if request.method=='POST':
        d=features.body()
        if d.get('action')=='resend':
            uid=features.integer(d.get('user_id'),1,2**53-1)
            user=conn.execute('SELECT u.*,e.email FROM users u JOIN account_emails e ON e.user_id=u.id WHERE u.id=?',(uid,)).fetchone()
            if not user:raise ValueError('This account has no email')
            return jsonify(**enqueue(conn,user,user['email'],True))
        for key in ('enabled','quota_fallback'):
            if not isinstance(d.get(key),bool):raise ValueError('Choose email and quota fallback settings')
            s[key]=d[key]
        if s['enabled'] and not configured():raise ValueError('Configure BREVO_API_KEY and EMAIL_FROM privately on the server first')
        s['daily_limit']=features.integer(d.get('daily_limit',250),1,250)
        for key in ('subject','heading','intro','footer'):
            value=d.get(key,s[key])
            if not isinstance(value,str) or not value.strip() or len(value)>1000:raise ValueError('Enter template text below 1,000 characters')
            s[key]=value.strip()
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(d.get('accent',s['accent']))):raise ValueError('Choose a six-digit hex color')
        s['accent']=d.get('accent',s['accent'])
        core['set_setting'](conn,'email_verification',json.dumps(s));features.audit(conn,'email_settings_updated')
        return jsonify(success=True,message='Email settings saved')
    queued=conn.execute("SELECT COUNT(*) FROM email_outbox WHERE status IN ('queued','sending')").fetchone()[0]
    logs=[dict(r) for r in conn.execute('SELECT id,user_id,recipient,created_at,status,attempts,error FROM email_outbox ORDER BY id DESC LIMIT 50')]
    accounts=[dict(r) for r in conn.execute('SELECT u.id,u.username,e.email,e.verified_at FROM users u LEFT JOIN account_emails e ON e.user_id=u.id ORDER BY u.username LIMIT 1000')]
    return jsonify(settings=s,configured=configured(),used=used(conn),remaining=max(0,s['daily_limit']-used(conn)),queued=queued,logs=logs,accounts=accounts,
        fallback_active=bool(s['enabled'] and s['quota_fallback'] and used(conn)>=s['daily_limit']))

def render(payload):
    s=payload['settings'];code=payload['code'];name=payload['username'];escape=html.escape
    text=f"{s['heading']}\n\nHello {name},\n{s['intro']}\n\n{code}\n\nExpires in 10 minutes.\n{s['footer']}"
    body=f'<html><body style="background:#101b2c;color:#eef2fa;font-family:Arial,sans-serif;padding:30px"><h1 style="color:{s["accent"]}">{escape(s["heading"])}</h1><p>Hello {escape(name)},</p><p>{escape(s["intro"])}</p><p style="font-size:32px;letter-spacing:6px;font-weight:bold">{code}</p><p>Expires in 10 minutes.</p><p>{escape(s["footer"])}</p></body></html>'
    return text,body

def deliver_once():
    """Claim and release the write lock before contacting the provider."""
    conn=core['get_db']();now=int(time.time());row=None
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE email_outbox SET status='expired',payload='' WHERE expires_at<=? AND status IN ('queued','sending')",(now,))
        conn.execute('DELETE FROM email_challenges WHERE expires_at<?',(now,))
        conn.execute('DELETE FROM email_request_limits WHERE expires_at<?',(now,))
        conn.execute('DELETE FROM email_outbox WHERE created_at<?',(now-7*86400,))
        conn.execute('DELETE FROM email_budget WHERE day<?',(datetime.fromtimestamp(now-7*86400,timezone.utc).strftime('%Y-%m-%d'),))
        if state(conn)['enabled'] and configured():
            row=conn.execute("SELECT * FROM email_outbox WHERE (status='queued' OR status='sending') AND next_attempt<=? AND expires_at>? AND attempts<3 ORDER BY id LIMIT 1",(now,now)).fetchone()
            if row:conn.execute("UPDATE email_outbox SET status='sending',attempts=attempts+1,next_attempt=? WHERE id=?",(now+60,row['id']))
        conn.commit()
    finally:conn.close()
    if not row:return
    status='accepted';error='';provider_id=''
    try:
        payload=json.loads(cipher().decrypt(row['payload'].encode(),ttl=600));text,body=render(payload)
        message=dict(sender=dict(name=os.getenv('EMAIL_FROM_NAME','World Conquest'),email=normalized(os.environ['EMAIL_FROM'])),to=[dict(email=row['recipient'])],subject=row['subject'],textContent=text,htmlContent=body,
            headers={'IdempotencyKey':'wc-email-'+str(row['id'])+'-'+digest(core['DB_PATH'])[:12]})
        req=urllib.request.Request('https://api.brevo.com/v3/smtp/email',data=json.dumps(message).encode(),headers={'api-key':os.environ['BREVO_API_KEY'],'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=8) as response:provider_id=json.load(response).get('messageId','')[:200]
    except urllib.error.HTTPError as exc:
        status='failed' if exc.code in (400,401,403) or row['attempts']>=2 else 'queued'
        error='Provider HTTP '+str(exc.code)
        # A confirmed exhausted-credit response activates the host's explicit
        # quota fallback. Generic 429/rate errors do not bypass verification.
        try:credit_error=json.loads(exc.read(4096)).get('code')=='not_enough_credits'
        except (ValueError,AttributeError):credit_error=False
        if credit_error:
            status='failed';error='Provider daily credits exhausted'
            conn=core['get_db']()
            try:conn.execute('INSERT INTO email_budget VALUES(?,?) ON CONFLICT(day) DO UPDATE SET used=MAX(used,excluded.used)',(day(),state(conn)['daily_limit']));conn.commit()
            finally:conn.close()
    except Exception:
        status='failed' if row['attempts']>=2 else 'queued';error='Delivery unavailable; check provider settings or connection'
    conn=core['get_db']()
    try:
        conn.execute("UPDATE email_outbox SET status=?,provider_id=?,error=?,next_attempt=?,payload=CASE WHEN ?='queued' THEN payload ELSE '' END WHERE id=? AND status='sending'",(status,provider_id,error,int(time.time())+60,status,row['id']));conn.commit()
    finally:conn.close()

def run():
    while True:
        try:deliver_once()
        except Exception:core['app'].logger.warning('Email queue temporarily unavailable')
        time.sleep(5)

def install(namespace):
    global core
    core=namespace;app=core['app']
    app.add_url_rule('/api/profile/email','account_email',core['require_login'](account),methods=['GET','POST'])
    app.add_url_rule('/api/admin/email','admin_email',core['require_admin'](admin),methods=['GET','POST'])
