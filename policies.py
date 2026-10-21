"""Public policy pages rendered as escaped text from host-editable documents."""
from html import escape
from pathlib import Path
from flask import Response
from config import VERSION
import re
from asset_versions import asset_version

def render_document(text):
    """Small, escaped prose subset; host documents cannot inject executable HTML."""
    result=[];paragraph=[];items=[]
    def flush():
        if paragraph:result.append('<p>'+escape(' '.join(paragraph))+'</p>');paragraph.clear()
        if items:result.append('<ul>'+''.join('<li>'+escape(item)+'</li>' for item in items)+'</ul>');items.clear()
    for index,line in enumerate(text.splitlines()):
        if index==0 and line.startswith('# '):continue
        heading=re.match(r'^(#{1,3})\s+(.+)',line)
        if heading:
            flush();level=min(3,max(2,len(heading[1])));result.append(f'<h{level}>'+escape(heading[2])+f'</h{level}>')
        elif line.startswith('- '):
            if paragraph:flush()
            items.append(line[2:].strip())
        elif not line.strip():flush()
        else:
            if items:flush()
            paragraph.append(line.strip())
    flush();return ''.join(result)

def install(app):
    def page(kind):
        names={'terms':('Terms and conditions','TERMS.md'),'privacy':('Privacy policy','PRIVACY.md')}
        title,filename=names[kind]
        text=(Path(__file__).parent/'docs'/filename).read_text(encoding='utf-8')
        styles=''.join('<link rel="stylesheet" href="'+url+'?v='+escape(asset_version(app.root_path,url,VERSION),quote=True)+'">' for url in ('/static/interface.css','/static/product-ui.css'))
        links=''.join('<a href="'+url+'"'+(' aria-current="page"' if key==kind else '')+'>'+label+'</a>'
            for key,url,label in [('game','/','Back to the game'),('terms','/terms','Terms'),('privacy','/privacy','Privacy')])
        return Response('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+escape(title)+' · World Conquest</title>'+styles+'</head>'
            '<body class="policy-page"><a class="ui-skip-link" href="#policy-content">Skip to policy</a><div class="policy-layout">'
            '<nav aria-label="Policy pages">'+links+'</nav><main id="policy-content" tabindex="-1"><h1>'+escape(title)+'</h1><div class="policy-copy">'+render_document(text)+'</div></main></div></body></html>',mimetype='text/html')
    app.add_url_rule('/terms','terms_policy',lambda:page('terms'))
    app.add_url_rule('/privacy','privacy_policy',lambda:page('privacy'))
