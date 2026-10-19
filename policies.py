"""Public policy pages rendered as escaped text from host-editable documents."""
from html import escape
from pathlib import Path
from flask import Response

def install(app):
    def page(kind):
        names={'terms':('Terms and conditions','TERMS.md'),'privacy':('Privacy policy','PRIVACY.md')}
        title,filename=names[kind]
        text=(Path(__file__).parent/'docs'/filename).read_text(encoding='utf-8')
        links=''.join('<a href="'+url+'"'+(' aria-current="page"' if key==kind else '')+'>'+label+'</a>'
            for key,url,label in [('game','/','Back to the game'),('terms','/terms','Terms'),('privacy','/privacy','Privacy')])
        return Response('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+escape(title)+' · World Conquest</title><link rel="stylesheet" href="/static/interface.css"></head>'
            '<body class="policy-page"><a class="ui-skip-link" href="#policy-content">Skip to policy</a><div class="policy-layout">'
            '<nav aria-label="Policy pages">'+links+'</nav><main id="policy-content" tabindex="-1"><h1>'+escape(title)+'</h1><pre>'+escape(text)+'</pre></main></div></body></html>',mimetype='text/html')
    app.add_url_rule('/terms','terms_policy',lambda:page('terms'))
    app.add_url_rule('/privacy','privacy_policy',lambda:page('privacy'))
