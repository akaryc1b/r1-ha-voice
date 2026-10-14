"""仅将设备 TTS 路由到独立播报音量，不改变音乐 AudioTrack。"""
from pathlib import Path


def apply_stream_selection(root):
    path = Path(root) / "smali/com/unisound/sdk/BlockingAudioTrack.smali"
    source = path.read_text(encoding="utf-8")
    assert '"TTS.BlockingAudioTrack"' in source, "Unexpected TTS implementation"
    if "LocalAsr;->speechStream()I" in source:
        assert source.count("LocalAsr;->speechStream()I") == 1, "Duplicate TTS selection"
        return
    marker = "    iput p1, p0, Lcom/unisound/sdk/BlockingAudioTrack;->g:I"
    fixed = "    const/16 p1, 0x9\n\n" + marker
    patched = ("    invoke-static {}, Lr1/local/asr/LocalAsr;->speechStream()I\n"
               "    move-result p1\n\n" + marker)
    if fixed in source:
        source = source.replace(fixed, patched, 1)
        path.write_bytes(source.encode("utf-8"))
    if patched not in source:
        assert source.count(marker) == 1, "TTS stream field differs"
        source = source.replace(marker, patched, 1)
        path.write_bytes(source.encode("utf-8"))


def apply_route_volume(root):
    """仅 BlockingAudioTrack 的已校验 play/stop/release 站点同步路由音量。"""
    path = Path(root) / "smali/com/unisound/sdk/BlockingAudioTrack.smali"
    source = path.read_text(encoding="utf-8")
    if "Lr1/local/asr/SpeechRouteVolume;->beforePlay" in source:
        assert source.count("SpeechRouteVolume;->beforePlay") == 2
        assert source.count("SpeechRouteVolume;->afterPlay") == 2
        assert source.count("SpeechRouteVolume;->afterStop") == 3
        return
    expected = {
        ".method private static a(Landroid/media/AudioTrack;[B)I": ("p0", "play"),
        ".method public start()V": ("v0", "play"),
        ".method public stop()V": ("v1", "stop"),
        ".method public waitAndRelease()V": ("v0", "stop"),
    }
    for signature, (register, operation) in expected.items():
        start = source.index(signature)
        end = source.index(".end method", start)
        body = source[start:end]
        marker = "    invoke-virtual {" + register + "}, Landroid/media/AudioTrack;->" + operation + "()V"
        assert body.count(marker) == 1, "Unexpected TTS site: " + signature
        if operation == "play":
            before = "    invoke-static {" + register + "}, Lr1/local/asr/SpeechRouteVolume;->beforePlay(Ljava/lang/Object;)V"
            after = "    invoke-static {" + register + "}, Lr1/local/asr/SpeechRouteVolume;->afterPlay(Ljava/lang/Object;)V"
            body = body.replace(marker, before + "\n" + marker + "\n" + after, 1)
        else:
            after = "    invoke-static {" + register + "}, Lr1/local/asr/SpeechRouteVolume;->afterStop(Ljava/lang/Object;)V"
            body = body.replace(marker, marker + "\n" + after, 1)
        if "waitAndRelease" in signature:
            release = "    invoke-virtual {v1}, Landroid/media/AudioTrack;->release()V"
            assert body.count(release) == 1, "Unexpected TTS release site"
            body = body.replace(release, release + "\n    invoke-static {v1}, Lr1/local/asr/SpeechRouteVolume;->afterStop(Ljava/lang/Object;)V", 1)
        source = source[:start] + body + source[end:]
    assert source.count("SpeechRouteVolume;->beforePlay") == 2
    assert source.count("SpeechRouteVolume;->afterPlay") == 2
    assert source.count("SpeechRouteVolume;->afterStop") == 3
    path.write_bytes(source.encode("utf-8"))


def apply(root):
    apply_stream_selection(root)
    apply_route_volume(root)
