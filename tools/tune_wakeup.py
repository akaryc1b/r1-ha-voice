"""相对设备实际原生配置收紧唤醒门槛；只写外置覆盖，保留系统配置。"""
import argparse
from datetime import datetime,timezone
import math
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

KEYS=('wakeup_benchmark','wakeup_benchmark_for_music_playing',
      'wakeup_benchmark_for_music_playing_two','wakeup_benchmark_for_music_playing_three',
      'wakeup_benchmark_for_continues')


def tune(source,offset):
    if not math.isfinite(offset) or not 0<=offset<=3:
        raise ValueError('偏移需为0～3；越大越严格，也可能降低远场唤醒率')
    result=source
    changes={}
    for key in KEYS:
        pattern=r'(?m)^('+re.escape(key)+r'\s*=\s*)(-?[0-9]+(?:\.[0-9]+)?)([ \t]*\r?)$'
        matches=list(re.finditer(pattern,result))
        if len(matches)!=1:raise ValueError('原生配置字段缺失或重复：'+key)
        before=float(matches[0][2]);after=round(before+offset,3)
        changes[key]=(before,after)
        result=re.sub(pattern,lambda m:m[1]+format(after,'.3f').rstrip('0').rstrip('.')+m[3],result)
    return result,changes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default='adb')
    parser.add_argument('--serial',required=True)
    parser.add_argument('--offset',type=float,default=1.5)
    parser.add_argument('--backup-dir',type=Path,default=Path(__file__).resolve().parents[1]/'device/build/backups')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    def adb(*parts):
        return subprocess.run([args.adb,'-s',args.serial,*parts],check=True,capture_output=True,timeout=45).stdout
    source=adb('shell','cat','/system/unisound/config/config.mg').decode('utf-8').replace('\r','')
    result,changes=tune(source,args.offset)
    for key,(before,after) in changes.items():print(key,before,'->',after)
    if not args.apply:
        print('仅预览；加 --apply 才会保存。不会自动重启语音应用。');return
    override='/sdcard/unisound/config/config.mg'
    previous=adb('shell','if [ -f '+override+' ]; then cat '+override+'; else echo R1_EXTERNAL_CONFIG_MISSING; fi')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=args.backup_dir/stamp;backup.mkdir(parents=True)
    (backup/'system.private.mg').write_text(source,encoding='utf-8',newline='')
    if b'R1_EXTERNAL_CONFIG_MISSING' not in previous:
        (backup/'external.private.mg').write_bytes(previous)
    else:(backup/'no-external-config.txt').write_text('No previous external override\n')
    with tempfile.TemporaryDirectory(prefix='r1-wakeup-') as temporary:
        local=Path(temporary)/'config.mg';local.write_text(result,encoding='utf-8',newline='')
        adb('push',str(local),'/sdcard/r1-wakeup-config.pending')
        expected=hashlib.sha256(local.read_bytes()).hexdigest()
        staged=adb('shell','/system/bin/busybox','sha256sum','/sdcard/r1-wakeup-config.pending').decode().split()[0]
        if staged!=expected:raise ValueError('设备暂存内容校验失败')
        adb('shell','mkdir -p /sdcard/unisound/config && mv /sdcard/r1-wakeup-config.pending '+override)
        saved=adb('shell','/system/bin/busybox','sha256sum',override).decode().split()[0]
        if saved!=expected:raise ValueError('外置配置保存校验失败')
    print('已保存，重启语音应用后生效；原配置备份：',backup)


if __name__=='__main__':main()
