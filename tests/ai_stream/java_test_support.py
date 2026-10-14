"""隔离 JVM suites 共用工具；厂商 SDK 编译桩仍留在 device/stubs。"""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
JSON_URL="https://repo.maven.apache.org/maven2/org/json/json/20240303/json-20240303.jar"
JSON_SHA256="3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed"

def java_tools(home=None):
    home=home or (Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None)
    suffix=".exe" if os.name=="nt" else ""
    tools=[str(Path(home)/"bin"/(name+suffix)) if home else shutil.which(name) for name in ("java","javac")]
    if not all(tools):raise SystemExit("Install JDK 11+ or supply --java-home")
    return tools

def json_dependency(work):
    target=Path(work)/"json-20240303.jar"
    cache=Path(tempfile.gettempdir())/"r1-voice-test-dependencies"/("json-"+JSON_SHA256+".jar")
    data=cache.read_bytes() if cache.is_file() and cache.stat().st_size<=2*1024*1024 else b""
    if hashlib.sha256(data).hexdigest()!=JSON_SHA256:
        with urllib.request.urlopen(JSON_URL,timeout=30) as response:data=response.read(2*1024*1024+1)
        if hashlib.sha256(data).hexdigest()!=JSON_SHA256:
            raise SystemExit("JSON dependency SHA256 mismatch")
        cache.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache.parent,delete=False) as output:
            output.write(data);temporary=Path(output.name)
        temporary.replace(cache)
    target.write_bytes(data)
    return target


def compile_suite(work,suite,production,home=None,dependencies=(),extra=()):
    java,javac=java_tools(home)
    generated=Path(work)/"SharedIntentRules.java"
    subprocess.run([sys.executable,str(ROOT/"tools/generate_intent_rules.py"),"--output",str(generated)],check=True,timeout=20)
    if not dependencies:dependencies=[json_dependency(work)]
    sources=sorted((HERE/"common_android_stubs").rglob("*.java"))+sorted((HERE/suite).rglob("*.java"))
    sources += [ROOT/"device/src"/name for name in production]+list(extra)
    sources.append(generated)
    missing=[str(path) for path in sources if not path.is_file()]
    if missing:raise SystemExit("Missing Java source: "+", ".join(missing))
    classes=Path(work)/"classes";classes.mkdir()
    command=[javac,"-encoding","UTF-8","--release","11","-d",str(classes)]
    if dependencies:command += ["-cp",os.pathsep.join(map(str,dependencies))]
    subprocess.run(command+list(map(str,sources)),check=True,timeout=30)
    return java,os.pathsep.join(map(str,[classes,*dependencies]))

def run_main(compiled,name,timeout=10):
    java,classpath=compiled
    subprocess.run([java,"-cp",classpath,name],check=True,timeout=timeout)
