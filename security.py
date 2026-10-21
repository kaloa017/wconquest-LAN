"""Defense in depth for public hosting; no game action rate limits."""
import os,time,hashlib,threading
from collections import OrderedDict
from urllib.parse import urlsplit
from flask import request,session,jsonify

_attempts=OrderedDict();_lock=threading.Lock()
MAX_AUTH_CLIENTS=10000
AUTH_ROUTES=('/api/login','/api/register','/api/forgot_password',
             '/api/profile/two_factor','/api/profile/recovery','/api/profile/email',
             '/api/profile/change_password','/api/profile/change_username')

def install(app):
    app.config['TRUSTED_HOSTS']=[host.strip() for host in os.getenv('ALLOWED_HOSTS','').split(',') if host.strip()] or None
    app.config.update(MAX_FORM_MEMORY_SIZE=1024*1024,MAX_FORM_PARTS=20)
    @app.before_request
    def protect():
        if not request.path.startswith('/api/'):return
        if request.method!='GET':
            if request.mimetype!='multipart/form-data':request.max_content_length=256*1024
            if request.headers.get('Sec-Fetch-Site')=='cross-site':return jsonify(error='Cross-site requests are blocked'),403
            origin=request.headers.get('Origin')
            if origin:
                try:valid=urlsplit(origin).netloc.lower()==request.host.lower() and urlsplit(origin).scheme==request.scheme
                except ValueError:valid=False
                if not valid:return jsonify(error='Request origin does not match this game'),403
            if request.mimetype!='multipart/form-data' and (request.content_length or 0)>256*1024:
                return jsonify(error='Request is too large'),413
        if session.get('user_id'):
            issued=session.setdefault('issued_at',int(time.time()))
            if time.time()-issued>12*3600:
                session.clear();return jsonify(error='Session expired; please log in again'),401
        if request.path in AUTH_ROUTES and request.method=='POST':
            # Separate from optional game limits: password hashing is expensive and needs protection.
            limit=max(1,int(os.getenv('AUTH_ATTEMPTS_PER_MINUTE','30')))
            data=request.get_json(silent=True) or {};name=data.get('username','') if isinstance(data,dict) else ''
            stamp=int(time.time()//60)
            account=('uid:'+str(session.get('user_id')) if request.path.startswith('/api/profile/')
                     else 'account:'+hashlib.sha256(str(name).casefold().encode()).hexdigest())
            keys=['ip:'+str(request.remote_addr),account]
            blocked=False
            with _lock:
                for key in keys:
                    previous=_attempts.get(key);count=previous[1]+1 if previous and previous[0]==stamp else 1
                    _attempts[key]=(stamp,count);_attempts.move_to_end(key)
                    blocked=blocked or count>limit
                while len(_attempts)>MAX_AUTH_CLIENTS:_attempts.popitem(last=False)
            if blocked:
                response=jsonify(error='Too many account attempts. Try again in one minute.');response.headers['Retry-After']='60';return response,429
    # Run before JSON parsing, hashing and database work in older request hooks.
    app.before_request_funcs[None].remove(protect)
    app.before_request_funcs[None].insert(0,protect)
    @app.after_request
    def headers(response):
        # Legacy onclick handlers require unsafe-inline; external scripts/eval are blocked.
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=(), payment=()'
        response.headers['Cross-Origin-Resource-Policy']='same-origin'
        if request.is_secure:response.headers['Strict-Transport-Security']='max-age=31536000'
        if request.path in ('/','/terms','/privacy'):response.headers['Cache-Control']='no-cache'
        return response
