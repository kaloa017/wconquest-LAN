"""Package current public files, including uncommitted fixes, without host saves."""
import argparse
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from check_release import ROOT, public_files, check_files


def package(output):
    root=ROOT.resolve()
    names=public_files(root)
    errors=check_files(root,names)
    if errors:
        raise ValueError('\n'.join(errors))
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            path=root/name
            if not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Cannot package linked files: '+name)
            info=zipfile.ZipInfo(name.replace('\\','/'))
            info.create_system=3
            info.external_attr=0o100644 << 16
            archive.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(package(args.output))
