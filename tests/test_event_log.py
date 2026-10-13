"""Exercise persistence and generation fences using temporary files only."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT if (ROOT/'event_log.py').is_file() else ROOT/'gateway'))
from event_log import EventLog,MAX_HTTP_BYTES,encode_json,sanitize_event


class EventLogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.logs=[]

    async def asyncTearDown(self):
        for history in self.logs:
            await history.close()
            self.assertFalse(history._thread.is_alive())
        self.temp.cleanup()

    async def new(self,**kwargs):
        history=await EventLog(self.temp.name,**kwargs).start()
        self.logs.append(history)
        return history

    async def test_default_disabled_does_not_create_files(self):
        history=await self.new()
        self.assertEqual(history.config()['status'],'disabled')
        self.assertFalse(history.record('ERROR','ASR',text='ignored'))
        self.assertEqual((await history.read())['entries'],[])
        await history.close()
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    async def test_level_filter_close_and_restart_preserve_history(self):
        history=await self.new()
        await history.configure({'enabled':True,'level':'WARN'})
        self.assertFalse(history.record('INFO','MA',text='filtered'))
        self.assertTrue(history.record('WARN','ASR',text='kept'))
        await history.close()
        restarted=await self.new()
        self.assertTrue(restarted.config()['enabled'])
        self.assertEqual(restarted.config()['level'],'WARN')
        self.assertEqual((await restarted.read())['entries'][0]['fields']['text'],'kept')
        await restarted.configure({'enabled':False})
        self.assertFalse(restarted.record('ERROR','ASR',text='off'))
        self.assertEqual(len((await restarted.read())['entries']),1)

    async def test_rotation_never_exceeds_two_bounded_files(self):
        history=await self.new(file_limit=1024)
        await history.configure({'enabled':True})
        for number in range(30):
            history.record('INFO','MA',text='x'*250,status=str(number))
            await history.read()
        paths=list(Path(self.temp.name).glob('*.jsonl'))
        self.assertEqual(len(paths),2)
        self.assertTrue(all(path.stat().st_size<=1024 for path in paths))
        entries=(await history.read())['entries']
        self.assertEqual(entries[0]['fields']['status'],'29')
        self.assertLess(len(entries),30)
        # Verify the production bound without leaving a worker behind.
        extra=await self.new()
        self.assertEqual(extra.file_limit,1024*1024)

    async def test_clear_fences_inflight_queued_and_late_device_events(self):
        history=await self.new()
        state=await history.configure({'enabled':True})
        entered=threading.Event();release=threading.Event()
        original=history._append
        def blocked(event):
            entered.set()
            if not release.wait(3):raise RuntimeError('Test gate timeout')
            original(event)
        history._append=blocked
        history.record('INFO','ASR',text='old in flight')
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        history.record('INFO','ASR',text='old queued')
        clear=asyncio.create_task(history.clear())
        await asyncio.sleep(0)
        generation=history.config()['generation']
        self.assertGreater(generation,state['generation'])
        history.record('INFO','ASR',text='new')
        stale=history.record_batch([{'stage':'TTS','fields':{'text':'late old'}}],state['generation'])
        self.assertTrue(stale['stale']);self.assertEqual(stale['accepted'],0)
        release.set()
        await clear
        self.assertEqual([e['fields']['text'] for e in (await history.read())['entries']],['new'])

    async def test_queue_capacity_drops_without_blocking(self):
        history=await self.new(queue_limit=1)
        await history.configure({'enabled':True})
        with history._condition:
            self.assertTrue(history.record('INFO','MA',text='first'))
            self.assertFalse(history.record('INFO','MA',text='dropped'))
        self.assertEqual(len((await history.read())['entries']),1)

    async def test_device_source_is_forced_schema_is_strict_and_text_redacted(self):
        history=await self.new()
        state=await history.configure({'enabled':True})
        value='Bearer SECRET_VALUE sk-secret123 eyJabc1234.payload123.signature123 https://example.invalid/private api_key=hidden '
        event={'stage':'AI','source':'gateway','headers':{'Authorization':'hidden'},'fields':{
            'text':value+'\u0000'+'\u4e2d'*3000,'response':'safe','unknown':'hidden'}}
        self.assertEqual(history.record_batch([event],state['generation'])['accepted'],1)
        saved=(await history.read())['entries'][0]
        self.assertEqual(saved['source'],'device')
        self.assertEqual(set(saved['fields']),{'text','response'})
        self.assertEqual(len(saved['fields']['text']),2048)
        for secret in ('SECRET_VALUE','sk-secret123','payload123','example.invalid','hidden','\u0000'):
            self.assertNotIn(secret,json.dumps(saved,ensure_ascii=False))
        for fields in ({'accepted':1},{'duration_ms':float('nan')},{'text':{}},{'status':[]}):
            with self.assertRaises(ValueError):sanitize_event({'stage':'ASR','fields':fields},'device')
        with self.assertRaises(ValueError):history.record_batch([event]*33,state['generation'])

    async def test_read_budget_recent_first_and_generation_persists(self):
        history=await self.new()
        state=await history.configure({'enabled':True})
        for number in range(100):
            history.record('INFO','ASR',text='\u4e2d'*2048,response='\u6587'*2048,status=str(number))
        result=await history.read(100)
        self.assertLessEqual(len(encode_json(result)),MAX_HTTP_BYTES)
        self.assertEqual(result['entries'][0]['fields']['status'],'99')
        clear=await history.clear()
        await history.close()
        restarted=await self.new()
        self.assertEqual(restarted.config()['generation'],clear['generation'])
        self.assertEqual((await restarted.read())['entries'],[])
        self.assertTrue(restarted.record_batch([],state['generation'])['stale'])

    async def test_config_toggle_fences_old_device_batch(self):
        history=await self.new()
        old=await history.configure({'enabled':True})
        await history.configure({'enabled':False})
        new=await history.configure({'enabled':True})
        self.assertGreater(new['generation'],old['generation'])
        self.assertTrue(history.record_batch([],old['generation'])['stale'])


if __name__=='__main__':unittest.main(verbosity=2)
