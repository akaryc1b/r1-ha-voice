"""精确插入新唤醒取消及 TTS 错误回调；重复运行不改变结果。"""
from pathlib import Path

def apply(root):
    root=Path(root)
    targets=[
        ("com/unisound/vui/handler/launch/DefaultANTLaunchHandler.smali",
         ".method public onWakeupResult(Lcom/unisound/vui/engine/ANTHandlerContext;Ljava/lang/String;)Z",
         "    invoke-static {}, Lr1/local/asr/LocalAsr;->wakeupStarted()V"),
        ("com/unisound/vui/engine/NativeANTEngine$c.smali",
         ".method public onError(ILjava/lang/String;)V",
         "    invoke-static {}, Lr1/local/asr/LocalAsr;->speechError()V"),
    ]
    for rel,signature,code in targets:
        path=root/"smali"/rel
        text=path.read_text(encoding="utf-8")
        assert text.count(signature)==1, "Expected one callback: "+signature
        start=text.index(signature);end=text.index(".end method",start)
        method=text[start:end]
        if code in method:
            assert method.count(code)==1, "Duplicate retry callback"
            continue
        register_end=text.index(chr(10),text.index(".registers",start))
        text=text[:register_end+1]+chr(10)+code+chr(10)+text[register_end+1:]
        path.write_text(text,encoding="utf-8")

if __name__=="__main__":
    apply(Path(__file__).resolve().parent)
