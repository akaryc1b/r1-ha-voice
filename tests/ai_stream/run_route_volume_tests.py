"""Run isolated speech route-volume tests; no hardware or network access."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-home", type=Path, help="JDK 11 or later")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    source = root / "device/src/r1/local/asr/SpeechRouteVolume.java"
    if not source.is_file():
        raise SystemExit("Missing device/src/r1/local/asr/SpeechRouteVolume.java")
    home = args.java_home or (Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None)
    suffix = ".exe" if os.name == "nt" else ""
    java = str(home / "bin" / ("java" + suffix)) if home else shutil.which("java")
    javac = str(home / "bin" / ("javac" + suffix)) if home else shutil.which("javac")
    if not java or not javac:
        raise SystemExit("Install JDK 11+ or supply --java-home")
    with tempfile.TemporaryDirectory(prefix="r1-speech-route-tests-") as temporary:
        classes = Path(temporary) / "classes"
        classes.mkdir()
        subprocess.run([javac, "-encoding", "UTF-8", "-d", str(classes)]
                       + [str(path) for path in (here / "route_volume/src").rglob("*.java")]
                       + [str(source)], check=True, timeout=30)
        subprocess.run([java, "-cp", str(classes), "RouteVolumeTest"], check=True, timeout=10)


if __name__ == "__main__":
    main()
