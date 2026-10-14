"""Run isolated flow regressions using the supplied source tree; no live controls."""
import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maintain_ma_optimizations import optimized_source
parser=argparse.ArgumentParser()
parser.add_argument("--source-root",type=Path,help="已应用补丁的 music_assistant 包目录；默认从固定官方缓存重建")
args=parser.parse_args()
files={
 path:optimized_source(path,args.source_root) for path in (
 "controllers/player_queues/controller.py",
 "controllers/player_queues/playback_tracker.py",
 "controllers/streams/audio.py")
}
code='''import ast,asyncio,copy,json,os,textwrap
from types import SimpleNamespace
from music_assistant_models.enums import MediaType,PlaybackState
from music_assistant_models.errors import MediaNotFoundError,AudioError,QueueEmpty
from music_assistant_models.player_queue import PlayLogEntry
files=FILES
for name,content in files.items():compile(content,name,'exec')
env={'copy':copy.copy,'MediaType':MediaType,'PlaybackState':PlaybackState,'PlayLogEntry':PlayLogEntry,'os':os}
tree=ast.parse(files['controllers/player_queues/controller.py'])
setting=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='R1_MA_QUEUE_ID' for t in n.targets))
exec(compile(ast.Module(body=[setting],type_ignores=[]),'queue-environment','exec'),env)
env.update(MediaNotFoundError=MediaNotFoundError,AudioError=AudioError,QueueEmpty=QueueEmpty,ProviderStreamLimitError=type('ProviderStreamLimitError',(Exception,),{}))
def extract(source,name):
 tree=ast.parse(source)
 node=next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name)
 node.decorator_list=[]
 module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
 ast.fix_missing_locations(module);exec(compile(module,name,'exec'),env)
 return env[name]
load=extract(files['controllers/player_queues/controller.py'],'load_next_queue_item')
flow=extract(files['controllers/player_queues/playback_tracker.py'],'_get_flow_queue_stream_index')
Entry=extract(files['controllers/streams/audio.py'],'_FlowPlayLogEntry')
async def main():
 buffer=object()
 details=SimpleNamespace(seek_position=146,buffer=buffer)
 media=SimpleNamespace(metadata=SimpleNamespace(images=[]),image=None,provider_mappings={'quality-original'})
 active=SimpleNamespace(queue_item_id='same',streamdetails=details,extra_attributes={},media_type=MediaType.TRACK,media_item=media,image=None,uri='apple_music://track/same',available=True,name='same')
 queue=SimpleNamespace(queue_id='upbac50e55',flow_mode=True,current_item=active,current_index=0,elapsed_time=146,state=PlaybackState.PLAYING)
 entry=Entry('same',details,1.0)
 data=SimpleNamespace(items=[active],flow_mode_stream_log=[entry],session_id='original')
 player=SimpleNamespace(state=SimpleNamespace(corrected_elapsed_time=14,playback_state=PlaybackState.PLAYING))
 calls=[]
 async def load_item(item,seek_position):
  calls.append({'id':item.queue_item_id,'seek':seek_position})
  item.streamdetails.seek_position=seek_position
 host=SimpleNamespace(get=lambda q:queue,index_by_id=lambda q,i:0,_get_next_index=lambda q,i:0,
      get_item=lambda q,i:active,_load_item=load_item,_queue_data={'upbac50e55':data},signal_update=lambda *a,**k:None,logger=SimpleNamespace(warning=lambda *a:None))
 assert flow(host,queue,player)[1]==160
 next_play=await load(host,'upbac50e55','same')
 assert next_play is not active and next_play.streamdetails is not details
 assert next_play.streamdetails.buffer is buffer
 assert next_play.streamdetails.seek_position==0 and active.streamdetails.seek_position==146
 assert flow(host,queue,player)[1]==160
 # Execute the candidate's exact ownership-handoff block when the repeat starts.
 audio_tree=ast.parse(files['controllers/streams/audio.py'])
 handoff=next(n for n in ast.walk(audio_tree) if isinstance(n,ast.If) and any(isinstance(c,ast.Name) and c.id=='central_item' for c in ast.walk(n)))
 handoff_fn=ast.FunctionDef(name='handoff',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[handoff],decorator_list=[])
 handoff_module=ast.Module(body=[handoff_fn],type_ignores=[]);ast.fix_missing_locations(handoff_module)
 context={'queue':queue,'queue_track':next_play,'self':SimpleNamespace(mass=SimpleNamespace(player_queues=host)),'_superseded':lambda:True,'R1_MA_QUEUE_ID':env['R1_MA_QUEUE_ID']}
 exec(compile(handoff_module,'actual-buffer-ownership-handoff','exec'),context)
 context['handoff']();assert active.streamdetails is details
 context['_superseded']=lambda:False;context['handoff']()
 assert active.streamdetails is next_play.streamdetails
 assert flow(host,queue,player)[1]==160
 # The next natural repeat starts at zero and preserves all original preload calls.
 entry.seconds_streamed=94
 data.flow_mode_stream_log.append(Entry('same',next_play.streamdetails,1.0))
 player.state.corrected_elapsed_time=108
 assert flow(host,queue,player)[1]==14
 await load(host,'upbac50e55','same');assert len(calls)==2 and all(c['seek']==0 for c in calls)
 # Producer-owned fade corrections remain visible, independent of later central metadata.
 data.flow_mode_stream_log=[entry];entry.seconds_streamed=None
 details.seek_position=150;player.state.corrected_elapsed_time=14
 active.streamdetails=SimpleNamespace(seek_position=999,buffer=buffer)
 active.extra_attributes['playback_speed']=2
 assert flow(host,queue,player)[1]==164
 entry.finish()
 assert entry.streamdetails is None and entry.seek_position==150
 details.seek_position=500
 assert flow(host,queue,player)[1]==164
 # Long queues retain scalar progress, never completed PCM buffers.
 archived=[Entry('same',SimpleNamespace(seek_position=i,buffer=buffer),1) for i in range(99)]
 for old in archived:old.finish()
 assert all(old.streamdetails is None and old.seek_position==i for i,old in enumerate(archived))
 # Legacy entries without owned metadata keep the official fallback behavior.
 data.flow_mode_stream_log=[PlayLogEntry('same')]
 assert flow(host,queue,player)[1]==1027
 # Native per-item players are unchanged by the flow-only ownership fix.
 queue.flow_mode=False
 result=await load(host,'upbac50e55','same')
 assert result is active
 queue.flow_mode=True;queue.queue_id='another-player'
 host._queue_data['another-player']=data
 result=await load(host,'another-player','same');assert result is active
 queue.queue_id='upbac50e55';queue.flow_mode=True
 async def enriched(item,seek_position):
  item.media_item=SimpleNamespace(metadata=SimpleNamespace(images=['cover']),image='cover',provider_mappings={'changed-quality'})
 host._load_item=enriched
 await load(host,'upbac50e55','same')
 assert media.metadata.images==['cover'] and active.image=='cover'
 assert active.media_item is media and media.provider_mappings=={'quality-original'}
 # A superseded preload must not enrich the new active occurrence.
 media.metadata.images=[];active.image=None
 async def stale_enriched(item,seek_position):
  await enriched(item,seek_position);data.session_id='changed'
 host._load_item=stale_enriched
 await load(host,'upbac50e55','same')
 assert media.metadata.images==[] and active.image is None
 for error_type in (MediaNotFoundError,AudioError):
  for stale in (False,True):
   data.session_id='original';active.available=True
   calls=[0]
   async def failure(item,seek_position):
    calls[0]+=1
    if stale and calls[0]==1:data.session_id='changed'
    raise error_type('unavailable')
   # End after the first failure so the test checks that occurrence's exact identity.
   host._get_next_index=lambda q,i:0 if calls[0]==0 else None
   host._load_item=failure
   try:await load(host,'upbac50e55','same')
   except QueueEmpty:pass
   assert active.available is stale
 return {'checks':22,'passed':True,'flow_seek_resume_before':160,'flow_seek_resume_after_preload':160,
      'natural_repeat_position':14,'preload_calls_preserved':True,'buffer_object_preserved':True,
      'active_buffer_ownership_transferred':True,'stale_session_handoff_blocked':True,'other_player_behavior_preserved':True,
      'fade_correction_preserved':True,'non_flow_behavior_preserved':True,'artwork_enriched_without_quality_replacement':True,'stale_artwork_blocked':True,'failure_availability_preserved':True,'stale_failure_blocked':True,'completed_entries_release_buffer_references':True,'archived_entries_tested':99,'production_mutation':False}
print(json.dumps(asyncio.run(main())))'''.replace('FILES',repr(files))
code=code.replace("'upbac50e55'",repr(os.environ.get('R1_MA_QUEUE_ID','upbac50e55').strip()))
exec(compile(code,'isolated-flow-regression','exec'))
