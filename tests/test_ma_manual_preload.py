"""单曲循环的手动下一首预取不得启动第二条音频流。"""
import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


class AudioError(Exception):
    pass


class MediaNotFoundError(Exception):
    pass


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ma'))
from maintain_ma_optimizations import optimized_source
SOURCE = Path('controllers/player_queues/stream_feeder.py')
tree = ast.parse(optimized_source(SOURCE.as_posix()))
original = next(node for node in tree.body if isinstance(node, ast.ClassDef))
method = next(node for node in original.body
              if isinstance(node, ast.AsyncFunctionDef)
              and node.name == "_preload_r1_manual_successor")
module = ast.Module(body=[method], type_ignores=[])
namespace = {"asyncio": asyncio, "MediaType": SimpleNamespace(TRACK="track"),
             "AudioError": AudioError, "MediaNotFoundError": MediaNotFoundError}
exec(compile(module, str(SOURCE), "exec"), namespace)
preload = namespace[method.name]


class ManualNextPreloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.item = SimpleNamespace(queue_item_id="next", available=True, media_type="track")
        queue = SimpleNamespace(current_item=SimpleNamespace(queue_item_id="current"))
        self.host = SimpleNamespace(
            _queue_data={"r1": SimpleNamespace(queue=queue)},
            index_by_id=Mock(return_value=2), _get_next_index=Mock(return_value=3),
            get_item=Mock(return_value=self.item), _load_item=AsyncMock(), logger=Mock())

    async def test_manual_successor_only_loads_details(self):
        await preload(self.host, "r1", "current")
        self.host._get_next_index.assert_called_once_with("r1", 2, is_skip=True)
        # No is_start=True: the actual MA loader's default excludes AudioBuffer creation.
        self.host._load_item.assert_awaited_once_with(self.item)

    async def test_changed_current_item_does_not_prefetch(self):
        await preload(self.host, "r1", "old")
        self.host._load_item.assert_not_awaited()

    async def test_missing_successor_does_not_prefetch(self):
        self.host._get_next_index.return_value = None
        await preload(self.host, "r1", "current")
        self.host._load_item.assert_not_awaited()

    async def test_unavailable_item_does_not_prefetch(self):
        self.item.available = False
        await preload(self.host, "r1", "current")
        self.host._load_item.assert_not_awaited()

    async def test_failed_optional_prefetch_does_not_interrupt_playback(self):
        self.host._load_item.side_effect = MediaNotFoundError()
        await preload(self.host, "r1", "current")
        self.host.logger.info.assert_not_called()

    async def test_stop_cancellation_propagates(self):
        self.host._load_item.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await preload(self.host, "r1", "current")


if __name__ == "__main__":
    unittest.main()
