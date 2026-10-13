"""Fetch pinned official provider sources into an explicit preparation directory."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads((ROOT/'upstream-manifest.json').read_text())
    for item in manifest['upstream_provider_files']:
        relative=Path(item['name'])
        if relative.is_absolute() or '..' in relative.parts:raise SystemExit('Invalid provider path')
        target=args.output_dir/relative
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:
                raise SystemExit('Existing preparation file differs: '+item['name'])
            continue
        data=urllib.request.urlopen(item['url'],timeout=30).read()
        if hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise SystemExit('Upstream checksum mismatch: '+item['name'])
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
    print('Prepared pinned upstream source files:',len(manifest['upstream_provider_files']))


if __name__=='__main__':main()
