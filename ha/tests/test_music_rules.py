"""Validate HA music grammar and gateway normalization without service calls."""
import argparse
import sys
from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from render_config import Loader,Dumper,replace_tokens,validate_settings
parser=argparse.ArgumentParser()
parser.add_argument("--sentences",type=Path,default=root/"custom_sentences/zh-cn/r1_music.yaml")
parser.add_argument("--package",type=Path,default=root/"packages/r1_apple_music.yaml")
parser.add_argument("--gateway",type=Path,default=root.parent/"gateway/voice_gateway.py")
parser.add_argument("--settings",type=Path,default=root/"r1_settings.example.yaml")
args=parser.parse_args()
source=args.sentences.read_text(encoding="utf-8")
settings=validate_settings(yaml.safe_load(args.settings.read_text(encoding="utf-8")))
package_data=yaml.load(args.package.read_text(encoding="utf-8"),Loader=Loader)
package=yaml.dump(replace_tokens(package_data,settings),Dumper=Dumper,allow_unicode=True,sort_keys=False)
explicit_package=yaml.dump(replace_tokens(package_data,dict(settings,provider='apple_music--selected')),Dumper=Dumper,allow_unicode=True,sort_keys=False)
player_package=yaml.dump(replace_tokens(yaml.load((root/'packages/r1_music_player.yaml').read_text(encoding='utf-8'),Loader=Loader),settings),Dumper=Dumper,allow_unicode=True,sort_keys=False)
generator=(root/"generate_music_commands.py").read_text(encoding="utf-8")
gateway=args.gateway.read_text(encoding="utf-8")
code = '''import json,re,asyncio,yaml,traceback,ast,sys
from hassil import Intents,recognize,recognize_all
from hassil.parse_expression import parse_sentence
from hassil.sample import sample_sentence
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
source=SOURCE
package_source=PACKAGE
class Loader(yaml.SafeLoader):pass
Loader.add_constructor('!include',lambda loader,node:loader.construct_scalar(node))
data=yaml.safe_load(source);intents=Intents.from_dict(data)
package=yaml.load(package_source,Loader=Loader)
package_explicit=yaml.load(EXPLICIT_PACKAGE,Loader=Loader)
package_player=yaml.load(PLAYER_PACKAGE,Loader=Loader)
gen_env={'__name__':'isolated_generator'}
exec(compile(GENERATOR,'generate_music_commands.py','exec'),gen_env)
core_commands=gen_env['generate_core_commands'](data)
commands={}
for row in intents.intents['R1MusicControl'].data:
 for sentence in row.sentence_texts:
  for text in sample_sentence(parse_sentence(sentence),expansion_rules=intents.expansion_rules,language='zh-cn'):
   key=text.replace(' ','');op=row.slots['operation']
   if key in commands and commands[key]!=op:raise AssertionError('Conflicting operation '+key)
   commands[key]=op
cases={
 '随机播放点音乐':'random','随机播放点儿音乐':'random','随便放点歌':'random','来点音乐':'random',
 '帮我随机播放点音乐':'random','给我放点歌听听':'random','播放一些歌曲':'random','放一首歌':'random',
 '随便来首歌':'random','听点音乐':'random','我想听点歌':'random','随机播放':'random',
 '播放':'resume','继续播放':'resume','接着放':'resume','播放音乐':'resume','打开卧室播放器':'resume',
 '暂停':'pause','先别放了':'pause','停止':'stop','下一首':'next','切换一下首':'next','上一首':'previous','播放第一首':'first',
}
sys.path.insert(0,INTENT_DIR)
import intent_rules
matcher_env={'re':re,'MUSIC_COMMANDS':core_commands,'INTENTS':intent_rules}
tree=ast.parse(GATEWAY)
for name in ('normalize_command','match_music_operation'):
 node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
 module=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(module)
 exec(compile(module,'actual_gateway_'+name,'exec'),matcher_env)
match=matcher_env['match_music_operation']
for text,op in commands.items():assert match(text)==op,(text,op,match(text))
rows=[]
for text,expected in cases.items():
 result=recognize(text,intents,language='zh-cn')
 actual=result.entities.get('operation').value if result and result.intent.name=='R1MusicControl' else None
 rows.append({'text':text,'expected':expected,'actual':actual,'intent':result.intent.name if result else None})
 if actual!=expected:raise AssertionError(rows[-1])
 assert match(text)==expected,text
for text in ('随机播放流行歌曲','随便放点国语精选','随机播放曾经是情侣','播放周杰伦的晴天'):
 result=recognize(text,intents,language='zh-cn')
 assert result and result.intent.name=='R1AppleMusicPlay',text
 rows.append({'text':text,'intent':result.intent.name,'query':result.entities['query'].value,'randomize':result.entities.get('randomize').value if 'randomize' in result.entities else False})
for text in ('放','打开','播放周杰伦的','不要随机播放音乐','别来点音乐','随机播放音乐是什么意思','怎么随机播放音乐','你能解释暂停的意思吗'):
 assert text not in commands,text
 # An incomplete named request is guarded by the gateway before this wildcard matcher.
 if text in ('放','打开','不要随机播放音乐','别来点音乐','怎么随机播放音乐','你能解释暂停的意思吗'):
  assert recognize(text,intents,language='zh-cn') is None,text
guard=package['script']['r1_apple_music_play']['sequence'][1]['if']
async def template_checks():
 hass=HomeAssistant('/tmp/r1-isolated-music-rules')
 for text,blocked in [('音乐是什么意思',True),('随机播放音乐是什么意思',True),('不要播放音乐',True),('是什么意思',True),('是啥意思',True),('曾经是情侣',False),('你好吗',False),('不要说话',False),('流行歌曲',False),('国语精选',False)]:
  actual=Template(guard,hass).async_render({'query_for_guard':text})
  assert bool(actual)==blocked,(text,actual,blocked)
 # Explicit shuffle goes into the existing MA play_media call; no extra shuffle request.
 script=package['script']['r1_apple_music_play']['sequence']
 choice=next(x['choose'] for x in script if 'choose' in x)[0]['sequence']
 call=next(x for x in choice if x.get('action')=='script.turn_on')
 play_args=call['data']['variables']['args']
 context={'is_style':True,'is_artist':False,'tracks':[{'uri':'apple_music://playlist/example'}]}
 assert Template(play_args,hass).async_render(dict(context,randomize=True))['shuffle'] is True
 assert 'shuffle' not in Template(play_args,hass).async_render(dict(context,randomize=False))
 # 专辑 ID 优先使用 Apple 映射，并逐个尝试 URL，不依赖列表第一项。
 album_template=call['data']['variables']['continuation_album']
 for track,expected in [
  ({'album':{'item_id':'123','provider':'apple_music'},'provider_mappings':[{'provider_domain':'apple_music','url':'https://music.apple.com/album/name/999'}]},123),
  ({'provider_mappings':[{'provider_domain':'other','url':'https://example.test/album/111'}, {'provider_domain':'apple_music','url':'https://music.apple.com/album/name/456?i=1'}]},456),
  ({'album':{'item_id':'789','provider':'library'},'provider_mappings':[{'provider_domain':'apple_music','url':'https://music.apple.com/album/654'}]},654),
  ({'album':None,'provider_mappings':[]},''),
  ({'album':{'provider':'apple_music'},'provider_mappings':[]},''),
 ]:
  actual=Template(album_template,hass).async_render({'is_style':False,'is_artist':False,'tracks':[track]})
  assert actual==expected,(track,actual,expected)
 assert Template(album_template,hass).async_render({'is_style':True,'is_artist':False,'tracks':[{}]})==''
 explicit_script=package_explicit['script']['r1_apple_music_play']['sequence']
 explicit_choice=next(x['choose'] for x in explicit_script if 'choose' in x)[0]['sequence']
 explicit_call=next(x for x in explicit_choice if x.get('action')=='script.turn_on')
 explicit_album=explicit_call['data']['variables']['continuation_album']
 track={'album':{'item_id':'333','provider':'apple_music--other'},'provider_mappings':[
  {'provider_domain':'apple_music','provider_instance':'apple_music--other','url':'https://music.apple.com/album/name/111'},
  {'provider_domain':'apple_music','provider_instance':'apple_music--selected','url':'https://music.apple.com/album/name/222'}]}
 assert Template(explicit_album,hass).async_render({'is_style':False,'is_artist':False,'tracks':[track]})==222
 track['provider_mappings']=[]
 assert Template(explicit_album,hass).async_render({'is_style':False,'is_artist':False,'tracks':[track]})==''
 delayed=package['script']['r1_music_delayed_request']['sequence']
 append=next(x['then'] for x in delayed if 'if' in x)[-1]['then'][0]
 media_template=append['data']['args']['media']
 def image(path,provider):return {'type':'thumb','path':path,'provider':provider,'remotely_accessible':False}
 first_images=[image('first-1','provider-a'),image('first-2','provider-b')]
 own_images=[image('own-1','provider-z'),image('own-2','provider-y')]
 album_image=image('album','album-provider')
 rows=[{'item_id':'1','provider':'apple_music','name':'one','uri':'apple_music://track/1','metadata':{'images':own_images},'provider_mappings':[{'provider_domain':'apple_music'}]},
       {'item_id':'2','provider':'apple_music','name':'two','album':{'item_id':'9','provider':'apple_music','image':album_image},'metadata':{'images':[]}},
       {'item_id':'3','provider':'apple_music','name':'three'},]
 result=Template(media_template,hass).async_render({'remaining':rows,'args':{'media':{'metadata':{'images':first_images}}}})
 assert result[0]['metadata']['images']==own_images and result[0]['provider_mappings']==rows[0]['provider_mappings']
 assert result[1]['metadata']['images']==[album_image] and result[1]['album']['image']==album_image
 assert result[2]['metadata']['images']==first_images and result[2]['album'] is None
 # 无效数字必须在 REST 调用前拒绝，不能被 int 默认转成静音。
 volume=package['script']['r1_volume_control']['sequence']
 percent_template=volume[0]['variables']['percent_text'];volume_guard=volume[1]['if']
 for percent,blocked in [(0,False),(30,False),(100,False),('30',False),('bad',True),('',True),(-1,True),(101,True),('三十',True),('30%',True),(None,True)]:
  value=Template(percent_template,hass).async_render({'percent':percent})
  actual=Template(volume_guard,hass).async_render({'volume_target':'music','operation':'set','percent_text':value})
  assert bool(actual)==blocked,(percent,actual,blocked)
 for target,operation,blocked in [('music','up',False),('speech','down',False),('other','set',True),('music','invalid',True)]:
  assert bool(Template(volume_guard,hass).async_render({'volume_target':target,'operation':operation,'percent_text':'30'}))==blocked
 slider=package_player['script']['r1_music_player_control']['sequence'][0]['choose'][0]['sequence'][0]['data']['percent']
 for value,expected in [(0,0),(.3,30),(1,100),('bad','invalid'),(-.1,'invalid'),(1.1,'invalid'),(None,'invalid')]:
  assert Template(slider,hass).async_render({'volume_level':value})==expected,(value,expected)
 for text,expected in [('音乐音量调到30%',30),('音乐音量调到百分之三十',30),('音乐音量调到0%',0),('音乐音量调到百分之一百',100)]:
  recognized=recognize(text,intents,language='zh-cn')
  assert recognized and recognized.intent.name=='R1VolumeControl',text
  assert recognized.entities['level'].value==expected,(text,recognized.entities)
 assert recognize('音乐音量调到百分之三百',intents,language='zh-cn') is None
asyncio.run(template_checks())
counts={op:sum(v==op for v in core_commands.values()) for op in sorted(set(core_commands.values()))}
print(json.dumps({'passed':True,'cases':rows,'control_aliases':len(core_commands),'normalized_full_variants_tested':len(commands),'operation_counts':counts,'negative_controls_blocked':True,'query_guard_cases':10,'album_id_cases':8,'artwork_cases':3,'volume_guard_cases':15,'slider_guard_cases':7,'spoken_volume_cases':5,'production_controls_sent':False},ensure_ascii=False))
'''.replace('EXPLICIT_PACKAGE',repr(explicit_package)).replace('PLAYER_PACKAGE',repr(player_package)).replace('SOURCE', repr(source)).replace('PACKAGE', repr(package)).replace('GENERATOR',repr(generator)).replace('GATEWAY',repr(gateway)).replace('INTENT_DIR',repr(str(root.parent/'gateway')))
exec(compile(code,'isolated-ha-music-rules','exec'))
