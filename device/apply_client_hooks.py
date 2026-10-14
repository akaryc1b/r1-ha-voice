"""保留成熟的基础挂钩步骤；仅由 hook_pipeline 在隔离副本调用。"""
from pathlib import Path
import re

def apply(root):
    root=Path(root)
    # 不改动云接口；仅在回复前检查是否已被新的本地语音轮次替代。
    chat=root/"smali/com/phicomm/speaker/device/custom/handler/PhicommChatHandler$1.smali"
    chat_source=chat.read_text(encoding="utf-8")
    if ".field private r1Turn:I" not in chat_source:
     chat_source=chat_source.replace("# instance fields", "# instance fields\n.field private r1Turn:I",1)
     chat_source=chat_source.replace("    .registers 3\n", "    .registers 4\n",1)
     marker="    invoke-direct {p0}, Ljava/lang/Object;-><init>()V"
     chat_source=chat_source.replace(marker,marker+"\n\n    invoke-static {}, Lr1/local/asr/VoiceSession;->currentTurn()I\n    move-result v0\n    iput v0, p0, Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler$1;->r1Turn:I",1)
     marker="    :cond_72\n"
     guard="    iget v0, p0, Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler$1;->r1Turn:I\n    invoke-static {v0}, Lr1/local/asr/VoiceSession;->isCurrent(I)Z\n    move-result v0\n    if-nez v0, :r1_reply_current\n    const-string v0, \"R1LocalASR\"\n    const-string v2, \"STALE_CHAT_REPLY_DROPPED\"\n    invoke-static {v0, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I\n    return-void\n    :r1_reply_current\n"
     assert marker in chat_source
     chat_source=chat_source.replace(marker,marker+guard,1)
     chat.write_text(chat_source,encoding="utf-8")
    # 本地采集采用一轮一唤醒，防止旧 SDK 的自动续聊重新录入播报声。
    chat=root/"smali/com/phicomm/speaker/device/custom/handler/PhicommChatHandler.smali"
    chat_source=chat.read_text(encoding="utf-8")
    marker=".method public onTTSEventPlayingEnd(Lcom/unisound/vui/engine/ANTHandlerContext;)Z\n    .registers 6\n"
    start=chat_source.index(".method public onTTSEventPlayingEnd(")
    end=chat_source.index(".end method",start)
    if "LocalAsr;->enabled()Z" not in chat_source[start:end]:
     code="\n    invoke-static {}, Lr1/local/asr/LocalAsr;->enabled()Z\n    move-result v0\n    if-eqz v0, :r1_original_multiturn\n    const/4 v0, 0x0\n    iput-boolean v0, p0, Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler;->isMultiTurnMode:Z\n    :r1_original_multiturn\n"
     assert marker in chat_source
     chat.write_text(chat_source.replace(marker,marker+code,1),encoding="utf-8")
    web=root/"smali/com/phicomm/speaker/device/custom/config/WebServer.smali"
    web_source=web.read_text(encoding="utf-8")
    web_source=web_source.replace("invoke-static {v14}, Lcom/unisound/vui/util/UserPerferenceUtil;->getMainWakeupWord(Landroid/content/Context;)Ljava/util/List;", "invoke-static {v14}, Lr1/local/asr/VoiceSession;->getWakeupWords(Landroid/content/Context;)Ljava/util/List;")
    web_source=web_source.replace("唤醒词已修改", "唤醒词已保存，需实际唤醒验证")
    # smali 中的字符串采用 Unicode 转义。
    web_source=web_source.replace(r"\u5524\u9192\u8bcd\u5df2\u4fee\u6539", r"\u5524\u9192\u8bcd\u5df2\u4fdd\u5b58\uff0c\u9700\u5b9e\u9645\u5524\u9192\u9a8c\u8bc1")
    web.write_text(web_source,encoding="utf-8")
    # 修改方法内入口，保留原来的参数寄存器布局。
    def entry(path,signature,code):
     p=root/"smali"/path;source=p.read_text(encoding="utf-8")
     match=re.search(r"(?m)^\.method "+re.escape(signature)+r"\n\s+\.registers \d+\n",source)
     if not match:raise ValueError("Method not found "+signature)
     if "r1/local/asr/LocalAsr;" not in source[match.end():source.index(".end method",match.end())]:
      source=source[:match.end()]+"\n"+code+"\n"+source[match.end():]
      p.write_text(source,encoding="utf-8")
    entry("com/unisound/common/e.smali","public readData([BI)I","    invoke-static {p0}, Lr1/local/asr/LocalAsr;->remember(Lcom/unisound/client/IAudioSource;)V")
    p=root/"smali/com/unisound/common/e.smali";source=p.read_text(encoding="utf-8")
    source=source.replace("    move-result p1\n\n    return p1\n.end method\n\n.method public writeData", "    move-result p2\n\n    invoke-static {p0, p1, p2}, Lr1/local/asr/LocalAsr;->capture(Lcom/unisound/client/IAudioSource;[BI)V\n\n    return p2\n.end method\n\n.method public writeData")
    p.write_text(source,encoding="utf-8")
    p=root/"smali/com/unisound/common/e.smali";source=p.read_text(encoding="utf-8");source=source.replace(".method public closeAudioIn()V\n    .registers 1", ".method public closeAudioIn()V\n    .registers 2");p.write_text(source,encoding="utf-8")
    entry("com/unisound/common/e.smali","public closeAudioIn()V","    invoke-static {p0}, Lr1/local/asr/LocalAsr;->keepMicrophoneOpen(Lcom/unisound/client/IAudioSource;)Z\n    move-result v0\n    if-eqz v0, :local_asr_close_original\n    return-void\n    :local_asr_close_original")
    entry("com/unisound/vui/engine/NativeANTEngine.smali","public doEnterASR()V","    invoke-static {p0}, Lr1/local/asr/LocalAsr;->begin(Lcom/unisound/vui/engine/NativeANTEngine;)Z\n    return-void")
    entry("com/unisound/vui/engine/NativeANTEngine.smali","public doEnterWakeup(Z)V","    invoke-static {}, Lr1/local/asr/LocalAsr;->deferWakeup()Z\n    move-result v0\n    if-eqz v0, :local_asr_original_wake\n    return-void\n    :local_asr_original_wake")
    # 原生 ASR 消费逻辑由已验证输入保留，不添加旧云通道。
    p=root/"smali/com/unisound/vui/engine/NativeANTEngine.smali";source=p.read_text(encoding="utf-8")
    start=source.index(".method public constructor <init>(");end=source.index(".end method",start)
    body=source[start:end]
    initialize="    iget-object v0, p0, Lcom/unisound/vui/engine/AbstractANTEngine;->context:Landroid/content/Context;\n    invoke-static {p0, v0}, Lr1/local/asr/LocalAsr;->initialize(Lcom/unisound/vui/engine/NativeANTEngine;Landroid/content/Context;)V\n"
    if "LocalAsr;->initialize(" not in body:
     body=body.replace("    return-void",initialize+"\n    return-void",1)
     source=source[:start]+body+source[end:];p.write_text(source,encoding="utf-8")
