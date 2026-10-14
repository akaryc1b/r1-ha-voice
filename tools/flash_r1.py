"""安装已验证源构建的 R1 APK；应用前备份实际已安装 APK，不绕过系统签名检查。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "device"))
from apk_contract import load_manifest, validate_output


def load_artifact():
    folder = REPO / "device/build"
    apk = folder / "r1-local-asr.apk"
    report = json.loads((folder / "build-report.json").read_text(encoding="utf-8"))
    manifest, manifest_sha = load_manifest(REPO / "device/base-apk.json")
    # 条目哈希确认与已验证输入相同，不代替 Android 安装时的签名验证。
    validate_output(apk.read_bytes(), report, manifest, manifest_sha)
    return apk, report


def installed_path(output):
    paths = [line.strip()[8:] for line in output.splitlines() if line.strip().startswith("package:")]
    if len(paths) != 1 or not re.fullmatch(r"/[A-Za-z0-9_./-]+\.apk", paths[0]) or "/../" in paths[0]:
        raise ValueError("无法确认单个已安装 APK 路径；不执行安装")
    return paths[0]


def backup_installed(adb, remote):
    folder = REPO / "device/build/backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = folder / ("r1-installed-" + stamp + ".apk")
    adb("pull", remote, str(backup))
    if not backup.is_file() or backup.stat().st_size == 0:
        raise ValueError("已安装 APK 备份为空；不执行安装")
    metadata = {"installed_path": remote, "backup_path": str(backup),
                "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(), "created_utc": stamp}
    backup.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup, metadata


def recovery_commands(args, backup):
    remote = "/data/local/tmp/r1-ha-voice-rollback.apk"
    commands = [[args.adb, "-s", args.serial, "push", str(backup), remote],
                [args.adb, "-s", args.serial, "shell", "sh", "/system/bin/pm", "install", "-r", remote]]
    quote = subprocess.list2cmdline if os.name == "nt" else shlex.join
    return "\n".join(quote(command) for command in commands)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True, help="R1 的 ADB 地址或 USB 序列号")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        apk, report = load_artifact()
    except (ValueError, OSError) as error:
        raise SystemExit("产物校验失败，请重新构建：" + str(error))

    def adb(*command):
        result = subprocess.run([args.adb, "-s", args.serial, *command], capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace") or "ADB command failed")
        return result.stdout.decode(errors="replace")

    try:
        state = adb("get-state").strip()
        if state != "device":
            raise ValueError("ADB 设备未就绪")
        remote_installed = installed_path(adb("shell", "sh", "/system/bin/pm", "path", "com.phicomm.speaker.device"))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
    print("目标 APK SHA256：", report["apk_sha256"])
    if not args.apply:
        print("只读检查通过；使用 --apply 备份当前 APK、传输并覆盖安装。")
        return
    try:
        backup, metadata = backup_installed(adb, remote_installed)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit("安装前备份失败，未传输或安装新 APK：" + str(error))
    print("已备份：", backup, "SHA256：", metadata["sha256"])
    try:
        remote = "/data/local/tmp/r1-ha-voice.apk"
        print(adb("push", str(apk), remote))
        verified = adb("shell", "/system/bin/busybox", "sha256sum", remote).split()[0]
        if verified != report["apk_sha256"]:
            raise ValueError("设备端 APK 校验失败")
        result = adb("shell", "sh", "/system/bin/pm", "install", "-r", remote)
        print(result)
        if "Success" not in [line.strip() for line in result.splitlines()]:
            raise ValueError("覆盖安装失败；保留系统签名检查，不卸载、不清数据")
        adb("shell", "monkey", "-p", "com.phicomm.speaker.device", "-c", "android.intent.category.LAUNCHER", "1")
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, IndexError) as error:
        print("安装流程未完成，原 APK 备份保留：", backup, file=sys.stderr)
        print("需要恢复时手动执行；不会自动回滚：\n" + recovery_commands(args, backup), file=sys.stderr)
        raise SystemExit(str(error))
    print("完成。打开 http://音箱地址:8080/ 检查配置；原 APK 备份已保留。")


if __name__ == "__main__":
    main()
