"""Explicitly acquire exact source archives and only declared adapter files.

Does not install dependencies or import/execute the upstream source. Existing
modified cache files are preserved and cause an error instead of being replaced.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/find-robot-skills/scripts'))
from rshlib.prepare import download_archive,extract_archive


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,required=True);p.add_argument('--fetch',action='store_true');args=p.parse_args()
    manifest=json.loads((ROOT/'catalog/executable-conversions.json').read_text())
    args.cache.mkdir(parents=True,exist_ok=True)
    for key,source in manifest['sources'].items():
        archive=args.cache/(key+'.tar.gz')
        if archive.is_symlink():raise ValueError('Cache archive cannot be a symlink')
        if not archive.is_file():
            if not args.fetch:raise ValueError('Missing archive; use explicit --fetch')
            with tempfile.TemporaryDirectory(dir=args.cache) as work:
                temp=Path(work)/'source.tar.gz';download_archive(source['archive_url'],temp,source['archive_sha256']);temp.replace(archive)
        archive_hash=hashlib.sha256()
        with archive.open('rb') as stream:
            while chunk:=stream.read(1024*1024):archive_hash.update(chunk)
        if archive_hash.hexdigest()!=source['archive_sha256']:
            raise ValueError('Cached archive checksum mismatch; preserved')
        target=args.cache/key
        if target.is_symlink():raise ValueError('Cache root cannot be a symlink')
        with tempfile.TemporaryDirectory(dir=args.cache) as work:
            extract_archive(archive,work,source['commit'],set(source['source_hashes']))
            for relative,expected in source['source_hashes'].items():
                src=Path(work)/relative
                if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=expected:raise ValueError('Source guard does not match exact archive: '+relative)
                dest=target/relative
                if dest.is_symlink() or not dest.resolve().is_relative_to(args.cache.resolve()):raise ValueError('Unsafe cache target')
                if dest.exists():
                    if hashlib.sha256(dest.read_bytes()).hexdigest()!=expected:raise ValueError('Modified source cache preserved: '+relative)
                else:
                    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(src.read_bytes())
        print(key+': verified '+str(len(source['source_hashes']))+' exact declared files',flush=True)


if __name__=='__main__':main()
