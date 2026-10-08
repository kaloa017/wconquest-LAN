"""Request-scoped SQLite transactions and conservative proxy trust."""
import os
import sqlite3
import secrets
import ipaddress
import time
from pathlib import Path
from flask import g, has_request_context, request
from werkzeug.middleware.proxy_fix import ProxyFix

def initialize_security(app):
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1',
                      MAX_CONTENT_LENGTH=16*1024*1024)
    key = os.getenv('SECRET_KEY')
    if not key:
        path = Path(os.getenv('DB_PATH', str(Path(app.root_path)/'game.db'))).resolve().parent/'.session-secret'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        except FileExistsError:
            # Another WSGI worker may have created the file just before writing it.
            deadline=time.monotonic()+2
            while True:
                key=path.read_text().strip()
                if len(key)>=32 or time.monotonic()>=deadline:break
                time.sleep(.02)
        else:
            key = secrets.token_hex(32)
            with os.fdopen(fd,'w') as f: f.write(key)
    if len(key) < 32: raise RuntimeError('Session secret must be at least 32 characters')
    app.secret_key = key
    app.wsgi_app = TrustedProxy(app.wsgi_app)

class TrustedProxy:
    def __init__(self, app):
        self.app = app
        self.networks = [ipaddress.ip_network(s.strip()) for s in os.getenv('TRUSTED_PROXIES','').split(',') if s.strip()]
        self.hops = int(os.getenv('PROXY_HOPS','1'))
        self.fixed = ProxyFix(app, x_for=self.hops, x_proto=1, x_host=0, x_port=0)
    def __call__(self, environ, start_response):
        try: trusted = any(ipaddress.ip_address(environ.get('REMOTE_ADDR','')) in n for n in self.networks)
        except ValueError: trusted = False
        if trusted:
            if os.getenv('PROXY_MODE') == 'cloudflare' and environ.get('HTTP_CF_CONNECTING_IP'):
                try: environ['HTTP_X_FORWARDED_FOR'] = str(ipaddress.ip_address(environ['HTTP_CF_CONNECTING_IP']))
                except ValueError: environ.pop('HTTP_X_FORWARDED_FOR',None)
            return self.fixed(environ,start_response)
        return self.app(environ,start_response)

class RequestConnection(sqlite3.Connection):
    """Legacy handlers can close/commit; the request owns the real lifecycle."""
    managed = False
    def close(self):
        if not self.managed: super().close()
    def commit(self):
        if not self.managed: super().commit()
    def execute(self, sql, parameters=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE' and self.in_transaction:
            return super().execute('SELECT 1')
        return super().execute(sql, parameters)

def connect_db(path):
    if has_request_context() and 'db' in g: return g.db
    conn = sqlite3.connect(path, timeout=10, factory=RequestConnection)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=10000')
    if has_request_context():
        g.db = conn; conn.managed = True
        # All mutations share one transaction, including auth and legacy routes.
        if request.method != 'GET' or request.path in ('/api/me','/api/game/status','/api/faction/info'):
            conn.execute('BEGIN IMMEDIATE')
    return conn

def finish_transaction(response):
    conn = g.get('db')
    if conn and conn.in_transaction:
        if response.status_code < 400: sqlite3.Connection.commit(conn)
        else: conn.rollback()
    return response

def close_transaction(error=None):
    conn = g.pop('db',None)
    if conn:
        if conn.in_transaction: conn.rollback()
        sqlite3.Connection.close(conn)
