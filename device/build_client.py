"""从明确允许的完整挂钩 APK 重建客户端；每次使用全新工作目录。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

from apk_contract import input_contract, load_manifest, validate_output
from hook_pipeline import apply as apply_hooks, atomic_write

ROOT = Path(__file__).resolve().parent


def java_tools(home):
    home = home or (Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None)
    suffix = ".exe" if os.name == "nt" else ""
    values = [str(home / "bin" / (name + suffix)) if home else shutil.which(name) for name in ("java", "javac")]
    if not all(values):
        raise ValueError("Set JAVA_HOME or pass --java-home (JDK 11 tested)")
    return values


def remove_owned_classes(smali):
    """只清理新工作目录内本项目拥有的类，保留厂商 SDK。"""
    smali = Path(smali).resolve()
    owned = smali / "r1/local/asr"
    if owned.exists():
        if owned.is_symlink() or not owned.resolve().is_relative_to(smali):
            raise ValueError("Owned class directory leaves build workspace")
        shutil.rmtree(owned)
    for path in (smali / "com/unisound/vui").glob("CloudSpeech*.smali"):
        if path.is_symlink() or not path.resolve().is_relative_to(smali):
            raise ValueError("Owned class leaves build workspace")
        path.unlink()


def repack(original, old_offset, rebuilt):
    prefix = bytearray(rebuilt)
    tail = bytearray(original[old_offset:])
    delta = len(prefix) - old_offset
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        central = archive.start_dir
    at = central - old_offset
    central_start = at
    while tail[at:at + 4] == b"PK\x01\x02":
        local = struct.unpack_from("<I", tail, at + 42)[0]
        struct.pack_into("<I", tail, at + 42, local + delta)
        names, extra, comment = struct.unpack_from("<HHH", tail, at + 28)
        at += 46 + names + extra + comment
    if tail[at:at + 4] != b"PK\x05\x06":
        raise ValueError("Unsupported ZIP trailer; refusing signature workaround")
    struct.pack_into("<I", tail, at + 16, central + delta)
    apk = prefix + tail
    struct.pack_into("<I", apk, 32, len(apk))
    apk[12:32] = hashlib.sha1(apk[32:]).digest()
    struct.pack_into("<I", apk, 8, zlib.adler32(apk[12:]) & 0xffffffff)
    return bytes(apk), len(prefix) + central_start


def build(base_apk, sdk, home):
    original = Path(base_apk).read_bytes()
    manifest, manifest_sha = load_manifest(ROOT / "base-apk.json")
    contract = input_contract(original, manifest)
    android = sdk / "platforms/android-29/android.jar"
    for path in (android, sdk / "build-tools/29.0.3/lib/d8.jar"):
        if not path.is_file():
            raise ValueError("Required SDK file missing: " + str(path))
    java, javac = java_tools(home)
    build_dir = ROOT / "build"
    build_dir.mkdir(exist_ok=True)
    # 生成源码来自已追踪规则；不会把旧编译产物当输入。
    subprocess.run([sys.executable, str(ROOT.parent / "tools/generate_intent_rules.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "generate_web.py")], check=True)
    with tempfile.TemporaryDirectory(prefix="work-", dir=build_dir) as temporary:
        work = Path(temporary)
        classes, dex, smali = [work / name for name in ("classes", "plugin-dex", "smali")]
        classes.mkdir()
        dex.mkdir()
        raw = bytearray(original[:contract["prefix_bytes"]])
        struct.pack_into("<I", raw, 32, len(raw))
        raw[12:32] = hashlib.sha1(raw[32:]).digest()
        struct.pack_into("<I", raw, 8, zlib.adler32(raw[12:]) & 0xffffffff)
        prefix_path = work / "base-prefix.dex"
        prefix_path.write_bytes(raw)

        def run(command):
            subprocess.run(command, check=True)

        run([java, "-cp", str(ROOT / "tools/*"), "org.jf.baksmali.Main", "disassemble",
             "--api", "22", "-o", str(smali), str(prefix_path)])
        remove_owned_classes(smali)
        # 编译期厂商桩留在 device/stubs；仅打包自有类和 CloudSpeech。
        sources = sorted(path for folder in ("src", "stubs") for path in (ROOT / folder).rglob("*.java"))
        run([javac, "-encoding", "UTF-8", "-source", "8", "-target", "8",
             "-bootclasspath", str(android), "-d", str(classes)] + list(map(str, sources)))
        jar = work / "local-asr-classes.jar"
        with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as archive:
            selected = list((classes / "r1").rglob("*.class"))
            selected += list((classes / "com/unisound/vui").glob("CloudSpeech*.class"))
            if not selected:
                raise ValueError("Plugin compilation produced no owned classes")
            for path in selected:
                archive.write(path, path.relative_to(classes).as_posix())
        run([java, "-cp", str(sdk / "build-tools/29.0.3/lib/d8.jar"), "com.android.tools.r8.D8",
             "--min-api", "22", "--lib", str(android), "--output", str(dex), str(jar)])
        run([java, "-cp", str(ROOT / "tools/*"), "org.jf.baksmali.Main", "disassemble",
             "--api", "22", "-o", str(smali), str(dex / "classes.dex")])
        hooks = apply_hooks(work)
        rebuilt = work / "rebuilt.dex"
        run([java, "-Xmx1g", "-cp", str(ROOT / "tools/*"), "org.jf.smali.Main", "assemble",
             "--api", "22", "-j", "4", "-o", str(rebuilt), str(smali)])
        prefix = rebuilt.read_bytes()
        apk, central = repack(original, contract["prefix_bytes"], prefix)
        report = {
            "schema_version": 1, "base_manifest_sha256": manifest_sha,
            "source_sha256": contract["sha256"], "apk_sha256": hashlib.sha256(apk).hexdigest(),
            "prefix_bytes": len(prefix), "central_offset": central, "apk_bytes": len(apk),
            "method_ids": struct.unpack_from("<I", apk, 88)[0],
            "old_zip_offset": contract["prefix_bytes"], "hook_pipeline": hooks,
        }
        validate_output(apk, report, manifest, manifest_sha)
        atomic_write(build_dir / "r1-local-asr.apk", apk)
        atomic_write(build_dir / "transfer-prefix.bin", apk[:len(prefix)])
        atomic_write(build_dir / "transfer-central.bin", apk[central:])
        atomic_write(build_dir / "build-report.json", (json.dumps(report, indent=2) + "\n").encode("utf-8"))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-apk", type=Path, default=ROOT / "r1-local-asr.apk")
    parser.add_argument("--android-sdk", type=Path)
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--check-base", action="store_true", help="仅检查源 APK 契约，不编译或安装")
    args = parser.parse_args()
    try:
        if args.check_base:
            manifest, _ = load_manifest(ROOT / "base-apk.json")
            contract = input_contract(args.base_apk.read_bytes(), manifest)
            print(json.dumps({"sha256": contract["sha256"], "prefix_bytes": contract["prefix_bytes"]}))
            return
        sdk = args.android_sdk or Path(os.environ.get("ANDROID_SDK_ROOT", os.environ.get("ANDROID_HOME",
            str(Path.home() / "AppData/Local/Android/Sdk"))))
        print(json.dumps(build(args.base_apk, sdk, args.java_home)))
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main()
