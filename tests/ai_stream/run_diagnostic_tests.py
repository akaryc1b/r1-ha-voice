"""Run isolated Java SSE tests with a verified temporary JSON dependency."""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request

JSON_URL = "https://repo.maven.apache.org/maven2/org/json/json/20240303/json-20240303.jar"
JSON_SHA256 = "3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-home", type=Path, help="JDK 11 or later")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    source = root / "device/src/r1/local/asr/VoiceDiagnostics.java"
    helper = root / "device/src/r1/local/asr/VoiceSettingsHttp.java"
    if not source.is_file():
        raise SystemExit("Missing device/src/r1/local/asr/VoiceAiStream.java")
    java_home = args.java_home or (Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None)
    suffix = ".exe" if os.name == "nt" else ""
    java = str(java_home / "bin" / ("java" + suffix)) if java_home else shutil.which("java")
    javac = str(java_home / "bin" / ("javac" + suffix)) if java_home else shutil.which("javac")
    if not java or not javac:
        raise SystemExit("Install JDK 11+ or supply --java-home")
    with tempfile.TemporaryDirectory(prefix="r1-ai-stream-tests-") as temporary:
        work = Path(temporary)
        jar = work / "json-20240303.jar"
        with urllib.request.urlopen(JSON_URL, timeout=30) as response:
            data = response.read(2 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != JSON_SHA256:
            raise SystemExit("JSON dependency SHA256 mismatch")
        jar.write_bytes(data)
        classes = work / "classes"
        classes.mkdir()
        subprocess.run([javac, "-encoding", "UTF-8", "-cp", str(jar), "-d", str(classes)]
                       + [str(path) for path in (here / "diagnostics/src").rglob("*.java")]
                       + [str(source), str(helper)], check=True, timeout=30)
        subprocess.run([java, "-cp", str(classes) + os.pathsep + str(jar), "r1.local.asr.DiagnosticsTest"],
                       check=True, timeout=35)


if __name__ == "__main__":
    main()
