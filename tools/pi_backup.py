"""Online SQLite backup plus private host assets, without importing the game."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone

BACKUP_NAME = re.compile(r'wconquest-\d{8}T\d{6}-\d{9}Z')


def create_backup(database, directory, keep=14, eva_directory=None):
    if keep < 1:
        raise ValueError('Keep at least one backup')
    database = Path(database).resolve(strict=True)
    directory = Path(directory).resolve()
    if directory == database.parent or directory in database.parents:
        raise ValueError('Use a separate backup directory')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    name = f'wconquest-{stamp}-{time.time_ns() % 1_000_000_000:09d}Z'
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=directory) as temporary:
        stage = Path(temporary)
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=30)) as source:
            with closing(sqlite3.connect(stage/'game.db')) as target:
                source.backup(target)
                if target.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise RuntimeError('Backup database integrity check failed')
        os.chmod(stage/'game.db', 0o600)
        for filename in ('.session-secret', 'ideas.txt'):
            path = database.parent/filename
            if path.is_file():
                shutil.copy2(path, stage/filename)
        media = database.parent/'media'
        if media.is_dir():
            shutil.copytree(media, stage/'media')
        if eva_directory and Path(eva_directory).is_dir():
            shutil.copytree(eva_directory, stage/'eva')
        (stage/'manifest.json').write_text(json.dumps({'format':1, 'created_utc':stamp, 'database':'game.db'}), encoding='utf-8')
        destination = directory/name
        stage.rename(destination)
    # Only this tool's completed, regular backup folders qualify for retention.
    completed = sorted(path for path in directory.iterdir()
                       if BACKUP_NAME.fullmatch(path.name) and not path.is_symlink()
                       and path.is_dir() and (path/'manifest.json').is_file())
    for expired in completed[:-keep]:
        if expired.resolve().parent != directory:
            raise ValueError('Backup retention path escaped the backup directory')
        shutil.rmtree(expired)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=os.getenv('DB_PATH'))
    parser.add_argument('--directory', required=True)
    parser.add_argument('--keep', type=int, default=14)
    parser.add_argument('--eva-directory', default=str(Path(__file__).resolve().parents[1]/'static'/'eva'))
    args = parser.parse_args()
    if not args.database:
        parser.error('Set DB_PATH or use --database')
    print(create_backup(args.database, args.directory, args.keep, args.eva_directory))


if __name__ == '__main__':
    main()
