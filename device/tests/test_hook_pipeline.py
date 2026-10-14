"""构建契约与挂钩事务测试；仅使用合成 APK/精简 smali，不编译或安装 APK。"""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "device"))
import apk_contract
import build_client
import hook_pipeline


def write(root, name, source):
    path = root / "smali" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def fixture(root):
    chat = hook_pipeline.CHAT
    engine = hook_pipeline.ENGINE
    write(root, chat + "PhicommChatHandler$1.smali", """# instance fields
.method constructor <init>(Lcom/phicomm/speaker/device/custom/handler/PhicommChatHandler;Ljava/lang/String;)V
    .registers 3
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method
.method public run()V
    .registers 5
    invoke-virtual {v0, v2, v3, v1}, Lcom/phicomm/speaker/device/custom/ai/OpenAIClient;->chatWithHistory(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    invoke-virtual {v0, v1}, Lcom/phicomm/speaker/device/custom/handler/BasePhicommHandler;->playTTS(Ljava/lang/String;)V
    :cond_72
    return-void
.end method
""")
    write(root, chat + "PhicommChatHandler.smali", """.method public onTTSEventPlayingEnd(Lcom/unisound/vui/engine/ANTHandlerContext;)Z
    .registers 6
    const/4 v0, 0x0
    return v0
.end method
""")
    write(root, "com/unisound/common/e.smali", """.method public closeAudioIn()V
    .registers 1
    return-void
.end method
.method public readData([BI)I
    .registers 3
    invoke-direct {p0, p1, p2}, Lcom/unisound/common/e;->b([BI)I
    move-result p1

    return p1
.end method

.method public writeData([BI)I
    .registers 3
    return p2
.end method
""")
    write(root, engine + "NativeANTEngine.smali", """.method public constructor <init>(Lcom/unisound/vui/engine/a$AbstractC0007a;Lcom/unisound/client/IAudioSource;)V
    .registers 5
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method
.method public doEnterASR()V
    .registers 1
    return-void
.end method
.method public doEnterWakeup(Z)V
    .registers 9
    return-void
.end method
""")
    write(root, engine + "NativeANTEngine$c.smali", """.method public onError(ILjava/lang/String;)V
    .registers 4
    return-void
.end method
.method public onEvent(I)V
    .registers 5
    invoke-static {p1}, Lr1/local/asr/LocalAsr;->speechEvent(I)V
    return-void
.end method
""")
    write(root, "com/unisound/vui/handler/launch/DefaultANTLaunchHandler.smali", """.method public onWakeupResult(Lcom/unisound/vui/engine/ANTHandlerContext;Ljava/lang/String;)Z
    .registers 5
    const/4 v0, 0x1
    return v0
.end method
""")
    write(root, "com/unisound/sdk/BlockingAudioTrack.smali", """# "TTS.BlockingAudioTrack"
.method public constructor <init>(IIII)V
    .registers 7
    iput p1, p0, Lcom/unisound/sdk/BlockingAudioTrack;->g:I
    return-void
.end method
.method private static a(Landroid/media/AudioTrack;[B)I
    .registers 4
    invoke-virtual {p0}, Landroid/media/AudioTrack;->play()V
    const/4 v0, 0x0
    return v0
.end method
.method public start()V
    .registers 3
    invoke-virtual {v0}, Landroid/media/AudioTrack;->play()V
    return-void
.end method
.method public stop()V
    .registers 3
    invoke-virtual {v1}, Landroid/media/AudioTrack;->stop()V
    return-void
.end method
.method public waitAndRelease()V
    .registers 3
    invoke-virtual {v0}, Landroid/media/AudioTrack;->stop()V
    invoke-virtual {v1}, Landroid/media/AudioTrack;->release()V
    return-void
.end method
""")
    write(root, "com/phicomm/speaker/device/custom/ha/HomeAssistant.smali", """.method public processCommand(Ljava/lang/String;)Ljava/lang/String;
    .registers 4
    const-string v1, "response"
    invoke-virtual {v0, v1}, Lorg/json/JSONObject;->optJSONObject(Ljava/lang/String;)Lorg/json/JSONObject;
    move-result-object v1
    if-eqz v1, :empty
    return-object v1
    :empty
    return-object v0
.end method
""")
    write(root, "com/phicomm/speaker/device/custom/config/WebServer.smali", """invoke-static {v14}, Lcom/unisound/vui/util/UserPerferenceUtil;->getMainWakeupWord(Landroid/content/Context;)Ljava/util/List;
invoke-static {v0}, Lr1/local/asr/CloudVoiceSettings;->decorate(Ljava/lang/String;)Ljava/lang/String;
invoke-static {p1, v1, v10, v11}, Lr1/local/asr/CloudVoiceSettings;->handle(Ljava/net/Socket;Ljava/lang/String;Ljava/io/BufferedReader;Ljava/lang/String;)Z
""")
    write(root, "com/unisound/vui/c.smali", """invoke-static {p0, p1}, Lcom/unisound/vui/CloudSpeech;->play(Lcom/unisound/vui/c;Ljava/lang/String;)Z
invoke-static {p0}, Lcom/unisound/vui/CloudSpeech;->cancel(Lcom/unisound/vui/c;)V
invoke-static {p0}, Lcom/unisound/vui/CloudSpeech;->cancel(Lcom/unisound/vui/c;)V
""")
    write(root, "com/phicomm/speaker/device/custom/ai/OpenAIClient.smali",
          "invoke-static {v0, v4, v1}, Lr1/local/asr/VoiceAiOptions;->apply(Lorg/json/JSONObject;Ljava/lang/String;Ljava/lang/String;)V\n")
    methods = []
    for name in ("onASRResultLocal", "onASRResultNet", "onASRError"):
        methods.append(f""".method public {name}(Lcom/unisound/vui/engine/ANTHandlerContext;Ljava/lang/String;)Z
    .registers 5
    const-string v0, "{name}_BLOCKED"
    const/4 v0, 0x1
    return v0
.end method
""")
    write(root, hook_pipeline.LEGACY, "".join(methods))


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.smali")}


class HookPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_then_idempotent(self):
        result = hook_pipeline.apply(self.root)
        self.assertGreater(result["files_changed"], 0)
        before = snapshot(self.root)
        self.assertEqual(hook_pipeline.apply(self.root)["files_changed"], 0)
        self.assertEqual(snapshot(self.root), before)

    def test_missing_signature_fails_without_writes(self):
        path = self.root / "smali/com/phicomm/speaker/device/custom/ha/HomeAssistant.smali"
        path.write_text(path.read_text().replace("public processCommand", "public changedCommand"), encoding="utf-8")
        before = snapshot(self.root)
        with self.assertRaises(ValueError):
            hook_pipeline.apply(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_baksmali_labels_and_spacing_remain_idempotent(self):
        hook_pipeline.apply(self.root)
        for path in (self.root / "smali").rglob("*.smali"):
            source = path.read_text(encoding="utf-8")
            source = source.replace(":r1_original_multiturn", ":cond_fixture_multiturn")
            source = source.replace(":r1_ai_stream_regular_end", ":cond_fixture_ai")
            source = source.replace("\n    move-result", "\n\n    move-result")
            path.write_text(source, encoding="utf-8")
        before = snapshot(self.root)
        self.assertEqual(hook_pipeline.apply(self.root)["files_changed"], 0)
        self.assertEqual(snapshot(self.root), before)

    def test_late_stage_failure_does_not_write_original(self):
        import apply_diagnostic_hooks
        before = snapshot(self.root)
        with patch.object(apply_diagnostic_hooks, "apply", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                hook_pipeline.apply(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_partial_commit_failure_rolls_back(self):
        real = hook_pipeline.atomic_write
        calls = 0

        def fail_once(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected replace failure")
            real(path, data)

        before = snapshot(self.root)
        with patch.object(hook_pipeline, "atomic_write", side_effect=fail_once):
            with self.assertRaises(OSError):
                hook_pipeline.apply(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_duplicate_hook_is_rejected_without_changes(self):
        hook_pipeline.apply(self.root)
        path = self.root / "smali" / "com/unisound/vui/engine/NativeANTEngine$c.smali"
        text = path.read_text()
        marker = "    invoke-static {}, Lr1/local/asr/LocalAsr;->speechError()V"
        path.write_text(text.replace(marker, marker + "\n" + marker), encoding="utf-8")
        before = snapshot(self.root)
        with self.assertRaises((ValueError, AssertionError)):
            hook_pipeline.apply(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_patched_register_contract_is_required(self):
        hook_pipeline.apply(self.root)
        path = self.root / "smali" / hook_pipeline.CHAT / "PhicommChatHandler$1.smali"
        source = path.read_text(encoding="utf-8")
        path.write_text(source.replace(".registers 6", ".registers 5"), encoding="utf-8")
        before = snapshot(self.root)
        with self.assertRaises(ValueError):
            hook_pipeline.apply(self.root)
        self.assertEqual(snapshot(self.root), before)


def synthetic_apk(prefix=112):
    data = io.BytesIO()
    data.write(b"dex\n035\x00" + bytes(prefix - 8))
    with zipfile.ZipFile(data, "a") as archive:
        for name in ("META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA"):
            archive.writestr(name, "synthetic identity fixture")
        archive.writestr("assets/value.txt", "payload")
    raw = data.getvalue()
    signatures = apk_contract.signature_hashes(raw)
    manifest = {"schema_version": 1, "package": "com.phicomm.speaker.device", "inputs": [
        {"sha256": hashlib.sha256(raw).hexdigest(), "prefix_bytes": prefix,
         "signature_entries_sha256": signatures}]}
    return raw, manifest


class ApkContractTests(unittest.TestCase):
    def test_verified_source_and_repack_keep_signature_entries(self):
        original, manifest = synthetic_apk()
        contract = apk_contract.input_contract(original, manifest)
        rebuilt = b"dex\n035\x00" + bytes(120 - 8)
        output, central = build_client.repack(original, 112, rebuilt)
        report = {"schema_version": 1, "base_manifest_sha256": "fixture", "source_sha256": contract["sha256"],
                  "old_zip_offset": 112, "apk_sha256": hashlib.sha256(output).hexdigest(),
                  "apk_bytes": len(output), "prefix_bytes": 120, "central_offset": central}
        apk_contract.validate_output(output, report, manifest, "fixture")

    def test_unknown_source_cannot_be_blessed_by_report(self):
        original, manifest = synthetic_apk()
        with self.assertRaises(ValueError):
            apk_contract.input_contract(original + b"unknown", manifest)

    def test_legacy_source_is_provenance_only(self):
        manifest, _ = apk_contract.load_manifest(ROOT / "device/base-apk.json")
        historical = manifest["historical_provenance"]["sha256"]
        self.assertFalse(manifest["historical_provenance"]["build_supported"])
        self.assertNotIn(historical, [item["sha256"] for item in manifest["inputs"]])

    def test_stale_owned_classes_removed_vendor_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            smali = Path(directory) / "smali"
            for name in ("r1/local/asr/DeletedHelper.smali", "com/unisound/vui/CloudSpeech$Old.smali",
                         "com/unisound/vui/Vendor.smali"):
                path = smali / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            build_client.remove_owned_classes(smali)
            self.assertFalse((smali / "r1/local/asr").exists())
            self.assertFalse((smali / "com/unisound/vui/CloudSpeech$Old.smali").exists())
            self.assertTrue((smali / "com/unisound/vui/Vendor.smali").exists())


class FlashBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location("flash_r1_under_test", ROOT / "tools/flash_r1.py")
        self.flash = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.flash)
        self.flash.REPO = self.repo
        self.apk = self.repo / "candidate.apk"
        self.apk.write_bytes(b"candidate fixture")
        self.digest = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        self.calls = []
        self.pull_fail = False
        self.install_fail = False
        self.bad_remote_hash = False

    def tearDown(self):
        self.temp.cleanup()

    def fake_adb(self, args, **kwargs):
        self.assertEqual(args[:3], ["adb", "-s", "fixture"])
        command = args[3:]
        self.calls.append(command)
        output, error, code = b"", b"", 0
        if command == ["get-state"]:
            output = b"device\n"
        elif command[:5] == ["shell", "sh", "/system/bin/pm", "path", "com.phicomm.speaker.device"]:
            output = b"package:/data/app/com.phicomm.speaker.device-1/base.apk\n"
        elif command[0] == "pull":
            if self.pull_fail:
                code, error = 1, b"fixture pull failure"
            else:
                Path(command[2]).write_bytes(b"original installed APK")
        elif command[0] == "push":
            backups = list((self.repo / "device/build/backups").glob("*.apk"))
            self.assertEqual(len(backups), 1)
            self.assertTrue(backups[0].with_suffix(".json").is_file())
        elif command[:3] == ["shell", "/system/bin/busybox", "sha256sum"]:
            output = (("0" * 64 if self.bad_remote_hash else self.digest) + " remote.apk\n").encode()
        elif command[:5] == ["shell", "sh", "/system/bin/pm", "install", "-r"]:
            output = b"Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n" if self.install_fail else b"Success\n"
        elif command[:2] != ["shell", "monkey"]:
            raise AssertionError(command)
        return __import__("subprocess").CompletedProcess(args, code, output, error)

    def run_flash(self, apply):
        argv = ["--serial", "fixture"] + (["--apply"] if apply else [])
        with patch.object(self.flash, "load_artifact", return_value=(self.apk, {"apk_sha256": self.digest})), \
                patch.object(self.flash.subprocess, "run", side_effect=self.fake_adb), \
                __import__("contextlib").redirect_stdout(io.StringIO()), \
                __import__("contextlib").redirect_stderr(self.stderr):
            self.flash.main(argv)

    def test_default_readonly_does_not_pull_backup(self):
        self.stderr = io.StringIO()
        self.run_flash(False)
        self.assertFalse(any(command[0] in ("pull", "push") for command in self.calls))
        self.assertFalse((self.repo / "device/build/backups").exists())

    def test_backup_failure_prevents_push_install(self):
        self.stderr = io.StringIO()
        self.pull_fail = True
        with self.assertRaises(SystemExit):
            self.run_flash(True)
        self.assertFalse(any(command[0] == "push" for command in self.calls))
        self.assertFalse(any("install" in command for command in self.calls))

    def test_install_signature_failure_preserves_backup_no_launch(self):
        self.stderr = io.StringIO()
        self.install_fail = True
        with self.assertRaises(SystemExit):
            self.run_flash(True)
        backups = list((self.repo / "device/build/backups").glob("*.apk"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"original installed APK")
        metadata = json.loads(backups[0].with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["sha256"], hashlib.sha256(backups[0].read_bytes()).hexdigest())
        self.assertFalse(any(command[:2] == ["shell", "monkey"] for command in self.calls))
        self.assertIn("/system/bin/pm", self.stderr.getvalue())

    def test_remote_hash_failure_preserves_backup_no_install(self):
        self.stderr = io.StringIO()
        self.bad_remote_hash = True
        with self.assertRaises(SystemExit):
            self.run_flash(True)
        self.assertEqual(len(list((self.repo / "device/build/backups").glob("*.apk"))), 1)
        self.assertFalse(any("install" in command for command in self.calls))

    def test_success_backups_before_push_and_installs_once(self):
        self.stderr = io.StringIO()
        self.run_flash(True)
        operations = [command[0] for command in self.calls]
        self.assertLess(operations.index("pull"), operations.index("push"))
        self.assertEqual(sum("install" in command for command in self.calls), 1)
        self.assertEqual(sum(command[:2] == ["shell", "monkey"] for command in self.calls), 1)

if __name__ == "__main__":
    unittest.main()
