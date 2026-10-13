"""只在现有 HA 调用边界记录选定字段，不改变分流或返回值。"""
import re
from pathlib import Path


def apply(root):
    path = Path(root) / "smali/com/phicomm/speaker/device/custom/ha/HomeAssistant.smali"
    source = path.read_text(encoding="utf-8")
    begin = source.index(".method public processCommand(Ljava/lang/String;)Ljava/lang/String;")
    end = source.index(".end method", begin)
    body = source[begin:end]
    if "VoiceDiagnostics;->haStarted" in body:
        assert body.count("VoiceDiagnostics;->haStarted") == 1
        assert body.count("VoiceDiagnostics;->haResponse") == 1
        assert body.count("VoiceDiagnostics;->haReturned") == len(re.findall(r"(?m)^    return-object ", body))
        return
    marker = re.search(r"(?m)^    \.registers \d+\n", body)
    assert marker
    entry = "\n    invoke-static {p1}, Lr1/local/asr/VoiceDiagnostics;->haStarted(Ljava/lang/String;)V\n"
    body = body[:marker.end()] + entry + body[marker.end():]
    # 同时兼容原备份与已经加入 no_intent_match 检查的客户端。
    response = re.search(r'    const-string v1, "response".*?    move-result-object v1\n', body, re.S)
    assert response is not None
    body = body[:response.end()] + "\n    invoke-static {v1}, Lr1/local/asr/VoiceDiagnostics;->haResponse(Lorg/json/JSONObject;)V\n" + body[response.end():]
    body = re.sub(r"(?m)^(    return-object ([vp]\d+))$",
                  lambda match: "    invoke-static {" + match[2] + "}, Lr1/local/asr/VoiceDiagnostics;->haReturned(Ljava/lang/String;)V\n" + match[1], body)
    path.write_text(source[:begin] + body + source[end:], encoding="utf-8")
