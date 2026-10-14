"""显式下载并校验公开运行时或模型；常规启动不访问下载地址。"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request

MODEL_NAMES=('encoder-epoch-99-avg-1.int8.onnx','decoder-epoch-99-avg-1.int8.onnx',
             'joiner-epoch-99-avg-1.int8.onnx','tokens.txt')


def manifest(path):
    entries=json.loads(Path(path).read_text(encoding='utf-8'))
    for entry in entries:
        if (not isinstance(entry,dict) or len(entry.get('sha256',''))!=64
                or any(c not in '0123456789abcdef' for c in entry['sha256'])
                or not entry.get('url','').startswith('https://')):
            raise ValueError('来源清单无效')
    return entries


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def download(entry,destination):
    destination=Path(destination)
    if destination.is_file() and digest(destination)==entry['sha256']:return
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.part')
    try:
        request=urllib.request.Request(entry['url'],headers={'User-Agent':'r1-ha-voice-bootstrap'})
        with urllib.request.urlopen(request,timeout=30) as response,temporary.open('wb') as output:
            if not response.geturl().startswith('https://'):raise ValueError('拒绝非 HTTPS 下载')
            shutil.copyfileobj(response,output,1024*1024)
        if digest(temporary)!=entry['sha256']:raise ValueError('下载校验失败：'+entry['name'])
        temporary.replace(destination)
    finally:temporary.unlink(missing_ok=True)


def model_entries(entries):
    selected=[]
    for name in MODEL_NAMES:
        matches=[entry for entry in entries if entry['name']==name]
        if len(matches)!=1:raise ValueError('模型来源缺失或重复：'+name)
        selected.append(matches[0])
    return selected


def verify_models(entries,directory):
    for entry in model_entries(entries):
        path=Path(directory)/entry['name']
        if not path.is_file() or digest(path)!=entry['sha256']:
            raise ValueError('模型缺失或校验失败；请先显式执行 bootstrap：'+entry['name'])


def bootstrap(entries,directory):
    for entry in model_entries(entries):
        download(entry,Path(directory)/entry['name'])
        print('已校验：'+entry['name'],flush=True)


def extract_runtime(archive,directory):
    """先写普通文件，再创建仅指向归档内部的链接，拒绝目录逃逸。"""
    directory=Path(directory).resolve()
    links=[]
    with tarfile.open(archive,'r:bz2') as source:
        for member in source.getmembers():
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or '\\' in member.name:
                raise ValueError('运行时归档路径无效')
            target=directory.joinpath(*name.parts)
            if member.isdir():target.mkdir(parents=True,exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True,exist_ok=True)
                with source.extractfile(member) as content,target.open('wb') as output:
                    shutil.copyfileobj(content,output)
                target.chmod(member.mode & 0o755)
            elif member.issym() or member.islnk():links.append((member,target))
            else:raise ValueError('运行时归档包含不支持的节点')
    hardlinks=[]
    for member,target in links:
        if PurePosixPath(member.linkname).is_absolute():raise ValueError('运行时链接无效')
        linked=(target.parent/member.linkname if member.issym() else directory/member.linkname).resolve()
        if not linked.is_relative_to(directory):raise ValueError('运行时链接越界')
        target.parent.mkdir(parents=True,exist_ok=True)
        if member.issym():target.symlink_to(member.linkname)
        else:hardlinks.append((target,linked))
    for target,linked in hardlinks:
        if not linked.is_file():raise ValueError('运行时硬链接目标缺失')
        os.link(linked,target)
    for _,target in links:
        if not target.resolve().is_relative_to(directory) or not target.is_file():
            raise ValueError('运行时链接越界或目标缺失')


def install_runtime(entries,architecture,destination):
    matches=[e for e in entries if e.get('architecture')==architecture]
    if architecture not in {'arm64','amd64'} or len(matches)!=1:
        raise ValueError('仅提供 ARM64 与 amd64 固定版本运行时')
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():raise ValueError('运行时目标应为空')
    with tempfile.TemporaryDirectory(prefix='sherpa-build-',dir=destination.parent) as temporary:
        work=Path(temporary);archive=work/'runtime.tar.bz2'
        download(matches[0],archive)
        extract_runtime(archive,work/'extracted')
        binaries=list((work/'extracted').glob('*/bin/sherpa-onnx-online-websocket-server'))
        if len(binaries)!=1:raise ValueError('运行时缺少唯一 WebSocket server')
        binaries[0].parent.parent.replace(destination)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=('runtime','bootstrap','verify'))
    parser.add_argument('--sources',default='/opt/r1/asr/sources.json')
    parser.add_argument('--destination',required=True)
    parser.add_argument('--architecture')
    args=parser.parse_args();entries=manifest(args.sources)
    if args.operation=='runtime':install_runtime(entries,args.architecture,args.destination)
    elif args.operation=='bootstrap':bootstrap(entries,args.destination)
    else:verify_models(entries,args.destination)


if __name__=='__main__':main()
