"""Single host-managed banner; plain text and validated URLs/styles only."""
import json,re
from urllib.parse import urlsplit
from flask import request,jsonify
import features

DEFAULT={'enabled':False,'badge':'Sponsored','title':'','message':'','button_text':'Learn more','link':'','image':'',
         'background':'#182437','text_color':'#eef2f8','accent':'#e6b963','border_color':'#3b516f',
         'font_size':12,'width':220,'radius':10,'alignment':'left','show_mobile':True,
         'color_mode':'solid','alternate_color':'#345b83','cycle_seconds':8}
core=None

def validate(data):
    if not isinstance(data,dict) or set(data)-set(DEFAULT):raise ValueError('Use supported banner settings')
    result={**DEFAULT,**data}
    for key in ('enabled','show_mobile'):
        if not isinstance(result[key],bool):raise ValueError(key+' must be true or false')
    for key,limit in [('badge',25),('title',60),('message',160),('button_text',30),('link',1000),('image',1000)]:
        value=result[key]
        if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 for c in value):raise ValueError('Invalid '+key)
        result[key]=value.strip()
    for key in ('background','text_color','accent','border_color','alternate_color'):
        value=result[key]
        if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value):continue
        match=re.fullmatch(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)',value or '') if isinstance(value,str) else None
        if not match or any(int(v)>255 for v in match.groups()):raise ValueError('Use #RRGGBB or rgb(0, 128, 255) for '+key)
        result[key]='#'+''.join(f'{int(v):02x}' for v in match.groups())
    if result['color_mode'] not in ('solid','alternate','rainbow'):raise ValueError('Choose solid, alternate or rainbow colors')
    for key,minimum,maximum in [('font_size',10,20),('width',100,360),('radius',0,24),('cycle_seconds',3,60)]:
        value=result[key]
        if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:raise ValueError('Invalid '+key)
    if result['alignment'] not in ('left','center'):raise ValueError('Choose left or center alignment')
    for key in ('link','image'):
        value=result[key]
        if not value:continue
        if '\\' in value or any(c.isspace() for c in value):raise ValueError('Invalid '+key+' URL')
        if value.startswith('/static/') and '..' not in value and not value.startswith('//'):continue
        try:parts=urlsplit(value);valid=parts.scheme in (('https',) if key=='image' else ('http','https')) and bool(parts.hostname) and not parts.username and not parts.password
        except ValueError:valid=False
        if not valid:raise ValueError('Use an HTTPS image URL or /static/ file; links must use HTTP or HTTPS')
    if result['enabled'] and not any(result[key] for key in ('title','message','image')):raise ValueError('Add a title, message or image before enabling the banner')
    return result

def read():
    saved=core['get_setting'](core['get_db'](),'advertisement')
    return validate(json.loads(saved)) if saved else dict(DEFAULT)

def public():
    banner=read()
    return jsonify(banner=banner if banner['enabled'] else {'enabled':False})

def manage():
    if request.method=='GET':return jsonify(banner=read())
    banner=validate(features.body());conn=core['get_db']()
    core['set_setting'](conn,'advertisement',json.dumps(banner))
    features.audit(conn,'advertisement_updated',details=banner)
    return jsonify(success=True,message='Banner saved for everyone',banner=banner)

def install(namespace):
    global core
    core=namespace
    core['app'].add_url_rule('/api/advertisement','public_advertisement',public,methods=['GET'])
    core['app'].add_url_rule('/api/admin/advertisement','manage_advertisement',core['require_admin'](manage),methods=['GET','POST'])
