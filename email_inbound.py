"""Signed Resend inbound queue. Only the configured support alias is forwarded.

No public inbox, arbitrary-recipient relay, or stored message bodies. Network
work runs in the existing email worker after releasing SQLite's write lock.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from email.utils import parseaddr
from urllib.parse import urlsplit
from flask import request, jsonify
import email_verification as mail


def configured():
    return mail.provider()=='resend' and mail.configured() and bool(os.getenv('RESEND_WEBHOOK_SECRET') and os.getenv('EMAIL_FORWARD_TO'))


def load(conn):
    return json.loads(mail.core['get_setting'](conn,'email_inbound_queue','[]'))


def save(conn,rows):
    mail.core['set_setting'](conn,'email_inbound_queue',json.dumps(rows))


def admin_status(conn):
    rows=load(conn)
    return dict(configured=configured(),alias=os.getenv('EMAIL_INBOUND_ADDRESS',os.getenv('EMAIL_FROM','')),
        destination_configured=bool(os.getenv('EMAIL_FORWARD_TO')),webhook='/integrations/resend/inbound',
        daily_max=10,logs=[{k:r[k] for k in ('id','created','status','attempts','error')} for r in rows[-30:]][::-1])


def verify(raw):
    secret=os.environ['RESEND_WEBHOOK_SECRET']
    if not secret.startswith('whsec_'):raise ValueError('Invalid configuration')
    stamp=request.headers.get('svix-timestamp','');event=request.headers.get('svix-id','')
    if not event or len(event)>200 or abs(int(stamp)-time.time())>300:raise ValueError('Expired signature')
    key=base64.b64decode(secret[6:]+'='*(-len(secret[6:])%4),validate=True)
    expected=base64.b64encode(hmac.new(key,event.encode()+b'.'+stamp.encode()+b'.'+raw,hashlib.sha256).digest()).decode()
    if not any(hmac.compare_digest(part,'v1,'+expected) for part in request.headers.get('svix-signature','').split()):raise ValueError('Invalid signature')


def webhook():
    if not configured():return jsonify(error='Inbound forwarding is not configured'),503
    request.max_content_length=65536
    raw=request.get_data()
    try:
        verify(raw)
        event=json.loads(raw)
        if not isinstance(event,dict):raise ValueError('Invalid event')
    except (ValueError,TypeError,KeyError):return jsonify(error='Invalid webhook'),400
    if event.get('type')!='email.received':return jsonify(received=True)
    try:
        data=event['data'];eid=str(uuid.UUID(data['email_id']))
        alias=mail.normalized(os.getenv('EMAIL_INBOUND_ADDRESS',os.environ['EMAIL_FROM']))
        recipients=data.get('to',[])
        if not isinstance(recipients,list):raise ValueError('Invalid recipients')
        if alias not in [parseaddr(v)[1].lower() for v in recipients if isinstance(v,str)]:return jsonify(received=True,ignored=True)
    except (ValueError,TypeError,KeyError,AttributeError):return jsonify(error='Invalid email event'),400
    conn=mail.core['get_db']();now=int(time.time())
    rows=[r for r in load(conn) if r['created']>now-7*86400]
    if any(r['id']==eid for r in rows):return jsonify(received=True)
    if len(rows)>=200:return jsonify(error='Forwarding queue full; inspect Resend receiving dashboard'),503
    rows.append(dict(id=eid,created=now,status='queued',attempts=0,next_attempt=0,error='',reserved=False))
    save(conn,rows)
    return jsonify(received=True)


def api_get(path):
    req=urllib.request.Request('https://api.resend.com'+path,headers={'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],'User-Agent':'WorldConquest/Email'})
    with urllib.request.urlopen(req,timeout=8) as response:
        raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('Email exceeds forwarding size limit; view it in Resend')
        return json.loads(raw)


def deliver_once():
    if not configured():return
    conn=mail.core['get_db']();now=int(time.time());row=None
    try:
        conn.execute('BEGIN IMMEDIATE');rows=[r for r in load(conn) if r['created']>now-7*86400]
        today=now//86400
        reserved=sum(1 for r in rows if r.get('reserved_day')==today)
        for item in rows:
            if item['status'] in ('queued','sending') and item['created']<now-3600:
                item.update(status='expired',error='Forwarding window expired; view original in Resend');item.pop('payload',None)
        row=next((r for r in rows if r['status'] in ('queued','sending') and r['next_attempt']<=now and r['attempts']<3
            and (r['reserved'] or (reserved<10 and not mail.exhausted(conn)))),None)
        if row:
            if not row['reserved']:
                conn.execute('INSERT INTO email_budget(day,used) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET used=used+1',(mail.day(),))
                row.update(reserved=True,reserved_day=today)
            row.update(status='sending',attempts=row['attempts']+1,next_attempt=now+300)
        save(conn,rows);conn.commit()
    finally:conn.close()
    if not row:return
    status='forwarded';error=''
    try:
        if row.get('payload'):
            payload=json.loads(mail.cipher().decrypt(row['payload'].encode(),ttl=3600))
            req=urllib.request.Request('https://api.resend.com/emails',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],'Content-Type':'application/json','Idempotency-Key':'wc-inbound-'+row['id'],'User-Agent':'WorldConquest/Email'},method='POST')
        else:
            incoming=api_get('/emails/receiving/'+row['id'])
            alias=mail.normalized(os.getenv('EMAIL_INBOUND_ADDRESS',os.environ['EMAIL_FROM']))
            destination=mail.normalized(os.environ['EMAIL_FORWARD_TO'])
            sender=mail.normalized(parseaddr(incoming.get('from',''))[1])
            to=incoming.get('to',[])
            if alias not in [parseaddr(v)[1].lower() for v in to]:raise ValueError('Support alias mismatch')
            if sender in (alias,mail.normalized(os.environ['EMAIL_FROM'])):raise ValueError('Forwarding loop prevented')
            if destination==alias:raise ValueError('Forwarding destination must be a personal inbox')
            # Only provider-generated attachment URLs are passed back to Resend;
            # the Pi never fetches arbitrary URLs or renders untrusted email HTML.
            attachments=api_get('/emails/receiving/'+row['id']+'/attachments')
            if attachments.get('has_more'):raise ValueError('Too many attachments; view original in Resend')
            files=[];size=0
            for attachment in attachments.get('data',[]):
                url=attachment['download_url'];parts=urlsplit(url)
                if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:raise ValueError('Invalid attachment URL')
                size+=int(attachment.get('size',0))
                if size>10*1024*1024:raise ValueError('Attachments exceed 10 MiB; view original in Resend')
                file=dict(filename=attachment.get('filename') or 'attachment',path=url)
                if attachment.get('content_id'):file['content_id']=attachment['content_id']
                files.append(file)
            text='Forwarded support email. Original sender (unverified): '+sender+'\n\n'+(incoming.get('text') or '')
            body='<p>Forwarded support email. Original sender (unverified): '+html.escape(sender)+'</p>'+(incoming.get('html') or '<pre>'+html.escape(incoming.get('text') or '')+'</pre>')
            req=mail.send_request(destination,'[Support] '+str(incoming.get('subject') or '(no subject)')[:200],text,body,'wc-inbound-'+row['id'],attachments=files,headers={'Auto-Submitted':'auto-generated','X-Auto-Response-Suppress':'All'})
            message=json.loads(req.data);message['reply_to']=sender;req.data=json.dumps(message).encode()
            # Persist the exact encrypted request before sending. Retried attachment
            # URLs must stay identical for Resend's idempotency protection.
            conn=mail.core['get_db']()
            try:
                conn.execute('BEGIN IMMEDIATE');pending=load(conn)
                for item in pending:
                    if item['id']==row['id']:item['payload']=mail.cipher().encrypt(req.data).decode()
                save(conn,pending);conn.commit()
            finally:conn.close()
        with urllib.request.urlopen(req,timeout=8) as response:json.load(response)
    except urllib.error.HTTPError as exc:
        status='failed' if exc.code in (400,401,403,404,422) or row['attempts']>=3 else 'queued'
        error='Provider HTTP '+str(exc.code)
        try:details=json.loads(exc.read(4096))
        except (ValueError,TypeError):details={}
        conn=mail.core['get_db']()
        try:
            if mail.quota_error(conn,details.get('name')):status='queued';error='Provider quota exhausted; original remains in Resend'
            conn.commit()
        finally:conn.close()
    except ValueError as exc:status='failed';error=str(exc)[:160]
    except Exception:status='failed' if row['attempts']>=3 else 'queued';error='Forwarding unavailable; inspect provider configuration'
    conn=mail.core['get_db']()
    try:
        conn.execute('BEGIN IMMEDIATE');rows=load(conn)
        for item in rows:
            if item['id']==row['id']:
                item.update(status=status,error=error)
                if status!='queued':item.pop('payload',None)
        save(conn,rows);conn.commit()
    finally:conn.close()
