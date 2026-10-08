"""Trusted bundled Natural Earth polygons; no map-colour or client-report trust."""
import json, math
from pathlib import Path
from functools import lru_cache
from config import GRID

def rings_contains(rings,x,y):
    def inside(ring):
        result=False
        ax,ay=ring[-1][:2]
        for v in ring:
            bx,by=v[:2]
            if (ay>y)!=(by>y) and x < (bx-ax)*(y-ay)/(by-ay)+ax: result=not result
            ax,ay=bx,by
        return result
    return inside(rings[0]) and not any(inside(r) for r in rings[1:])

def rings_intersect_cell(rings,a,b):
    left,bottom,right,top=b*GRID,a*GRID,(b+1)*GRID,(a+1)*GRID
    if any(rings_contains(rings,x,y) for x,y in ((left,bottom),(left,top),(right,bottom),(right,top))):return True
    for ring in rings:
        for p,q in zip(ring,ring[1:]):
            x,y=p[:2];xx,yy=q[:2];lo,hi=0.,1.
            for origin,delta,minimum,maximum in ((x,xx-x,left,right),(y,yy-y,bottom,top)):
                if delta==0:
                    if not minimum<=origin<=maximum:lo,hi=1.,0.;break
                else:
                    s,t=sorted(((minimum-origin)/delta,(maximum-origin)/delta));lo=max(lo,s);hi=min(hi,t)
            if lo<=hi:return True
    return False

class PolygonIndex:
    def __init__(self,path,only_country=None):
        self.buckets={}
        for feature in json.loads(Path(path).read_text(encoding='utf-8'))['features']:
            if only_country and feature['properties'].get('ADM0_A3') != only_country: continue
            geo=feature['geometry']
            polygons=geo['coordinates'] if geo['type']=='MultiPolygon' else [geo['coordinates']]
            for rings in polygons:
                xs=[p[0] for p in rings[0]];ys=[p[1] for p in rings[0]]
                bounds=min(xs),min(ys),max(xs),max(ys)
                for x in range(math.floor(bounds[0]/5),math.floor(bounds[2]/5)+1):
                    for y in range(math.floor(bounds[1]/5),math.floor(bounds[3]/5)+1): self.buckets.setdefault((x,y),[]).append((bounds,rings))
    def contains(self,x,y):
        for (a,b,c,d),rings in self.buckets.get((math.floor(x/5),math.floor(y/5)),[]):
            if a<=x<=c and b<=y<=d and rings_contains(rings,x,y): return True
        return False

_land=None;_coasts=None;_japan=None;_islands=None;_island_cells=None
def load():
    global _land,_coasts,_japan,_islands,_island_cells
    root=Path(__file__).parent/'data'
    if _land is None: _land=(root/'land-cells.bin').read_bytes()
    if _coasts is None: _coasts=(root/'coastal-cells.bin').read_bytes()
    if _islands is None:
        _islands={f['properties']['key']:f for f in json.loads((root/'pacific-islands.geojson').read_text(encoding='utf-8'))['features']}
        _island_cells={}
        for key,feature in _islands.items():
            a,b,c,d=feature['properties']['bounds']
            for lat in range(math.floor(b/GRID),math.floor(d/GRID)+1):
                for lng in range(math.floor(a/GRID),math.floor(c/GRID)+1):_island_cells.setdefault((lat,lng),[]).append(key)
    if _japan is None: _japan=PolygonIndex(root/'countries.geojson','JPN')

def island_feature(key):
    load();return _islands.get(key)

def island_grid(key):
    feature=island_feature(key)
    if not feature:raise ValueError('Unknown island tile')
    p=feature['properties'];return math.floor(p['lat']/GRID),math.floor(p['lng']/GRID)

def island_neighbors(a,b,include_grid=False):
    load();return list(dict.fromkeys(key for lat in range(a-1,a+2) for lng in range(b-1,b+2) for key in _island_cells.get((lat,lng),[]) if include_grid or not _islands[key]['properties'].get('grid_tiles')))

def island_at(lat,lng,include_grid=False):
    load()
    for key in _island_cells.get((math.floor(lat/GRID),math.floor(lng/GRID)),[]):
        if (include_grid or not _islands[key]['properties'].get('grid_tiles')) and rings_contains(_islands[key]['geometry']['coordinates'],lng,lat):return key
    return None

@lru_cache(maxsize=32768)
def cell_land(key):
    load()
    if key.startswith('island:'):return key in _islands
    a,b=map(int,key.split(','))
    if not (-473<=a<=472 and -1000<=b<=999):return False
    n=(a+473)*2000+b+1000
    return bool(_land[n>>3] & (1<<(n&7)))

@lru_cache(maxsize=8192)
def cell_japan(key):
    if key.startswith('island:'):
        f=island_feature(key)
        return bool(f and _japan.contains(f['properties']['lng'],f['properties']['lat']))
    load();a,b=map(int,key.split(','))
    return _japan.contains((b+.5)*GRID,(a+.5)*GRID)

def landmark_key(info):
    return f"{math.floor(info['lat']/GRID)},{math.floor(info['lng']/GRID)}" if 'lat' in info else None

@lru_cache(maxsize=32768)
def cell_coastal(key):
    load()
    if key.startswith('island:'):return key in _islands
    a,b=map(int,key.split(','))
    if not (-473<=a<=472 and -1000<=b<=999):return False
    n=(a+473)*2000+b+1000
    return bool(_coasts[n>>3] & (1<<(n&7)))


def islands_in_radius(a,b,radius):
    """Include custom island centers in the same grid-distance blast rules."""
    load();candidates=set()
    for lat in range(a-radius,a+radius+1):
        for lng in range(b-radius,b+radius+1):candidates.update(_island_cells.get((lat,lng),[]))
    return sorted(key for key in candidates if not _islands[key]['properties'].get('grid_tiles') and sum((x-y)**2 for x,y in zip(island_grid(key),(a,b)))<=radius**2)
