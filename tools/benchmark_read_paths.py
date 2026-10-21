"""Measure read endpoints on an isolated copy; never benchmark a live save.

This in-process diagnostic excludes HTTP/tunnel/browser and Pi hardware costs.
It is not a player-capacity or production-load-test claim.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,help='Save to copy read-only')
    parser.add_argument('--requests',type=int,default=100)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.requests<=1000 or not 1<=args.workers<=16:parser.error('Use 1–1000 requests and 1–16 workers')
    source=Path(args.database).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='wconquest-benchmark-') as temp:
        target=Path(temp)/'game.db'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(target)) as copied:old.backup(copied)
        os.environ.update(DB_PATH=str(target),DISABLE_SCHEDULER='1',ENABLE_IP_GEOLOOKUP='0')
        # Never send provider emails or load credentials for this diagnostic.
        os.environ.pop('BREVO_API_KEY',None)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        import app
        conn=app.get_db();world=dict(territories=conn.execute('SELECT COUNT(*) FROM territories').fetchone()[0],buildings=conn.execute('SELECT COUNT(*) FROM buildings').fetchone()[0]);conn.close()
        seed=app.app.test_client().get('/api/map/sync').json['version']
        def measure(path):
            client=app.app.test_client();start=time.perf_counter();response=client.get(path)
            return (time.perf_counter()-start)*1000,response.status_code,len(response.data)
        result={}
        for label,path in [('unchanged_map','/api/map/sync?since='+seed),('guest_combined','/api/spectator/sync?since='+seed)]:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:rows=list(pool.map(measure,[path]*args.requests))
            times=sorted(row[0] for row in rows)
            result[label]=dict(requests=len(rows),workers=args.workers,median_ms=round(statistics.median(times),2),p95_ms=round(times[max(0,int(len(times)*.95)-1)],2),errors=sum(row[1]!=200 for row in rows),median_bytes=statistics.median(row[2] for row in rows))
        print(json.dumps(dict(world=world,paths=result,scope='Isolated in-process Windows/Linux diagnostics; not Pi capacity'),indent=2))

if __name__=='__main__':main()
