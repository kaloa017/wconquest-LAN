"""Rebuild compact gameplay geography from official Natural Earth source files."""
import argparse,gzip,json,math,hashlib,urllib.request,sys
from collections import Counter
from pathlib import Path
project=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(project))
from config import GRID, SINGLE_ISLAND_MAX_SPAN
parser=argparse.ArgumentParser()
parser.add_argument('--source-dir',type=Path,default=Path(__file__).parent/'terrain-source')
parser.add_argument('--download',action='store_true',help='Download official Natural Earth GeoJSON source files')
args=parser.parse_args();root=args.source_dir;output=project/'data';root.mkdir(parents=True,exist_ok=True)
if args.download:
    for name in ('ne_10m_land','ne_10m_minor_islands','ne_10m_antarctic_ice_shelves_polys'):
        with urllib.request.urlopen('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/'+name+'.geojson',timeout=60) as response:
            (root/(name+'.geojson')).write_bytes(response.read())
polygons=[]
for name in ('ne_10m_land','ne_10m_minor_islands','ne_10m_antarctic_ice_shelves_polys'):
    for f in json.loads((root/(name+'.geojson')).read_text(encoding='utf-8'))['features']:
        g=f['geometry'];polygons.extend(g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']])
islands=[];main=[]
for rings in polygons:
    xs=[p[0] for p in rings[0]];ys=[p[1] for p in rings[0]];box=[min(xs),min(ys),max(xs),max(ys)]
    a,b,c,d=box
    if (a>=120 or c<=-70) and b>=-60 and d<=65 and c-a<25 and d-b<25:
        key='island:'+hashlib.sha256(json.dumps(rings[0],separators=(',',':')).encode()).hexdigest()[:16]
        # Use a scanline interior point, avoiding markers in the ocean or lagoon.
        lat=(b+d)/2;cross=[]
        for ring in rings:
            for p,q in zip(ring,ring[1:]):
                if (p[1]>lat)!=(q[1]>lat):cross.append(p[0]+(lat-p[1])*(q[0]-p[0])/(q[1]-p[1]))
        cross.sort();pairs=list(zip(cross[::2],cross[1::2]));left,right=max(pairs,key=lambda p:p[1]-p[0]) if pairs else (a,c)
        lng=(left+right)/2
        islands.append({'type':'Feature','properties':{'key':key,'name':'Pacific island '+key[-6:],'lat':lat,'lng':lng,'bounds':box,'grid_tiles':max(c-a,d-b)>SINGLE_ISLAND_MAX_SPAN},'geometry':{'type':'Polygon','coordinates':rings}})
        if max(c-a,d-b)>SINGLE_ISLAND_MAX_SPAN:main.append(rings)
    else:main.append(rings)
islands=list({f['properties']['key']:f for f in islands}.values())
(output/'pacific-islands.geojson').write_text(json.dumps({'type':'FeatureCollection','features':islands},separators=(',',':')))
print('Small dedicated islands',sum(not f['properties']['grid_tiles'] for f in islands),'grid islands',sum(f['properties']['grid_tiles'] for f in islands),'all islands',len(islands),'mainland/other components',len(main))
GRID=.18;WIDTH=2000;MINLAT=-473;HEIGHT=946
bits=bytearray((WIDTH*HEIGHT+7)//8)
coasts=bytearray(len(bits))
def edge_key(p,q):return tuple(sorted((tuple(p[:2]),tuple(q[:2]))))
# Shared polygon edges are dataset splits rather than coastline.
edges=Counter(edge_key(p,q) for rings in main for ring in rings for p,q in zip(ring,ring[1:]))
def mark(a,b,target=bits):
    if MINLAT<=a<MINLAT+HEIGHT and -1000<=b<1000:
        n=(a-MINLAT)*WIDTH+b+1000;target[n>>3]|=1<<(n&7)
for rings in main:
    rows={}
    for ring in rings:
        for p,q in zip(ring,ring[1:]):
            x,y=p[:2];xx,yy=q[:2]
            if y!=yy:
                start=math.ceil(min(y,yy)/GRID-.5);end=math.ceil(max(y,yy)/GRID-.5)
                for a in range(max(MINLAT,start),min(MINLAT+HEIGHT,end)):
                    at=(a+.5)*GRID
                    rows.setdefault(a,[]).append(x+(at-y)*(xx-x)/(yy-y))
            # Split exactly at grid lines; each interval lies in one touched cell.
            cuts=[0.,1.]
            for v,w in ((x,xx),(y,yy)):
                if v!=w:
                    cuts.extend((k*GRID-v)/(w-v) for k in range(math.floor(min(v,w)/GRID)+1,math.ceil(max(v,w)/GRID)))
            cuts.sort()
            for t,u in zip(cuts,cuts[1:]):
                mid=(t+u)/2;a,b=math.floor((y+(yy-y)*mid)/GRID),math.floor((x+(xx-x)*mid)/GRID);mark(a,b)
                if edges[edge_key(p,q)]==1:mark(a,b,coasts)
    for a,cross in rows.items():
        cross.sort()
        for left,right in zip(cross[::2],cross[1::2]):
            for b in range(max(-1000,math.ceil(left/GRID-.5)),min(1000,math.ceil(right/GRID-.5))):mark(a,b)
(output/'land-cells.bin').write_bytes(bits)
(output/'coastal-cells.bin').write_bytes(coasts)
print('Land cells',sum(v.bit_count() for v in bits),'bitset bytes',len(bits),'island bytes',(output/'pacific-islands.geojson').stat().st_size)

(output/'pacific-islands.geojson.gz').write_bytes(gzip.compress((output/'pacific-islands.geojson').read_bytes(),mtime=0))
