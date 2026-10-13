"""Validate HA music grammar and gateway normalization without service calls."""
import argparse
from pathlib import Path
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument("--sentences",type=Path,default=root/"custom_sentences/zh-cn/r1_music.yaml")
parser.add_argument("--package",type=Path,default=root/"packages/r1_apple_music.yaml")
parser.add_argument("--gateway",type=Path,default=root.parent/"gateway/voice_gateway.py")
args=parser.parse_args()
source=args.sentences.read_text(encoding="utf-8")
package=args.package.read_text(encoding="utf-8")
generator=(root/"generate_music_commands.py").read_text(encoding="utf-8")
gateway=args.gateway.read_text(encoding="utf-8")
code = '''import json,re,asyncio,yaml,traceback,ast
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
matcher_env={'re':re,'MUSIC_COMMANDS':core_commands}
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
asyncio.run(template_checks())
counts={op:sum(v==op for v in core_commands.values()) for op in sorted(set(core_commands.values()))}
print(json.dumps({'passed':True,'cases':rows,'control_aliases':len(core_commands),'normalized_full_variants_tested':len(commands),'operation_counts':counts,'negative_controls_blocked':True,'query_guard_cases':10,'production_controls_sent':False},ensure_ascii=False))
'''.replace('SOURCE', repr(source)).replace('PACKAGE', repr(package)).replace('GENERATOR',repr(generator)).replace('GATEWAY',repr(gateway))
exec(compile(code,'isolated-ha-music-rules','exec'))
