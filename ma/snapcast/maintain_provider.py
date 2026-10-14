"""Check/apply/restore reviewed Snapcast source within an existing MA installation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import time

ROOT=Path(__file__).resolve().parent


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider-dir',type=Path,required=True)
    parser.add_argument('--backup-dir',type=Path)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--apply',action='store_true')
    actions.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    manifest=json.loads((ROOT/'upstream-manifest.json').read_text(encoding='utf-8'))
    if importlib.metadata.version('music-assistant')!=manifest['music_assistant_version']:
        raise SystemExit('Only Music Assistant '+manifest['music_assistant_version']+' is covered')
    if (args.apply or args.restore) and not args.backup_dir:
        raise SystemExit('Pass --backup-dir for a source-only backup before writing')
    plan=[]
    for item in manifest['files']:
        target=args.provider_dir/item['name']
        current_bytes=target.read_bytes() if target.exists() else None
        current=hashlib.sha256(current_bytes).hexdigest() if current_bytes is not None else None
        known={item['upstream_sha256'],item['patched_sha256'],*item.get('accepted_prior_sha256',[])}
        normalized=hashlib.sha256(current_bytes.replace(b'\r\n',b'\n')).hexdigest() if current_bytes is not None else None
        if current not in known and normalized not in known:
            raise SystemExit('Unknown source; refuse overwrite: '+item['name'])
        source=ROOT/('upstream' if args.restore else 'provider')/item['name']
        if args.restore and item['upstream_sha256'] is None:
            continue  # Leave the unreferenced helper in place; no deletion is needed.
        payload=source.read_bytes()
        expected=item['upstream_sha256'] if args.restore else item['patched_sha256']
        if hashlib.sha256(payload).hexdigest()!=expected:raise SystemExit('Backup payload checksum mismatch')
        compile(payload,str(target),'exec')
        plan.append((target,payload,current))
    backup=None
    if args.apply or args.restore:
        backup=args.backup_dir/str(time.time_ns())
        backup.mkdir(parents=True,exist_ok=False)
        for target,payload,current in plan:
            if target.exists():shutil.copy2(target,backup/target.name)
        for target,payload,current in plan:
            temp=target.with_suffix(target.suffix+'.r1-staged')
            temp.write_bytes(payload);os.replace(temp,target)
    print(json.dumps({'verified_files':len(plan),'written':bool(args.apply or args.restore),
                      'backup':str(backup) if backup else None},indent=2))


if __name__=='__main__':main()
