"""模拟时钟与并发验证，不访问真实 R1、MA 或 Snapserver。"""
import asyncio
import importlib.util
from pathlib import Path
import re
import textwrap
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('polling_hardware_volume',ROOT/'provider/r1_hardware_volume.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Response:
    def __init__(self,session,params):self.session=session;self.params=params
    async def __aenter__(self):
        self.session.requests.append(self.params)
        if self.session.gate is not None:await self.session.gate.wait()
        if self.session.fail:raise ValueError('simulated failure')
        return self
    async def __aexit__(self,*args):pass
    def raise_for_status(self):pass
    async def json(self):
        operation=self.params['operation']
        if operation=='set':self.session.percent=round(self.params['percent']*15/100)*100//15
        elif operation=='mute':self.session.percent=0
        elif operation=='unmute':self.session.percent=40
        return {'target':'music','percent':self.session.percent}


class Session:
    def __init__(self):self.requests=[];self.percent=27;self.fail=False;self.gate=None
    def get(self,url,params,timeout):return Response(self,params)


def player_methods():
    """仅提取可运行的方法，避开上游其它方法的 Python 3.14 专用 except 语法。"""
    source=(ROOT/'provider/player.py').read_text(encoding='utf-8')
    names=('poll','volume_set','volume_mute','_r1_publish_volume')
    blocks=[]
    for name in names:
        match=re.search(r'^    (?:async )?def '+name+r'\(.*?(?=^    (?:async )?def |^    @|\Z)',source,re.M|re.S)
        if not match:raise AssertionError('Missing actual player method '+name)
        blocks.append(textwrap.dedent(match.group()))
    environment={'R1HardwareVolume':module.R1HardwareVolume,'refresh_server_status':module.refresh_server_status,
                 'PlaybackState':NS(PLAYING='playing'),'ClientError':ValueError,'TimeoutError':TimeoutError}
    exec('\n'.join(blocks),environment)
    return environment


class PollingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=0.;self.session=Session()
        self.control=module.R1HardwareVolume(self.session,'http://example.invalid/voice_volume',clock=lambda:self.now)
        self.provider=NS(mass=NS(loop=NS(time=lambda:self.now)),refresh_server_status=AsyncMock())

    async def test_hardware_playing_two_seconds_idle_ten_seconds(self):
        for second in range(7):
            self.now=float(second);await self.control.poll(True)
        self.assertEqual(len(self.session.requests),4)
        self.now=7;self.assertFalse(await self.control.poll(False))
        self.now=15.999;self.assertFalse(await self.control.poll(False))
        self.now=16;self.assertTrue(await self.control.poll(False))

    async def test_idle_to_playing_shortens_interval(self):
        await self.control.poll(False)
        self.now=2;self.assertTrue(await self.control.poll(True))

    async def test_failed_or_cancelled_read_retains_attempt_throttle(self):
        self.session.fail=True
        with self.assertRaises(ValueError):await self.control.poll(True)
        self.now=1.999;self.assertFalse(await self.control.poll(True))
        self.now=2
        with self.assertRaises(ValueError):await self.control.poll(True)
        self.assertEqual(len(self.session.requests),2)
        self.session.fail=False;self.session.gate=asyncio.Event();self.now=4
        task=asyncio.create_task(self.control.poll(True));await asyncio.sleep(0);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.now=5;self.assertFalse(await self.control.poll(True))

    async def test_unity_failure_also_obeys_cooldown(self):
        unity=AsyncMock(side_effect=ValueError('simulated unity failure'))
        with self.assertRaises(ValueError):await self.control.poll(True,before_read=unity)
        self.now=1;self.assertFalse(await self.control.poll(True,before_read=unity))
        self.assertEqual(unity.await_count,1);self.assertEqual(self.session.requests,[])

    async def test_concurrent_initial_reads_are_coalesced(self):
        self.session.gate=asyncio.Event()
        tasks=[asyncio.create_task(self.control.poll(True)) for _ in range(12)]
        await asyncio.sleep(0);self.assertEqual(len(self.session.requests),1)
        self.session.gate.set()
        results=await asyncio.gather(*tasks)
        self.assertEqual(results.count(True),1);self.assertEqual(len(self.session.requests),1)

    async def test_explicit_set_bypasses_passive_throttle_and_blocks_stale_get(self):
        await self.control.poll(True)
        self.now=.2;self.assertEqual(await self.control.request('set',41),(40,False))
        self.assertFalse(await self.control.poll(True))
        self.assertEqual([p['operation'] for p in self.session.requests],['get','set'])
        self.now=2.2;self.assertTrue(await self.control.poll(True))

    async def test_inflight_get_cannot_overwrite_new_explicit_set(self):
        self.session.gate=asyncio.Event()
        reading=asyncio.create_task(self.control.poll(True));await asyncio.sleep(0)
        setting=asyncio.create_task(self.control.request('set',41));await asyncio.sleep(0)
        self.assertEqual(len(self.session.requests),1)
        self.session.gate.set();await asyncio.gather(reading,setting)
        self.assertEqual(self.control.percent,40)
        self.assertEqual([q['operation'] for q in self.session.requests],['get','set'])
        self.assertFalse(await self.control.poll(True))

    async def test_server_status_five_seconds_shared_across_players(self):
        for second in range(13):
            self.now=second
            await asyncio.gather(*(module.refresh_server_status(self.provider) for _ in range(5)))
        self.assertEqual(self.provider.refresh_server_status.await_count,3)

    async def test_server_slow_refresh_never_overlaps_after_five_seconds(self):
        gate=asyncio.Event()
        async def slow():await gate.wait()
        self.provider.refresh_server_status.side_effect=slow
        first=asyncio.create_task(module.refresh_server_status(self.provider));await asyncio.sleep(0)
        self.now=20;await module.refresh_server_status(self.provider)
        self.assertEqual(self.provider.refresh_server_status.await_count,1)
        gate.set();await first
        await module.refresh_server_status(self.provider)
        self.assertEqual(self.provider.refresh_server_status.await_count,2)

    async def test_server_error_and_cancellation_do_not_create_retry_storm(self):
        self.provider.refresh_server_status.side_effect=ValueError('simulated error')
        with self.assertRaises(ValueError):await module.refresh_server_status(self.provider)
        self.now=4;await module.refresh_server_status(self.provider)
        self.assertEqual(self.provider.refresh_server_status.await_count,1)
        self.provider.refresh_server_status.side_effect=asyncio.CancelledError()
        self.now=5
        with self.assertRaises(asyncio.CancelledError):await module.refresh_server_status(self.provider)
        self.now=6;await module.refresh_server_status(self.provider)
        self.assertFalse(self.provider._r1_status_refresh_inflight)
        self.assertEqual(self.provider.refresh_server_status.await_count,2)

    async def test_provider_instances_do_not_share_timers(self):
        second=NS(mass=self.provider.mass,refresh_server_status=AsyncMock())
        await module.refresh_server_status(self.provider);await module.refresh_server_status(second)
        self.assertEqual(second.refresh_server_status.await_count,1)

    def player(self):
        player=NS(snap_provider=self.provider,playback_state='playing',snap_client=NS(set_volume=AsyncMock()),
                  _r1_volume_control=lambda:self.control,_r1_unity_gain=AsyncMock(),
                  poke_player_update=lambda:None,update_state=lambda:None,
                  logger=NS(warning=lambda *args:None))
        methods=player_methods()
        player._r1_publish_volume=lambda control:methods['_r1_publish_volume'](player,control)
        return player,methods

    async def test_actual_player_poll_independent_server_and_hardware_cadence(self):
        player,methods=self.player()
        for second in range(11):self.now=second;await methods['poll'](player)
        self.assertEqual(len(self.session.requests),6)
        self.assertEqual(self.provider.refresh_server_status.await_count,3)
        self.assertEqual(player._r1_unity_gain.await_count,6)

    async def test_actual_player_explicit_set_publishes_quantized_value_before_poll(self):
        player,methods=self.player()
        await methods['volume_set'](player,41)
        self.assertEqual(player._attr_volume_level,40)
        self.assertFalse(player._attr_volume_muted)
        self.assertEqual(len(self.session.requests),1)
        player._r1_unity_gain.assert_awaited_once()
        await methods['volume_mute'](player,True)
        self.assertEqual(player._attr_volume_level,0);self.assertTrue(player._attr_volume_muted)
        await methods['volume_mute'](player,False)
        self.assertEqual(player._attr_volume_level,40);self.assertFalse(player._attr_volume_muted)

    async def test_other_snapcast_clients_keep_software_volume(self):
        player,methods=self.player();player._r1_volume_control=lambda:None
        await methods['volume_set'](player,41)
        player.snap_client.set_volume.assert_awaited_once_with(41)
        self.assertEqual(self.session.requests,[])


if __name__=='__main__':unittest.main(verbosity=2)
