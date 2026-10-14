"""只读检查受监督进程、ASR WebSocket 握手与网关健康端点。"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import urllib.request

STATE=Path('/tmp/r1-health.json')


def websocket_ready(port=16066):
    key=base64.b64encode(os.urandom(16)).decode('ascii')
    request=(f'GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n'
             f'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n')
    with socket.create_connection(('127.0.0.1',port),timeout=2) as connection:
        connection.sendall(request.encode('ascii'));data=b''
        while b'\r\n\r\n' not in data and len(data)<8192:
            chunk=connection.recv(1024)
            if not chunk:break
            data+=chunk
    expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
    return data.startswith(b'HTTP/1.1 101 ') and b'sec-websocket-accept: '+expected.lower() in data.lower()


def process_alive(pid):
    if type(pid) is not int or pid<=1 or os.name!='posix':return False
    try:os.kill(pid,0);return True
    except (OSError,ValueError):return False


def healthy(state=STATE):
    payload=json.loads(Path(state).read_text(encoding='utf-8'))
    if not all(process_alive(payload.get(key)) for key in ('asr_pid','gateway_pid')):return False
    if not websocket_ready():return False
    address=payload['gateway_host']
    if address in {'0.0.0.0','::'}:address='127.0.0.1'
    if ':' in address:address='['+address+']'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://{address}:{payload['gateway_port']}/health",timeout=2) as response:
        data=response.read(65537)
        return response.status==200 and len(data)<=65536 and json.loads(data).get('ready') is True


if __name__=='__main__':
    try:success=healthy()
    except Exception:success=False
    raise SystemExit(0 if success else 1)
