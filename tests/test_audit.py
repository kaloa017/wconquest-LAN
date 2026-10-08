"""Regression tests for the audit, using the existing isolated test database."""
import unittest, time, os
from unittest.mock import patch
from flask import Flask
from test_upgrade import app, features

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.client=app.app.test_client()
        self.csrf=self.client.get('/api/bootstrap').json['csrf']
        name='Audit'+str(time.time_ns())[-12:]
        self.post('/api/register',{'username':name,'password':'testpassword'})
        self.post('/api/login',{'username':name,'password':'testpassword'})
        self.uid=self.client.get('/api/me').json['id']
    def post(self,path,data):return self.client.post(path,json=data,headers={'X-WC-CSRF':self.csrf})
    def user(self,conn,label):
        return conn.execute('INSERT INTO users(username,password) VALUES(?,?)',(label+str(time.time_ns())[-8:],app.ph('testpassword'))).lastrowid
    def faction(self,conn,members):
        fid=conn.execute('INSERT INTO factions(name,tag,leader_id,color) VALUES(?,?,?,?)',('Audit'+str(time.time_ns()),str(time.time_ns())[-4:],members[0],'#ef4444')).lastrowid
        for uid in members:features.join_faction(conn,uid,fid)
        return fid
    def test_loan_cannot_transfer_faction_mates_vehicles(self):
        conn=app.get_db();owner=self.user(conn,'Owner');borrower=self.user(conn,'Borrower')
        self.faction(conn,[self.uid,owner]);conn.execute('UPDATE users SET boats=5,share_boats=1 WHERE id=?',(owner,))
        lid=conn.execute("INSERT INTO loans(lender_id,borrower_id,unit,amount,status,ts) VALUES(?,?, 'boats',3,'pending',0)",(self.uid,borrower)).lastrowid
        conn.commit();conn.close()
        self.assertEqual(self.post('/api/loan/respond',{'loan_id':lid,'accept':True}).status_code,400)
        conn=app.get_db();self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(owner,)).fetchone()[0],5);conn.close()
    def test_loan_return_does_not_take_shared_vehicles(self):
        conn=app.get_db();owner=self.user(conn,'Owner');lender=self.user(conn,'Lender')
        self.faction(conn,[self.uid,owner]);conn.execute('UPDATE users SET boats=5,share_boats=1 WHERE id=?',(owner,))
        lid=conn.execute("INSERT INTO loans(lender_id,borrower_id,unit,amount,status,ts) VALUES(?,?, 'boats',3,'active',0)",(lender,self.uid)).lastrowid
        conn.commit();conn.close();self.assertEqual(self.post('/api/loan/return',{'loan_id':lid}).status_code,200)
        conn=app.get_db();self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(owner,)).fetchone()[0],5);self.assertEqual(conn.execute('SELECT boats FROM users WHERE id=?',(lender,)).fetchone()[0],0);conn.close()
    def test_malformed_text_and_toggles_are_rejected(self):
        conn=app.get_db();conn.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.uid,));conn.commit();conn.close()
        for url,data in [('/api/chat/send',{'message':42}),('/api/faction/create',{'name':[],'tag':'AA'}),('/api/admin/ban',{'user_id':self.uid,'ban':'false'}),('/api/admin/set_setting',{'key':'income_mult','value':'nan'})]:
            with self.subTest(url=url):self.assertEqual(self.post(url,data).status_code,400)
    def test_explicit_session_secret_has_minimum_length(self):
        from runtime import initialize_security
        with patch.dict(os.environ,{'SECRET_KEY':'weak'}):
            with self.assertRaises(RuntimeError):initialize_security(Flask('audit'))
