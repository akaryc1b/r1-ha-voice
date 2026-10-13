(function () {
 'use strict';
 const nav = document.querySelector('.nav-bar');
 const firstTab = document.getElementById('tab-r1');
 if (!nav || !firstTab || document.getElementById('tab-logs')) return;
 const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'];
 const state = {busy:false, loaded:false, enabled:false, level:'INFO', dirty:false, visible:false,
  timer:null, previous:'r1', lastRead:'', entries:[]};
 function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
 }
 function safe(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return '（非文本内容已省略）';
  return String(value)
   .replace(/(?:https?|wss?):\/\/[^\s<>"'，。；]+/gi, '[地址已隐藏]')
   .replace(/\bBearer\s+[^\s,;"']+/gi, 'Bearer [密钥已隐藏]')
   .replace(/((?:api[_ -]?key|authorization|access[_ -]?token|token|password|secret|密钥|密码)["']?\s*[=:：]\s*)["']?[^\s,;，；"']+/gi, '$1[密钥已隐藏]')
   .replace(/\b(?:sk|pk)-[A-Za-z0-9_-]{8,}/g, '[密钥已隐藏]')
   .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[令牌已隐藏]')
   .slice(0, 2500);
 }
 const panel = el('div', 'tab-content'); panel.id = 'tab-logs';
 const card = el('section', 'card vl-card'); panel.appendChild(card);
 const heading = el('div', 'vl-heading');
 heading.appendChild(el('h3', '', '语音诊断日志'));
 const back = el('button', 'vl-secondary', '返回原设置页'); back.type = 'button';
 back.addEventListener('click', function () { window.showTab(state.previous); });
 heading.appendChild(back); card.appendChild(heading);
 card.appendChild(el('p', 'vl-help', '只保存开启后的记录；旧记录达到上限自动轮转；不保存录音和密钥。'));
 const config = el('div', 'vl-config'); card.appendChild(config);
 const enabledLabel = el('label', 'vl-toggle');
 const enabled = el('input'); enabled.id = 'vl-enabled'; enabled.type = 'checkbox'; enabled.disabled = true;
 enabledLabel.appendChild(enabled); enabledLabel.appendChild(el('span', '', '保存诊断日志')); config.appendChild(enabledLabel);
 const levelLabel = el('label', 'vl-level'); levelLabel.appendChild(el('span', '', '保存等级'));
 const level = el('select'); level.id = 'vl-level'; level.disabled = true;
 levels.forEach(function (name) { const option = el('option', '', name); option.value = name; level.appendChild(option); });
 level.value = 'INFO'; levelLabel.appendChild(level); config.appendChild(levelLabel);
 const save = el('button', '', '保存日志设置'); save.id = 'vl-save'; save.type = 'button'; save.disabled = true;
 config.appendChild(save);
 const configStatus = el('p', 'vl-status', '默认关闭记录，保存等级 INFO；打开日志页后读取实际设置。');
 configStatus.id = 'vl-config-status'; configStatus.setAttribute('role', 'status'); configStatus.setAttribute('aria-live', 'polite'); card.appendChild(configStatus);
 const tools = el('div', 'vl-tools'); card.appendChild(tools);
 const autoLabel = el('label', 'vl-toggle');
 const auto = el('input'); auto.id = 'vl-auto'; auto.type = 'checkbox'; auto.checked = true;
 autoLabel.appendChild(auto); autoLabel.appendChild(el('span', '', '每5秒刷新')); tools.appendChild(autoLabel);
 const refresh = el('button', 'vl-secondary', '刷新'); refresh.id = 'vl-refresh'; refresh.type = 'button'; tools.appendChild(refresh);
 const clear = el('button', 'vl-danger', '清空诊断日志'); clear.id = 'vl-clear'; clear.type = 'button'; clear.disabled = true; tools.appendChild(clear);
 const logStatus = el('p', 'vl-status', '打开日志页后读取最近50条记录。'); logStatus.id = 'vl-log-status';
 logStatus.setAttribute('role', 'status'); logStatus.setAttribute('aria-live', 'polite'); card.appendChild(logStatus);
 const list = el('div', 'vl-list'); list.id = 'vl-list'; card.appendChild(list);
 firstTab.parentNode.appendChild(panel);
 const navButton = el('button', 'nav-btn', '日志'); navButton.id = 'nav-logs'; navButton.type = 'button';
 navButton.setAttribute('aria-controls', 'tab-logs');
 navButton.addEventListener('click', function () {
  const current = document.querySelector('.tab-content.active');
  if (current && current !== panel) state.previous = current.id.replace(/^tab-/, '');
  window.showTab('logs');
 });
 nav.appendChild(navButton);
 function status(node, message, error) { node.textContent = safe(message); node.classList.toggle('vl-error', !!error); }
 function updateButtons() {
  enabled.disabled = level.disabled = state.busy || !state.loaded;
  save.disabled = state.busy || !state.loaded || !state.dirty;
  refresh.disabled = state.busy;
  clear.disabled = state.busy || !state.loaded;
 }
 function busy(value) { state.busy = value; panel.setAttribute('aria-busy', String(value)); updateButtons(); }
 async function request(path, payload) {
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timeout = controller ? setTimeout(function () { controller.abort(); }, 8000) : null;
  const options = {cache:'no-store'};
  if (controller) options.signal = controller.signal;
  if (payload !== undefined) {
   options.method = 'POST'; options.headers = {'Content-Type':'application/json'}; options.body = JSON.stringify(payload);
  }
  try {
   const response = await fetch(path, options);
   let data;
   try { data = await response.json(); }
   catch (e) { throw Error('接口返回非 JSON，HTTP ' + response.status); }
   if (!response.ok || (data && data.error)) throw Error(safe(data && data.error) || ('接口请求失败，HTTP ' + response.status));
   if (!data || typeof data !== 'object') throw Error('接口返回格式不正确');
   return data;
  } catch (e) {
   if (e.name === 'AbortError') throw Error('请求超时，请检查设备与网关连接');
   throw Error(safe(e.message) || '网络请求失败');
  } finally { if (timeout !== null) clearTimeout(timeout); }
 }
 function applyConfig(data) {
  if (typeof data.enabled !== 'boolean' || levels.indexOf(data.level) < 0) throw Error('日志设置返回格式不正确');
  state.enabled = data.enabled; state.level = data.level; state.loaded = true; state.dirty = false;
  enabled.checked = data.enabled; level.value = data.level;
 }
 async function loadConfig() {
  if (state.busy) return;
  busy(true); status(configStatus, '正在读取日志设置…');
  try {
   applyConfig(await request('/voice_logs_config'));
   status(configStatus, (state.enabled ? '已开启记录' : '已关闭记录') + ' · 保存等级 ' + state.level);
  } catch (e) { state.loaded = false; status(configStatus, '日志设置读取失败：' + e.message + '；点击“刷新”重试。', true); }
  finally { busy(false); }
 }
 async function saveConfig() {
  if (state.busy || !state.loaded) return;
  const patch = {enabled:enabled.checked, level:level.value};
  busy(true); status(configStatus, '正在保存日志设置…');
  try {
   applyConfig(await request('/voice_logs_config', patch));
   status(configStatus, '已保存：' + (state.enabled ? '开启记录' : '关闭记录') + ' · ' + state.level);
  } catch (e) { status(configStatus, '保存失败：' + e.message + '；当前实际设置未能确认。', true); }
  finally { busy(false); }
 }
 function timestamp(value) {
  const raw = typeof value === 'number' ? (value < 100000000000 ? value * 1000 : value) : value;
  const date = new Date(raw);
  return {value:isNaN(date.getTime()) ? 0 : date.getTime(), label:isNaN(date.getTime()) ? safe(value) : date.toLocaleString('zh-CN', {hour12:false})};
 }
 const fields = [
  ['text','转写'], ['route','分流'], ['operation','操作'], ['response','回复'], ['model','模型'], ['backend','识别通道'],
  ['status','接口状态'], ['duration_ms','耗时'], ['audio_seconds','音频时长'], ['accepted','已采用'],
  ['executed','已执行'], ['error_kind','错误类型'], ['request_id','请求ID']
 ];
 function render(entries) {
  if (entries.some(function (entry) { return !entry || typeof entry !== 'object' || Array.isArray(entry); })) {
   throw Error('日志条目返回格式不正确');
  }
  while (list.firstChild) list.removeChild(list.firstChild);
  if (!entries.length) { list.appendChild(el('p', 'vl-empty', '暂无诊断记录。需要记录时，请先开启并保存日志设置。')); return; }
  entries.slice().sort(function (a, b) { return timestamp(b.timestamp).value - timestamp(a.timestamp).value; }).forEach(function (entry) {
   if (!entry || typeof entry !== 'object') return;
   const name = levels.indexOf(entry.level) >= 0 ? entry.level : 'INFO';
   const item = el('article', 'vl-entry vl-' + name.toLowerCase());
   const header = el('div', 'vl-entry-head');
   header.appendChild(el('span', 'vl-badge', name));
   header.appendChild(el('strong', 'vl-stage', safe(entry.stage || '事件')));
   header.appendChild(el('time', 'vl-time', timestamp(entry.timestamp).label)); item.appendChild(header);
   const meta = [safe(entry.source)].filter(Boolean);
   if (entry.turn !== undefined && entry.turn !== null && entry.turn !== '') meta.push('轮次 ' + safe(entry.turn));
   if (meta.length) item.appendChild(el('p', 'vl-meta', meta.join(' · ')));
   const detail = el('dl', 'vl-fields'); const values = entry.fields && typeof entry.fields === 'object' ? entry.fields : {};
   fields.forEach(function (field) {
    const value = values[field[0]];
    if (value === undefined || value === null || value === '') return;
    let text = typeof value === 'boolean' ? (value ? '是' : '否') : safe(value);
    if (field[0] === 'duration_ms' && typeof value === 'number') text = value + ' ms';
    if (field[0] === 'audio_seconds' && typeof value === 'number') text = value + ' 秒';
    detail.appendChild(el('dt', '', field[1])); detail.appendChild(el('dd', '', text));
   });
   item.appendChild(detail); list.appendChild(item);
  });
 }
 async function readLogs() {
  if (state.busy || !isVisible()) return;
  busy(true); status(logStatus, '正在读取诊断日志…');
  try {
   const data = await request('/voice_logs?limit=50');
   if (!Array.isArray(data.entries)) throw Error('日志接口没有返回 entries 数组');
   state.entries = data.entries; render(data.entries); state.lastRead = new Date().toLocaleTimeString('zh-CN', {hour12:false});
   status(logStatus, '最近 ' + data.entries.length + ' 条 · 更新于 ' + state.lastRead);
  } catch (e) {
   status(logStatus, '读取日志失败：' + e.message + (state.lastRead ? '；仍显示 ' + state.lastRead + ' 的记录。' : '；尚未读到记录，不能确定日志是否为空。'), true);
  } finally { busy(false); }
 }
 async function manualRefresh() { if (state.busy) return; if (!state.loaded) await loadConfig(); await readLogs(); }
 async function clearLogs() {
  if (state.busy || !state.loaded || !window.confirm('确定清空诊断日志？已保存的诊断记录将被删除。')) return;
  busy(true); status(logStatus, '正在清空诊断日志…');
  try {
   await request('/voice_logs_clear', {}); state.entries = []; render([]); state.lastRead = '';
   status(logStatus, '诊断日志已清空。');
  } catch (e) { status(logStatus, '清空失败：' + e.message, true); }
  finally { busy(false); }
 }
 function isVisible() { return panel.classList.contains('active') && !document.hidden; }
 function schedule() {
  if (state.timer !== null) { clearInterval(state.timer); state.timer = null; }
  if (isVisible() && auto.checked) state.timer = setInterval(readLogs, 5000);
 }
 async function visibility() {
  const visible = isVisible(); navButton.setAttribute('aria-pressed', String(visible));
  schedule(); if (visible && !state.visible) { state.visible = true; await manualRefresh(); }
  else if (!visible) state.visible = false;
 }
 enabled.addEventListener('change', function () { state.dirty = true; status(configStatus, '设置尚未保存'); updateButtons(); });
 level.addEventListener('change', function () { state.dirty = true; status(configStatus, '设置尚未保存'); updateButtons(); });
 save.addEventListener('click', saveConfig); refresh.addEventListener('click', manualRefresh); clear.addEventListener('click', clearLogs);
 auto.addEventListener('change', schedule); document.addEventListener('visibilitychange', visibility);
 new MutationObserver(visibility).observe(panel, {attributes:true, attributeFilter:['class']});
 visibility();
}());
