"""Exercise actual gateway lifecycle methods with isolated, cancellable fake I/O."""
import ast
import asyncio
import json
import logging
import re
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'voice_gateway.py'
if not SOURCE.is_file():SOURCE=ROOT/'gateway/voice_gateway.py'


class ClientError(Exception):
    pass

class FakeEventLog:
    def __init__(self,*args,**kwargs):pass
    async def start(self):return self
    async def close(self):pass


class Session:
    def __init__(self,**kwargs):
        self.closed=False
        self.close_entered=asyncio.Event()
        self.close_gate=None

    async def close(self):
        self.closed=True
        self.close_entered.set()
        if self.close_gate is not None:await self.close_gate.wait()


class Request:
    def __init__(self,app,text):
        self.app=app
        self.text=text

    async def json(self):
        return {'text':self.text}


def isolated():
    names={'startup','cleanup','perform_music','music_worker','music_control',
           'normalize_command','match_music_operation'}
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    funcs=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names]
    assert len(funcs)==len(names)
    module=ast.Module(body=funcs,type_ignores=[])
    sys.path.insert(0,str(ROOT/'gateway'))
    import intent_rules
    env={'INTENTS':intent_rules,'asyncio':asyncio,'time':time,'re':re,'LOG':logging.getLogger('isolated-music'),
         'EventLog':FakeEventLog,'ROOT':ROOT,'log_event':lambda *args,**kwargs:None,
         'SETTINGS':NS(snapshot=lambda:{'ma_queue_id':'test_queue','r1_control_url':'http://invalid.test'}),
         'MUSIC_COMMANDS':{'播放':'resume','继续播放':'resume','随机播放点音乐':'random',
                           '暂停':'pause','停止':'stop','下一首':'next'},
         'web':NS(json_response=lambda value:value),
         'aiohttp':NS(ClientError=ClientError,ClientSession=Session,
                      ClientTimeout=lambda **kw:NS(**kw),TCPConnector=lambda **kw:NS(**kw))}
    exec(compile(module,str(SOURCE),'exec'),env)
    return env


async def eventually(predicate,timeout=.6):
    until=asyncio.get_running_loop().time()+timeout
    while not predicate():
        if asyncio.get_running_loop().time()>until:raise AssertionError('condition not reached')
        await asyncio.sleep(.001)


async def ignore_cancellation_until(gate,cancel_seen):
    # An I/O adapter can finish late despite cancellation. Generation fences must
    # still stop it from issuing another MA command after its response returns.
    while not gate.is_set():
        try:await gate.wait()
        except asyncio.CancelledError:cancel_seen.set()


class MusicPreemptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.initial_tasks=set(asyncio.all_tasks())
        self.env=isolated()
        self.app={}
        self.calls=[]
        self.hook=None
        self.releases=[]
        self.captured_tasks=[]

        async def ma_request(app,command,args):
            self.calls.append((command,dict(args)))
            if self.hook is not None:
                response=await self.hook(command,args)
                if response is not None:return response
            if command=='music/search':return {'playlists':[{'uri':'apple_music://playlist/synthetic'}]}
            if command=='player_queues/get':return {'items':3,'current_index':0}
            return {}
        self.env['ma_request']=ma_request
        await self.env['startup'](self.app)

    async def asyncTearDown(self):
        for gate in self.releases:gate.set()
        if not self.app['music_stopping']:await self.env['cleanup'](self.app)
        await asyncio.sleep(0)
        self.assertTrue(self.app['http'].closed)
        self.assertTrue(self.app['music_worker'].done())
        self.assertFalse(self.app['music_tasks'])
        leftovers=[task for task in asyncio.all_tasks() if task not in self.initial_tasks
                   and task is not asyncio.current_task() and not task.done()]
        self.assertFalse(leftovers,'background job or interrupt waiter leaked')

    async def control(self,text):
        return await self.env['music_control'](Request(self.app,text))

    def commands(self):
        return [command for command,args in self.calls]

    async def slow_search_preemption(self,text,command):
        started=asyncio.Event();release=asyncio.Event();cancel_seen=asyncio.Event()
        self.releases.append(release)
        async def hook(cmd,args):
            if cmd=='music/search':
                self.captured_tasks.append(asyncio.current_task())
                started.set()
                await ignore_cancellation_until(release,cancel_seen)
        self.hook=hook
        self.assertTrue((await self.control('随机播放点音乐'))['accepted'])
        await asyncio.wait_for(started.wait(),.5)
        # A pending second random request must disappear when stop/pause arrives.
        self.assertTrue((await self.control('随机播放点音乐'))['accepted'])
        before=asyncio.get_running_loop().time()
        self.assertTrue((await self.control(text))['accepted'])
        await eventually(lambda:command in self.commands())
        self.assertLess(asyncio.get_running_loop().time()-before,.5)
        self.assertTrue(cancel_seen.is_set())
        self.assertFalse(release.is_set(),'priority control waited for old search')
        release.set()
        await eventually(lambda:self.captured_tasks[0].done())
        await self.app['music_jobs'].join()
        self.assertEqual(self.commands(),['music/search',command])
        self.assertTrue(self.captured_tasks[0].cancelled())
        self.assertEqual(self.app['music_last_error'],'')

    async def test_pause_preempts_noncooperative_search_and_discards_pending_play(self):
        await self.slow_search_preemption('暂停','player_queues/pause')

    async def test_stop_preempts_noncooperative_search_and_discards_pending_play(self):
        await self.slow_search_preemption('停止','player_queues/stop')

    async def test_pause_preempts_repeat_preparation_before_play_is_submitted(self):
        started=asyncio.Event();release=asyncio.Event();cancel_seen=asyncio.Event()
        self.releases.append(release)
        async def hook(command,args):
            if command=='player_queues/repeat':
                started.set();await ignore_cancellation_until(release,cancel_seen)
        self.hook=hook
        await self.control('随机播放点音乐')
        await asyncio.wait_for(started.wait(),.5)
        await self.control('暂停')
        await eventually(lambda:'player_queues/pause' in self.commands())
        release.set();await eventually(lambda:not self.app['music_tasks'])
        self.assertEqual(self.commands(),['music/search','player_queues/repeat','player_queues/pause'])

    async def test_generation_fence_works_without_task_cancellation(self):
        started=asyncio.Event();release=asyncio.Event();self.releases.append(release)
        async def hook(command,args):
            if command=='music/search':started.set();await release.wait()
        self.hook=hook
        task=asyncio.create_task(self.env['perform_music'](self.app,'random',0))
        await started.wait();self.app['music_generation']+=1;release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.commands(),['music/search'])

    async def test_stale_generation_does_not_send_first_request(self):
        self.app['music_generation']=1
        with self.assertRaises(asyncio.CancelledError):
            await self.env['perform_music'](self.app,'random',0)
        self.assertFalse(self.calls)

    async def test_already_submitted_ma_play_cannot_be_claimed_rolled_back(self):
        started=asyncio.Event();release=asyncio.Event();cancel_seen=asyncio.Event()
        self.releases.append(release)
        async def hook(command,args):
            if command=='player_queues/play_media':
                started.set();await ignore_cancellation_until(release,cancel_seen)
        self.hook=hook
        await self.control('随机播放点音乐');await asyncio.wait_for(started.wait(),.5)
        await self.control('暂停')
        await eventually(lambda:'player_queues/pause' in self.commands())
        self.assertIn('player_queues/play_media',self.commands())
        release.set();await eventually(lambda:not self.app['music_tasks'])
        # The fake accepted the old request before pause. We only guarantee no
        # further submission, not rollback of side effects in MA's server task.
        self.assertEqual(self.commands().count('player_queues/play_media'),1)
        self.assertEqual(self.commands()[-1],'player_queues/pause')

    async def test_old_preflight_cannot_enqueue_resume_after_new_stop(self):
        started=asyncio.Event();release=asyncio.Event();self.releases.append(release)
        async def hook(command,args):
            if command=='player_queues/get':started.set();await release.wait()
        self.hook=hook
        request=asyncio.create_task(self.control('播放'))
        await started.wait();await self.control('停止')
        await eventually(lambda:'player_queues/stop' in self.commands())
        release.set();response=await request
        self.assertFalse(response['accepted'])
        await self.app['music_jobs'].join()
        self.assertNotIn('players/cmd/play',self.commands())

    async def test_explicit_new_play_after_pause_is_not_cancelled_as_stale(self):
        await self.control('暂停')
        await eventually(lambda:'player_queues/pause' in self.commands())
        self.assertTrue((await self.control('随机播放点音乐'))['accepted'])
        await self.app['music_jobs'].join()
        self.assertEqual(self.commands(),['player_queues/pause','music/search','player_queues/repeat','player_queues/play_media'])
        self.assertEqual(self.calls[-1][1],{'queue_id':'test_queue','media':'apple_music://playlist/synthetic','option':'replace','shuffle':True})
        self.assertEqual(self.calls[-2][1]['repeat_mode'],'off')

    async def test_cleanup_cancels_active_and_pending_jobs_without_leaks(self):
        started=asyncio.Event();cancelled=asyncio.Event()
        async def hook(command,args):
            if command=='music/search':
                try:started.set();await asyncio.Event().wait()
                finally:cancelled.set()
        self.hook=hook
        await self.control('随机播放点音乐');await started.wait()
        await self.control('随机播放点音乐')
        task=self.app['music_active_task']
        await asyncio.wait_for(self.env['cleanup'](self.app),.5)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(task.cancelled())
        self.assertEqual(self.commands(),['music/search'])
        await asyncio.wait_for(self.app['music_jobs'].join(),.1)
        self.assertFalse((await self.control('暂停'))['accepted'])

    async def test_cleanup_cancellation_is_propagated(self):
        session=self.app['http'];session.close_gate=asyncio.Event()
        clean=asyncio.create_task(self.env['cleanup'](self.app))
        await session.close_entered.wait();clean.cancel()
        with self.assertRaises(asyncio.CancelledError):await clean
        self.assertTrue(session.closed)

    async def test_non_superseded_music_error_remains_visible_and_worker_survives(self):
        async def hook(command,args):
            if command=='music/search':raise RuntimeError('synthetic failure')
        self.hook=hook
        await self.control('随机播放点音乐');await self.app['music_jobs'].join()
        self.assertTrue(self.app['music_last_error'])
        self.assertFalse(self.app['music_worker'].done())
        await self.control('停止');await self.app['music_jobs'].join()
        self.assertEqual(self.commands(),['music/search','player_queues/stop'])

    async def test_play_timeout_records_unknown_outcome_and_does_not_resubmit(self):
        events=[]
        self.env['log_event']=lambda *args,**fields:events.append(fields)
        async def hook(command,args):
            if command=='player_queues/play_media':raise asyncio.TimeoutError()
        self.hook=hook
        await self.control('随机播放点音乐');await self.app['music_jobs'].join()
        failed=[e for e in events if e.get('error_kind')=='TimeoutError']
        self.assertEqual(len(failed),1)
        self.assertEqual(failed[0]['status'],'unconfirmed')
        self.assertIn('player_queues/play_media',failed[0]['response'])
        self.assertIn('尚未确认',self.app['music_last_error'])
        self.assertEqual(self.commands().count('player_queues/play_media'),1)

    async def test_search_timeout_records_preparation_failure_without_mutation(self):
        events=[]
        self.env['log_event']=lambda *args,**fields:events.append(fields)
        async def hook(command,args):
            if command=='music/search':raise asyncio.TimeoutError()
        self.hook=hook
        await self.control('随机播放点音乐');await self.app['music_jobs'].join()
        failed=[e for e in events if e.get('error_kind')=='TimeoutError']
        self.assertEqual(failed[0]['status'],'failed')
        self.assertIn('music/search',failed[0]['response'])
        self.assertEqual(self.commands(),['music/search'])

    async def test_late_old_error_does_not_overwrite_new_control_status(self):
        started=asyncio.Event();release=asyncio.Event();cancel_seen=asyncio.Event();self.releases.append(release)
        async def hook(command,args):
            if command=='music/search':
                started.set();await ignore_cancellation_until(release,cancel_seen)
                raise RuntimeError('late synthetic failure')
        self.hook=hook
        await self.control('随机播放点音乐');await started.wait();await self.control('停止')
        await eventually(lambda:'player_queues/stop' in self.commands())
        release.set();await eventually(lambda:not self.app['music_tasks'])
        self.assertEqual(self.app['music_last_error'],'')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MusicPreemptionTests))
    if SOURCE.parent==ROOT:
        out=ROOT/'music-preemption';out.mkdir(exist_ok=True)
        (out/'test-result.json').write_text(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'successful':result.wasSuccessful(),'production_access':False},indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
