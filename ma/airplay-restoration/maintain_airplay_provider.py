"""Check or restore the official optional AirPlay files for MA 2.10.6."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import shutil
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
assert importlib.metadata.version('music-assistant') == '2.10.6', 'Unknown MA version; refusing restore'
root = Path('/data/r1-cloud-voice/airplay-restoration')
bundle = root / 'bundle'
if not bundle.exists():
    assert args.apply, 'Restoration bundle is not extracted'
    with tarfile.open(root / 'official-airplay-provider.tar.gz', 'r:gz') as archive:
        archive.extractall(bundle, filter='data')
site = Path('/app/venv/lib/python3.14/site-packages')
files = []
for item in json.loads((bundle / 'dependency-files.json').read_text()):
    files.append((bundle / 'dependencies' / item['file'], site / item['file'], item['sha256']))
for source in (bundle / 'source').rglob('*'):
    if source.is_file():
        target = site / 'music_assistant/providers' / source.relative_to(bundle / 'source')
        files.append((source, target, hashlib.sha256(source.read_bytes()).hexdigest()))
source = bundle / 'cliairplay-linux-aarch64'
files.append((source, site / 'music_assistant/providers/airplay/bin/cliairplay-linux-aarch64',
              hashlib.sha256(source.read_bytes()).hexdigest()))
missing = []
for source, target, expected in files:
    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected, 'Backup checksum mismatch'
    if target.exists():
        assert target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected, \
            'Existing file differs; refusing overwrite: ' + str(target)
    else:
        missing.append((source, target))
if args.apply:
    for source, target in missing:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (site / 'music_assistant/providers/airplay/bin/cliairplay-linux-aarch64').chmod(0o755)
print(json.dumps({'version': '2.10.6', 'checked_files': len(files),
                  'missing_before': len(missing), 'restored': len(missing) if args.apply else 0}))
if missing and not args.apply:
    raise SystemExit(1)
