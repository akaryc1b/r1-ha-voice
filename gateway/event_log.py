"""Bounded opt-in event history. Only the worker thread touches persistent files."""
import asyncio
from collections import deque
from concurrent.futures import Future
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import threading

LEVELS={'DEBUG':10,'INFO':20,'WARN':30,'ERROR':40}
STAGES={'ASR','ROUTE','MA','HA','AI','TTS'}
FIELDS={'text','response','route','model','backend','operation','error_kind','status',
        'duration_ms','audio_seconds','accepted','executed','request_id'}
MAX_HTTP_BYTES=262144
_URL=re.compile(r'(?i)\b(?:https?|wss?)://[^\s<>"\']+')
_BEARER=re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+')
_JWT=re.compile(r'\b(?:eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b')
_KEY=re.compile(r'\bsk-[A-Za-z0-9_-]+')
_SECRET=re.compile(r'(?i)\b(authorization|api[_-]?key|token|secret|password)\s*[:=]\s*["\']?[^\s,;"\']+')


def encode_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')


def clean_text(value):
    if not isinstance(value,str):raise ValueError('Expected text field')
    value=value[:MAX_HTTP_BYTES]
    value=_URL.sub('[url omitted]',value)
    value=_BEARER.sub('Bearer [redacted]',value)
    value=_JWT.sub('[redacted]',value)
    value=_KEY.sub('[redacted]',value)
    value=_SECRET.sub(lambda match:match.group(1)+'=[redacted]',value)
    return ''.join(c for c in value if c in '\n\t' or ord(c)>=32)[:2048]


def sanitize_event(event,source):
    if not isinstance(event,dict) or source not in {'gateway','device'}:raise ValueError('Invalid event')
    level=event.get('level','INFO')
    stage=event.get('stage')
    turn=event.get('turn',0)
    if not isinstance(level,str) or not isinstance(stage,str) or level not in LEVELS or stage not in STAGES:
        raise ValueError('Invalid event level or stage')
    if type(turn) is not int or not 0<=turn<2**63:raise ValueError('Invalid turn')
    timestamp=event.get('timestamp')
    if timestamp is None:
        stamp=datetime.now(timezone.utc)
    else:
        if not isinstance(timestamp,str) or len(timestamp)>64:raise ValueError('Invalid timestamp')
        stamp=datetime.fromisoformat(timestamp.replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('Timestamp requires timezone')
    raw=event.get('fields',{})
    if not isinstance(raw,dict):raise ValueError('Invalid event fields')
    fields={}
    for key,value in raw.items():
        if key not in FIELDS:continue
        if key in {'accepted','executed'}:
            if type(value) is not bool:raise ValueError('Invalid boolean field')
        elif key in {'duration_ms','audio_seconds'}:
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError('Invalid duration field')
        elif key=='status' and type(value) is int:
            pass
        else:value=clean_text(value)
        fields[key]=value
    return {'timestamp':stamp.astimezone(timezone.utc).isoformat(timespec='milliseconds'),
            'level':level,'source':source,'stage':stage,'turn':turn,'fields':fields}


class EventLog:
    CONFIG_NAME='event-log.config.json'
    CURRENT_NAME='events.private.jsonl'
    PREVIOUS_NAME='events.previous.private.jsonl'

    def __init__(self,directory,file_limit=1024*1024,queue_limit=256):
        self.directory=Path(directory)
        self.file_limit=file_limit
        self.queue_limit=queue_limit
        self._condition=threading.Condition()
        self._pending=deque()
        self._event_count=0
        self._enabled=False
        self._level='INFO'
        self._generation=0
        self._error=''
        self._closing=False
        self._close_future=None
        self._ready=Future()
        self._thread=threading.Thread(target=self._run,name='r1-event-log',daemon=True)
        self._thread.start()

    async def start(self):
        await asyncio.wrap_future(self._ready)
        return self

    def _snapshot(self):
        return {'enabled':self._enabled,'level':self._level,'generation':self._generation,
                'status':self._error or ('closed' if self._closing else 'ok' if self._enabled else 'disabled')}

    def config(self):
        with self._condition:return self._snapshot()

    def _command(self,kind,payload=None):
        future=Future()
        self._pending.append((kind,payload,future))
        self._condition.notify()
        return future

    async def configure(self,patch):
        if not isinstance(patch,dict) or set(patch)-{'enabled','level'}:raise ValueError('Invalid log config')
        if 'enabled' in patch and type(patch['enabled']) is not bool:raise ValueError('Invalid enabled flag')
        if 'level' in patch and (not isinstance(patch['level'],str) or patch['level'] not in LEVELS):
            raise ValueError('Invalid log level')
        with self._condition:
            if self._closing:raise RuntimeError('Event log closed')
            enabled=patch.get('enabled',self._enabled)
            level=patch.get('level',self._level)
            if (enabled,level)!=(self._enabled,self._level):self._generation+=1
            self._enabled=enabled;self._level=level
            payload={k:self._snapshot()[k] for k in ('enabled','level','generation')}
            future=self._command('configure',payload)
        await asyncio.wrap_future(future)
        return self.config()

    async def clear(self):
        with self._condition:
            if self._closing:raise RuntimeError('Event log closed')
            self._generation+=1
            payload={k:self._snapshot()[k] for k in ('enabled','level','generation')}
            future=self._command('clear',payload)
        await asyncio.wrap_future(future)
        return {'cleared':True,**self.config()}

    def record(self,level,stage,turn=0,**fields):
        # Never perform filesystem work or wait for queue capacity on the caller.
        with self._condition:
            if self._closing or not self._enabled or level not in LEVELS or LEVELS[level]<LEVELS[self._level]:
                return False
        try:event=sanitize_event({'level':level,'stage':stage,'turn':turn,'fields':fields},'gateway')
        except (ValueError,TypeError,OverflowError):return False
        with self._condition:
            if self._closing or not self._enabled or LEVELS[level]<LEVELS[self._level]:return False
            if self._event_count>=self.queue_limit:return False
            self._pending.append(('event',(self._generation,event),None))
            self._event_count+=1;self._condition.notify()
            return True

    def record_batch(self,events,generation):
        if type(generation) is not int or generation<0:raise ValueError('Invalid generation')
        if not isinstance(events,list) or len(events)>32:raise ValueError('Invalid batch size')
        with self._condition:
            if generation!=self._generation:return {'accepted':0,'stale':True,**self._snapshot()}
        cleaned=[sanitize_event(event,'device') for event in events]
        with self._condition:
            current=self._generation
            if generation!=current:return {'accepted':0,'stale':True,**self._snapshot()}
            accepted=0
            if self._enabled and not self._closing:
                for event in cleaned:
                    if LEVELS[event['level']]<LEVELS[self._level] or self._event_count>=self.queue_limit:continue
                    self._pending.append(('event',(current,event),None))
                    self._event_count+=1;accepted+=1
                self._condition.notify()
            return {'accepted':accepted,'stale':False,**self._snapshot()}

    async def read(self,limit=50):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid log limit')
        with self._condition:
            if self._closing:raise RuntimeError('Event log closed')
            future=self._command('read',(limit,self._generation))
        return await asyncio.wrap_future(future)

    async def close(self):
        with self._condition:
            if self._close_future is None:
                self._closing=True
                self._close_future=self._command('close')
            future=self._close_future
        try:await asyncio.wrap_future(future)
        finally:await asyncio.to_thread(self._thread.join)

    def _save_config(self,payload):
        self.directory.mkdir(parents=True,exist_ok=True)
        target=self.directory/self.CONFIG_NAME
        temp=target.with_suffix('.tmp')
        temp.write_bytes(encode_json(payload))
        temp.replace(target)

    def _load(self):
        path=self.directory/self.CONFIG_NAME
        if not path.exists():return
        try:
            if path.stat().st_size>4096:raise ValueError('Oversized config')
            payload=json.loads(path.read_bytes())
            if type(payload.get('enabled')) is not bool or payload.get('level') not in LEVELS:
                raise ValueError('Invalid saved config')
            generation=payload.get('generation',0)
            if type(generation) is not int or generation<0:raise ValueError('Invalid saved generation')
            with self._condition:
                self._enabled=payload['enabled'];self._level=payload['level'];self._generation=generation
        except (OSError,ValueError,TypeError,AttributeError):
            with self._condition:self._error='invalid_config'

    def _append(self,event):
        data=encode_json(event)+b'\n'
        if len(data)>self.file_limit:return
        self.directory.mkdir(parents=True,exist_ok=True)
        current=self.directory/self.CURRENT_NAME
        previous=self.directory/self.PREVIOUS_NAME
        if current.exists() and current.stat().st_size+len(data)>self.file_limit:
            previous.unlink(missing_ok=True)
            current.replace(previous)
        with current.open('ab') as output:output.write(data)

    def _read(self,limit,generation):
        entries=[];budget=MAX_HTTP_BYTES-4096
        for name in (self.CURRENT_NAME,self.PREVIOUS_NAME):
            path=self.directory/name
            if not path.exists() or budget<=0:continue
            size=path.stat().st_size;take=min(size,budget);start=size-take
            with path.open('rb') as stream:stream.seek(start);data=stream.read(take)
            budget-=len(data)
            if start:data=data.partition(b'\n')[2]
            for line in reversed(data.splitlines()):
                try:
                    value=json.loads(line)
                    event=sanitize_event(value,value.get('source'))
                    entries.append(event)
                except (ValueError,TypeError,AttributeError,OverflowError):continue
                if len(entries)>=limit:break
            if len(entries)>=limit:break
        with self._condition:
            if generation!=self._generation:entries=[]
            result={'entries':entries,**self._snapshot()}
        while len(encode_json(result))>MAX_HTTP_BYTES:entries.pop()
        return result

    @staticmethod
    def _resolve(future,result=None,error=None):
        if future is not None and not future.cancelled():
            if error is None:future.set_result(result)
            else:future.set_exception(error)

    def _run(self):
        try:self._load();self._resolve(self._ready)
        except Exception as error:self._resolve(self._ready,error=error)
        while True:
            with self._condition:
                while not self._pending:self._condition.wait()
                kind,payload,future=self._pending.popleft()
                if kind=='event':self._event_count-=1
            try:
                if kind=='close':self._resolve(future);return
                if kind=='event':
                    generation,event=payload
                    with self._condition:
                        valid=generation==self._generation and self._enabled and LEVELS[event['level']]>=LEVELS[self._level]
                    if valid:self._append(event)
                elif kind in {'configure','clear'}:
                    self._save_config(payload)
                    if kind=='clear':
                        for name in (self.CURRENT_NAME,self.PREVIOUS_NAME):
                            (self.directory/name).unlink(missing_ok=True)
                    with self._condition:self._error=''
                    self._resolve(future)
                elif kind=='read':self._resolve(future,self._read(*payload))
            except Exception:
                with self._condition:self._error='io_error'
                self._resolve(future,error=RuntimeError('Event log storage unavailable'))
