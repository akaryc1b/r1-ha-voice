"""Browser-only diagnostic UI tests. All endpoints are mocked; no device calls."""
import argparse
import hashlib
import json
import re
import sys
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--firmware", type=Path, default=ROOT / "firmware" if (ROOT / "firmware").is_dir() else ROOT)
parser.add_argument("--playwright-path", type=Path)
parser.add_argument("--browser", type=Path)
parser.add_argument("--report", type=Path)
parser.add_argument("--screenshot", type=Path)
args = parser.parse_args()
if args.playwright_path:
    sys.path.insert(0, str(args.playwright_path))
from playwright.sync_api import sync_playwright, expect

web = args.firmware / "web"
js = (web / "voice-logs.js").read_text(encoding="utf-8")
css = (web / "voice-logs.css").read_text(encoding="utf-8")
# Relevant styles from the existing navigation shell, with no device configuration.
base_style = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:20px;background:#f0f2f5;color:#333;line-height:1.6;}
.nav-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px;background:white;padding:12px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.08);}
.nav-btn{flex:1;min-width:100px;padding:10px 5px;font-size:13px;background:#f0f2f5;color:#666;border-radius:8px;border:none;cursor:pointer;font-weight:bold;transition:all .3s;text-align:center;}
.nav-btn.active{background:#1890ff;color:white;}.tab-content{display:none;}.tab-content.active{display:block;}
.card{background:white;padding:20px;margin-bottom:20px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.08);}
h3{margin-top:0;color:#1890ff;border-bottom:1px solid #eee;padding-bottom:10px;margin-bottom:15px;}
input[type=text],input[type=number],input[type=password],select{width:100%;padding:12px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box;background:#f9f9f9;transition:border .3s;}
button{padding:12px 24px;cursor:pointer;border-radius:8px;border:none;background:#1890ff;color:white;font-weight:bold;transition:all .3s;width:100%;margin-top:10px;font-size:15px;}
button:hover{opacity:.9;transform:translateY(-1px);}button:active{transform:translateY(0);}
"""
tabs = [("r1", "音响"), ("music", "音乐"), ("weather", "天气"), ("ha", "HA"), ("ai", "AI"), ("alarm", "闹钟")]
html = "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><style>" + base_style + css + "</style></head><body><div class='nav-bar'>"
for name, label in tabs:
    html += f"<button class='nav-btn' id='nav-{name}' onclick=\"showTab('{name}')\">{label}</button>"
html += "</div>"
for name, _ in tabs:
    active = " active" if name == "r1" else ""
    html += f"<div class='tab-content{active}' id='tab-{name}'><input id='original-{name}' value='unchanged'></div>"
html += """<script>function showTab(id) {
 document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
 document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
 document.getElementById('tab-'+id).classList.add('active');
 document.getElementById('nav-'+id).classList.add('active');
}</script><script>""" + js + "</script></body></html>"
mock = r"""
window.testAPI = {calls:[], active:0,maxActive:0,delay:0,mode:'ok',configMode:'ok',
 config:{enabled:false,level:'INFO'},entries:[{timestamp:1791993600000,level:'INFO',source:'gateway',stage:'transcription',turn:'t1',
 fields:{text:'播放点音乐',route:'HA_DIRECT',operation:'random',status:200,duration_ms:12,accepted:true,executed:false}}]};
window.fetch = function(path, options={}) {
 const api=window.testAPI, endpoint=String(path).split('?')[0];
 api.calls.push({path:String(path),method:options.method||'GET',body:options.body?JSON.parse(options.body):null});
 api.active++; api.maxActive=Math.max(api.maxActive,api.active);
 return new Promise((resolve,reject)=> {
  let done=false;
  const finish=()=> {
   if(done)return;done=true;api.active--;
   let data={},http=200,nonjson=false;
   if(endpoint==='/voice_logs_config') {
    if(api.configMode==='bad')data={error:'configuration unavailable'};
    else { if(options.method==='POST')api.config=JSON.parse(options.body);data={...api.config,generation:2}; }
   } else if(endpoint==='/voice_logs_clear') {api.entries=[];data={ok:true,generation:3};}
   else if(endpoint==='/voice_logs') {
    if(api.mode==='http'){data={error:'service unavailable'};http=503;}
    else if(api.mode==='nonjson')nonjson=true;
    else if(api.mode==='malformed')data={records:[]};
    else if(api.mode==='badentry')data={entries:[null]};
    else data={entries:api.entries,enabled:true,level:'ERROR'};
   } else throw Error('Unexpected endpoint: '+path);
   resolve({ok:http>=200&&http<300,status:http,json:()=>nonjson?Promise.reject(Error('not JSON')):Promise.resolve(data)});
  };
  if(options.signal)options.signal.addEventListener('abort',()=> {
   if(done)return;done=true;api.active--;const e=Error('aborted');e.name='AbortError';reject(e);
  });
  if(api.delay)setTimeout(finish,api.delay);else finish();
 });
};
"""
checks=[]
def passed(name):
    checks.append(name)

with sync_playwright() as p:
    launch = {'headless':True, 'args':['--no-proxy-server']}
    if args.browser:
        launch['executable_path'] = str(args.browser)
    browser = p.chromium.launch(**launch)
    page = browser.new_page(viewport={"width":1280,"height":900})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script(mock)
    page.route('http://logs.test/**',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
    page.goto('http://logs.test/')
    assert not errors,errors
    assert page.locator('#nav-logs').count()==1,page.content()[-1000:]
    page.clock.install()
    page.clock.fast_forward(10000)
    assert page.evaluate('testAPI.calls.length')==0
    passed('inactive page makes no API requests')
    page.locator('#original-r1').fill('preserved-user-setting')
    page.locator('#nav-logs').click()
    expect(page.locator('#vl-log-status')).to_contain_text('最近 1 条')
    expect(page.locator('#vl-enabled')).not_to_be_checked()
    expect(page.locator('#vl-level')).to_have_value('INFO')
    expect(page.locator('#vl-save')).to_be_disabled()
    assert page.evaluate('testAPI.calls.map(x=>x.path)')==['/voice_logs_config','/voice_logs?limit=50']
    passed('initial configuration and latest entries load without writes')
    page.locator('#vl-enabled').check()
    page.locator('#vl-level').select_option('DEBUG')
    page.locator('#vl-save').click()
    expect(page.locator('#vl-config-status')).to_contain_text('已保存')
    assert page.evaluate('testAPI.calls.at(-1)')=={'path':'/voice_logs_config','method':'POST','body':{'enabled':True,'level':'DEBUG'}}
    passed('only explicit save writes enabled and storage level')
    page.locator('#vl-level').select_option('WARN')
    page.locator('#vl-refresh').click()
    expect(page.locator('#vl-log-status')).to_contain_text('最近 1 条')
    expect(page.locator('#vl-level')).to_have_value('WARN')
    expect(page.locator('#vl-config-status')).to_contain_text('尚未保存')
    passed('log refresh cannot overwrite unsaved storage level')
    before=page.evaluate('testAPI.calls.length')
    page.clock.fast_forward(5100)
    expect(page.locator('#tab-logs')).to_have_attribute('aria-busy','false')
    assert page.evaluate('testAPI.calls.length')==before+1
    passed('visible page refreshes every five seconds')
    page.locator('#vl-auto').uncheck()
    before=page.evaluate('testAPI.calls.length')
    page.clock.fast_forward(12000)
    assert page.evaluate('testAPI.calls.length')==before
    page.locator('#vl-refresh').click()
    expect(page.locator('#tab-logs')).to_have_attribute('aria-busy','false')
    assert page.evaluate('testAPI.calls.length')==before+1
    passed('automatic refresh can be disabled while manual refresh works')
    page.locator('#vl-auto').check()
    page.locator('.vl-heading button').click()
    expect(page.locator('#tab-r1')).to_have_class('tab-content active')
    expect(page.locator('#original-r1')).to_have_value('preserved-user-setting')
    before=page.evaluate('testAPI.calls.length')
    page.clock.fast_forward(11000)
    assert page.evaluate('testAPI.calls.length')==before
    passed('return restores original page and values; inactive refresh stops')
    page.locator('#nav-logs').click()
    expect(page.locator('#tab-logs')).to_have_attribute('aria-busy','false')
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
    before=page.evaluate('testAPI.calls.length')
    page.clock.fast_forward(11000)
    assert page.evaluate('testAPI.calls.length')==before
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator('#tab-logs')).to_have_attribute('aria-busy','false')
    passed('document visibility gates background refresh')
    page.evaluate('testAPI.delay=7000')
    page.locator('#vl-refresh').click()
    expect(page.locator('#vl-save')).to_be_disabled()
    page.clock.fast_forward(5100)
    assert page.evaluate('testAPI.active')==1
    page.clock.fast_forward(2000)
    expect(page.locator('#tab-logs')).to_have_attribute('aria-busy','false')
    assert page.evaluate('testAPI.maxActive')==1
    page.evaluate('testAPI.delay=0')
    passed('single request in flight including overlapping refresh intervals')
    page.locator('#vl-auto').uncheck()
    for mode,expected in [('http','读取日志失败'),('nonjson','非 JSON'),('malformed','entries 数组'),('badentry','条目返回格式')]:
        page.evaluate('(mode)=>testAPI.mode=mode',mode)
        page.locator('#vl-refresh').click()
        expect(page.locator('#vl-log-status')).to_contain_text(expected)
        expect(page.locator('#vl-log-status')).to_contain_text('仍显示')
        expect(page.locator('.vl-entry')).to_have_count(1)
    passed('HTTP, non-JSON and malformed data retain last records with explicit error')
    page.evaluate('testAPI.mode="ok";testAPI.delay=9000')
    page.locator('#vl-refresh').click()
    page.clock.fast_forward(8100)
    expect(page.locator('#vl-log-status')).to_contain_text('请求超时')
    expect(page.locator('.vl-entry')).to_have_count(1)
    page.clock.fast_forward(1000)
    page.evaluate('testAPI.delay=0')
    passed('request timeout preserves records and releases request lock')
    page.evaluate("""testAPI.entries=[{timestamp:1791993600000,level:'WARN',source:'test',stage:'result',fields:{
     text:'<img src=x onerror="window.injected=true"> https://example.test/private api_key=FAKE_SECRET_A',
     response:'{"api_key":"FAKE_SECRET_B"} Bearer FAKE_SECRET_C sk-FAKE_SECRET_D',
     request_id:'eyJFAKE.e30.FAKEFAKE',unknown:'FAKE_UNKNOWN',api_key:'FAKE_KEY_FIELD',executed:false}}]""")
    page.locator('#vl-refresh').click()
    expect(page.locator('#vl-log-status')).to_contain_text('最近 1 条')
    shown=page.locator('#vl-list').inner_text()
    for secret in ['FAKE_SECRET_A','FAKE_SECRET_B','FAKE_SECRET_C','FAKE_SECRET_D','FAKE_UNKNOWN','FAKE_KEY_FIELD','eyJFAKE.e30.FAKEFAKE','example.test']:
        assert secret not in shown,secret
    assert '<img' in shown and '否' in shown
    assert page.locator('#vl-list img').count()==0 and not page.evaluate('!!window.injected')
    passed('text-only rendering, URL and credential masking, unknown field rejection')
    before=page.evaluate('testAPI.calls.filter(x=>x.path==="/voice_logs_clear").length')
    page.once('dialog',lambda dialog:dialog.dismiss())
    page.locator('#vl-clear').click()
    assert page.evaluate('testAPI.calls.filter(x=>x.path==="/voice_logs_clear").length')==before
    expect(page.locator('.vl-entry')).to_have_count(1)
    page.once('dialog',lambda dialog:dialog.accept())
    page.locator('#vl-clear').click()
    expect(page.locator('#vl-log-status')).to_have_text('诊断日志已清空。')
    assert page.evaluate('testAPI.calls.at(-1)')=={'path':'/voice_logs_clear','method':'POST','body':{}}
    expect(page.locator('.vl-empty')).to_be_visible()
    passed('clear cancellation has no write; confirmed clear targets diagnostic endpoint only')
    page.evaluate("testAPI.entries=[{timestamp:1,level:'ERROR',fields:{text:'x'.repeat(3000)}}]")
    page.locator('#vl-refresh').click()
    expect(page.locator('.vl-entry')).to_have_count(1)
    page.set_viewport_size({'width':375,'height':812})
    if args.screenshot:
        page.screenshot(path=str(args.screenshot),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),page.evaluate('[document.documentElement.scrollWidth,innerWidth]')
    passed('375px mobile viewport wraps long entries without horizontal overflow')
    page.evaluate('testAPI.configMode="bad"')
    page.reload()
    page.evaluate('testAPI.configMode="bad"')
    page.locator('#nav-logs').click()
    expect(page.locator('#vl-config-status')).to_contain_text('读取失败')
    expect(page.locator('#vl-save')).to_be_disabled()
    page.evaluate('testAPI.configMode="ok"')
    page.locator('#vl-refresh').click()
    expect(page.locator('#vl-config-status')).to_contain_text('已关闭记录')
    expect(page.locator('#vl-enabled')).to_be_enabled()
    passed('configuration read failure disables writes and manual refresh recovers')
    assert not errors,errors
    passed('no uncaught browser errors')
    browser.close()

with tempfile.TemporaryDirectory(prefix='r1-logs-web-') as tmp:
    fixture=Path(tmp)
    (fixture/'web').mkdir()
    (fixture/'src/r1/local/asr').mkdir(parents=True)
    for name in ['voice-card.html','voice-settings.js','voice-settings.css','voice-logs.js','voice-logs.css']:
        (fixture/'web'/name).write_bytes((web/name).read_bytes())
    (fixture/'generate_web.py').write_bytes((args.firmware/'generate_web.py').read_bytes())
    subprocess.run([sys.executable,str(fixture/'generate_web.py')],check=True)
    java=(fixture/'src/r1/local/asr/VoiceConfigPage.java').read_text(encoding='utf-8')
    script=json.loads(re.search(r'public static String script\(\) \{ return (.*); \}',java).group(1))
    assert script.count('<script>')==2 and '语音诊断日志' in script
    script_bytes=len(script.encode('utf-8'))
    assert script_bytes<60000
    passed('temporary Java generator includes both modules below constant byte limit')

report={'scope':'mock browser and temporary generated Java only; no live endpoint writes, no APK build or install',
 'passed':len(checks),'checks':checks,'script_utf8_bytes':script_bytes,
 'source_sha256':{name:hashlib.sha256((web/name).read_bytes()).hexdigest() for name in ['voice-logs.js','voice-logs.css']}}
if args.report:
    args.report.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps(report,ensure_ascii=False,indent=2))
