"""容器启动边界复用网关校验；环境变量仅提供非秘密覆盖与文件路径。"""
import json
import os
from pathlib import Path
import sys


def prepare(code,state,environment=None):
    sys.path.insert(0,str(code))
    from gateway_config import DEFAULTS,SECRETS,GatewayConfig
    environment=os.environ if environment is None else environment
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    store=GatewayConfig(state)
    patch={}
    if not store.path.exists():
        patch=json.loads((Path(code)/'gateway.example.json').read_text(encoding='utf-8'))
        patch['bind_host']='0.0.0.0'
        patch['local_asr_url']='http://127.0.0.1:16066'
    for field,default in DEFAULTS.items():
        name='R1_'+field.upper()
        if field in SECRETS:
            if name in environment:raise ValueError('秘密值请使用 '+name+'_FILE')
            if name+'_FILE' in environment:
                with Path(environment[name+'_FILE']).open('rb') as source:data=source.read(4097)
                if len(data)>4096:raise ValueError('秘密文件过大：'+field)
                patch[field]=data.decode('utf-8').strip()
        elif name in environment:
            raw=environment[name]
            patch[field]=raw if isinstance(default,str) else json.loads(raw)
    current=store.snapshot()
    patch={key:value for key,value in patch.items() if current.get(key)!=value}
    if patch:store.update(patch)
    # 重新读取启动绑定值，避免把启动覆盖误标为需重启。
    return GatewayConfig(state)
