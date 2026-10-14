/* 使用现有 HA 实体与脚本，不向浏览器暴露 Music Assistant 凭据。 */
class R1PlayerCard extends HTMLElement {
  setConfig(config) {
    const url = new URL(config.r1_url || 'http://192.168.1.3:8080/', window.location.href);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('r1_url 需填写 HTTP 或 HTTPS 地址');
    this.config = config;
    this.r1Url = url.href;
    if (this.shadowRoot) { this.$('r1-settings').href = this.r1Url; return; }
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = [
      '<style>',
      ':host{display:block;max-width:900px;width:calc(100% - 32px);margin:24px auto;font-family:var(--primary-font-family,Roboto,"Microsoft YaHei",sans-serif);--ink:var(--primary-text-color,#242333);--muted:var(--secondary-text-color,#727383);--accent:#7961cb}',
      '*{box-sizing:border-box}button,input{font:inherit}button{cursor:pointer}button:disabled{cursor:wait;opacity:.55}',
      'ha-card{border:0;border-radius:28px;overflow:hidden;background:var(--card-background-color,#fff);box-shadow:0 8px 32px #28243d0c;color:var(--ink)}',
      '.top{padding:26px 28px 12px;display:flex;align-items:center;justify-content:space-between;gap:12px}',
      '.eyebrow{font-size:11px;letter-spacing:2px;color:var(--muted);font-weight:600}.top h2{font-size:25px;letter-spacing:1px;margin:7px 0 0;font-weight:650}',
      '.pill{display:inline-flex;gap:6px;align-items:center;font-size:12px;border-radius:20px;background:#7961cb12;color:var(--accent);padding:8px 11px;white-space:nowrap}.dot{width:6px;height:6px;background:currentColor;border-radius:50%}',
      '.player{display:grid;grid-template-columns:200px minmax(0,1fr);gap:30px;padding:20px 28px 28px;align-items:center}',
      '.art{aspect-ratio:1;position:relative;border-radius:23px;background:linear-gradient(145deg,#e5dbfa,#c6c5e9 55%,#dfdff0);box-shadow:0 15px 28px #3f335426;display:grid;place-items:center;overflow:hidden}',
      '.art img{position:absolute;width:100%;height:100%;object-fit:cover}.art>ha-icon{--mdc-icon-size:65px;color:#7961cb99}',
      '.service{font-size:11px;letter-spacing:1.8px;color:var(--muted);display:flex;align-items:center;gap:5px}.service ha-icon{--mdc-icon-size:14px}',
      'h1{font-size:28px;line-height:1.3;margin:12px 0 8px;overflow-wrap:anywhere;font-weight:650}.artist{font-size:15px;color:var(--muted);margin-bottom:22px;min-height:20px}',
      '.track{height:4px;border-radius:9px;background:#88888820;overflow:hidden}.fill{height:100%;background:var(--accent);width:0;transition:width .5s linear}.times{display:flex;justify-content:space-between;font-size:11px;font-variant-numeric:tabular-nums;color:var(--muted);margin-top:7px;min-height:14px}',
      '.transport{display:flex;align-items:center;justify-content:center;gap:24px;margin-top:12px}.icon{border:0;background:transparent;color:var(--ink);display:grid;place-items:center;width:38px;height:38px;border-radius:50%}.icon:hover{background:#7961cb10}.icon ha-icon{--mdc-icon-size:24px}',
      '.play{flex-shrink:0;width:60px;height:60px;color:white;background:var(--accent);box-shadow:0 5px 15px #7961cb35}.play:hover{background:#6951bb}.play ha-icon{--mdc-icon-size:29px}.stop{margin-left:auto;color:var(--muted)}',
      '.bottom{padding:0 28px 26px}.volume{display:flex;align-items:center;gap:12px;padding:16px 0;border-top:1px solid #88888816}.volume ha-icon{--mdc-icon-size:19px;color:var(--muted)}.volume label{font-size:12px;white-space:nowrap;color:var(--muted)}',
      'input[type=range]{accent-color:var(--accent);flex:1;min-width:0;cursor:pointer;height:18px}.number{width:37px;text-align:right;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}',
      '.search{display:flex;gap:10px;margin-top:4px}.search input{width:0;flex:1;padding:13px 15px;border-radius:14px;border:1px solid #88888828;outline:0;background:var(--secondary-background-color,#faf9fc);color:var(--ink);font-size:14px}.search input:focus{border-color:var(--accent)}',
      '.search button{border:0;border-radius:14px;background:var(--accent);color:#fff;padding:0 20px;font-size:14px}',
      '.styles{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}.chip{background:#88888809;border:1px solid #88888819;border-radius:11px;padding:8px 12px;font-size:12px;color:var(--muted)}.chip:hover{border-color:#7961cb77;color:var(--accent)}',
      '.feedback{font-size:12px;color:var(--muted);line-height:1.6;min-height:21px;margin-top:14px}.climate{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:18px}.metric{border-radius:17px;background:var(--secondary-background-color,#f7f7fb);padding:15px 17px}.metric .label{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--muted)}.metric ha-icon{--mdc-icon-size:17px;color:var(--accent)}.metric strong{display:block;font-size:23px;letter-spacing:.2px;margin-top:8px;font-weight:600}',
      'details{margin-top:16px;border-top:1px solid #88888816;padding-top:15px}summary{cursor:pointer;font-size:12px;color:var(--muted)}.speech-volume{border-top:0;padding-bottom:0}.links{display:flex;gap:18px;margin-top:17px;font-size:12px}.links a{color:var(--muted);text-decoration:none}.links a:hover{color:var(--accent)}',
      'button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:4px}',
      '@media(max-width:550px){:host{width:calc(100% - 16px);margin:8px auto}.top{padding:22px 22px 10px}.player{grid-template-columns:1fr;padding:20px 22px 18px;gap:25px}.art{width:min(100%,220px);justify-self:center}.metadata{text-align:center}.service{justify-content:center}h1{font-size:25px;margin-top:10px}.artist{margin-bottom:18px}.transport{gap:27px;margin-top:15px;position:relative}.stop{margin:0;position:absolute;right:0}.bottom{padding:0 22px 22px}.top h2{font-size:23px}}',
      '</style>',
      '<ha-card><header class="top"><div><div class="eyebrow">YOUR EVERYDAY SOUND</div><h2>卧室 · 音乐</h2></div><span class="pill"><i class="dot"></i><span id="state">连接中</span></span></header>',
      '<section class="player"><div class="art"><ha-icon icon="mdi:music-note"></ha-icon><img id="cover" alt="专辑封面" hidden></div><div class="metadata">',
      '<div class="service"><ha-icon icon="mdi:apple"></ha-icon> APPLE MUSIC · R1</div><h1 id="title">准备听点什么</h1><div class="artist" id="artist">选一首歌，让音乐开始</div>',
      '<div class="track" role="progressbar" aria-label="歌曲播放进度" id="progress"><div class="fill" id="fill"></div></div><div class="times"><span id="elapsed">—</span><span id="duration">—</span></div>',
      '<div class="transport"><button class="icon" data-op="previous" title="上一首" aria-label="上一首"><ha-icon icon="mdi:skip-previous"></ha-icon></button><button class="icon play" data-op="toggle" id="play" title="播放" aria-label="播放"><ha-icon id="play-icon" icon="mdi:play"></ha-icon></button><button class="icon" data-op="next" title="下一首" aria-label="下一首"><ha-icon icon="mdi:skip-next"></ha-icon></button><button class="icon stop" data-op="stop" title="停止" aria-label="停止"><ha-icon icon="mdi:stop"></ha-icon></button></div>',
      '</div></section><section class="bottom"><div class="volume"><ha-icon icon="mdi:volume-medium"></ha-icon><label for="volume">音乐音量</label><input id="volume" type="range" min="0" max="100" aria-label="音乐音量"><span class="number" id="volume-label">—</span></div>',
      '<form class="search"><input id="query" type="search" autocomplete="off" maxlength="120" placeholder="想听哪首歌？输入歌名或歌手" aria-label="歌名或歌手"><button type="submit">播放</button></form>',
      '<div class="styles"><button class="chip" data-query="流行音乐">流行精选</button><button class="chip" data-query="轻音乐">轻松一下</button><button class="chip" data-query="爵士音乐">爵士时光</button><button class="chip" data-query="睡眠音乐">晚安音乐</button></div>',
      '<div class="feedback" id="feedback" role="status" aria-live="polite">音乐播放到卧室 R1</div>',
      '<div class="climate"><div class="metric"><div class="label"><ha-icon icon="mdi:thermometer"></ha-icon>卧室温度</div><strong id="temperature">—</strong></div><div class="metric"><div class="label"><ha-icon icon="mdi:water-percent"></ha-icon>卧室湿度</div><strong id="humidity">—</strong></div></div>',
      '<details><summary>助手播报音量</summary><div class="volume speech-volume"><ha-icon icon="mdi:account-voice"></ha-icon><label for="speech-volume">回答音量</label><input id="speech-volume" type="range" min="0" max="100" aria-label="助手播报音量"><span class="number" id="speech-label">—</span></div></details>',
      '<div class="links"><a href="/r1-music/library">浏览音乐库与播放队列 ↗</a><a id="r1-settings" href="#" target="_blank" rel="noopener">音箱设置 ↗</a></div></section></ha-card>'
    ].join("");
    this.$ = (id) => root.getElementById(id);
    this.$("r1-settings").href = this.r1Url;
    root.querySelectorAll("[data-op]").forEach((button) => button.onclick = () => {
      const operation = button.dataset.op === "toggle" ? (this.entity?.state === "playing" ? "pause" : "resume") : button.dataset.op;
      this.run("r1_music_player_control", { operation }, button);
    });
    root.querySelectorAll("[data-query]").forEach((button) => button.onclick = () => this.run("r1_apple_music_play", { query: button.dataset.query }, button));
    root.querySelector("form").onsubmit = (e) => {
      e.preventDefault();
      const query = this.$("query").value.trim();
      if (query) this.run("r1_apple_music_play", { query }, root.querySelector("form button"));
    };
    for (const target of ["music", "speech"]) {
      const id = target === "music" ? "volume" : "speech-volume";
      const label = target === "music" ? "volume-label" : "speech-label";
      this.$(id).oninput = () => this.$(label).textContent = this.$(id).value + "%";
      this.$(id).onchange = () => this.run("r1_volume_control", { volume_target: target, operation: "set", percent: Number(this.$(id).value) });
    }
    this.$("cover").onerror = () => { this.$("cover").hidden = true; };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) return;
    this.entity = hass.states[this.config.entity || "media_player.r1_apple_music"];
    const e = this.entity;
    const a = e?.attributes || {};
    this.$("state").textContent = ({ playing: "正在播放", paused: "已暂停", idle: "待机", unavailable: "音箱离线", off: "已停止" })[e?.state] || "待机";
    this.$("title").textContent = a.media_title || "准备听点什么";
    this.$("artist").textContent = [a.media_artist, a.media_album_name].filter(Boolean).join(" · ") || "选一首歌，让音乐开始";
    const cover = a.entity_picture_local || a.entity_picture;
    if (cover && cover !== this.cover) {
      this.cover = cover; this.$("cover").hidden = false; this.$("cover").src = cover;
    } else if (!cover) { this.cover = null; this.$("cover").hidden = true; }
    const playing = e?.state === "playing";
    this.$("play-icon").setAttribute("icon", playing ? "mdi:pause" : "mdi:play");
    this.$("play").setAttribute("aria-label", playing ? "暂停" : "播放");
    this.$("play").title = playing ? "暂停" : "播放";
    this.updateVolume("music", "volume", "volume-label");
    this.updateVolume("speech", "speech-volume", "speech-label");
    this.renderMetric("temperature", this.config.temperature, "℃");
    this.renderMetric("humidity", this.config.humidity, "%");
    this.updateProgress();
    this.syncProgressTimer();
  }

  updateVolume(target, input, label) {
    const s = this._hass.states["sensor.r1_" + target + "_volume"];
    const value = Number(s?.state);
    if (s && Number.isFinite(value) && this.shadowRoot.activeElement !== this.$(input)) {
      this.$(input).value = value;
      this.$(label).textContent = Math.round(value) + "%";
    }
  }

  renderMetric(element, entity, unit) {
    const s = this._hass.states[entity];
    const value = Number(s?.state);
    this.$(element).textContent = s && s.state !== "" && Number.isFinite(value) ? value + unit : "暂不可用";
  }

  updateProgress() {
    if (document.hidden || !this._hass || !this.shadowRoot) return;
    const media = this._hass.states["sensor.r1_music_status"]?.attributes?.current_media || {};
    const duration = Number(media.duration || this.entity?.attributes.media_duration || 0);
    let elapsed = Number(media.elapsed_time || 0);
    if (this.entity?.state === "playing" && media.elapsed_time_last_updated) elapsed += Math.max(0, Date.now() / 1000 - media.elapsed_time_last_updated);
    elapsed = Math.min(duration || elapsed, Math.max(0, elapsed));
    const clock = (seconds) => Math.floor(seconds / 60) + ":" + String(Math.floor(seconds % 60)).padStart(2, "0");
    this.$("elapsed").textContent = duration ? clock(elapsed) : "—";
    this.$("duration").textContent = duration ? clock(duration) : "—";
    this.$("fill").style.width = (duration ? elapsed / duration * 100 : 0) + "%";
    this.$("progress").setAttribute("aria-valuenow", Math.round(elapsed));
    this.$("progress").setAttribute("aria-valuemax", duration);
  }

  async run(script, data, button) {
    if (button) button.disabled = true;
    this.$("feedback").textContent = script === "r1_apple_music_play" ? "正在查找歌曲，准备播放…" : "正在发送指令…";
    try {
      const result = await this._hass.callWS({ type: "call_service", domain: "script", service: script, service_data: data, return_response: script !== "r1_music_player_control" });
      const response = result?.response;
      this.$("feedback").textContent = response?.message || "指令已发送，播放状态正在更新";
      if (script === "r1_volume_control") {
        await this._hass.callService("homeassistant", "update_entity", { entity_id: ["sensor.r1_music_volume", "sensor.r1_speech_volume"] });
      }
    } catch (error) {
      this.$("feedback").textContent = "操作未完成：" + (error.message || "请检查音箱连接");
    } finally { if (button) button.disabled = false; }
  }

  syncProgressTimer() {
    const running = this._connected && !document.hidden && this.entity?.state === "playing";
    if (running && this.timer == null) this.timer = setInterval(() => this.updateProgress(), 1000);
    if (!running && this.timer != null) { clearInterval(this.timer); this.timer = null; }
  }

  connectedCallback() {
    this._connected = true;
    if (!this.visibilityHandler) this.visibilityHandler = () => {
      this.syncProgressTimer();
      if (!document.hidden) this.updateProgress();
    };
    document.addEventListener("visibilitychange", this.visibilityHandler);
    this.syncProgressTimer();
  }

  disconnectedCallback() {
    this._connected = false;
    document.removeEventListener("visibilitychange", this.visibilityHandler);
    this.syncProgressTimer();
  }
  getCardSize() { return 9; }
}
if (!customElements.get("r1-player-card")) customElements.define("r1-player-card", R1PlayerCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "r1-player-card")) window.customCards.push({ type: "r1-player-card", name: "卧室 R1 播放器", description: "Apple Music、音量与卧室温湿度" });
