"""Additive analytics and account-email storage; existing worlds remain intact."""
import time


def migrate(get_db):
    conn=get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=22').fetchone():conn.commit();return
        columns={r['name'] for r in conn.execute('PRAGMA table_info(guest_visits)')}
        for name,definition in [('is_crawler','INTEGER'),('crawler_name',"TEXT NOT NULL DEFAULT ''")]:
            if name not in columns:conn.execute(f'ALTER TABLE guest_visits ADD COLUMN {name} {definition}')
        conn.execute('CREATE INDEX IF NOT EXISTS guest_visits_ip ON guest_visits(ip,last_seen)')
        conn.execute('CREATE INDEX IF NOT EXISTS guest_visits_crawler ON guest_visits(is_crawler,last_seen)')
        conn.execute('''CREATE TABLE IF NOT EXISTS ip_bans(ip TEXT PRIMARY KEY,reason TEXT NOT NULL,
            created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,actor_id INTEGER)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS account_emails(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,verified_at INTEGER NOT NULL DEFAULT 0)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS email_challenges(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            email TEXT NOT NULL,code_hash TEXT NOT NULL,expires_at INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,auth_version INTEGER NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS email_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,recipient TEXT NOT NULL,subject TEXT NOT NULL,
            payload TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,next_attempt INTEGER NOT NULL DEFAULT 0,
            provider_id TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '')''')
        conn.execute('CREATE INDEX IF NOT EXISTS email_outbox_queue ON email_outbox(status,next_attempt)')
        conn.execute('''CREATE TABLE IF NOT EXISTS email_budget(day TEXT PRIMARY KEY,used INTEGER NOT NULL DEFAULT 0)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS email_request_limits(key TEXT PRIMARY KEY,window INTEGER NOT NULL,count INTEGER NOT NULL,expires_at INTEGER NOT NULL)''')
        conn.execute('INSERT INTO schema_migrations VALUES(22,?)',(int(time.time()),));conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()
