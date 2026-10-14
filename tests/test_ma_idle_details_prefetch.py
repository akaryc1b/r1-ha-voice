"""待机详情预取只发布仍属于原队列的资料，不能改写已开始播放的进度。"""
import ast,asyncio,__future__
from copy import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"ma"))
from maintain_ma_optimizations import optimized_source
tree=ast.parse(optimized_source("controllers/player_queues/stream_feeder.py"))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="_preload_r1_idle_resume")
class AudioError(Exception):pass
class MediaNotFoundError(Exception):pass
ns=dict(asyncio=asyncio,copy=copy,PlaybackState=SimpleNamespace(IDLE="idle"),MediaType=SimpleNamespace(TRACK="track"),AudioError=AudioError,MediaNotFoundError=MediaNotFoundError)
exec(compile(ast.Module(body=[method],type_ignores=[]),"actual_idle_prefetch","exec",flags=__future__.annotations.compiler_flag),ns)
preload=ns[method.name]

class IdlePrefetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.details=SimpleNamespace(seek_position=73,created_at=0)
        self.item=SimpleNamespace(queue_item_id="current",media_type="track",streamdetails=self.details)
        self.queue=SimpleNamespace(state="idle",current_item=self.item,elapsed_time=73)
        self.data=SimpleNamespace(queue=self.queue,transitioning=False,session_id=None)
        async def load(candidate):
            candidate.streamdetails.seek_position=0
            candidate.streamdetails.created_at=123
        self.host=SimpleNamespace(_queue_data={"r1":self.data},_load_item=AsyncMock(side_effect=load),get_item=Mock(return_value=self.item),logger=Mock(),mass=SimpleNamespace(call_later=Mock()))
        self.host._preload_r1_idle_resume=Mock()
    async def test_idle_prefetch_clones_and_does_not_start_audio_or_change_position(self):
        await preload(self.host,"r1","current")
        candidate=self.host._load_item.call_args.args[0]
        self.assertIsNot(candidate,self.item)
        self.assertIsNot(candidate.streamdetails,self.details)
        self.host._load_item.assert_awaited_once_with(candidate)
        self.assertEqual(self.details.seek_position,73)
        self.assertEqual(self.queue.elapsed_time,73)
        self.assertEqual(self.item.streamdetails.created_at,123)
    async def test_playing_or_transitioning_queue_is_not_prefetched(self):
        self.queue.state="playing";await preload(self.host,"r1","current")
        self.queue.state="idle";self.data.transitioning=True;await preload(self.host,"r1","current")
        self.host._load_item.assert_not_awaited()
    async def test_restored_wire_item_and_queue_item_share_loaded_details(self):
        restored=copy(self.item)
        self.queue.current_item=restored
        await preload(self.host,"r1","current")
        self.host._load_item.assert_awaited_once()
        self.assertIs(restored.streamdetails,self.item.streamdetails)
        self.assertEqual(self.item.streamdetails.created_at,123)
    async def test_startup_provider_unavailable_retries_with_a_limit(self):
        self.host._load_item.side_effect=MediaNotFoundError()
        await preload(self.host,"r1","current")
        self.assertEqual(self.host.mass.call_later.call_args.args,(5,self.host._preload_r1_idle_resume,"r1","current",1))
        self.host.mass.call_later.reset_mock()
        await preload(self.host,"r1","current",3)
        self.host.mass.call_later.assert_not_called()
        self.assertIs(self.item.streamdetails,self.details)
    async def test_foreground_play_during_fetch_cannot_have_seek_overwritten(self):
        async def load(candidate):
            self.queue.state="playing";self.details.seek_position=91
            candidate.streamdetails.seek_position=0
        self.host._load_item.side_effect=load
        await preload(self.host,"r1","current")
        self.assertIs(self.item.streamdetails,self.details)
        self.assertEqual(self.item.streamdetails.seek_position,91)
    async def test_replaced_queue_cannot_receive_old_result(self):
        async def load(candidate):self.host._queue_data["r1"]=SimpleNamespace()
        self.host._load_item.side_effect=load
        await preload(self.host,"r1","current")
        self.assertIs(self.item.streamdetails,self.details)
    async def test_changed_session_cannot_receive_old_result(self):
        async def load(candidate):self.data.session_id="new"
        self.host._load_item.side_effect=load
        await preload(self.host,"r1","current")
        self.assertIs(self.item.streamdetails,self.details)
    async def test_foreground_replacement_of_details_is_preserved(self):
        newer=SimpleNamespace(seek_position=91)
        async def load(candidate):self.item.streamdetails=newer
        self.host._load_item.side_effect=load
        await preload(self.host,"r1","current")
        self.assertIs(self.item.streamdetails,newer)
    async def test_failure_and_cancel_do_not_publish(self):
        for failure in (AudioError(),asyncio.CancelledError()):
            self.host._load_item.side_effect=failure
            if isinstance(failure,asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):await preload(self.host,"r1","current")
            else:await preload(self.host,"r1","current")
            self.assertIs(self.item.streamdetails,self.details)
    async def test_removed_item_cannot_receive_old_result(self):
        self.host.get_item.return_value=None
        await preload(self.host,"r1","current")
        self.assertIs(self.item.streamdetails,self.details)
if __name__=="__main__":unittest.main()

