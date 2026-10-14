"""Idempotent AI-only hooks; called after recovering the matching DEX prefix."""
from pathlib import Path

def apply(root):
    root = Path(root)
    path = root / "smali/com/phicomm/speaker/device/custom/handler/PhicommChatHandler$1.smali"
    source = path.read_text(encoding="utf-8")
    old = "    invoke-virtual {v0, v2, v3, v1}, Lcom/phicomm/speaker/device/custom/ai/OpenAIClient;->chatWithHistory(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;"
    if old in source:
        source = source.replace(".method public run()V\n    .registers 5", ".method public run()V\n    .registers 6", 1)
        replacement = """    iget-object v1, p0, Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler$1;->this$0:Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler;
    iget v4, p0, Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler$1;->r1Turn:I
    invoke-static {v0, v1, v2, v3, v4}, Lr1/local/asr/VoiceAiStream;->chat(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;I)Ljava/lang/String;"""
        source = source.replace(old, replacement, 1)
        oldplay = "    invoke-virtual {v0, v1}, Lcom/phicomm/speaker/device/custom/handler/BasePhicommHandler;->playTTS(Ljava/lang/String;)V"
        assert oldplay in source
        source = source.replace(oldplay, """    iget v2, p0, Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler$1;->r1Turn:I
    invoke-static {v0, v1, v2}, Lr1/local/asr/VoiceAiStream;->playReply(Ljava/lang/Object;Ljava/lang/String;I)V""", 1)
        path.write_text(source, encoding="utf-8")
    else:
        assert "VoiceAiStream;->chat(" in source, "AI chat hook target missing"
    path = root / "smali/com/phicomm/speaker/device/custom/handler/PhicommChatHandler.smali"
    source = path.read_text(encoding="utf-8")
    marker = ".method public onTTSEventPlayingEnd(Lcom/unisound/vui/engine/ANTHandlerContext;)Z\n    .registers 6\n"
    start = source.index(".method public onTTSEventPlayingEnd(")
    end = source.index(".end method", start)
    body = source[start:end]
    # baksmali 会重命名分支标签；以调用契约识别已有挂钩。
    if "VoiceAiStream;->onSpeechEnd(" not in body:
        assert marker in source
        source = source.replace(marker, marker + """
    invoke-static {p0}, Lr1/local/asr/VoiceAiStream;->onSpeechEnd(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :r1_ai_stream_regular_end
    const/4 v0, 0x1
    return v0
    :r1_ai_stream_regular_end
""", 1)
        path.write_text(source, encoding="utf-8")
