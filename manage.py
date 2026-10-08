"""Local host administration. Passwords are prompted, never command arguments."""
import argparse,getpass,os,sqlite3
from werkzeug.security import generate_password_hash

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['create-admin','reset-password','backup']);parser.add_argument('--username');parser.add_argument('--output');args=parser.parse_args()
    os.environ['DISABLE_SCHEDULER']='1'
    import app
    conn=app.get_db()
    try:
        if args.action=='backup':
            if not args.output:parser.error('--output is required for backup')
            with sqlite3.connect(args.output) as dest:conn.backup(dest)
            print('Consistent database backup saved.');return
        name=args.username or input('Username: ').strip();password=getpass.getpass('New password (8+ characters): ')
        if len(password)<8 or password!=getpass.getpass('Repeat password: '):parser.error('Passwords must match and contain at least 8 characters')
        existing=conn.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE',(name,)).fetchone()
        if args.action=='reset-password' and not existing:parser.error('Account not found')
        if existing:
            conn.execute('UPDATE users SET password=?,auth_version=auth_version+1,reset_code_hash=NULL,reset_code_until=0 WHERE id=?',(generate_password_hash(password),existing['id']))
            if args.action=='create-admin':conn.execute('UPDATE users SET is_admin=1,is_banned=0 WHERE id=?',(existing['id'],))
            uid=existing['id']
        else:
            import re
            if not re.fullmatch(r'[\w .-]{3,20}',name):parser.error('Name must be 3–20 letters, digits, spaces, dots or dashes')
            uid=conn.execute('INSERT INTO users(username,password,color,base_color,is_admin) VALUES(?,?,?,?,1)',(name,generate_password_hash(password),'#3b82f6','#3b82f6')).lastrowid
        conn.execute('INSERT INTO audit_log(ts,actor,action,target_id,details) VALUES(strftime("%s","now"),"Local host",?,?,"{}")',(args.action,uid));conn.commit();print('Host account operation completed.')
    finally:conn.close()

if __name__=='__main__':main()
