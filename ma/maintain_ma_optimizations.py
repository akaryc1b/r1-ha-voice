"""核对、重装或恢复同版本 MA 的少量优化，拒绝覆盖未知版本源码。"""
import argparse,hashlib,json
from pathlib import Path
import music_assistant
ROOT=Path(__file__).resolve().parent
PACKAGE=ROOT/'ma-final' if (ROOT/'ma-final').is_dir() else ROOT
manifest=json.loads((ROOT/'ma-optimizations-manifest.json').read_text())
parser=argparse.ArgumentParser()
group=parser.add_mutually_exclusive_group()
group.add_argument('--check',action='store_true')
group.add_argument('--apply',action='store_true')
group.add_argument('--restore',action='store_true')
args=parser.parse_args()
base=Path(music_assistant.__file__).resolve().parent
plan=[]
def sha(data):return hashlib.sha256(data).hexdigest()
for item in manifest['files']:
 relative=Path(item['path'])
 if relative.is_absolute() or '..' in relative.parts:raise SystemExit('Invalid package path')
 target=base/relative
 current=sha(target.read_bytes())
 if current not in {item['before_sha256'],item['after_sha256']}:
  raise SystemExit('MA source differs from the tested version: '+item['path'])
 which='before' if args.restore else 'after'
 payload=(PACKAGE/item[which+'_file']).read_bytes()
 if sha(payload)!=item[which+'_sha256']:raise SystemExit('Payload checksum mismatch')
 compile(payload,str(target),'exec')
 plan.append((target,payload,current,item))
for target,payload,current,item in plan:
 state='optimized' if current==item['after_sha256'] else 'original'
 print(item['path'],state)
 if args.apply or args.restore:target.write_bytes(payload)
if args.apply or args.restore:print('Source changes saved. Restart the existing MA container to load them.')
else:print('Read-only verification passed; no files changed.')
