"""复用本地识别的断句，通过硅基流动转写；提供独立的云端播报音频。"""
import asyncio,json,logging,time,re
from pathlib import Path
from urllib.parse import urlsplit
import aiohttp
from gateway_config import GatewayConfig,ASR_PRESETS,model_id
from event_log import EventLog,encode_json,MAX_HTTP_BYTES
from audio_transport import wav_bytes,sample_width,sherpa_frame
from tts_cache import AudioCache
import intent_rules as INTENTS
from aiohttp import web,WSMsgType
import numpy as np
ROOT=Path(__file__).resolve().parent
SETTINGS=GatewayConfig(ROOT)
LOG=logging.getLogger('r1-cloud-voice')
CACHE=AudioCache()
CACHE_GENERATION=0
MUSIC_COMMANDS=json.loads((ROOT/'music-commands.json').read_text(encoding='utf-8'))
ASR_RETRY_MESSAGE='没有听清，请再说一遍。'
ASR_UNAVAILABLE_MESSAGE='语音识别服务暂时没有响应，请稍后再试。'

def log_event(app,level,stage,turn=0,**fields):
    history=app.get('event_log')
    if history is not None:history.record(level,stage,turn,**fields)

def request_turn(request):
    try:
        turn=int(request.query.get('turn','0'))
        return turn if 0<=turn<2**63 else 0
    except (ValueError,TypeError):return 0

class CloudAsrUnavailable(Exception):
    """云端没有确认识别结果，禁止回退执行本地猜测。"""
    def __init__(self,retryable=False):
        super().__init__()
        self.retryable=retryable

class CloudAsrRejected(RuntimeError):
    """只保留可公开的失败分类；不保存云端正文或请求凭据。"""
    def __init__(self,kind,status=0):
        super().__init__(kind)
        self.kind=kind
        self.status=status

async def transcribe_cloud(session,audio,primary=None,settings=None,events=None):
    """按当前配置选择模型与超时；所有云端尝试失败后要求重说。"""
    config=settings or SETTINGS.snapshot()
    primary=model_id(primary or config['asr_model'])
    attempts=[(primary,config['asr_timeout_seconds'])]
    fallback=config['asr_fallback_model']
    if fallback and fallback!=primary:
        attempts.append((fallback,config['asr_fallback_timeout_seconds']))
    failure_kinds=[]
    for model,budget in attempts:
        started=time.monotonic()
        try:
            form=aiohttp.FormData()
            form.add_field('model',model)
            form.add_field('file',audio,filename='command.wav',content_type='audio/wav')
            headers={'Authorization':'Bearer '+config['asr_api_key']} if config['asr_api_key'] else {}
            async with session.post(config['asr_base_url']+'/audio/transcriptions',data=form,
                    headers=headers,timeout=aiohttp.ClientTimeout(total=budget,connect=1.5)) as response:
                if response.status!=200:raise CloudAsrRejected('http_status',response.status)
                result=await response.json()
            text=result.get('text','').strip()
            if not text:raise CloudAsrRejected('empty_text')
            backend={'TeleAI/TeleSpeechASR':'telespeech',
                'FunAudioLLM/SenseVoiceSmall':'sensevoice',
                'XingChenAGI/XingChenGSR-V1.0':'xingchen-gsr'}.get(model,'cloud:'+model)
            return text,backend
        except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError,TypeError,AttributeError) as exc:
            kind=(exc.kind if isinstance(exc,CloudAsrRejected) else
                'timeout' if isinstance(exc,asyncio.TimeoutError) else
                'invalid_response' if isinstance(exc,(ValueError,TypeError,AttributeError,aiohttp.ContentTypeError)) else
                'transport' if isinstance(exc,aiohttp.ClientError) else 'runtime')
            failure_kinds.append(kind)
            if events:events('WARN',model=model,error_kind=kind,status=getattr(exc,'status',0),
                duration_ms=round((time.monotonic()-started)*1000),audio_seconds=max(0,len(audio)-44)/32000,
                response='attempt_failed budget_seconds='+str(budget),backend='cloud')
            LOG.warning('ASR model=%s failed=%s kind=%s status=%d elapsed_ms=%d',
                model,type(exc).__name__,kind,getattr(exc,'status',0),
                round((time.monotonic()-started)*1000))
    # 至少一个服务正常返回空文字时允许重说；备用服务故障不能阻止这次续听。
    raise CloudAsrUnavailable('empty_text' in failure_kinds)

async def startup(app):
    app['event_log']=await EventLog(app.get('event_log_dir',ROOT/'diagnostic-logs')).start()
    app['music_jobs']=asyncio.Queue(maxsize=4)
    app['music_generation']=0
    app['music_revision']=0
    app['music_precheck_lock']=asyncio.Lock()
    app['music_interrupt']=asyncio.Event()
    app['music_tasks']=set()
    app['music_active_task']=None
    app['music_stopping']=False
    app['music_last_error']=''
    app['http']=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12,connect=1.5),connector=aiohttp.TCPConnector(ttl_dns_cache=600,keepalive_timeout=90),trust_env=False)
    app['music_worker']=asyncio.create_task(music_worker(app))
async def cleanup(app):
    app['music_stopping']=True
    app['music_generation']+=1
    app['music_interrupt'].set()
    app['music_worker'].cancel()
    tasks=tuple(app['music_tasks'])
    for task in tasks:task.cancel()
    while not app['music_jobs'].empty():
        app['music_jobs'].get_nowait();app['music_jobs'].task_done()
    try:
        await asyncio.gather(app['music_worker'],*tasks,return_exceptions=True)
    finally:
        try:await app['http'].close()
        finally:await app['event_log'].close()
@web.middleware
async def local_only(request,handler):
    if request.remote not in SETTINGS.snapshot()['allowed_clients']:
        raise web.HTTPForbidden()
    if request.method=='POST' and request.path in {'/config','/asr/test','/logs/config','/logs/clear','/logs/events'}:
        origin=request.headers.get('Origin')
        if origin and (urlsplit(origin).netloc!=request.host or urlsplit(origin).scheme!=request.scheme):
            raise web.HTTPForbidden()
    return await handler(request)
def normalize_command(text):
    return INTENTS.normalize(text)

def match_music_operation(text):
    return INTENTS.match_music_operation(text,MUSIC_COMMANDS)

def is_fast_control(text):
    return INTENTS.is_fast_control(text)


def is_clear_local_control(text,max_chars=12):
    """只接受完整短指令；需要同音纠错的本地结果必须交给云端。"""
    compact=lambda value:re.sub(r'[\s，。！？、,.!?]+','',value)
    candidate=normalize_command(text)
    return (bool(text.strip()) and len(compact(text))<=max_chars and
        compact(candidate)==compact(text) and is_fast_control(candidate) and
        not is_incomplete_transcription(candidate))

def is_incomplete_transcription(text):
    return INTENTS.is_incomplete_transcription(text)
async def recognize(request):
    config=SETTINGS.snapshot()
    try:primary=model_id(request.query.get('model') or config['asr_model'])
    except ValueError as error:raise web.HTTPBadRequest(text=str(error))
    audio_format=request.query.get('audio_format','float32')
    try:width=sample_width(audio_format)
    except ValueError as error:raise web.HTTPBadRequest(text=str(error))
    audio_rate=16000*width
    ws=web.WebSocketResponse(max_msg_size=256*1024,heartbeat=10)
    await ws.prepare(request)
    chunks=[];size=0;last_local='';finished=False;input_error=False
    session=request.app['http']
    turn=request_turn(request)
    events=lambda level,**fields:log_event(request.app,level,'ASR',turn,**fields)
    try:
        async with session.ws_connect(config['local_asr_url'],timeout=2,max_msg_size=1024*1024) as local:
            async def upload_audio():
                nonlocal size,input_error
                async for msg in ws:
                    if finished:return
                    if msg.type==WSMsgType.BINARY:
                        if not msg.data:continue
                        if len(msg.data)%width or size+len(msg.data)>audio_rate*config['max_record_seconds']:
                            input_error=True
                            await local.send_str('Done');return
                        chunks.append(msg.data);size+=len(msg.data)
                        await local.send_bytes(sherpa_frame(msg.data,audio_format))
                    elif msg.type==WSMsgType.TEXT and msg.data=='Done':
                        await local.send_str('Done');return
                await local.close()
            async def deliver_final():
                nonlocal finished
                finished=True
                if input_error:
                    if not ws.closed:
                        await ws.send_json({'text':'','is_final':True,'error':ASR_UNAVAILABLE_MESSAGE,'retryable':False})
                        await ws.send_str('Done!')
                    return
                if not size:
                    if not ws.closed:
                        await ws.send_json({'text':'','is_final':True,'error':ASR_RETRY_MESSAGE,'retryable':True})
                        await ws.send_str('Done!')
                    return
                started=time.monotonic();backend='sensevoice'
                local_candidate=normalize_command(last_local)
                if config['local_first'] and is_clear_local_control(last_local,config['local_max_chars']):
                    backend='local-fast';text=local_candidate
                else:
                    try:
                        text,backend=await transcribe_cloud(session,wav_bytes(chunks,audio_format),primary,config,events)
                    except CloudAsrUnavailable as error:
                        LOG.warning('ASR retry_required reason=cloud_unavailable')
                        events('WARN' if error.retryable else 'ERROR',model=primary,backend='cloud',
                            error_kind='empty_text' if error.retryable else 'cloud_unavailable',
                            duration_ms=round((time.monotonic()-started)*1000),audio_seconds=size/audio_rate)
                        if not ws.closed:
                            await ws.send_json({'text':'','is_final':True,'error':ASR_RETRY_MESSAGE if error.retryable else ASR_UNAVAILABLE_MESSAGE,'retryable':error.retryable})
                            await ws.send_str('Done!')
                        return
                if is_incomplete_transcription(text):
                    LOG.info('ASR retry_required reason=incomplete_transcription')
                    events('WARN',text=text,model=primary,backend=backend,error_kind='incomplete_transcription',
                        duration_ms=round((time.monotonic()-started)*1000),audio_seconds=size/audio_rate)
                    if not ws.closed:
                        await ws.send_json({'text':'','is_final':True,'error':ASR_RETRY_MESSAGE,'retryable':True})
                        await ws.send_str('Done!')
                    return
                text=normalize_command(text)
                LOG.info('ASR backend=%s seconds=%.3f audio_seconds=%.2f text=%s',backend,time.monotonic()-started,size/audio_rate,text)
                actual_model={'telespeech':'TeleAI/TeleSpeechASR','sensevoice':'FunAudioLLM/SenseVoiceSmall',
                    'xingchen-gsr':'XingChenAGI/XingChenGSR-V1.0','local-fast':'local'}.get(backend,backend.removeprefix('cloud:'))
                events('INFO',text=text,model=actual_model,backend=backend,status='final',
                    duration_ms=round((time.monotonic()-started)*1000),audio_seconds=size/audio_rate)
                if not ws.closed:
                    await ws.send_json({'text':text,'is_final':True,'backend':backend})
                    await ws.send_str('Done!')
            async def read_local():
                nonlocal last_local
                async for msg in local:
                    if msg.type==WSMsgType.TEXT:
                        if msg.data=='Done!':
                            await deliver_final();return
                        try:result=json.loads(msg.data)
                        except ValueError:continue
                        text=result.get('text','').strip()
                        if text:last_local=text
                        if result.get('is_final'):
                            await deliver_final();return
                        if not ws.closed:await ws.send_json({'text':text,'is_final':False})
                if not finished:await deliver_final()
            sending=asyncio.create_task(upload_audio())
            receiving=asyncio.create_task(read_local())
            try:await asyncio.wait_for(receiving,config['max_record_seconds']+config['asr_timeout_seconds']+
                    (config['asr_fallback_timeout_seconds'] if config['asr_fallback_model'] else 0)+3)
            finally:
                sending.cancel()
                await asyncio.gather(sending,return_exceptions=True)
    except (aiohttp.ClientError,asyncio.TimeoutError) as exc:
        LOG.warning('ASR session ended cause=%s',type(exc).__name__)
        events('ERROR',model=primary,backend='local_endpoint',error_kind='timeout' if isinstance(exc,asyncio.TimeoutError) else 'transport')
        if not ws.closed:
            await ws.send_json({'text':'','is_final':True,'error':ASR_UNAVAILABLE_MESSAGE,'retryable':False})
            await ws.send_str('Done!')
    finally:await ws.close()
    return ws
async def ma_request(app,command,args):
    config=SETTINGS.snapshot()
    token=config['ma_token']
    if token and not token.startswith('Bearer '):token='Bearer '+token
    async with app['http'].post(config['ma_url']+'/api',
            json={'command':command,'args':args},
            headers={'Authorization':token},
            timeout=aiohttp.ClientTimeout(total=15,connect=1.5)) as response:
        if response.status!=200:raise RuntimeError('Music Assistant HTTP '+str(response.status))
        return await response.json()

async def perform_music(app,operation,generation=None,precheck=None):
    async def current_request(command,args):
        # Cancellation cannot retract an MA request already sent. Fence every
        # request boundary so a superseded preparation cannot submit another one.
        def check_current():
            if generation is not None and generation!=app['music_generation']:
                raise asyncio.CancelledError()
        check_current()
        if command not in {'player_queues/get','music/search'}:
            app['music_revision']+=1
        result=await ma_request(app,command,args)
        check_current()
        return result
    config=SETTINGS.snapshot()
    queue_id=config['ma_queue_id']
    if operation in {'pause','stop'}:
        await current_request('player_queues/'+operation,{'queue_id':queue_id})
        return
    if operation=='random':
        # 随机听歌选择完整歌单，不能把一首歌的旧队列当成随机推荐。
        search={'search_query':config.get('default_random_query','国语流行'),'media_types':['playlist'],'limit':1}
        providers=config.get('default_random_providers',['apple_music'])
        if providers:search['providers']=providers
        result=await current_request('music/search',search)
        playlists=result.get('playlists') or []
        if not playlists or not playlists[0].get('uri'):raise RuntimeError('No music playlist')
        await current_request('player_queues/repeat',{'queue_id':queue_id,'repeat_mode':'off'})
        await current_request('player_queues/play_media',{'queue_id':queue_id,
            'media':playlists[0]['uri'],'option':'replace','shuffle':True})
        return
    if (precheck and precheck['generation']==generation and precheck['revision']==app['music_revision']
            and precheck['queue_id']==queue_id and time.monotonic()-precheck['at']<0.5):
        queue=precheck['queue']
    else:
        queue=await current_request('player_queues/get',{'queue_id':queue_id})
    count=int(queue.get('items') or 0);index=int(queue.get('current_index') or 0)
    if operation in {'first','next','previous'}:
        if not count or operation=='next' and index+1>=count:raise RuntimeError('Queue boundary')
        target=0 if operation=='first' else index+1 if operation=='next' else max(0,index-1)
        await current_request('player_queues/play_index',{'queue_id':queue_id,'index':target})
    elif operation=='resume':
        await current_request('players/cmd/play',{'player_id':queue_id})
    else:
        await current_request('player_queues/'+operation,{'queue_id':queue_id})

async def music_worker(app):
    async def run_job(operation,turn,generation,precheck):
        started=time.monotonic()
        try:
            await perform_music(app,operation,generation,precheck)
            if generation!=app['music_generation']:return
            app['music_last_error']=''
            LOG.info('MUSIC_DIRECT operation=%s seconds=%.3f',operation,time.monotonic()-started)
            log_event(app,'INFO','MA',turn,operation=operation,status='completed',executed=True,
                duration_ms=round((time.monotonic()-started)*1000))
        except asyncio.CancelledError:
            log_event(app,'INFO','MA',turn,operation=operation,status='preempted',executed=False,
                duration_ms=round((time.monotonic()-started)*1000))
            raise
        except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError,TypeError) as error:
            if generation!=app['music_generation']:return
            app['music_last_error']='音乐指令未能完成，请稍后再试。'
            LOG.warning('MUSIC_DIRECT failed=%s',type(error).__name__)
            log_event(app,'ERROR','MA',turn,operation=operation,status='failed',error_kind=type(error).__name__,
                duration_ms=round((time.monotonic()-started)*1000))
            if turn:
                try:
                    async with app['http'].get(SETTINGS.snapshot()['r1_control_url']+'/voice_test',
                            params={'music_error':'1','turn':str(turn)},
                            timeout=aiohttp.ClientTimeout(total=3)) as response:
                        await response.read()
                except (aiohttp.ClientError,asyncio.TimeoutError):pass
    def job_done(task,generation,operation,turn):
        app['music_tasks'].discard(task)
        if not task.cancelled() and (error:=task.exception()) is not None:
            LOG.warning('MUSIC_DIRECT task failed=%s',type(error).__name__)
            log_event(app,'ERROR','MA',turn,operation=operation,status='failed',error_kind=type(error).__name__)
            if generation==app['music_generation']:
                app['music_last_error']='音乐指令未能完成，请稍后再试。'
    while True:
        operation,turn,generation,precheck=await app['music_jobs'].get()
        task=None;interrupted=None
        try:
            if generation!=app['music_generation']:continue
            app['music_interrupt'].clear()
            task=asyncio.create_task(run_job(operation,turn,generation,precheck))
            app['music_tasks'].add(task)
            task.add_done_callback(lambda done,g=generation,op=operation,t=turn:job_done(done,g,op,t))
            app['music_active_task']=task
            interrupted=asyncio.create_task(app['music_interrupt'].wait())
            await asyncio.wait({task,interrupted},return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Do not await a superseded HTTP task here: pause/stop must not wait
            # for an old search to return. Tracked tasks are joined on cleanup.
            if task is not None and not task.done():task.cancel()
            if interrupted is not None:
                interrupted.cancel()
                await asyncio.gather(interrupted,return_exceptions=True)
            if app['music_active_task'] is task:app['music_active_task']=None
            app['music_jobs'].task_done()

async def music_control(request):
    try:
        data=await request.json()
        text=normalize_command(str(data.get('text','')).strip()).strip('，。！？、,.!? ')
        if len(text)>160:raise ValueError('Command too long')
        operation=match_music_operation(text)
        if operation is None:
            log_event(request.app,'DEBUG','ROUTE',text=text,route='fallback',accepted=False)
            return web.json_response({'handled':False})
        if data.get('dry_run') is True:return web.json_response({'handled':True,'operation':operation,'executed':False})
        turn=int(data.get('turn') or 0)
        if request.app['music_stopping']:
            return web.json_response({'handled':True,'accepted':False,'message':'音乐通道正在关闭，请稍后再试。'})
        generation=request.app['music_generation']
        precheck=None
        if operation not in {'pause','stop','random'}:
            async with request.app['music_precheck_lock']:
                revision=request.app['music_revision']
                active=request.app['music_active_task']
                can_reuse=(active is None or active.done()) and request.app['music_jobs'].empty()
                queue_id=SETTINGS.snapshot()['ma_queue_id']
                queue=await ma_request(request.app,'player_queues/get',{'queue_id':queue_id})
                if generation!=request.app['music_generation']:
                    return web.json_response({'handled':True,'accepted':False,'message':'音乐指令已被新的暂停或停止请求取消。'})
                count=int(queue.get('items') or 0);index=int(queue.get('current_index') or 0)
                if operation in {'resume','first'} and not count:return web.json_response({'handled':False})
                if operation=='next' and index+1>=count:return web.json_response({'handled':True,'accepted':False,'message':'队列里没有下一首，请先点一首歌。'})
                active=request.app['music_active_task']
                if (can_reuse and revision==request.app['music_revision'] and
                        (active is None or active.done()) and request.app['music_jobs'].empty()):
                    precheck={'queue':queue,'at':time.monotonic(),'generation':generation,
                              'revision':revision,'queue_id':queue_id}
        jobs=request.app['music_jobs']
        if operation in {'pause','stop'}:
            request.app['music_generation']+=1
            generation=request.app['music_generation']
            while not jobs.empty():
                old_operation,old_turn,_,_=jobs.get_nowait();jobs.task_done()
                log_event(request.app,'INFO','MA',old_turn,operation=old_operation,status='preempted',executed=False)
            for task in tuple(request.app['music_tasks']):task.cancel()
            request.app['music_interrupt'].set()
        if jobs.full():return web.json_response({'handled':True,'accepted':False,'message':'音乐指令较多，请稍等片刻。'})
        jobs.put_nowait((operation,turn,generation,precheck))
        log_event(request.app,'INFO','ROUTE',turn,text=text,route='direct',operation=operation,accepted=True,executed=False)
        log_event(request.app,'INFO','MA',turn,operation=operation,status='accepted',accepted=True,executed=False)
        messages={'pause':'正在暂停。','stop':'正在停止。','resume':'正在继续播放。','random':'正在随机播放音乐。','first':'正在播放第一首。','next':'正在切换下一首。','previous':'正在切换上一首。'}
        return web.json_response({'handled':True,'accepted':True,'message':messages[operation],'operation':operation})
    except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError,TypeError) as error:
        LOG.warning('MUSIC_DIRECT failed=%s',type(error).__name__)
        log_event(request.app,'ERROR','MA',operation=locals().get('operation') or 'unknown',accepted=False,error_kind=type(error).__name__)
        return web.json_response({'handled':True,'accepted':False,'message':'音乐通道暂时无法确认执行结果，请稍后再试。'})

async def tts(request):
    text=request.query.get('text','').strip()
    if not text or len(text)>1500:raise web.HTTPBadRequest(text='Expected 1-1500 text characters')
    config=SETTINGS.snapshot()
    voice=request.query.get('voice') or config['tts_voice']
    if voice in {'anna','bella','alex'}:voice=config['tts_model']+':'+voice
    if len(voice)>256 or any(ord(c)<32 for c in voice):
        raise web.HTTPBadRequest(text='Unsupported voice')
    cache_key=(config['tts_base_url'],config['tts_model'],voice,config['tts_speed'],config['tts_gain'],text)
    started=time.monotonic()
    cache_generation=CACHE_GENERATION
    if cache_key in CACHE:
        log_event(request.app,'INFO','TTS',request_turn(request),text=text,model=config['tts_model'],backend='cache',status='first_audio',duration_ms=0)
        return web.Response(body=CACHE[cache_key],content_type='audio/mpeg',headers={'Cache-Control':'no-store'})
    body={'model':config['tts_model'],'voice':voice,'input':text,'response_format':'mp3',
        'stream':True,'speed':config['tts_speed'],'gain':config['tts_gain']}
    data=bytearray()
    try:
        # 等首个音频块成功后才返回 200，Android 才能在失败时恢复原有播报。
        async with request.app['http'].post(config['tts_base_url']+'/audio/speech',json=body,
                headers={'Authorization':'Bearer '+config['tts_api_key']} if config['tts_api_key'] else {},
                timeout=aiohttp.ClientTimeout(total=config['tts_timeout_seconds'],connect=2)) as upstream:
            if upstream.status!=200:raise RuntimeError('HTTP '+str(upstream.status))
            first=await asyncio.wait_for(upstream.content.read(8192),config['tts_first_chunk_timeout_seconds'])
            if not first:raise RuntimeError('Empty audio')
            response=web.StreamResponse(headers={'Content-Type':'audio/mpeg','Cache-Control':'no-store','Accept-Ranges':'none'})
            await response.prepare(request);await response.write(first);data.extend(first)
            LOG.info('TTS first_audio_seconds=%.3f characters=%d',time.monotonic()-started,len(text))
            log_event(request.app,'INFO','TTS',request_turn(request),text=text,model=config['tts_model'],backend='cloud',
                status='first_audio',duration_ms=round((time.monotonic()-started)*1000))
            async for chunk in upstream.content.iter_chunked(8192):
                await response.write(chunk)
                if len(data)<512*1024:data.extend(chunk)
            await response.write_eof()
        if len(text)<=80 and len(data)<512*1024 and cache_generation==CACHE_GENERATION:
            CACHE[cache_key]=bytes(data)
        return response
    except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError) as exc:
        LOG.warning('TTS failed cause=%s',type(exc).__name__)
        log_event(request.app,'ERROR','TTS',request_turn(request),model=config['tts_model'],backend='cloud',
            status='failed',error_kind='timeout' if isinstance(exc,asyncio.TimeoutError) else type(exc).__name__,
            duration_ms=round((time.monotonic()-started)*1000))
        raise web.HTTPBadGateway(text='Cloud speech unavailable')
async def gateway_config(request):
    global CACHE_GENERATION
    if request.method=='GET':return web.json_response(SETTINGS.public(),headers={'Cache-Control':'no-store'})
    try:
        patch=await request.json()
        result=SETTINGS.update(patch)
        CACHE_GENERATION+=1
        CACHE.clear()
        return web.json_response(result,headers={'Cache-Control':'no-store'})
    except (ValueError,TypeError,json.JSONDecodeError):
        return web.json_response({'error':'配置无效，请检查模型 ID、接口地址、数字范围和密钥格式。'},status=400)

async def asr_models(request):
    config=SETTINGS.snapshot()
    try:
        async with request.app['http'].get(config['asr_base_url']+'/models',
                headers={'Authorization':'Bearer '+config['asr_api_key']} if config['asr_api_key'] else {},
                timeout=aiohttp.ClientTimeout(total=8,connect=2)) as upstream:
            if upstream.status!=200:raise RuntimeError('HTTP '+str(upstream.status))
            payload=await upstream.json()
        ids=[]
        for item in payload.get('data',[])[:3000]:
            try:ids.append(model_id(item['id']))
            except (ValueError,TypeError,KeyError):continue
        return web.json_response({'models':sorted(set(ids)),'presets':ASR_PRESETS})
    except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError,TypeError,AttributeError):
        return web.json_response({'error':'无法获取模型列表，可直接填写支持音频转写的模型 ID。'},status=502)

async def asr_test(request):
    """仅转写随安装包提供的合成录音，不执行识别出的任何指令。"""
    fixture=ROOT/'command-pause-16k.wav'
    if not fixture.is_file():return web.json_response({'error':'缺少合成测试音频。'},status=503)
    started=time.monotonic()
    try:
        text,backend=await transcribe_cloud(request.app['http'],fixture.read_bytes())
        return web.json_response({'text':text,'backend':backend,'seconds':round(time.monotonic()-started,3),'executed':False})
    except CloudAsrUnavailable:
        return web.json_response({'error':'ASR 接口没有返回可用文字，请检查模型、密钥、地址和超时。'},status=502)

async def health(request):
    config=SETTINGS.snapshot()
    return web.json_response({'ready':True,'asr':config['asr_model'],'asr_models':ASR_PRESETS,
        'custom_asr_models':True,'tts':config['tts_model'],'fallback':'retry-required',
        'endpoint_silence_seconds':1.3,'cache_entries':len(CACHE),'cache_bytes':CACHE.current_bytes,
        'music_last_error':request.app.get('music_last_error',''),
        'fast_local_controls':config['local_first'],'complex_asr_timeout_seconds':config['asr_timeout_seconds'],
        'restart_required':SETTINGS.public()['restart_required']})

def log_response(payload,status=200):
    return web.Response(body=encode_json(payload),status=status,content_type='application/json',
        headers={'Cache-Control':'no-store'})

async def log_payload(request,empty=False):
    if request.content_length is not None and request.content_length>MAX_HTTP_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_HTTP_BYTES,actual_size=request.content_length)
    data=bytearray()
    async for chunk in request.content.iter_chunked(8192):
        data.extend(chunk)
        if len(data)>MAX_HTTP_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_HTTP_BYTES,actual_size=len(data))
    if empty and not data:return {}
    try:payload=json.loads(data)
    except (ValueError,UnicodeError):raise web.HTTPBadRequest(text='Invalid log JSON')
    if not isinstance(payload,dict):raise web.HTTPBadRequest(text='Expected log object')
    return payload

async def event_history(request):
    history=request.app['event_log']
    try:
        if request.path=='/logs':
            return log_response(await history.read(int(request.query.get('limit','50'))))
        if request.path=='/logs/config':
            if request.method=='GET':return log_response(history.config())
            return log_response(await history.configure(await log_payload(request)))
        if request.path=='/logs/clear':
            if await log_payload(request,empty=True):raise ValueError('Unexpected clear fields')
            return log_response(await history.clear())
        payload=await log_payload(request)
        if set(payload)!={'generation','events'}:raise ValueError('Expected generation and events')
        return log_response(history.record_batch(payload['events'],payload['generation']))
    except (ValueError,TypeError,OverflowError):
        return log_response({'error':'Invalid log request'},400)
    except RuntimeError:
        return log_response({'error':'Event log storage unavailable'},503)

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
app=web.Application(middlewares=[local_only],client_max_size=1024*1024)
app.on_startup.append(startup);app.on_cleanup.append(cleanup)
app.router.add_get('/config',gateway_config);app.router.add_post('/config',gateway_config)
app.router.add_get('/models',asr_models);app.router.add_post('/asr/test',asr_test)
app.router.add_post('/music/control',music_control);app.router.add_get('/asr',recognize);app.router.add_get('/tts',tts);app.router.add_get('/health',health)
app.router.add_get('/logs',event_history)
app.router.add_get('/logs/config',event_history);app.router.add_post('/logs/config',event_history)
app.router.add_post('/logs/clear',event_history);app.router.add_post('/logs/events',event_history)
if __name__=='__main__':
    config=SETTINGS.snapshot()
    web.run_app(app,host=config['bind_host'],port=config['bind_port'],access_log=None)
