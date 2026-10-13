import hashlib,json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent
target=root/'tools';target.mkdir(exist_ok=True)
for item in json.loads((root/'build-tools.json').read_text()):
 p=target/item['name']
 if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
  with urllib.request.urlopen(item['url'],timeout=30) as response:data=response.read()
  if hashlib.sha256(data).hexdigest()!=item['sha256']:raise SystemExit('Checksum mismatch: '+item['name'])
  p.write_bytes(data)
 print('Verified',item['name'])
