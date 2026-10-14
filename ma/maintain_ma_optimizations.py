"""固定官方源码、SHA256 与精确补丁；未知版本拒绝覆盖。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "ma-optimizations-manifest.json"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)\n$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    """仅兼容纯换行差异，不放宽其它哈希校验。"""
    return data.replace(b"\r\n", b"\n")


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise ValueError("不安全的包路径：" + value)
    return Path(*path.parts)


def parse_patch(payload, expected):
    lines = payload.decode("utf-8").splitlines(keepends=True)
    patches, index = {}, 0
    while index < len(lines):
        if not lines[index].startswith("--- a/"):
            raise ValueError("补丁文件头不正确")
        path = lines[index][6:].rstrip("\n")
        relative_path(path)
        index += 1
        if index >= len(lines) or lines[index] != "+++ b/" + path + "\n" or path in patches:
            raise ValueError("补丁路径重复或不匹配")
        index += 1
        hunks = []
        while index < len(lines) and not lines[index].startswith("--- a/"):
            match = HUNK.match(lines[index])
            if not match:
                raise ValueError("补丁 hunk 头不正确：" + path)
            old_start, old_count, new_start, new_count = (int(x) if x is not None else 1 for x in match.groups())
            index += 1
            removed, added = [], []
            while index < len(lines) and lines[index][:1] in (" ", "+", "-"):
                if lines[index].startswith("--- a/"):
                    break
                prefix, text = lines[index][0], lines[index][1:]
                if prefix in (" ", "-"):
                    removed.append(text)
                if prefix in (" ", "+"):
                    added.append(text)
                index += 1
            if len(removed) != old_count or len(added) != new_count:
                raise ValueError("补丁行数不匹配：" + path)
            hunks.append((old_start, new_start, removed, added))
        patches[path] = hunks
    if set(patches) != set(expected) or len(set(expected)) != len(expected):
        raise ValueError("补丁与清单文件集合不匹配")
    return patches


def checked_patch(manifest, name, paths):
    payload = (ROOT / manifest[name + "_file"]).read_bytes()
    if sha(payload) != manifest[name + "_sha256"]:
        raise ValueError("补丁 SHA256 不匹配")
    return parse_patch(payload, paths)


def read_bundle():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return manifest, checked_patch(manifest, "patch", [item["path"] for item in manifest["files"]])


def read_migrations(manifest):
    paths = [item["path"] for item in manifest["files"] if "previous_after_sha256" in item]
    return checked_patch(manifest, "previous_patch", paths)


def read_upgrade(manifest, kind="upgrade"):
    paths = [item["path"] for item in manifest["files"] if kind + "_from_sha256" in item]
    return checked_patch(manifest, kind + "_patch", paths) if paths else {}


def transform(data, item, hunks, reverse=False):
    """精确匹配行位置与内容，不搜索、不模糊套用。"""
    source = normalized(data)
    start, end = ("after", "before") if reverse else ("before", "after")
    if sha(source) != item[start + "_sha256"]:
        raise ValueError("输入源码 SHA256 不匹配：" + item["path"])
    lines = source.decode("utf-8").splitlines(keepends=True)
    result, cursor = [], 0
    for old_start, new_start, removed, added in hunks:
        position, previous, replacement = (new_start, added, removed) if reverse else (old_start, removed, added)
        position = position - 1 if previous else position
        if position < cursor or lines[position:position + len(previous)] != previous:
            raise ValueError("补丁上下文不匹配：" + item["path"])
        result.extend(lines[cursor:position])
        result.extend(replacement)
        cursor = position + len(previous)
    result.extend(lines[cursor:])
    output = "".join(result).encode("utf-8")
    if sha(output) != item[end + "_sha256"]:
        raise ValueError("输出源码 SHA256 不匹配：" + item["path"])
    return output


def upstream_source(item, manifest, cache_dir=None):
    cache = cache_dir or Path(tempfile.gettempdir()) / "r1-ha-voice-ma" / manifest["upstream_commit"]
    target = cache / relative_path(item["path"])
    if target.exists():
        data = target.read_bytes()
    else:
        url = ("https://raw.githubusercontent.com/music-assistant/server/" + manifest["upstream_commit"]
               + "/music_assistant/" + item["path"])
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        if sha(data) != item["before_sha256"]:
            raise ValueError("官方下载 SHA256 不匹配：" + item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if sha(data) != item["before_sha256"]:
        raise ValueError("上游缓存 SHA256 不匹配：" + item["path"])
    return data


def optimized_source(path, source_root=None, cache_dir=None):
    """测试按需重建源码；环境变量可指定已准备的离线目录。"""
    manifest, patches = read_bundle()
    item = next((entry for entry in manifest["files"] if entry["path"] == path), None)
    if item is None:
        raise ValueError("清单没有该文件：" + path)
    selected = source_root or os.environ.get("R1_MA_SOURCE_ROOT")
    if selected:
        data = normalized((Path(selected) / relative_path(path)).read_bytes())
    else:
        cache = cache_dir or (Path(os.environ["R1_MA_CACHE_DIR"]) if os.environ.get("R1_MA_CACHE_DIR") else None)
        data = transform(upstream_source(item, manifest, cache), item, patches[path])
    if sha(data) != item["after_sha256"]:
        raise ValueError("测试源码 SHA256 不匹配：" + path)
    return data.decode("utf-8")


def source_base(source_root):
    if source_root:
        return source_root.resolve()
    package = importlib.util.find_spec("music_assistant")
    if package is None or not package.submodule_search_locations:
        raise ValueError("未安装 MA；请用 --source-root 指定 music_assistant 源码目录")
    return Path(next(iter(package.submodule_search_locations))).resolve()


def replace_bytes(path, data):
    """同目录原子替换单文件，保留原权限。"""
    mode = path.stat().st_mode
    handle, name = tempfile.mkstemp(prefix=".r1-ma-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def maintain(base, action):
    manifest, patches = read_bundle()
    migrations = read_migrations(manifest)
    upgrades = {}
    for kind in ("upgrade", "network_upgrade"):
        for path, hunks in read_upgrade(manifest, kind).items():
            item = next(item for item in manifest["files"] if item["path"] == path)
            upgrades[(path, item[kind + "_from_sha256"])] = hunks
    plan = []
    for item in manifest["files"]:
        target = (base / relative_path(item["path"])).resolve()
        if not target.is_relative_to(base.resolve()):
            raise ValueError("源码路径超出目标目录：" + item["path"])
        original = target.read_bytes()
        current = normalized(original)
        digest = sha(current)
        previous = digest == item.get("previous_after_sha256")
        upgrade = (item["path"], digest) in upgrades
        if digest not in (item["before_sha256"], item["after_sha256"]) and not (previous or upgrade):
            raise ValueError("MA 源码不属于已验证版本：" + item["path"])
        before = digest == item["before_sha256"]
        if previous or upgrade:
            transition = {"path":item["path"], "before_sha256":digest,
                          "after_sha256":item["after_sha256"]}
            hunks = migrations[item["path"]] if previous else upgrades[(item["path"], digest)]
            current = transform(current, transition, hunks)
        # 预览同样核对 hunk 和最终哈希；先验证所有文件再写入。
        opposite = transform(current, item, patches[item["path"]], reverse=not before)
        payload = opposite if ((action == "apply" and before) or (action == "restore" and not before)) else original
        if action == "apply" and (previous or upgrade):
            payload = current
        state = "previous-optimized" if previous else "upgrade-from-optimized" if upgrade else "original" if before else "optimized"
        plan.append((target, original, payload, item["path"], state))
    written = []
    if action != "check":
        try:
            for target, original, payload, _, _ in plan:
                if target.read_bytes() != original:
                    raise ValueError("验证期间源码发生变化，停止写入")
                if payload != original:
                    replace_bytes(target, payload)
                    written.append((target, original))
        except BaseException:
            for target, original in reversed(written):
                replace_bytes(target, original)
            raise
    return [(path, state) for _, _, _, path, state in plan]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="只读预览，默认操作")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--restore", action="store_true")
    group.add_argument("--prepare", type=Path, metavar="DIR", help="从固定官方源准备隔离测试目录")
    parser.add_argument("--source-root", type=Path, help="music_assistant 包目录；默认已安装 MA")
    parser.add_argument("--cache-dir", type=Path, help="固定官方源下载缓存，建议仓库外目录")
    parser.add_argument("--state", choices=("before", "after"), default="after", help="--prepare 的目标状态")
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            manifest, patches = read_bundle()
            for item in manifest["files"]:
                data = upstream_source(item, manifest, args.cache_dir)
                if args.state == "after":
                    data = transform(data, item, patches[item["path"]])
                target = args.prepare / relative_path(item["path"])
                if target.exists() and target.read_bytes() != data:
                    raise ValueError("拒绝覆盖不匹配的准备目录文件：" + item["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            print(f"已准备 {len(manifest['files'])} 个已校验源码文件；未修改已安装 MA。")
        else:
            action = "apply" if args.apply else "restore" if args.restore else "check"
            for path, state in maintain(source_base(args.source_root), action):
                print(path, state)
            print("只读验证通过；未写入。" if action == "check" else "源码操作完成；重启已有 MA 容器后生效。")
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
