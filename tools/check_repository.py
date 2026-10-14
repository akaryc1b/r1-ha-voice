"""检查发布文件、文档链接和补丁清单；不读取私人运行目录。"""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [re.compile(rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}'),
            re.compile(rb'sk-[A-Za-z0-9_-]{20,}'),
            re.compile(rb'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='同时扫描可达 Git 历史的凭据格式')
    args = parser.parse_args()
    paths = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).decode('utf-8').split('\0')
    errors, count, total = [], 0, 0
    for rel in set(paths):
        file = ROOT / rel
        if not rel or not file.is_file():
            continue
        data = file.read_bytes()
        count += 1
        total += len(data)
        if any(pattern.search(data) for pattern in PATTERNS):
            errors.append({'file': rel, 'kind': 'credential-pattern'})
        if re.search(r'\.private|(?:^|/)diagnostic-logs/|\.(?:apk|jar|onnx|pyc|class|jks|keystore|p12|pfx|pem|log)$', rel):
            errors.append({'file': rel, 'kind': 'private-or-generated-artifact'})
        if file.suffix == '.md':
            text = data.decode('utf-8')
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                if re.match(r'^[a-z]+://', target) or target.startswith('#'):
                    continue
                target = target.split('#', 1)[0]
                if target and not (file.parent / target).exists():
                    errors.append({'file': rel, 'kind': 'missing-link', 'target': target})
    # 清单既是来源契约也是发布内容，必须与实际 patch 字节一致。
    spec = importlib.util.spec_from_file_location('checked_ma_tool', ROOT / 'ma/maintain_ma_optimizations.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    manifest, _ = tool.read_bundle()
    tool.read_migrations(manifest)
    tool.read_upgrade(manifest)
    snap = ROOT / 'ma/snapcast'
    manifest = json.loads((snap / 'upstream-manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        for folder, key in [('provider', 'patched_sha256'), ('upstream', 'upstream_sha256')]:
            if entry[key] is not None:
                data = (snap / folder / entry['name']).read_bytes()
                if hashlib.sha256(data).hexdigest() != entry[key]:
                    errors.append({'file': folder + '/' + entry['name'], 'kind': 'snapcast-manifest-mismatch'})
    hacs = json.loads((ROOT / 'hacs.json').read_text(encoding='utf-8'))
    if hacs.get('filename') != 'r1-ha-voice.js' or not (ROOT / hacs['filename']).is_file():
        errors.append({'file': 'hacs.json', 'kind': 'invalid-card-entry'})
    history_count = 0
    if args.history:
        objects = subprocess.check_output(['git', '-C', str(ROOT), 'rev-list', '--objects', '--all']).splitlines()
        for row in objects:
            oid = row.split(b' ', 1)[0]
            kind = subprocess.check_output(['git', '-C', str(ROOT), 'cat-file', '-t', oid]).strip()
            if kind != b'blob':
                continue
            data = subprocess.check_output(['git', '-C', str(ROOT), 'cat-file', 'blob', oid])
            history_count += 1
            if any(pattern.search(data) for pattern in PATTERNS):
                errors.append({'object': oid.decode(), 'kind': 'historical-credential-pattern'})
    print(json.dumps({'files': count, 'bytes': total, 'history_blobs': history_count, 'issues': errors}, ensure_ascii=False))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
