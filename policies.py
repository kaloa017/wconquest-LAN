"""Public policy pages rendered as escaped text from host-editable documents."""
from html import escape
from pathlib import Path
from flask import Response

def install(app):
    def page(kind):
        names={'terms':('Terms and conditions','TERMS.md'),'privacy':('Privacy policy','PRIVACY.md')}
        title,filename=names[kind]
        text=(Path(__file__).parent/'docs'/filename).read_text(encoding='utf-8')
        return Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+escape(title)+'</title><style>body{font:16px/1.7 system-ui;max-width:760px;margin:32px auto;padding:0 20px;background:#101928;color:#eef2f8}a{color:#f2cd87}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}</style>'
            '<nav><a href="/">Back to the game</a> · <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a></nav><main><pre>'+escape(text)+'</pre></main></html>',mimetype='text/html')
    app.add_url_rule('/terms','terms_policy',lambda:page('terms'))
    app.add_url_rule('/privacy','privacy_policy',lambda:page('privacy'))
