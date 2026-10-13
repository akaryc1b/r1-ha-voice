import pathlib,subprocess,sys,zipfile,re,struct,hashlib,zlib,json,os,shutil,argparse
sys.stdout.reconfigure(encoding="utf-8")
root=pathlib.Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description="Build the R1 voice client from a matching backup APK")
parser.add_argument("--base-apk",type=pathlib.Path)
parser.add_argument("--android-sdk",type=pathlib.Path)
parser.add_argument("--java-home",type=pathlib.Path)
options=parser.parse_args()
sdk=options.android_sdk or pathlib.Path(os.environ.get("ANDROID_SDK_ROOT",os.environ.get("ANDROID_HOME",
    str(pathlib.Path.home()/"AppData/Local/Android/Sdk"))))
android=sdk/"platforms/android-29/android.jar"
java_home=options.java_home or (pathlib.Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None)
if java_home:
    java=str(java_home/"bin"/("java.exe" if os.name=="nt" else "java"))
    javac=str(java_home/"bin"/("javac.exe" if os.name=="nt" else "javac"))
else:
    java=shutil.which("java");javac=shutil.which("javac")
    if not java or not javac:raise SystemExit("Set JAVA_HOME or pass --java-home (JDK 11 tested)")
legacy=pathlib.Path.home()/"Downloads/R1-MA-Voice-20261012/unisound-ma-routing-v2.apk"
base_apk=options.base_apk or (legacy if legacy.exists() else root/"r1-local-asr.apk")
for required in [android,sdk/"build-tools/29.0.3/lib/d8.jar",base_apk]:
    if not required.is_file():raise SystemExit("Required file missing: "+str(required)+"; set --android-sdk / --base-apk")
original=base_apk.read_bytes()
base_hash=hashlib.sha256(original).hexdigest()
prior=json.loads((root/"build-report.json").read_text()) if (root/"build-report.json").exists() else {}
if base_hash==prior.get("apk_sha256"):
    old_offset=prior["prefix_bytes"]
elif base_hash=="6cd76aea5b050fafe2e31cde93f533eb9476f8b07d0b5be7d47703af55a982ce":
    old_offset=8128580
else:raise SystemExit("Unsupported base APK: use the APK matching build-report.json")
if not (root/"smali/com/phicomm/speaker/device/custom/handler/PhicommChatHandler$1.smali").exists():
    # 备份 APK 已包含原生挂钩；从其 DEX 前缀恢复完整反汇编后再覆盖自有插件。
    prefix=root/"base-prefix.dex"
    raw=bytearray(original[:old_offset])
    struct.pack_into("<I",raw,32,len(raw))
    raw[12:32]=hashlib.sha1(raw[32:]).digest()
    struct.pack_into("<I",raw,8,zlib.adler32(raw[12:])&0xffffffff)
    prefix.write_bytes(raw)
    subprocess.run([java,"-cp",str(root/"tools/*"),"org.jf.baksmali.Main","disassemble",
        "--api","22","-o",str(root/"smali"),str(prefix)],check=True)
subprocess.run([sys.executable,str(root/"generate_web.py")],check=True)
stubs={
"com/unisound/vui/util/SharedPreferencesHelper.java": "package com.unisound.vui.util; public class SharedPreferencesHelper {public static SharedPreferencesHelper getInstance(android.content.Context context,String name){return null;} public java.util.Set<String> getStringSetValue(String name){return null;}}",
"com/unisound/vui/util/UserPerferenceUtil.java": "package com.unisound.vui.util; public class UserPerferenceUtil {public static void setCurrentVolume(android.content.Context context,int level){} public static java.util.List<String> getMainWakeupWord(android.content.Context context){return null;}}",
"com/unisound/client/IAudioSource.java": "package com.unisound.client; public interface IAudioSource {int openAudioIn(); void closeAudioIn(); int readData(byte[] data,int count);}",
"com/unisound/vui/engine/NativeANTEngine.java": "package com.unisound.vui.engine; public class NativeANTEngine {public android.content.Context androidContext(){return null;} public void doCancelEngine(){} public void doEnterASR(){} public final void setEngineState(int state){} public ANTPipeline pipeline(){return null;} public void enterWakeup(boolean value){}}",
"com/unisound/vui/engine/ANTPipeline.java": "package com.unisound.vui.engine; public interface ANTPipeline {ANTPipeline fireASREvent(int value); ANTPipeline fireUserEventTriggered(Object value); void playTTS(String text);}",
"nluparser/scheme/NLU.java": "package nluparser.scheme; public class NLU {public void setService(String value){} public void setText(String value){}}",
"okhttp3/OkHttpClient.java": "package okhttp3; public class OkHttpClient {public WebSocket newWebSocket(Request request,WebSocketListener listener){return null;} public static class Builder {public Builder connectTimeout(long value,java.util.concurrent.TimeUnit unit){return this;} public Builder readTimeout(long value,java.util.concurrent.TimeUnit unit){return this;} public OkHttpClient build(){return null;}}}",
"okhttp3/WebSocket.java": "package okhttp3; public interface WebSocket {boolean send(String value); boolean send(okio.ByteString value); boolean close(int code,String reason);}",
"okhttp3/WebSocketListener.java": "package okhttp3; public abstract class WebSocketListener {public void onOpen(WebSocket socket,Response response){} public void onMessage(WebSocket socket,String text){} public void onFailure(WebSocket socket,Throwable error,Response response){} public void onClosed(WebSocket socket,int code,String reason){}}",
"okhttp3/Request.java": "package okhttp3; public class Request {public static class Builder {public Builder url(String value){return this;} public Request build(){return null;}}}",
"okhttp3/Response.java": "package okhttp3; public class Response {}",
"okio/ByteString.java": "package okio; public class ByteString {public ByteString(byte[] data){}}",
}
for name,text in stubs.items():
 dest=root/"stubs"/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text,encoding="utf-8")
(root/"classes").mkdir(exist_ok=True);(root/"plugin-dex").mkdir(exist_ok=True)
def run(args):subprocess.run(args,check=True)
run([javac,"-encoding","UTF-8","-source","8","-target","8","-bootclasspath",str(android),"-d",str(root/"classes")]+[str(p) for folder in ["src","stubs"] for p in (root/folder).rglob("*.java")])
with zipfile.ZipFile(root/"local-asr-classes.jar","w",zipfile.ZIP_DEFLATED) as out:
 for p in (root/"classes/r1").rglob("*.class"):out.write(p,p.relative_to(root/"classes").as_posix())
 for p in (root/"classes/com/unisound/vui").glob("CloudSpeech*.class"):out.write(p,p.relative_to(root/"classes").as_posix())
run([java,"-cp",str(sdk/"build-tools/29.0.3/lib/d8.jar"),"com.android.tools.r8.D8","--min-api","22","--lib",str(android),"--output",str(root/"plugin-dex"),str(root/"local-asr-classes.jar")])
run([java,"-cp",str(root/"tools/*"),"org.jf.baksmali.Main","disassemble","--api","22","-o",str(root/"smali"),str(root/"plugin-dex/classes.dex")])
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
if ":r1_original_multiturn" not in chat_source:
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
# Legacy ASR result/error methods are unconditional consumers; no native fallback.
p=root/"smali/com/unisound/vui/engine/NativeANTEngine.smali";source=p.read_text(encoding="utf-8")
start=source.index(".method public constructor <init>(");end=source.index(".end method",start)
body=source[start:end]
initialize="    iget-object v0, p0, Lcom/unisound/vui/engine/AbstractANTEngine;->context:Landroid/content/Context;\n    invoke-static {p0, v0}, Lr1/local/asr/LocalAsr;->initialize(Lcom/unisound/vui/engine/NativeANTEngine;Landroid/content/Context;)V\n"
if initialize not in body:
 body=body.replace("    return-void",initialize+"\n    return-void",1)
 source=source[:start]+body+source[end:];p.write_text(source,encoding="utf-8")
from apply_ai_stream_hooks import apply as apply_ai_stream_hooks
from apply_speech_stream import apply as apply_speech_stream
from apply_asr_retry_hooks import apply as apply_asr_retry_hooks
from apply_diagnostic_hooks import apply as apply_diagnostic_hooks
apply_ai_stream_hooks(root)
apply_speech_stream(root)
apply_asr_retry_hooks(root)
apply_diagnostic_hooks(root)
run([java,"-Xmx1g","-cp",str(root/"tools/*"),"org.jf.smali.Main","assemble","--api","22","-j","4","-o",str(root/"rebuilt.dex"),str(root/"smali")])
prefix=bytearray((root/"rebuilt.dex").read_bytes());tail=bytearray(original[old_offset:]);delta=len(prefix)-old_offset
# APK 的 ZIP 条目和 v1 签名保持原样，仅调整容器的绝对偏移。
with zipfile.ZipFile(__import__("io").BytesIO(original)) as archive:central=archive.start_dir
at=central-old_offset;central_start=at
while tail[at:at+4]==b"PK\x01\x02":
 local=struct.unpack_from("<I",tail,at+42)[0];struct.pack_into("<I",tail,at+42,local+delta)
 names,extra,comment=struct.unpack_from("<HHH",tail,at+28);at+=46+names+extra+comment
assert tail[at:at+4]==b"PK\x05\x06","Unsupported ZIP trailer"
struct.pack_into("<I",tail,at+16,central+delta)
apk=prefix+tail
struct.pack_into("<I",apk,32,len(apk))
apk[12:32]=hashlib.sha1(apk[32:]).digest()
struct.pack_into("<I",apk,8,zlib.adler32(apk[12:])&0xffffffff)
(root/"r1-local-asr.apk").write_bytes(apk)
(root/"transfer-prefix.bin").write_bytes(apk[:len(prefix)])
(root/"transfer-central.bin").write_bytes(apk[len(prefix)+central_start:])
report={"source_sha256":hashlib.sha256(original).hexdigest(),"apk_sha256":hashlib.sha256(apk).hexdigest(),"prefix_bytes":len(prefix),"central_offset":len(prefix)+central_start,"apk_bytes":len(apk),"method_ids":struct.unpack_from("<I",apk,88)[0],"old_zip_offset":old_offset,"classes_added":["r1.local.asr.LocalAsr"],"hooks":["audio source reference","ASR entry","wake deferral","ASR error filtering","diagnostic registration"]}
(root/"build-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report),flush=True)
