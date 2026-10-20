"""Build public, content-addressed geography assets without opening a game save."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def simplify_ring(ring,tolerance=.25):
    # Radial reduction is intentionally conservative; Leaflet also simplifies
    # the resulting world-only geometry in screen space. Gameplay uses originals.
    if len(ring)<4:return None
    result=[ring[0]]
    for point in ring[1:-1]:
        if (point[0]-result[-1][0])**2+(point[1]-result[-1][1])**2>=tolerance**2:result.append(point)
    if len(result)<3:return None
    return result+[result[0]]


def build(root=ROOT):
    destination=root/'static'/'map';destination.mkdir(parents=True,exist_ok=True)
    terrain=root/'data'/'land-cells.bin'
    terrain.with_suffix('.bin.gz').write_bytes(gzip.compress(terrain.read_bytes(),compresslevel=9,mtime=0))
    def asset(prefix,value):
        raw=json.dumps(value,separators=(',',':'),ensure_ascii=False).encode()
        name=prefix+'-'+hashlib.sha256(raw).hexdigest()[:16]+'.json'
        (destination/name).write_bytes(raw)
        (destination/(name+'.gz')).write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))
        return '/static/map/'+name
    islands=json.loads((root/'data'/'pacific-islands.geojson').read_text(encoding='utf-8'))['features']
    regions={};metadata=[]
    for feature in islands:
        properties=feature['properties'];region=f"{int(properties['lng']//20)},{int(properties['lat']//20)}"
        regions.setdefault(region,[]).append(feature)
        metadata.append({**properties,'region':region})
    chunks={region:asset('islands-'+region.replace(',','_'),{'type':'FeatureCollection','features':features}) for region,features in sorted(regions.items())}
    world=[]
    for feature in json.loads((root/'data'/'land.geojson').read_text(encoding='utf-8'))['features']:
        geometry=feature['geometry'];polygons=geometry['coordinates'] if geometry['type']=='MultiPolygon' else [geometry['coordinates']]
        for polygon in polygons:
            outer=simplify_ring(polygon[0])
            if outer:world.append({'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[outer]+[r for ring in polygon[1:] if (r:=simplify_ring(ring))]}})
    world_url=asset('world',{'type':'FeatureCollection','features':world})
    manifest={'format':1,'world':world_url,'regions':chunks,'islands':metadata}
    raw=json.dumps(manifest,separators=(',',':'),ensure_ascii=False).encode()
    (destination/'manifest.json').write_bytes(raw)
    (destination/'manifest.json.gz').write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))
    return manifest


if __name__=='__main__':
    manifest=build()
    print(f"Built {len(manifest['islands'])} island entries in {len(manifest['regions'])} regions")
