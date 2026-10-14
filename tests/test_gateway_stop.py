"""覆盖 /proc 消失竞争、自身排除和停止超时；所有信号均为 mock。"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
import stop_gateway


class GatewayStopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.proc = Path(self.temp.name)

    def process(self, pid, command=None):
        directory = self.proc / str(pid)
        directory.mkdir()
        if command is not None:
            (directory / "cmdline").write_bytes(command)
        return directory

    def test_skips_disappeared_process_and_self_and_partial_match(self):
        self.process(12)  # 已枚举，但 cmdline 消失。
        self.process(999, stop_gateway.TARGET)
        self.process(13, b"python\0-c\0print(" + stop_gateway.TARGET + b")\0")
        target = self.process(14, b"python\0-u\0" + stop_gateway.TARGET + b"\0")
        def terminate(pid, sig):
            self.assertEqual(pid, 14)
            self.assertEqual(sig, stop_gateway.signal.SIGTERM)
            (target / "cmdline").write_bytes(b"")
        with patch.object(os, "getpid", return_value=999), patch.object(os, "kill", side_effect=terminate) as kill:
            self.assertEqual(stop_gateway.stop_gateway(self.proc), 1)
        self.assertEqual(kill.call_count, 1)

    def test_exit_race_when_sending_signal_does_not_abort_later_process(self):
        self.process(20, stop_gateway.TARGET)
        target = self.process(21, stop_gateway.TARGET)
        def terminate(pid, sig):
            if pid == 20:
                raise ProcessLookupError()
            (target / "cmdline").write_bytes(b"")
        with patch.object(os, "kill", side_effect=terminate) as kill, patch.object(os, "getpid", return_value=999):
            self.assertEqual(stop_gateway.stop_gateway(self.proc), 1)
        self.assertEqual({call.args[0] for call in kill.call_args_list}, {20, 21})

    def test_wait_is_bounded_and_never_escalates_to_sigkill(self):
        self.process(30, stop_gateway.TARGET)
        with patch.object(os, "kill") as kill, patch.object(os, "getpid", return_value=999), \
             patch.object(stop_gateway.time, "monotonic", side_effect=[0, 0, 6]), \
             patch.object(stop_gateway.time, "sleep"):
            with self.assertRaises(TimeoutError):
                stop_gateway.stop_gateway(self.proc, timeout=5)
        self.assertEqual(kill.call_args.args, (30, stop_gateway.signal.SIGTERM))

    def test_cmdline_io_error_does_not_propagate(self):
        with patch.object(Path, "read_bytes", side_effect=PermissionError()):
            self.assertFalse(stop_gateway.is_gateway(self.proc / "40"))


if __name__ == "__main__":
    unittest.main()

