"""从唯一设置文件渲染 HA 准备目录，不连接设备、不覆盖现有配置。"""
from __future__ import annotations

import argparse
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent
FIELDS = {'queue_id', 'provider', 'r1_url', 'ma_url'}


class Include(str):
    pass


class Loader(yaml.SafeLoader):
    pass


class Dumper(yaml.SafeDumper):
    pass


Loader.add_constructor('!include', lambda loader,node:Include(loader.construct_scalar(node)))
Dumper.add_representer(Include,lambda dumper,value:dumper.represent_scalar('!include',str(value)))


def validate_settings(settings):
    if not isinstance(settings,dict) or set(settings)!=FIELDS:
        raise ValueError('设置必须且只能包含 queue_id、provider、r1_url、ma_url')
    if any(not isinstance(value,str) or not value.strip() for value in settings.values()):
        raise ValueError('所有设置必须是非空字符串')
    result={key:value.strip() for key,value in settings.items()}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',result['queue_id']):
        raise ValueError('queue_id 格式不正确')
    if not re.fullmatch(r'apple_music(?:--[A-Za-z0-9_-]+)?',result['provider']):
        raise ValueError('provider 必须是 apple_music 域或其具体实例 ID')
    for key in ('r1_url','ma_url'):
        value=result[key]
        url=urlsplit(value)
        if (url.scheme not in ('http','https') or not url.hostname or url.username is not None or url.password is not None
                or url.query or url.fragment or re.search(r'[\s{}<>"\x00-\x1f]',value)):
            raise ValueError(key+' 必须是不含凭据、查询和片段的 HTTP(S) 地址')
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError(key+' 端口不正确')
        if re.fullmatch(r'[0-9.]+',url.hostname) or ':' in url.hostname:
            ipaddress.ip_address(url.hostname)
        elif not re.fullmatch(r'[A-Za-z0-9.-]+',url.hostname):
            raise ValueError(key+' 主机名不正确')
        result[key]=value.rstrip('/')
    return result


def replace_tokens(value,settings):
    if isinstance(value,str):
        text=value
        for key,item in settings.items():
            text=text.replace('__'+key.upper()+'__',item)
        if re.search(r'__[A-Z][A-Z0-9_]*__',text):
            raise ValueError('模板中存在未知配置占位符')
        return Include(text) if isinstance(value,Include) else text
    if isinstance(value,list):
        return [replace_tokens(item,settings) for item in value]
    if isinstance(value,dict):
        return {key:replace_tokens(item,settings) for key,item in value.items()}
    return value


def render(settings,output):
    settings=validate_settings(settings)
    sources={
        'r1_apple_music.yaml':ROOT/'packages/r1_apple_music.yaml',
        'r1_music_player.yaml':ROOT/'packages/r1_music_player.yaml',
        'r1_music_dashboard.yaml':ROOT/'dashboards/r1_music_dashboard.yaml',
        'configuration.snippet.yaml':ROOT/'configuration.snippet.yaml',
    }
    plan={}
    for name,source in sources.items():
        data=yaml.load(source.read_text(encoding='utf-8'),Loader=Loader)
        text=yaml.dump(replace_tokens(data,settings),Dumper=Dumper,allow_unicode=True,sort_keys=False,width=120)
        plan[name]=text.encode('utf-8')
    plan['r1-ma.env.example']=('R1_MA_QUEUE_ID='+settings['queue_id']+'\n').encode('utf-8')
    output=Path(output).resolve()
    if output in {ROOT,ROOT/'packages',ROOT/'dashboards'}:
        raise ValueError('输出必须是独立准备目录，不能覆盖仓库模板')
    for name,data in plan.items():
        target=output/name
        if target.exists() and target.read_bytes()!=data:
            raise ValueError('准备目录已有不同内容，请选择新目录：'+name)
    output.mkdir(parents=True,exist_ok=True)
    for name,data in plan.items():
        (output/name).write_bytes(data)
    return list(plan)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,default=ROOT/'r1_settings.yaml')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'rendered')
    args=parser.parse_args(argv)
    try:
        settings=yaml.safe_load(args.settings.read_text(encoding='utf-8'))
        files=render(settings,args.output_dir)
        print('已准备 '+str(len(files))+' 个文件；尚未部署 HA 或修改 MA 环境。')
        return 0
    except (OSError,ValueError,yaml.YAMLError) as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__':
    raise SystemExit(main())
