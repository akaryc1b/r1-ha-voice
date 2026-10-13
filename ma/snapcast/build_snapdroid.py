"""Build the pinned API21 R1 Snapdroid adaptation; no installation is performed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-apk',type=Path,required=True)
    parser.add_argument('--tools-dir',type=Path,required=True,help='smali 2.5.2 tools directory')
    parser.add_argument('--download-tools',action='store_true')
    parser.add_argument('--build-tools',type=Path,required=True,help='Android build-tools directory; 29.0.3 tested')
    parser.add_argument('--java-home',type=Path,default=os.environ.get('JAVA_HOME'))
    parser.add_argument('--keystore',type=Path,required=True)
    parser.add_argument('--key-alias',required=True)
    parser.add_argument('--password-env',default='R1_SIGNING_PASSWORD')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-log',action='store_true',help='Mirror native sync diagnostics to SnapNative logcat; off by default')
    args=parser.parse_args()
    if not os.environ.get(args.password_env):raise SystemExit('Set '+args.password_env+' in the child process environment')
    java=str(args.java_home/('bin/java.exe' if os.name=='nt' else 'bin/java')) if args.java_home else shutil.which('java')
    if not java:raise SystemExit('Set JAVA_HOME or pass --java-home')
    manifest=json.loads((ROOT/'upstream-manifest.json').read_text())
    if hashlib.sha256(args.source_apk.read_bytes()).hexdigest()!=manifest['snapdroid_apk_sha256']:
        raise SystemExit('Use the pinned official Snapdroid 0.29.0.2 APK')
    args.tools_dir.mkdir(parents=True,exist_ok=True)
    for item in json.loads((ROOT/'build-tools.json').read_text()):
        path=args.tools_dir/item['name']
        if not path.exists() and args.download_tools:
            data=urllib.request.urlopen(item['url'],timeout=30).read()
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise SystemExit('Tool checksum mismatch: '+item['name'])
            path.write_bytes(data)
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise SystemExit('Missing or mismatched tool: '+str(path))
    align=args.build_tools/('zipalign.exe' if os.name=='nt' else 'zipalign')
    signer=args.build_tools/'lib/apksigner.jar'
    for path in (align,signer,args.keystore):
        if not path.is_file():raise SystemExit('Missing build input: '+str(path))

    def run(*values: object) -> None:
        subprocess.run([str(v) for v in values],check=True)

    with tempfile.TemporaryDirectory(prefix='r1-snapdroid-build-') as directory:
        work=Path(directory);smali=work/'smali'
        run(java,'-cp',args.tools_dir/'*','org.jf.baksmali.Main','disassemble','--api','21','-o',smali,args.source_apk)
        settings=smali/'de/badaix/snapcast/utils/Settings.smali'
        text=settings.read_text()
        pattern=r'(\.method public doResample\(\)Z\s+\.registers 2\s+const/4 v0, )0x1(\s+return v0\s+\.end method)'
        patched,count=re.subn(pattern,r'\g<1>0x0\2',text)
        if count!=1:raise SystemExit('Unexpected doResample source')
        old='''.method public getAudioEngine()Ljava/lang/String;
    .registers 2

    .line 127
    const-string v0, "Auto"

    return-object v0
.end method'''
        new='''.method public getAudioEngine()Ljava/lang/String;
    .registers 3
    const-string v0, "audioEngine"
    const-string v1, "Auto"
    invoke-virtual {p0, v0, v1}, Lde/badaix/snapcast/utils/Settings;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    return-object v0
.end method'''
        if patched.count(old)!=1:raise SystemExit('Unexpected audio engine getter')
        patched=patched.replace(old,new,1)
        helper=(ROOT/'patches/persist-start.smali').read_text()
        settings.write_text(patched+'\n'+helper,encoding='utf-8')
        service=smali/'de/badaix/snapcast/SnapclientService.smali'
        text=service.read_text();start=text.index('.method public onStartCommand(')
        tail=text[start:];anchor='    :cond_4\n'
        if tail.count(anchor)!=1:raise SystemExit('Unexpected onStartCommand null guard')
        hook='    invoke-static {p0, p1}, Lde/badaix/snapcast/utils/Settings;->persistStart(Landroid/content/Context;Landroid/content/Intent;)V\n'
        text=text[:start]+tail.replace(anchor,anchor+hook,1)
        # The official no-resample branch also drops the hardware burst hint.
        # Keep that hint independently, so OpenSL does not fall back to 192 frames.
        old='''    :cond_5f
    const/4 v4, 0x0

    .line 241
    const-string v3, "*:16:*"

    move-object v14, v3

    move-object v3, v4

    move-object v15, v3
'''
        new='''    :cond_5f
    # Preserve the hardware burst hint independently from optional resampling.
    const-string v4, "android.media.property.OUTPUT_FRAMES_PER_BUFFER"
    invoke-virtual {v3, v4}, Landroid/media/AudioManager;->getProperty(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    const-string v14, "*:16:*"
    const/4 v15, 0x0
'''
        if text.count(old)!=1:raise SystemExit('Unexpected no-resample burst branch')
        text=text.replace(old,new,1)
        if args.native_log:
            anchor='.method private log(Ljava/lang/String;)V\n    .registers 14\n'
            if text.count(anchor)!=1:raise SystemExit('Unexpected native log method')
            text=text.replace(anchor,anchor+'''\n    const-string v0, "SnapNative"
    invoke-static {v0, p1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
''',1)
        service.write_bytes(text.encode('utf-8'))
        dex=work/'patched.dex'
        run(java,'-cp',args.tools_dir/'*','org.jf.smali.Main','assemble','--api','21','-o',dex,smali)
        unsigned=work/'unsigned.apk'
        with zipfile.ZipFile(args.source_apk) as source,zipfile.ZipFile(unsigned,'w') as target:
            for item in source.infolist():
                if item.filename.upper().startswith('META-INF/'):continue
                target.writestr(item,dex.read_bytes() if item.filename=='classes.dex' else source.read(item.filename))
        aligned=work/'aligned.apk'
        run(align,'-f','4',unsigned,aligned)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        run(java,'-jar',signer,'sign','--ks',args.keystore,'--ks-key-alias',args.key_alias,
            '--ks-pass','env:'+args.password_env,'--key-pass','env:'+args.password_env,
            '--min-sdk-version','21','--out',args.output,aligned)
        run(java,'-jar',signer,'verify','--verbose',args.output)
    changed=[]
    with zipfile.ZipFile(args.source_apk) as source,zipfile.ZipFile(args.output) as target:
        for name in source.namelist():
            if not name.upper().startswith('META-INF/') and source.read(name)!=target.read(name):changed.append(name)
    if changed!=['classes.dex']:raise SystemExit('Unexpected APK changes: '+repr(changed))
    report={'source_sha256':manifest['snapdroid_apk_sha256'],
            'output_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
            'changed_entries':changed,'hardware_burst_property_preserved':True,
            'player_preference_enabled':True,
            'native_log':args.native_log,'installed':False}
    args.output.with_suffix('.build.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
