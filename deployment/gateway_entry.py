"""仅改变部署时的配置根目录，不改变网关端点或协议。"""
import os
from pathlib import Path
import sys
from configuration import prepare


def main():
    os.umask(0o077)
    code=Path('/opt/r1/gateway');state=Path('/data')
    settings=prepare(code,state)
    sys.path.insert(0,str(code))
    import voice_gateway as gateway
    gateway.SETTINGS=settings
    gateway.app['event_log_dir']=state/'diagnostic-logs'
    config=settings.snapshot()
    gateway.web.run_app(gateway.app,host=config['bind_host'],port=config['bind_port'],access_log=None)


if __name__=='__main__':main()
