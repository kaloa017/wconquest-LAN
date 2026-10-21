"""Host-managed literal chat filters and public social-link metadata."""
from functools import lru_cache
import html
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit
from flask import jsonify, request, session

core=None


def normalized(text):
    text=unicodedata.normalize('NFKC',text).casefold()
    return ' '.join(''.join(c for c in text if unicodedata.category(c)!='Cf').split())


@lru_cache(maxsize=16)
def expressions(words):
    return tuple(re.compile(r'(?<!\w)'+re.escape(normalized(word)).replace(r'\ ',r'\s+')+r'(?!\w)') for word in words)


def settings(conn):
    raw=core['get_setting'](conn,'chat_word_filter','')
    return json.loads(raw) if raw else {'enabled':True,'words':[]}


def blocked(text,configuration):
    return configuration['enabled'] and any(pattern.search(normalized(text)) for pattern in expressions(tuple(configuration['words'])))


def filter_settings():
    conn=core['get_db']()
    if request.method=='GET':return jsonify(settings(conn))
    data=request.get_json();words=data.get('words');enabled=data.get('enabled')
    if not isinstance(enabled,bool) or not isinstance(words,list) or len(words)>200:raise ValueError('Use a toggle and up to 200 words or phrases')
    if any(not isinstance(word,str) or not 1<=len(word.strip())<=64 for word in words):raise ValueError('Each blocked word or phrase needs 1–64 characters')
    words=list(dict.fromkeys(normalized(word) for word in words))
    if any(not word for word in words):raise ValueError('Blocked words must contain visible characters')
    core['set_setting'](conn,'chat_word_filter',json.dumps({'enabled':enabled,'words':words}))
    return jsonify(success=True,message='Chat word filter saved')


def index():
    app=core['app'];source=(Path(app.root_path)/'index.html').read_text(encoding='utf-8')
    url=os.getenv('PUBLIC_URL') or ('https://'+os.environ['PUBLIC_HOST'] if os.getenv('PUBLIC_HOST') else request.url_root)
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.netloc:raise ValueError('PUBLIC_URL must be an absolute HTTP or HTTPS address')
    url=url.rstrip('/')+'/'
    description='Build a country, trade with players, research advanced technology and conquer a persistent multiplayer world.'
    tags={'description':description,'og:type':'website','og:title':'World Conquest','og:description':description,'og:url':url,'og:image':url+'static/share-card.png','og:image:width':'1200','og:image:height':'630','og:image:alt':'World Conquest — build, trade, conquer','twitter:card':'summary_large_image','twitter:title':'World Conquest','twitter:description':description,'twitter:image':url+'static/share-card.png'}
    metadata='\n'.join(f'<meta {"property" if key.startswith("og:") else "name"}="{key}" content="{html.escape(value,quote=True)}">' for key,value in tags.items())
    from asset_versions import asset_version
    source=re.sub(r'((?:src|href)=")(/static/[^"?]+\.(?:js|css))"',lambda match:match[1]+match[2]+'?v='+html.escape(asset_version(app.root_path,match[2],core['VERSION']),quote=True)+'"',source)
    return core['app'].response_class(source.replace('</head>',metadata+'\n</head>'),mimetype='text/html')


def install(namespace):
    global core
    core=namespace;app=namespace['app']
    app.view_functions['index']=index
    app.add_url_rule('/api/admin/chat_filter','chat_filter',core['require_admin'](filter_settings),methods=['GET','POST'])
    @app.before_request
    def enforce():
        if request.method!='POST' or not session.get('user_id'):return
        fields={'/api/chat/send':'message','/api/admin/chat_as':'message','/api/admin/chat_edit':'text','/api/trade/discussion':'message'}
        field=fields.get(request.path)
        if field:
            text=(request.get_json(silent=True) or {}).get(field,'')
            if isinstance(text,str) and blocked(text,settings(core['get_db']())):return jsonify(error='Message contains a blocked word or phrase.'),400
