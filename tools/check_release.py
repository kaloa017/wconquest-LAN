"""Check the public release without importing the game or opening its save."""
import argparse, ast, gzip, json, re, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=('LICENSE','README.md','CHANGELOG.md','requirements.txt','config.py','app.py',
          'docs/DEPLOYMENT.md','docs/EVA_IMAGES.md','docs/MIGRATIONS.md')

def private_path(name):
    path=Path(name);parts={part.lower() for part in path.parts};base=path.name.lower()
    return (bool(parts & {'backups','media','.cloudflared','terrain-source','eva_images'}) or
            base in {'.session-secret','ideas.txt'} or
            (base.startswith('.env') and base!='.env.example') or
            base.startswith('credentials') or path.suffix.lower() in {'.db','.sqlite','.sqlite3','.pem','.key','.mp3'} or
            base.endswith(('-wal','-shm')) or
            ('static' in parts and 'eva' in parts and path.suffix.lower() in {'.jpg','.jpeg','.png'}))

def check_files(root,names):
    errors=[]
    for name in names:
        if private_path(name):errors.append(f'{name}: host-private file must not be published');continue
        path=root/name
        if not path.is_file() or path.suffix.lower() in {'.bin','.gz'}:continue
        try:text=path.read_text(encoding='utf-8')
        except UnicodeDecodeError:continue
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):errors.append(f'{name}: private key material')
        if re.search(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b',text):errors.append(f'{name}: GitHub credential')
    return errors

def public_files(root,archive=False):
    if archive:return sorted(str(p.relative_to(root)).replace('\\','/') for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in ('.git','__pycache__','.venv')))
    result=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root,check=True,capture_output=True)
    return sorted(set(result.stdout.decode('utf-8').strip('\0').split('\0')))

def validate(root,names):
    errors=check_files(root,names)
    for name in REQUIRED:
        if name not in names:errors.append(f'{name}: required release file missing')
    for name in ('land-cells.bin','coastal-cells.bin'):
        path=root/'data'/name
        if not path.exists() or path.stat().st_size!=236500:errors.append(f'data/{name}: terrain mask missing or wrong size')
    try:
        raw=(root/'data/pacific-islands.geojson').read_bytes();collection=json.loads(raw)
        keys=[feature['properties']['key'] for feature in collection['features']]
        if len(keys)!=len(set(keys)):errors.append('data/pacific-islands.geojson: duplicate territory IDs')
        if gzip.decompress((root/'data/pacific-islands.geojson.gz').read_bytes())!=raw:errors.append('data/pacific-islands.geojson.gz: stale compressed geography')
        for name in ('countries.geojson','land.geojson'):
            if json.loads((root/'data'/name).read_text(encoding='utf-8')).get('type')!='FeatureCollection':errors.append(f'data/{name}: invalid collection')
    except (OSError,ValueError,KeyError) as error:errors.append(f'data: geography validation failed ({type(error).__name__})')
    try:
        tree=ast.parse((root/'config.py').read_text(encoding='utf-8'))
        community=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='COMMUNITY' for t in n.targets))
        if community.get('vipps_number'):errors.append('config.py: clear personal payment details before publishing')
    except (OSError,SyntaxError,ValueError,StopIteration):errors.append('config.py: unable to validate public community settings')
    return errors

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',action='store_true',help='Check an extracted source archive without Git');args=parser.parse_args()
    problems=validate(ROOT,public_files(ROOT,args.archive))
    for problem in problems:print(problem)
    if problems:raise SystemExit(1)
    print('Public release checks passed: private-file exclusions, payment redaction and geography integrity.')
