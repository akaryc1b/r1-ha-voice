"""把网关生成的组合计划接到现有 HA 实例，不新增凭据或代理。"""
from pathlib import Path
import re


def apply(root):
    path = Path(root) / 'smali/com/phicomm/speaker/device/custom/ha/HomeAssistant.smali'
    source = path.read_text(encoding='utf-8')
    begin = source.index('.method public processCommand(Ljava/lang/String;)Ljava/lang/String;')
    end = source.index('.end method', begin)
    body = source[begin:end]
    if 'VoiceCommands;->process(' in body:
        assert body.count('VoiceCommands;->process(') == 1
        assert body.count('VoiceCommands;->haResponse(') == 1
        return
    marker = re.search(r'(?m)^    \.registers \d+\n', body)
    assert marker
    # v0 在原方法首条指令前可用；组合返回放在所有原 try/catch 区间之外。
    entry = '''
    invoke-static {p0, p1}, Lr1/local/asr/VoiceCommands;->process(Ljava/lang/Object;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    if-nez v0, :r1_compound_return
'''
    body = body[:marker.end()] + entry + body[marker.end():]
    response = '    invoke-static {v1}, Lr1/local/asr/VoiceDiagnostics;->haResponse(Lorg/json/JSONObject;)V'
    assert body.count(response) == 1
    body = body.replace(response, response + '\n    invoke-static {v1}, Lr1/local/asr/VoiceCommands;->haResponse(Lorg/json/JSONObject;)V')
    body += '''
    :r1_compound_return
    invoke-static {v0}, Lr1/local/asr/VoiceDiagnostics;->haReturned(Ljava/lang/String;)V
    return-object v0
'''
    path.write_text(source[:begin] + body + source[end:], encoding='utf-8')
