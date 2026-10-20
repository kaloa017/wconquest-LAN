"""Public precompressed geography, independent of ownership and player sessions."""
from pathlib import Path
import re
from flask import abort, request, send_file


def install(app):
    @app.get('/static/map/<name>')
    def map_asset(name):
        if name!='manifest.json' and not re.fullmatch(r'(?:world|islands--?\d+_-?\d+)-[a-f0-9]{16}\.json',name):abort(404)
        path=Path(app.static_folder)/'map'/name
        if not path.is_file():abort(404)
        compressed=request.accept_encodings['gzip']>0
        response=send_file(str(path)+'.gz' if compressed else path,mimetype='application/json',conditional=True,max_age=300 if name=='manifest.json' else 31536000)
        if compressed:response.headers['Content-Encoding']='gzip'
        response.headers['Vary']='Accept-Encoding'
        response.headers['Cache-Control']='public, max-age='+('300' if name=='manifest.json' else '31536000, immutable')
        return response
