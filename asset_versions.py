"""Cache static files by content, including edits within an unreleased version."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

@lru_cache(maxsize=128)
def fingerprint(filename,mtime,size):
    return sha256(Path(filename).read_bytes()).hexdigest()[:12]

def asset_version(root,url,version):
    static=(Path(root)/'static').resolve();path=(Path(root)/url.lstrip('/')).resolve()
    if not path.is_relative_to(static):return str(version)
    try:
        info=path.stat();digest=fingerprint(str(path),info.st_mtime_ns,info.st_size)
    except OSError:return str(version)
    return str(version)+'&h='+digest
