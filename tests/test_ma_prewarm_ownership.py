"""预加载被替换时，不能清理已由前台播放接管的音频缓存。"""
import ast
import asyncio
import __future__
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ma"))
from maintain_ma_optimizations import optimized_source

tree = ast.parse(optimized_source("controllers/player_queues/stream_feeder.py"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "prepare_next_audio_buffer")
namespace = {
    "asyncio": asyncio, "MediaType": SimpleNamespace(AUDIO_SOURCE="source"),
    "QueueEmpty": type("QueueEmpty", (Exception,), {}),
    "AudioError": type("AudioError", (Exception,), {}),
    "MediaNotFoundError": type("MediaNotFoundError", (Exception,), {}),
    "STREAM_SLOT_WAIT_TIMEOUT": 15, "R1_MA_QUEUE_ID": "r1",
}
exec(compile(ast.Module(body=[method], type_ignores=[]), "stream_feeder.py", "exec",
             flags=__future__.annotations.compiler_flag), namespace)
prepare = namespace[method.name]


class PrewarmOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.buffer = SimpleNamespace(is_buffering=True, clear=AsyncMock())
        self.details = SimpleNamespace(buffer=None, queue_session_id="old")
        self.item = SimpleNamespace(queue_item_id="next", name="synthetic next", media_type="track", streamdetails=self.details)
        self.queue = SimpleNamespace(session_id="old", next_item_id_preparing=None,
                                     queue=SimpleNamespace(display_name="r1"))
        async def audio(item, **kwargs):
            item.streamdetails.buffer = self.buffer
            item.streamdetails.queue_session_id = self.queue.session_id
            self.started.set()
            await self.release.wait()
        def create_task(function, **kwargs):
            return asyncio.create_task(function())
        self.host = SimpleNamespace(
            get_next_item=Mock(return_value=self.item), get_item=Mock(return_value=self.item),
            _queue_data={"r1": self.queue}, load_next_queue_item=AsyncMock(return_value=self.item),
            _single_source_slot_holder=Mock(return_value=None), logger=Mock(),
            mass=SimpleNamespace(create_task=create_task,
                streams=SimpleNamespace(audio=SimpleNamespace(get_audio_buffer=audio))))

    async def begin(self):
        task = prepare(self.host, "r1", "current")
        await asyncio.wait_for(self.started.wait(), .2)
        return task

    async def cancel(self, task):
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancelled_old_prewarm_leaves_foreground_claim_intact(self):
        task = await self.begin()
        self.queue.session_id = "new"
        self.details.queue_session_id = "new"  # 前台播放已接管同一个 buffer。
        await self.cancel(task)
        self.buffer.clear.assert_not_awaited()

    async def test_cancelled_unclaimed_prewarm_releases_own_source(self):
        task = await self.begin()
        await self.cancel(task)
        self.buffer.clear.assert_awaited_once()

    async def test_cancelled_old_task_does_not_clear_replacement_details(self):
        task = await self.begin()
        newer = SimpleNamespace(is_buffering=True, clear=AsyncMock())
        self.item.streamdetails = SimpleNamespace(buffer=newer, queue_session_id="new")
        self.queue.session_id = "new"
        await self.cancel(task)
        newer.clear.assert_not_awaited()

    async def test_changed_session_during_metadata_load_does_not_start_pcm(self):
        async def load(*args):
            self.queue.session_id = "new"
            return self.item
        self.host.load_next_queue_item.side_effect = load
        self.release.set()
        await prepare(self.host, "r1", "current")
        self.assertFalse(self.started.is_set())


if __name__ == "__main__":
    unittest.main()

