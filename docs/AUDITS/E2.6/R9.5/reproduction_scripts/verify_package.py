"""Verify package SHA256SUMS; no inference, extraction, or runtime imports."""
import argparse,hashlib
from pathlib import Path

def verify(root):
    root=Path(root).resolve();checked=0
    for line in (root/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split('  ',1);path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('invalid package member')
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1048576),b''):h.update(block)
        if h.hexdigest()!=expected:raise ValueError('checksum mismatch: '+name)
        checked+=1
    return checked

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();print('MATCHED',verify(args.root))
