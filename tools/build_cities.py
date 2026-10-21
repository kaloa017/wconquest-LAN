"""Build the offline major-city registry without importing/opening the game save."""
import argparse,csv,hashlib,json,math,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config import GRID
from geography import cell_land,load,island_feature,rings_contains

SOURCE='https://raw.githubusercontent.com/nvkelso/natural-earth-vector/789c9904087846cc3361302857aa2e76b0ae71ff/geojson/ne_10m_populated_places_simple.geojson'

def build(raw):
    load();islands=json.loads((ROOT/'data/pacific-islands.geojson').read_text(encoding='utf-8'))['features']
    cities=[]
    for feature in json.loads(raw)['features']:
        p=feature['properties'];population=int(p.get('pop_max') or 0)
        if population<250000 and not p.get('adm0cap'):continue
        lng,lat=feature['geometry']['coordinates'];a,b=math.floor(lat/GRID),math.floor(lng/GRID)
        key=f'{a},{b}';mapped_lat,mapped_lng=(a+.5)*GRID,(b+.5)*GRID
        if not cell_land(key):
            found=None
            for island in islands:
                q=island['properties'];left,bottom,right,top=q['bounds']
                if q.get('grid_tiles') or not (left<=lng<=right and bottom<=lat<=top):continue
                geometry=island['geometry'];polys=geometry['coordinates'] if geometry['type']=='MultiPolygon' else [geometry['coordinates']]
                if any(rings_contains(r,lng,lat) for r in polys):found=q;break
            if found:key=found['key'];mapped_lat,mapped_lng=found['lat'],found['lng']
            else:
                nearby=[(x,y) for x in range(max(-473,a-6),min(472,a+6)+1) for y in range(max(-1000,b-6),min(999,b+6)+1) if cell_land(f'{x},{y}')]
                if nearby:
                    x,y=min(nearby,key=lambda q:((q[0]+.5)*GRID-lat)**2+(((q[1]+.5)*GRID-lng)*math.cos(math.radians(lat)))**2)
                    key=f'{x},{y}';mapped_lat,mapped_lng=(x+.5)*GRID,(y+.5)*GRID
        playable=cell_land(key)
        cities.append(dict(id=str(p['ne_id']),name=p['name'],country=p.get('adm0name') or p.get('sov0name') or '',country_code=p.get('adm0_a3') or '',population=population,national_capital=bool(p.get('adm0cap')),lat=round(lat,6),lng=round(lng,6),grid_key=key,tile_lat=round(mapped_lat,6),tile_lng=round(mapped_lng,6),playable=playable,relocated=key!=f'{a},{b}'))
    cities.sort(key=lambda c:(-c['population'],c['id']))
    return dict(version=1,grid=GRID,source=SOURCE,source_sha256=hashlib.sha256(raw).hexdigest(),definition='Natural Earth POP_MAX >= 250000, plus listed national capitals; historical dataset estimates, not live census figures.',cities=cities)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path);args=parser.parse_args()
    raw=args.source.read_bytes() if args.source else urllib.request.urlopen(SOURCE,timeout=60).read()
    data=build(raw);(ROOT/'data/major-cities.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    with (ROOT/'data/major-cities.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(data['cities'][0]));writer.writeheader();writer.writerows(data['cities'])
    print(f"Saved {len(data['cities'])} cities; {sum(c['playable'] for c in data['cities'])} mapped to playable land; {len({c['grid_key'] for c in data['cities'] if c['playable']})} unique bonus tiles")
