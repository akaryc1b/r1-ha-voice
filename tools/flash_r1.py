"""安装匹配的 R1 语音 APK，不卸载应用，也不覆盖设备的用户设置。"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--adb", default="adb")
parser.add_argument("--serial", required=True, help="例如 192.168.1.3:5555 或 USB 序列号")
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
apk = REPO / "device/r1-local-asr.apk"
report = json.loads((REPO / "device/build-report.json").read_text(encoding="utf-8"))
if hashlib.sha256(apk.read_bytes()).hexdigest() != report["apk_sha256"]:
    raise SystemExit("APK 校验不匹配，停止安装")
def adb(*command):
    result = subprocess.run([args.adb, "-s", args.serial, *command], capture_output=True, timeout=180)
    if result.returncode:
        raise SystemExit(result.stderr.decode(errors="replace"))
    return result.stdout.decode(errors="replace")
print(adb("get-state").strip())
installed = adb("shell", "pm", "path", "com.phicomm.speaker.device")
if "package:" not in installed:
    raise SystemExit("没有检测到同包名的已有 R1 语音应用；此工具只支持覆盖安装")
print("目标 APK SHA256：", report["apk_sha256"])
if not args.apply:
    print("只读检查通过；使用 --apply 传输并覆盖安装，期间语音服务会短暂重启。")
    raise SystemExit(0)
remote = "/data/local/tmp/r1-ha-voice.apk"
print(adb("push", str(apk), remote))
verified = adb("shell", "/system/bin/busybox", "sha256sum", remote).split()[0]
if verified != report["apk_sha256"]:
    raise SystemExit("设备端 APK 校验失败")
result = adb("shell", "sh", "/system/bin/pm", "install", "-r", remote)
print(result)
if "Success" not in result:
    raise SystemExit("覆盖安装未成功；不执行卸载或清除数据")
adb("shell", "monkey", "-p", "com.phicomm.speaker.device", "-c", "android.intent.category.LAUNCHER", "1")
print("完成。打开 http://音箱地址:8080/ 检查配置。")
