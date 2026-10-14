"""停止已有网关，容忍 /proc 竞争并有界等待，不发送 SIGKILL。"""
import os
from pathlib import Path
import signal
import time

TARGET = b"/data/r1-cloud-voice/voice_gateway.py"


def is_gateway(directory):
    try:
        return TARGET in (directory / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False


def stop_gateway(proc_root=Path("/proc"), timeout=5):
    targets = []
    own_pid = os.getpid()
    for directory in proc_root.iterdir():
        if not directory.name.isdigit():
            continue
        pid = int(directory.name)
        if pid == own_pid or not is_gateway(directory):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            targets.append(directory)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while any(is_gateway(directory) for directory in targets):
        if time.monotonic() >= deadline:
            raise TimeoutError("Voice gateway did not stop within the grace period")
        time.sleep(0.1)
    return len(targets)


if __name__ == "__main__":
    try:
        stop_gateway()
    except (OSError, TimeoutError) as error:
        raise SystemExit("Voice gateway stop failed: " + type(error).__name__) from error

