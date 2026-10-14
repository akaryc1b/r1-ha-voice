"""显式挂钩流水线：隔离变换、验证计数和幂等性，全部成功后提交。"""
from pathlib import Path
import importlib
import os
import re
import tempfile

STAGES=(
    ("client","apply_client_hooks","apply"),
    ("ai_stream","apply_ai_stream_hooks","apply"),
    ("speech_stream","apply_speech_stream","apply"),
    ("asr_retry","apply_asr_retry_hooks","apply"),
    ("diagnostics","apply_diagnostic_hooks","apply"),
)
CHAT="com/phicomm/speaker/device/custom/handler/"
ENGINE="com/unisound/vui/engine/"
SITES=(
    (CHAT+"PhicommChatHandler$1.smali",None,(".field private r1Turn:I",1),None),
    (CHAT+"PhicommChatHandler$1.smali","public run()V",("VoiceAiStream;->chat(",1),(5,6)),
    (CHAT+"PhicommChatHandler$1.smali","public run()V",("VoiceAiStream;->playReply(",1),(5,6)),
    (CHAT+"PhicommChatHandler.smali","public onTTSEventPlayingEnd(Lcom/unisound/vui/engine/ANTHandlerContext;)Z",("VoiceAiStream;->onSpeechEnd(",1),(6,)),
    (CHAT+"PhicommChatHandler.smali","public onTTSEventPlayingEnd(Lcom/unisound/vui/engine/ANTHandlerContext;)Z",("LocalAsr;->enabled()Z",1),(6,)),
    ("com/unisound/common/e.smali","public readData([BI)I",("LocalAsr;->remember(",1),(3,)),
    ("com/unisound/common/e.smali","public readData([BI)I",("LocalAsr;->capture(",1),(3,)),
    ("com/unisound/common/e.smali","public closeAudioIn()V",("LocalAsr;->keepMicrophoneOpen(",1),(1,2)),
    (ENGINE+"NativeANTEngine.smali","public doEnterASR()V",("LocalAsr;->begin(",1),(1,)),
    (ENGINE+"NativeANTEngine.smali","public doEnterWakeup(Z)V",("LocalAsr;->deferWakeup(",1),(9,)),
    (ENGINE+"NativeANTEngine.smali","public constructor <init>(Lcom/unisound/vui/engine/a$AbstractC0007a;Lcom/unisound/client/IAudioSource;)V",("LocalAsr;->initialize(",1),(5,)),
    (ENGINE+"NativeANTEngine$c.smali","public onError(ILjava/lang/String;)V",("LocalAsr;->speechError(",1),(4,)),
    ("com/unisound/vui/handler/launch/DefaultANTLaunchHandler.smali","public onWakeupResult(Lcom/unisound/vui/engine/ANTHandlerContext;Ljava/lang/String;)Z",("LocalAsr;->wakeupStarted(",1),(5,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","public constructor <init>(IIII)V",("LocalAsr;->speechStream(",1),(7,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","private static a(Landroid/media/AudioTrack;[B)I",("SpeechRouteVolume;->beforePlay(",1),(4,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","private static a(Landroid/media/AudioTrack;[B)I",("SpeechRouteVolume;->afterPlay(",1),(4,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","public start()V",("SpeechRouteVolume;->beforePlay(",1),(3,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","public start()V",("SpeechRouteVolume;->afterPlay(",1),(3,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","public stop()V",("SpeechRouteVolume;->afterStop(",1),(3,)),
    ("com/unisound/sdk/BlockingAudioTrack.smali","public waitAndRelease()V",("SpeechRouteVolume;->afterStop(",2),(3,)),
    ("com/phicomm/speaker/device/custom/ha/HomeAssistant.smali","public processCommand(Ljava/lang/String;)Ljava/lang/String;",("VoiceDiagnostics;->haStarted(",1),None),
    ("com/phicomm/speaker/device/custom/ha/HomeAssistant.smali","public processCommand(Ljava/lang/String;)Ljava/lang/String;",("VoiceDiagnostics;->haResponse(",1),None),
)
# 这些挂钩是允许的基础 APK 已有契约；缺失时拒绝，绝不靠旧 smali 缓存补齐。
BASELINE=(
    ("com/unisound/vui/c.smali","CloudSpeech;->play(",1),
    ("com/unisound/vui/c.smali","CloudSpeech;->cancel(",2),
    ("com/phicomm/speaker/device/custom/config/WebServer.smali","CloudVoiceSettings;->decorate(",1),
    ("com/phicomm/speaker/device/custom/config/WebServer.smali","CloudVoiceSettings;->handle(",1),
    ("com/phicomm/speaker/device/custom/ai/OpenAIClient.smali","VoiceAiOptions;->apply(",1),
    (ENGINE+"NativeANTEngine$c.smali","LocalAsr;->speechEvent(",1),
)
LEGACY="com/unisound/vui/handler/filter/NLUDispatcher.smali"
FILES=tuple(sorted({site[0] for site in SITES}|{site[0] for site in BASELINE}|{LEGACY}))

def method(source,signature):
    matches=list(re.finditer(r"(?m)^\.method "+re.escape(signature)+r"\s*$",source))
    if len(matches)!=1:raise ValueError("Method signature count differs: "+signature)
    begin=matches[0].start();end=source.find(".end method",begin)
    if end<0:raise ValueError("Method end missing: "+signature)
    return source[begin:end]

def validate(root,patched):
    sources={name:(Path(root)/"smali"/name).read_text(encoding="utf-8") for name in FILES}
    for path,signature,(marker,count),registers in SITES:
        body=method(sources[path],signature) if signature else sources[path]
        if registers:
            match=re.search(r"(?m)^\s+\.registers (\d+)\s*$",body)
            allowed=(registers[-1],) if patched else registers
            if not match or int(match[1]) not in allowed:
                raise ValueError("Register contract differs: "+signature)
        if patched and body.count(marker)!=count:
            raise ValueError("Hook count differs: "+marker)
    for path,marker,count in BASELINE:
        if sources[path].count(marker)!=count:raise ValueError("Base APK hook missing: "+marker)
    for name in ("onASRResultLocal","onASRResultNet","onASRError"):
        body=method(sources[LEGACY],"public "+name+"(Lcom/unisound/vui/engine/ANTHandlerContext;Ljava/lang/String;)Z")
        if (body.count(name+"_BLOCKED")!=1 or
                not re.search(r"const/4 v0, 0x1\s+return v0\s*$",body) or
                re.search(r"(?m)^\s+(if-|goto|invoke-(?!static.*Landroid/util/Log;))",body)):
            raise ValueError("Legacy ASR gate differs: "+name)
    if patched:
        path="com/phicomm/speaker/device/custom/ha/HomeAssistant.smali"
        body=method(sources[path],"public processCommand(Ljava/lang/String;)Ljava/lang/String;")
        if body.count("VoiceDiagnostics;->haReturned(")!=len(re.findall(r"(?m)^    return-object ",body)):
            raise ValueError("HA return hook count differs")
    return sources

def run_stages(root):
    for name,module,function in STAGES:
        getattr(importlib.import_module(module),function)(root)

def atomic_write(path,data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as output:
        output.write(data);temporary=Path(output.name)
    try:os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()

def apply(root):
    root=Path(root).resolve()
    paths={name:root/"smali"/name for name in FILES}
    if any(not path.is_file() or path.is_symlink() for path in paths.values()):
        raise ValueError("Required regular smali file missing")
    originals={name:path.read_bytes() for name,path in paths.items()}
    validate(root,False)
    with tempfile.TemporaryDirectory(prefix="r1-hook-stage-") as directory:
        stage=Path(directory)
        for name,data in originals.items():
            path=stage/"smali"/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        run_stages(stage);validate(stage,True)
        changed={name:(stage/"smali"/name).read_bytes() for name in FILES}
        run_stages(stage);validate(stage,True)
        if any((stage/"smali"/name).read_bytes()!=data for name,data in changed.items()):
            raise ValueError("Hook pipeline is not idempotent")
        if {str(path.relative_to(stage/"smali")).replace(os.sep,"/") for path in (stage/"smali").rglob("*") if path.is_file()}!=set(FILES):
            raise ValueError("Stage changed undeclared files")
        if any(path.read_bytes()!=originals[name] for name,path in paths.items()):
            raise ValueError("Smali changed concurrently")
        committed=[]
        try:
            for name,data in changed.items():
                if data!=originals[name]:
                    atomic_write(paths[name],data);committed.append(name)
        except BaseException:
            for name in reversed(committed):atomic_write(paths[name],originals[name])
            raise
    return {"stages":[item[0] for item in STAGES],"files_changed":len(committed),"idempotent":True}

if __name__=="__main__":
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",nargs="?",type=Path,default=Path(__file__).resolve().parent)
    print(json.dumps(apply(parser.parse_args().root)))
