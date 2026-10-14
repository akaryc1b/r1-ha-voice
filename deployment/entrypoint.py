"""监督两个子服务；任一退出则停全组，由容器重启策略恢复。"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from assets import bootstrap,manifest,verify_models
from configuration import prepare
from healthcheck import STATE,websocket_ready

CODE=Path('/opt/r1/gateway')
SOURCES=Path('/opt/r1/asr/sources.json')
MODELS=Path('/models')


def asr_command(models=MODELS):
    command=['/opt/sherpa/bin/sherpa-onnx-online-websocket-server','--port=16066',
        '--num-threads=2','--num-work-threads=1','--num-io-threads=1','--max-batch-size=1',
        '--model-type=zipformer','--decoding-method=modified_beam_search',
        '--hotwords-file=/opt/r1/asr/music-hotwords.txt','--hotwords-score=1.5',
        '--rule2-min-trailing-silence=1.3','--rule1-min-trailing-silence=4',
        '--log-file=/tmp/r1-local-asr.log','--print-args=false']
    for flag,name in [('tokens','tokens.txt'),('encoder','encoder-epoch-99-avg-1.int8.onnx'),
            ('decoder','decoder-epoch-99-avg-1.int8.onnx'),('joiner','joiner-epoch-99-avg-1.int8.onnx')]:
        command.append('--'+flag+'='+str(Path(models)/name))
    return command


def stop_children(children,grace=8):
    for child in children:
        if child.poll() is None:
            try:
                if os.name=='posix':os.killpg(child.pid,signal.SIGTERM)
                else:child.terminate()
            except ProcessLookupError:pass
    deadline=time.monotonic()+grace
    for child in children:
        try:child.wait(timeout=max(0,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                if os.name=='posix':os.killpg(child.pid,signal.SIGKILL)
                else:child.kill()
            except ProcessLookupError:pass
            child.wait()


def supervise(commands,ready=websocket_ready,on_ready=None,start_timeout=90):
    stopping=False;children=[];old_handlers={}
    def stop_signal(signum,frame):
        nonlocal stopping
        stopping=True
    for signum in (signal.SIGTERM,signal.SIGINT):
        old_handlers[signum]=signal.signal(signum,stop_signal)
    try:
        for index,command in enumerate(commands):
            environment=os.environ.copy();environment.pop('LD_PRELOAD',None)
            if index==0:environment['LD_LIBRARY_PATH']='/opt/sherpa/lib'
            children.append(subprocess.Popen(command,env=environment,start_new_session=True))
            if index==0:
                deadline=time.monotonic()+start_timeout
                while not stopping:
                    if children[0].poll() is not None:raise RuntimeError('ASR 子进程提前退出')
                    try:
                        if ready():break
                    except OSError:pass
                    if time.monotonic()>=deadline:raise RuntimeError('ASR 启动等待超时')
                    time.sleep(.1)
            if stopping:return 0
        if on_ready:on_ready(children)
        while not stopping:
            if any(child.poll() is not None for child in children):return 1
            time.sleep(.1)
        return 0
    finally:
        stop_children(children)
        for signum,handler in old_handlers.items():signal.signal(signum,handler)


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',nargs='?',default='serve',choices=('serve','bootstrap','verify'))
    args=parser.parse_args();entries=manifest(SOURCES)
    if args.operation=='bootstrap':bootstrap(entries,MODELS);return 0
    verify_models(entries,MODELS)
    if args.operation=='verify':return 0
    # 不自动下载。启动前复用校验，失败时不创建监听服务。
    settings=prepare(CODE,Path('/data')).snapshot()
    def save_health(children):
        STATE.write_text(json.dumps({'asr_pid':children[0].pid,'gateway_pid':children[1].pid,
            'gateway_host':settings['bind_host'],'gateway_port':settings['bind_port']}),encoding='utf-8')
    STATE.unlink(missing_ok=True)
    try:
        return supervise([asr_command(),[sys.executable,'/opt/r1/deployment/gateway_entry.py']],on_ready=save_health)
    finally:STATE.unlink(missing_ok=True)


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print('可选语音容器启动失败：'+type(error).__name__+'；检查模型校验与非秘密配置。',file=sys.stderr)
        raise SystemExit(1)
