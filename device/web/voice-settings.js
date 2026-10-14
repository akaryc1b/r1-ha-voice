

let cvDeviceReady=false,cvGatewayReady=false,cvVolumesReady=false;
const cvVoiceFields=['asr_base_url','asr_model','asr_api_key','asr_timeout_seconds','asr_fallback_model',
 'asr_fallback_timeout_seconds','local_first','local_max_chars','local_asr_url','max_record_seconds',
 'tts_base_url','tts_model','tts_voice','tts_api_key','tts_timeout_seconds','tts_first_chunk_timeout_seconds','tts_speed','tts_gain'];
const cvMusicFields=['ma_url','ma_queue_id','ma_token'];
const cvNumbers=new Set(['asr_timeout_seconds','asr_fallback_timeout_seconds','local_max_chars','max_record_seconds',
 'tts_timeout_seconds','tts_first_chunk_timeout_seconds','tts_speed','tts_gain']);
const cvSecrets={asr_api_key:'asr',tts_api_key:'tts',ma_token:'ma'};
// 预置 ID 仅用于已知模型，网关仍接收原有 tts_voice 字段。
const cvTtsVoicePresets={
 'FunAudioLLM/CosyVoice2-0.5B':[
  ['anna','沉稳女声'],['bella','激情女声'],['claire','温柔女声'],['diana','欢快女声'],
  ['alex','沉稳男声'],['benjamin','低沉男声'],['charles','磁性男声'],['david','欢快男声']]
};
function cvSyncTtsVoices(){
 const model=document.getElementById('cv-gw-tts_model').value.trim();
 const input=document.getElementById('cv-gw-tts_voice');
 const choice=document.getElementById('cv-tts-voice-choice');
 const current=input.value.trim(),presets=cvTtsVoicePresets[model]||[];
 choice.replaceChildren();
 for(const [id,label] of presets){
  const option=document.createElement('option');option.value=model+':'+id;
  option.textContent=label+'（'+id+'）';choice.appendChild(option);
 }
 const custom=document.createElement('option');custom.value='__custom__';
 custom.textContent='自定义音色 ID';choice.appendChild(custom);
 choice.value=presets.some(([id])=>model+':'+id===current)?current:'__custom__';
 document.getElementById('cv-tts-voice-custom').hidden=choice.value!=='__custom__';
 document.getElementById('cv-tts-voice-help').textContent=presets.length
  ?'预置音色适用于支持该模型音色的接口；选择后点击“保存语音设置”生效。也可填写服务商的自定义音色 ID。'
  :'此模型的音色由服务商定义，请填写其提供的音色 ID。已有音色不会因切换模型而被覆盖。';
}
function cvTtsVoiceChanged(){
 const choice=document.getElementById('cv-tts-voice-choice');
 const custom=choice.value==='__custom__';
 document.getElementById('cv-tts-voice-custom').hidden=!custom;
 if(!custom)document.getElementById('cv-gw-tts_voice').value=choice.value;
 else document.getElementById('cv-gw-tts_voice').focus();
}
function cvUpdateReady(){
 let offline=document.getElementById('cv-asr').value==='local'&&document.getElementById('cv-tts').value==='original';
 document.getElementById('cv-save-voice').disabled=!(cvDeviceReady&&cvVolumesReady&&(cvGatewayReady||offline));
 document.getElementById('cv-save-music').disabled=!(cvGatewayReady&&cvVolumesReady);
 document.getElementById('cv-test-asr').disabled=!cvGatewayReady;
}
function cvToggleAsr(){document.getElementById('cv-asr-options').hidden=document.getElementById('cv-asr').value==='local';cvUpdateReady();}
function cvPost(url,value){return cvFetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});}
function cvApplyGateway(data,fields=[...cvVoiceFields,...cvMusicFields]){
 for(let key of fields){
  let el=document.getElementById('cv-gw-'+key);if(!el)continue;
  if(key in cvSecrets){
   el.value='';document.getElementById('cv-clear-'+key).checked=false;
   document.getElementById('cv-'+cvSecrets[key]+'-key-state').textContent=data[key+'_configured']?'（已配置）':'（未配置）';
  }else if(el.type==='checkbox'){el.checked=!!data[key];}
  else{el.value=data[key];}
 }
 if(fields.includes('tts_model')||fields.includes('tts_voice'))cvSyncTtsVoices();
 if(data.ma_url){
  try{let link=new URL(data.ma_url),gateway=new URL(document.getElementById('cv-gateway-url').value);
   if(['127.0.0.1','localhost'].includes(link.hostname))link.hostname=gateway.hostname;
   document.getElementById('cv-ma-link').href=link.href;
  }catch(e){}
 }
}
async function cvSaveGateway(fields){
 let patch={};
 for(let key of fields){
  let el=document.getElementById('cv-gw-'+key);
  if(!el.checkValidity())throw Error('配置格式无效：'+el.closest('.form-item').querySelector('label').textContent);
  patch[key]=el.type==='checkbox'?el.checked:cvNumbers.has(key)?Number(el.value):el.value.trim();
  if(key in cvSecrets)patch['clear_'+key]=document.getElementById('cv-clear-'+key).checked;
 }
 let result=await cvPost('/voice_gateway_config',patch);cvApplyGateway(result,fields);
 if(result.restart_required)cvStatus('配置已保存；监听地址修改需要重启 N1 语音网关');
 return result;
}
function cvConnectionValues(){
 return {gateway_url:document.getElementById('cv-gateway-url').value.trim(),
  local_server:document.getElementById('cv-local-server').value.trim(),
  session_timeout_seconds:Number(document.getElementById('cv-session-timeout').value)};
}
async function cvSaveConnection(b){
 b.disabled=true;try{await cvPost('/voice_connection',cvConnectionValues());await cvLoad();}
 catch(e){cvStatus(e.message);}finally{b.disabled=false;}
}
async function cvModels(b){
 b.disabled=true;cvStatus('正在读取已保存接口的模型列表…');
 try{let d=await cvFetch('/voice_models'),list=document.getElementById('cv-asr-models');list.replaceChildren();
  for(let id of [...new Set([...d.presets,...d.models])]){let option=document.createElement('option');option.value=id;list.appendChild(option);}
  cvStatus('已读取 '+d.models.length+' 个模型；请选择支持音频转写的模型，也可以手动填写');
 }catch(e){cvStatus(e.message);}finally{b.disabled=false;}
}
async function cvAsrTest(b){
 b.disabled=true;cvStatus('正在转写合成测试录音，不执行指令…');
 try{let d=await cvPost('/voice_asr_test',{});cvStatus('ASR 测试：'+d.text+'；耗时 '+d.seconds+' 秒（未执行指令）');}
 catch(e){cvStatus(e.message);}finally{b.disabled=false;}
}

const cvStatus=t=>document.getElementById('cv-status').textContent=t;
async function cvFetch(u,o){let r=await fetch(u,{cache:'no-store',...o});let d=await r.json();if(!r.ok||d.error)throw Error(d.error||'请求失败');return d;}
function cvToggleTts(){cvUpdateReady();let original=document.getElementById('cv-tts').value==='original';document.getElementById('cv-original-options').hidden=!original;document.getElementById('cv-cloud-options').hidden=original;}
function cvConsolidate(){
 let voice=document.getElementById('voice-select'),old=voice&&voice.closest('.card');
 if(old){for(let id of ['voice-select','tts-speed','tts-pitch']){let el=document.getElementById(id);if(el)document.getElementById('cv-original-options').appendChild(el.closest('.form-item'));}
 old.querySelectorAll('button').forEach(b=>{if(/^(setVoice|setTts)\(/.test(b.getAttribute('onclick')||''))b.remove();});let heading=old.querySelector('h3');if(heading)heading.textContent='唤醒与休眠';}
 let tab=document.getElementById('tab-music');
 if(tab){tab.insertAdjacentHTML('afterbegin',"<div class=\"card\" id=\"ma-music-card\">\n<h3>音乐播放与音源</h3>\n<p><strong>当前音乐源：Music Assistant · Apple Music</strong></p>\n<div class=\"form-item\"><label>语音播放通道</label><select id=\"cv-music-route\"><option value=\"direct\">播放控制直连 MA（快速通道）</option><option value=\"ha\">所有音乐指令交给 HA → MA</option></select></div>\n<p class=\"cv-help\" id=\"cv-music-path\"></p>\n<p class=\"cv-help\">快速通道直接处理播放第一首、上下首、暂停和继续；具体歌名、风格点歌使用现有 HA 点歌规则。电脑和温湿度仍由 HA 处理，普通问答调用 AI。</p>\n<div class=\"form-item\"><label>音乐音量 <span id=\"cv-music-value\"></span></label><input id=\"cv-music-volume\" type=\"range\" min=\"0\" max=\"100\" step=\"1\" oninput=\"cvVolumeLabel('music')\"></div>\n<details class=\"cv-advanced\"><summary>Music Assistant 连接</summary>\n<div class=\"form-item\"><label>网关访问的 MA 地址</label><input id=\"cv-gw-ma_url\" type=\"url\" autocomplete=\"off\"></div>\n<div class=\"form-item\"><label>MA 播放器 / 队列 ID</label><input id=\"cv-gw-ma_queue_id\" autocomplete=\"off\"></div>\n<div class=\"form-item\"><label>MA 访问令牌 <span id=\"cv-ma-key-state\"></span></label><input id=\"cv-gw-ma_token\" type=\"password\" autocomplete=\"new-password\" placeholder=\"留空保留已有令牌\"><label class=\"cv-help\"><input id=\"cv-clear-ma_token\" type=\"checkbox\">清除已保存令牌</label></div>\n<p class=\"cv-help\">HA 中的点歌脚本也需要使用相同队列。此处仅配置 R1 直连控制，不会自动改写 HA 自动化。</p></details>\n<button id=\"cv-save-music\" disabled onclick=\"cvSaveMusic(this)\">保存音乐设置</button>\n<a id=\"cv-ma-link\" class=\"cv-link\" href=\"http://192.168.1.88:8095/\" target=\"_blank\" rel=\"noopener\">管理 Apple Music 授权与音乐源</a>\n<a class=\"cv-link\" href=\"http://192.168.1.88:8123/r1-music/music\" target=\"_blank\" rel=\"noopener\">打开音乐播放器</a>\n<p id=\"cv-music-status\" role=\"status\"></p>\n<p class=\"cv-help\">音质由 MA 播放器设置决定，本页不改变音乐编码。旧音乐源不参与当前语音点歌。</p>\n</div>");let legacy=document.getElementById('api-url')?.closest('.card');if(legacy){let details=document.createElement('details');details.id='legacy-music-sources';let summary=document.createElement('summary');summary.textContent='旧音乐源配置（已停用，仅保留原值）';legacy.before(details);details.appendChild(summary);let fieldset=document.createElement('fieldset');fieldset.disabled=true;fieldset.style.cssText='border:0;margin:0;padding:0;opacity:.65';details.appendChild(fieldset);fieldset.appendChild(legacy);}}
}
function cvVolumeLabel(k){document.getElementById('cv-'+k+'-value').textContent=document.getElementById('cv-'+k+'-volume').value+'%';}
async function cvLoadVolume(k){let d=await cvFetch('/voice_volume?target='+k);document.getElementById('cv-'+k+'-volume').value=d.percent;cvVolumeLabel(k);}
async function cvLoad(){
 cvDeviceReady=false;cvGatewayReady=false;cvVolumesReady=false;cvUpdateReady();
 try{
  let d=await cvFetch('/voice_config');
  for(let k of ['asr','tts'])document.getElementById('cv-'+k).value=d[k];
  document.getElementById('cv-gateway-url').value=d.gateway_url;
  document.getElementById('cv-local-server').value=d.local_server;
  document.getElementById('cv-session-timeout').value=d.session_timeout_seconds;
  document.getElementById('cv-music-route').value=d.music_route||'ha';
  document.getElementById('cv-music-ack').checked=!!d.music_ack;
  document.getElementById('cv-listen-music-mute').checked=d.listen_music_mute!==false;
  document.getElementById('cv-asr-retry-once').checked=d.asr_retry_once!==false;
  document.getElementById('cv-ai-streaming').checked=d.ai_streaming!==false;
  document.getElementById('cv-ai-first-content').value=(d.ai_first_content_timeout_ms||4500)/1000;
  document.getElementById('cv-ai-first-reply').value=(d.ai_first_reply_timeout_ms||8000)/1000;
  document.getElementById('cv-ai-answer').value=(d.ai_answer_timeout_ms||30000)/1000;
  document.getElementById('cv-speech-stream').value=d.speech_stream||9;
  cvDeviceReady=true;cvToggleTts();cvToggleAsr();cvMusicPath();
  let warning='';
  try{let gateway=await cvFetch('/voice_gateway_config');cvApplyGateway(gateway);cvGatewayReady=true;}
  catch(e){warning=e.message+'；可展开“语音网关连接”修改地址后重连';}
  await Promise.all([cvLoadVolume('speech'),cvLoadVolume('music')]);cvVolumesReady=true;
  cvUpdateReady();cvStatus(warning||'当前设置已载入');
 }catch(e){cvStatus(e.message);}
}
async function cvSave(b){
 b.disabled=true;cvStatus('正在保存语音设置…');
 try{
  let ai={ai_first_content_timeout_ms:Number(document.getElementById('cv-ai-first-content').value)*1000,
   ai_first_reply_timeout_ms:Number(document.getElementById('cv-ai-first-reply').value)*1000,
   ai_answer_timeout_ms:Number(document.getElementById('cv-ai-answer').value)*1000};
  for(let id of ['cv-ai-first-content','cv-ai-first-reply','cv-ai-answer'])if(!document.getElementById(id).checkValidity())throw Error('AI 等待时间超出允许范围');
  if(ai.ai_first_content_timeout_ms>ai.ai_first_reply_timeout_ms||ai.ai_first_reply_timeout_ms>ai.ai_answer_timeout_ms)throw Error('AI 超时需满足正文等待 ≤ 首次回答 ≤ 整答');
  let required=Number(document.getElementById('cv-gw-max_record_seconds').value||18)+3;
  if(document.getElementById('cv-asr').value!=='local'){
   required+=Number(document.getElementById('cv-gw-asr_timeout_seconds').value);
   if(document.getElementById('cv-gw-asr_fallback_model').value.trim())required+=Number(document.getElementById('cv-gw-asr_fallback_timeout_seconds').value);
  }
  if(cvConnectionValues().session_timeout_seconds<required)throw Error('整轮识别超时至少需 '+Math.ceil(required)+' 秒，请展开“识别速度与分流”调整');
  if(document.getElementById('cv-tts').value==='original'){
   let speed=Number(document.getElementById('tts-speed').value),pitch=Number(document.getElementById('tts-pitch').value);
   if(!Number.isInteger(speed)||!Number.isInteger(pitch)||speed<0||speed>100||pitch<0||pitch>100)throw Error('语速和音调需为 0～100 的整数');
   for(let u of ['/set_voice?speaker='+encodeURIComponent(document.getElementById('voice-select').value),'/set_tts?'+new URLSearchParams({speed,pitch})]){
    let d=await cvFetch(u);if(d.code!==200)throw Error('设备播报设置未能保存');
   }
  }
  if(cvGatewayReady)await cvSaveGateway(cvVoiceFields);
  await cvPost('/voice_config',{asr:document.getElementById('cv-asr').value,tts:document.getElementById('cv-tts').value,
   music_ack:document.getElementById('cv-music-ack').checked,
   listen_music_mute:document.getElementById('cv-listen-music-mute').checked,
    asr_retry_once:document.getElementById('cv-asr-retry-once').checked,
    ai_streaming:document.getElementById('cv-ai-streaming').checked,
   speech_stream:Number(document.getElementById('cv-speech-stream').value),...ai,...cvConnectionValues()});
  await cvFetch('/voice_volume?target=speech&operation=set&percent='+document.getElementById('cv-speech-volume').value);
  await cvLoadVolume('speech');cvStatus('已保存，下次识别和播报生效');
 }catch(e){cvStatus(e.message);}finally{cvUpdateReady();}
}
function cvMusicPath(){let direct=document.getElementById('cv-music-route').value==='direct';document.getElementById('cv-music-path').textContent=direct?'播放控制：R1 → MA；点歌：R1 → HA → MA':'播放与点歌：R1 → HA → MA';}
async function cvSaveMusic(b){b.disabled=true;try{await cvSaveGateway(cvMusicFields);await cvFetch('/music_config?'+new URLSearchParams({action:'save',route:document.getElementById('cv-music-route').value}));await cvFetch('/voice_volume?target=music&operation=set&percent='+document.getElementById('cv-music-volume').value);await cvLoadVolume('music');cvMusicPath();document.getElementById('cv-music-status').textContent='音乐设置已保存';}catch(e){document.getElementById('cv-music-status').textContent=e.message;}finally{b.disabled=false;}}
async function cvHealth(){cvStatus('正在检查网关…');try{let d=await cvFetch('/voice_health');cvStatus(d.ready?'N1 语音网关已连接；云服务效果请用播报或真实语音测试':'网关未就绪');}catch(e){cvStatus(e.message);}}
async function cvTest(b){b.disabled=true;try{await cvFetch('/voice_test');cvStatus('播报测试已发送，请留意音箱声音');}catch(e){cvStatus(e.message);}finally{b.disabled=false;}}
document.getElementById('cv-gw-tts_model').addEventListener('input',cvSyncTtsVoices);
cvSyncTtsVoices();
cvConsolidate();document.getElementById('cv-asr').addEventListener('change',cvToggleAsr);document.getElementById('cv-music-route').addEventListener('change',cvMusicPath);cvLoad();
