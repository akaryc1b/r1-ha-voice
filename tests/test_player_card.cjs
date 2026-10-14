/* 验证卡片真实生命周期，不连接 HA 或播放设备。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const timers = new Map(), listeners = new Set(), registry = new Map();
let nextTimer = 1;
function node() { return { style: {}, setAttribute(k, v) { this[k] = v; } }; }
class HTMLElement {
  attachShadow() {
    const nodes = new Map();
    const lookup = key => { if (!nodes.has(key)) nodes.set(key, node()); return nodes.get(key); };
    this.shadowRoot = { getElementById: lookup, querySelector: lookup, querySelectorAll: () => [] };
    return this.shadowRoot;
  }
}
const document = {
  hidden: false,
  addEventListener(name, callback) { if (name === 'visibilitychange') listeners.add(callback); },
  removeEventListener(name, callback) { listeners.delete(callback); },
};
const context = vm.createContext({
  HTMLElement, document, URL, Date,
  window: { location: { href: 'http://ha.test/' } },
  customElements: { get: name => registry.get(name), define: (name, type) => registry.set(name, type) },
  setInterval(callback) { const id = nextTimer++; timers.set(id, callback); return id; },
  clearInterval(id) { timers.delete(id); },
});
const source = fs.readFileSync(path.join(__dirname, '..', 'r1-ha-voice.js'), 'utf8');
vm.runInContext(`(() => {${source}\n})()`, context);
vm.runInContext(`(() => {${source}\n})()`, context);
assert.equal(context.window.customCards.length, 1);
const Card = registry.get('r1-player-card');
const card = new Card();
card.setConfig({ entity: 'media_player.test', r1_url: 'http://r1.test:8080/' });
assert.equal(card.$('r1-settings').href, 'http://r1.test:8080/');
card.connectedCallback();
assert.equal(timers.size, 0);
function state(value) {
  card.hass = { states: { 'media_player.test': { state: value, attributes: { media_duration: 100 } } } };
}
state('playing');
assert.equal(timers.size, 1);
state('playing');
card.connectedCallback();
assert.equal(timers.size, 1);
assert.equal(listeners.size, 1);
state('paused');
assert.equal(timers.size, 0);
document.hidden = true;
state('playing');
assert.equal(timers.size, 0);
document.hidden = false;
for (const listener of listeners) listener();
assert.equal(timers.size, 1);
document.hidden = true;
for (const listener of listeners) listener();
assert.equal(timers.size, 0);
document.hidden = false;
card.connectedCallback();
assert.equal(timers.size, 1);
card.disconnectedCallback();
assert.equal(timers.size, 0);
assert.equal(listeners.size, 0);
card.setConfig({ entity: 'media_player.test', r1_url: 'https://new-r1.test/' });
assert.equal(card.$('r1-settings').href, 'https://new-r1.test/');
for (const value of ['javascript:alert(1)', 'http://user:password@r1.test/']) {
  assert.throws(() => card.setConfig({ r1_url: value }));
}
console.log('Card lifecycle, visibility, reconnect, configuration and URL checks passed.');
