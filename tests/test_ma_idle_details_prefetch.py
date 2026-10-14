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
class ProviderUnavailableError(Exception):pass
ns=dict(asyncio=asyncio,copy=copy,PlaybackState=SimpleNamespace(IDLE="idle"),MediaType=SimpleNamespace(TRACK="track"),AudioError=AudioError,MediaNotFoundError=MediaNotFoundError,ProviderUnavailableError=ProviderUnavailableError,R1_IDLE_DETAILS_REFRESH=True,time=SimpleNamespace(time=lambda:100))
exec(compile(ast.Module(body=[method],type_ignores=[]),"actual_idle_prefetch","exec",flags=__future__.annotations.compiler_flag),ns)
preload=ns[method.name]

class IdlePrefetchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.details=SimpleNamespace(seek_position=73,created_at=0,expiration=600)
        self.item=SimpleNamespace(queue_item_id="current",media_type="track",streamdetails=self.details)
        self.queue=SimpleNamespace(state="idle",current_item=self.item,current_index=7,elapsed_time=73)
        self.data=SimpleNamespace(queue=self.queue,transitioning=False,session_id=None)
        async def load(candidate):
            if candidate.streamdetails is None:candidate.streamdetails=SimpleNamespace(seek_position=0,created_at=123,expiration=600)
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
    async def test_restored_index_can_prefetch_before_wire_item_is_populated(self):
        self.queue.current_item=None
        await preload(self.host,"r1","current")
        self.host._load_item.assert_awaited_once()
        self.assertEqual(self.item.streamdetails.created_at,123)
        self.assertIsNone(self.queue.current_item)
    async def test_changed_restored_index_does_not_publish_details(self):
        async def load(candidate):self.queue.current_index=8
        self.host._load_item.side_effect=load
        await preload(self.host,"r1","current")
        self.assertIs(self.item.streamdetails,self.details)
    async def test_startup_provider_unavailable_retries_with_a_limit(self):
        self.host._load_item.side_effect=MediaNotFoundError()
        await preload(self.host,"r1","current")
        self.assertEqual(self.host.mass.call_later.call_args.args,(5,self.host._preload_r1_idle_resume,"r1","current",1,False))
        self.host.mass.call_later.reset_mock()
        await preload(self.host,"r1","current",6)
        self.host.mass.call_later.assert_not_called()
        self.assertIs(self.item.streamdetails,self.details)
        self.host._load_item.side_effect=ProviderUnavailableError()
        await preload(self.host,"r1","current")
        self.host.mass.call_later.assert_called_once()
    async def test_idle_refresh_is_scheduled_before_details_expire(self):
        await preload(self.host,"r1","current")
        self.assertEqual(self.host.mass.call_later.call_args.args,(593,self.host._preload_r1_idle_resume,"r1","current",0,True))
    async def test_refresh_fetches_new_details_without_mutating_original_or_seek(self):
        await preload(self.host,"r1","current",refresh=True)
        self.assertEqual(self.details.seek_position,73)
        self.assertIsNot(self.item.streamdetails,self.details)
        self.assertEqual(self.queue.elapsed_time,73)
    async def test_refresh_switch_disables_periodic_requests(self):
        ns['R1_IDLE_DETAILS_REFRESH']=False
        try:
            await preload(self.host,"r1","current")
            self.host.mass.call_later.assert_not_called()
        finally:ns['R1_IDLE_DETAILS_REFRESH']=True
    async def test_failed_refresh_keeps_old_snapshot_and_retries_with_a_limit(self):
        self.host._load_item.side_effect=TimeoutError()
        await preload(self.host,"r1","current",refresh=True)
        self.assertIs(self.item.streamdetails,self.details)
        self.assertEqual(self.host.mass.call_later.call_args.args,(5,self.host._preload_r1_idle_resume,"r1","current",1,True))
        self.host.mass.call_later.reset_mock()
        await preload(self.host,"r1","current",2,refresh=True)
        self.host.mass.call_later.assert_not_called()
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

