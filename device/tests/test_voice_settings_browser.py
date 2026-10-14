"""模拟配置端点验证真实语音页面；不读取设备、密钥或运行时 HTML。"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'gateway'))
from gateway_config import DEFAULTS, SECRETS

parser = argparse.ArgumentParser()
parser.add_argument('--browser', type=Path)
parser.add_argument('--report', type=Path)
args = parser.parse_args()
gateway = {k: value for k, value in DEFAULTS.items() if k not in SECRETS}
gateway.update({key + '_configured': False for key in SECRETS})
voice = {'asr': 'gateway', 'tts': 'cosy', 'gateway_url': 'http://gateway.test:16068',
         'local_server': 'ws://gateway.test:16066', 'session_timeout_seconds': 45,
         'music_route': 'direct', 'speech_stream': 2, 'channels': 2}
card = (ROOT / 'device/web/voice-card.html').read_text(encoding='utf-8')
script = (ROOT / 'device/web/voice-settings.js').read_text(encoding='utf-8')
with sync_playwright() as playwright:
    options = {'headless': True}
    if args.browser:
        options['executable_path'] = str(args.browser)
    browser = playwright.chromium.launch(**options)
    page = browser.new_page()
    page.set_content(card + '<div id="tab-music"></div>')
    page.evaluate('''data => {
      window.saved=[];window.mockGateway=data.gateway;window.mockVoice=data.voice;
      window.fetch=async (path,options={}) => {
        let value;
        if(options.method==='POST') {
          const patch=JSON.parse(options.body);window.saved.push({path,patch});
          value=path==='/voice_gateway_config'?Object.assign(window.mockGateway,patch):Object.assign(window.mockVoice,patch);
        } else if(path==='/voice_gateway_config')value=window.mockGateway;
        else if(path==='/voice_config')value=window.mockVoice;
        else if(path.startsWith('/voice_volume'))value={percent:40};
        else value={code:200};
        return {ok:true,json:async()=>value};
      };
    }''', {'gateway': gateway, 'voice': voice})
    page.add_script_tag(content=script)
    page.wait_for_function('cvGatewayReady && cvVolumesReady')
    result = page.evaluate('''async () => {
      const get=id=>document.getElementById(id);
      if(get('cv-channels').value!=='2'||get('cv-channel-mix').value!=='left')throw Error('existing microphone selection');
      get('cv-channel-mix').value='mix';
      await cvSave(get('cv-save-voice'));
      const audioPatch=window.saved.filter(row=>row.path==='/voice_config').at(-1).patch;
      if(audioPatch.channels!==2||audioPatch.asr_channel_mix!=='mix')throw Error('microphone selection saved');
      const choice=get('cv-tts-voice-choice'),voice=get('cv-gw-tts_voice');
      if(choice.options.length!==9||choice.value!=='FunAudioLLM/CosyVoice2-0.5B:anna')throw Error('preset load');
      choice.value='FunAudioLLM/CosyVoice2-0.5B:claire';cvTtsVoiceChanged();
      if(voice.value!==choice.value||!get('cv-tts-voice-custom').hidden)throw Error('preset selection');
      voice.value='speech:my-own-voice';cvSyncTtsVoices();
      if(choice.value!=='__custom__'||get('cv-tts-voice-custom').hidden)throw Error('custom retention');
      get('cv-gw-tts_model').value='other/model';cvSyncTtsVoices();
      if(choice.options.length!==1||voice.value!=='speech:my-own-voice')throw Error('unknown model');
      get('cv-gw-default_random_query').value='爵士';
      get('cv-gw-default_random_providers').value='apple_music, local';
      await cvSaveMusic(get('cv-save-music'));
      let patch=window.saved.filter(row=>row.path==='/voice_gateway_config').at(-1).patch;
      if(patch.default_random_query!=='爵士'||JSON.stringify(patch.default_random_providers)!=='["apple_music","local"]')throw Error('random saved');
      get('cv-gw-default_random_providers').value='';
      await cvSaveMusic(get('cv-save-music'));
      patch=window.saved.filter(row=>row.path==='/voice_gateway_config').at(-1).patch;
      if(patch.default_random_providers.length!==0)throw Error('all-provider setting');
      return {passed:true,scope:'mock browser only',tts_presets:8,custom_retained:true,random_defaults_saved:true};
    }''')
    browser.close()
if args.report:
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
