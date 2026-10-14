"""源 APK 输入清单与本地产物校验；不从生成报告扩展允许输入。"""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path


def load_manifest(path):
    raw = Path(path).read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1 or manifest.get("package") != "com.phicomm.speaker.device":
        raise ValueError("Unsupported base APK manifest")
    inputs = manifest.get("inputs", [])
    if not inputs:
        raise ValueError("No verified base APK inputs")
    seen = set()
    for item in inputs:
        sha, prefix = item.get("sha256", ""), item.get("prefix_bytes")
        if not re.fullmatch("[0-9a-f]{64}", sha) or sha in seen:
            raise ValueError("Invalid base APK SHA256")
        if type(prefix) is not int or prefix < 112:
            raise ValueError("Invalid base DEX prefix")
        signatures = item.get("signature_entries_sha256", {})
        if "META-INF/MANIFEST.MF" not in signatures or not any(name.endswith((".RSA", ".DSA", ".EC")) for name in signatures):
            raise ValueError("Base APK signature contract missing")
        if any(not re.fullmatch("[0-9a-f]{64}", value) for value in signatures.values()):
            raise ValueError("Invalid signature entry hash")
        seen.add(sha)
    return manifest, hashlib.sha256(raw).hexdigest()


def signature_hashes(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate APK ZIP entries")
        selected = [name for name in names if name == "META-INF/MANIFEST.MF" or
                    (name.startswith("META-INF/") and name.endswith((".SF", ".RSA", ".DSA", ".EC")))]
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in selected}


def input_contract(data, manifest):
    digest = hashlib.sha256(data).hexdigest()
    match = next((item for item in manifest["inputs"] if item["sha256"] == digest), None)
    if match is None:
        raise ValueError("Unsupported base APK SHA256; use a verified input in base-apk.json")
    prefix = match["prefix_bytes"]
    if data[:8] != b"dex\n035\x00" or prefix >= len(data) or data[prefix:prefix + 4] != b"PK\x03\x04":
        raise ValueError("Base APK DEX/ZIP boundary differs")
    if signature_hashes(data) != match["signature_entries_sha256"]:
        raise ValueError("Base APK v1 signature entries differ")
    return match


def validate_output(data, report, manifest, manifest_sha):
    if report.get("schema_version") != 1 or report.get("base_manifest_sha256") != manifest_sha:
        raise ValueError("Build report does not match current base-apk.json; rebuild")
    source = next((item for item in manifest["inputs"] if item["sha256"] == report.get("source_sha256")), None)
    if source is None or source["prefix_bytes"] != report.get("old_zip_offset"):
        raise ValueError("Build source APK is not an allowed input")
    if report.get("apk_sha256") != hashlib.sha256(data).hexdigest() or report.get("apk_bytes") != len(data):
        raise ValueError("APK SHA256/size does not match build report")
    prefix, central = report.get("prefix_bytes"), report.get("central_offset")
    if type(prefix) is not int or type(central) is not int or not 112 <= prefix < central < len(data):
        raise ValueError("Build report DEX/ZIP offsets invalid")
    if data[:8] != b"dex\n035\x00" or data[prefix:prefix + 4] != b"PK\x03\x04":
        raise ValueError("Built APK DEX/ZIP boundary differs")
    if signature_hashes(data) != source["signature_entries_sha256"]:
        raise ValueError("Built APK v1 signature entries differ; refusing signature workaround")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.start_dir != central:
            raise ValueError("Built APK central directory differs")
