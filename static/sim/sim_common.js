/* ============================================================
 * sim_common.js —— 模拟器考试公共层
 *
 * 两个模拟器（BIOS / WinPE）共用这一层，负责：
 *   ① 身份与考试模式判定（在线考试 / 离线练习）
 *   ② 操作事件采集与上报（节流批量 + 关页补发）
 *   ③ 倒计时（以服务端时间为准，改本机系统时间无效）
 *   ④ 切屏检测（3 秒去抖，避免教师机广播误伤）
 *   ⑤ 断网续传与刷新恢复
 *
 * 设计原则：**采集的是"做了什么"，不是"得了多少分"**。
 * 学生可以在浏览器里改任何变量，但改不了服务端按事件重放算出的分数。
 * ============================================================ */
(function (global) {
  'use strict';

  /* ---------------- 内部状态 ---------------- */
  var S = {
    simType: null,       // 'bios' | 'winpe'
    sessionId: null,
    mode: 'practice',    // 'exam' | 'practice'
    seq: 0,
    t0: 0,
    outbox: [],
    mute: false,         // 批量改状态时为 true，避免刷屏（如 F9 恢复出厂）
    offset: 0,           // 服务端时间 - 本机时间，用于倒计时校准
    deadline: 0,         // 服务端 deadline（已换算成本机时钟）
    finished: false,
    timer: null,
    flushTimer: null,
    hbTimer: null,
    lastSwitch: 0,
    online: true,
    started: false
  };

  var FLUSH_MS = 1500;      // 节流间隔：既保证实时性，又不至于打爆服务端
  var BATCH_MAX = 50;       // 单次上报上限
  var SWITCH_DEBOUNCE = 3000;
  var HEARTBEAT_MS = 30000;

  /* ---------------- 工具 ---------------- */
  function $(id) { return document.getElementById(id); }

  /**
   * 统一的 POST。
   * async === false 时走 sendBeacon（关页/刷新场景，浏览器保证发出但拿不到响应）；
   * 其余一律用 fetch —— 注意这里必须严格判断 === false，
   * 若写成 !async，那么不传该参数的调用会拿到 undefined，
   * !undefined === true，于是所有正常请求都走 sendBeacon，
   * 拿不到服务端响应，被误判为失败（页面会以为"你已考过"而跳转）。
   */
  function post(url, body, async) {
    var payload = JSON.stringify(body || {});
    if (async === false && global.navigator && navigator.sendBeacon) {
      try {
        var ok = navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }));
        if (ok) return Promise.resolve({ beacon: true });
      } catch (e) { /* 降级到 fetch */ }
    }
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true
    }).then(function (r) { return r.json(); }).catch(function () {
      return { success: false, offline: true };
    });
  }

  function syncNow() { return Date.now() + S.offset; }

  /* ============================================================
   * 一、启动
   * ============================================================ */
  function boot(opts) {
    opts = opts || {};
    S.simType = opts.simType;
    var bootData = global.SIM_BOOT || null;

    if (!bootData || !bootData.logged_in) {
      // 直接双击打开文件，或没从 /portal 登录：降级为练习模式
      S.mode = 'practice';
      S.started = true;
      showBanner('离线练习模式：本次操作不计入成绩。请从统一入口 <b>/portal</b> 登录后参加正式考试。', 'warn');
      if (typeof opts.onReady === 'function') opts.onReady(S);
      return S;
    }

    // 练习模式：留在模拟器自己的"选模式/选皮肤"页，不计时、不上报事件
    if (bootData.mode === 'practice') {
      S.mode = 'practice';
      S.started = true;
      showBanner('练习模式：本次操作<b>不计入成绩</b>，可自由尝试。'
                 + '正式考试请返回首页点【开始正式考试】。', 'warn');
      if (typeof opts.onReady === 'function') opts.onReady(S);
      return S;
    }

    S.mode = 'exam';
    S.offset = (function () {
      if (!bootData.server_now) return 0;
      // server_now 是 UTC 字符串（无时区标记），按 UTC 解析后与本机时间求差
      var t = Date.parse(bootData.server_now.replace(' ', 'T') + 'Z');
      return isNaN(t) ? 0 : (t - Date.now());
    })();

    startExam(opts);
    return S;
  }

  function startExam(opts) {
    post('/api/sim/start', { sim_type: S.simType, mode: 'exam' })
      .then(function (d) {
        if (d && d.success) {
          S.sessionId = d.session_id;
          S.t0 = Date.now();
          S.seq = d.last_seq || 0;
          S.deadline = Date.parse(d.deadline.replace(' ', 'T') + 'Z') - S.offset;
          S.started = true;
          startTimers(opts);
          if (typeof opts.onReady === 'function') opts.onReady(S);
        } else {
          // 409：已考过。明确告诉学生，不要静默转练习模式让人以为没交上
          S.started = true;
          showBanner(d && d.message ? d.message : '无法开始考试，请联系老师。', 'err');
          if (typeof opts.onBlocked === 'function') opts.onBlocked(d);
        }
      });
  }

  /* ============================================================
   * 二、事件采集与上报
   * ============================================================ */
  function emit(kind, target, value) {
    if (S.mode !== 'exam' || !S.sessionId || S.finished) return;
    if (S.mute) return;

    S.seq += 1;
    S.outbox.push({
      seq: S.seq,
      t_ms: Date.now() - S.t0,
      kind: kind,
      target: target,
      value: JSON.stringify(value === undefined ? {} : value)
    });

    if (S.outbox.length >= BATCH_MAX) {
      flush();
    } else {
      scheduleFlush();
    }
  }

  function scheduleFlush() {
    if (S.flushTimer) return;
    S.flushTimer = setTimeout(function () { S.flushTimer = null; flush(); }, FLUSH_MS);
  }

  function flush(async) {
    if (!S.sessionId || !S.outbox.length) return Promise.resolve();
    var batch = S.outbox.slice(0, BATCH_MAX);
    S.outbox = S.outbox.slice(batch.length);
    var p = post('/api/sim/event', { session_id: S.sessionId, events: batch }, async)
      .then(function (d) {
        if (d && d.offline) { S.online = false; S.outbox = batch.concat(S.outbox); }
        else if (d && d.success) { S.online = true; }
        else { S.outbox = batch.concat(S.outbox); }   // 失败就放回队首，下次再发
        return d;
      })
      .catch(function () {
        S.outbox = batch.concat(S.outbox);
        return { success: false, offline: true };
      });
    // 记下这次上报，交卷前要等它真正落库，否则最后几步会被判 0 分
    S.flushPromise = p;
    return p;
  }

  /**
   * 用 Proxy 包住状态对象：任何字段赋值都会自动产生一条 set 事件。
   *
   * 为什么用 Proxy 而不是在每个函数里手工埋点：
   * 手工埋点必然遗漏（十几处赋值点，改一次就漏一次）；
   * Proxy 在数据层统一拦截，只要 state 被改就一定能采到，零遗漏。
   */
  function makeObservable(raw) {
    if (typeof Proxy === 'undefined') return raw;   // 极老浏览器直接降级
    return new Proxy(raw, {
      set: function (t, k, v) {
        var old = t[k];
        t[k] = v;
        if (S.mode === 'exam' && !S.mute && String(k).charAt(0) !== '_') {
          emit('set', String(k), { from: old, to: v });
        }
        return true;
      }
    });
  }

  /** 批量改状态前调用，避免一次操作刷出十几条事件（如 F9 恢复出厂默认） */
  function muteOn() { S.mute = true; }
  function muteOff(emitKind, emitTarget, emitValue) {
    S.mute = false;
    if (emitKind) emit(emitKind, emitTarget, emitValue);
  }

  /* ============================================================
   * 三、倒计时与心跳
   * ============================================================ */
  function startTimers(opts) {
    ensureBar();        // 必须先建状态条，否则 renderClock 找不到 #simClock 会静默失效
    renderClock();
    S.timer = setInterval(renderClock, 1000);
    S.hbTimer = setInterval(heartbeat, HEARTBEAT_MS);

    document.addEventListener('visibilitychange', onSwitch);
    global.addEventListener('blur', onSwitch);
    global.addEventListener('beforeunload', onBeforeUnload);
    global.addEventListener('online', function () { S.online = true; flush(); });

    // 考试模式下封锁刷新/打印/开发者工具快捷键
    global.addEventListener('keydown', function (e) {
      var k = (e.key || '').toLowerCase();
      if (e.ctrlKey && (k === 'r' || k === 'p' || k === 'u' || k === 's')) {
        e.preventDefault();
        emit('suspect', 'blocked_key', { key: k });
      }
      if (k === 'f11') { e.preventDefault(); }
    }, true);

    // 检测到 DevTools 只上报不阻断（机房常有教师端工具条，误伤代价太大）
    setInterval(function () {
      if (global.outerHeight - global.innerHeight > 160 ||
          global.outerWidth - global.innerWidth > 160) {
        emit('suspect', 'devtools');
      }
    }, 5000);
  }

  function renderClock() {
    var el = $('simClock');
    if (!el) return;
    var remain = Math.max(0, S.deadline - syncNow());
    var m = Math.floor(remain / 60000), s = Math.floor((remain % 60000) / 1000);
    el.textContent = '剩余 ' + pad(m) + ':' + pad(s);
    el.className = 'sim-clock' + (remain < 60000 ? ' danger' : (remain < 300000 ? ' warning' : ''));
    if (remain <= 0 && !S.finished) autoSubmit();
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function heartbeat() {
    if (S.mode !== 'exam' || !S.sessionId || S.finished) return;
    post('/api/sim/heartbeat', { session_id: S.sessionId }).then(function (d) {
      if (d && d.success && d.remain_ms != null) {
        // 用服务端剩余时间重新校准，防止学生改本机时间
        S.deadline = Date.now() + d.remain_ms;
      }
      if (d && d.finished && !S.finished) autoSubmit();
    });
  }

  /* ============================================================
   * 四、切屏检测
   * ============================================================ */
  function onSwitch() {
    if (S.mode !== 'exam' || S.finished || !S.sessionId) return;
    var hidden = document.hidden || document.visibilityState === 'hidden';
    var now = Date.now();
    if (now - S.lastSwitch < SWITCH_DEBOUNCE) return;   // 3 秒去抖
    S.lastSwitch = now;
    emit('switch', hidden ? 'hidden' : 'blur', {});
    post('/api/sim/switch', { session_id: S.sessionId, reason: hidden ? 'hidden' : 'blur',
                              t_ms: Date.now() - S.t0 });
  }

  /* ============================================================
   * 五、交卷
   * ============================================================ */
  function onBeforeUnload() {
    if (S.mode === 'exam' && S.outbox.length) flush(false);
  }

  function autoSubmit() {
    if (S.finished) return;
    S.finished = true;
    if (S.timer) clearInterval(S.timer);
    submit('timeout');
  }

  function submit(reason) {
    if (S.mode !== 'exam' || !S.sessionId) return Promise.resolve(null);
    S.finished = true;
    if (S.timer) clearInterval(S.timer);
    if (S.hbTimer) clearInterval(S.hbTimer);

    // 先把残留事件发出去，并且**一并塞进交卷请求**。
    //
    // 为什么不能只 sendBeacon：beacon 是"发了就不管"，浏览器不保证它
    // 比紧接着的交卷请求先到服务端。实测会出现"最后一步装机已完成，
    // 但交卷时事件还没入库 → 该项判 0 分"。
    // 这里双保险：① 正常 POST 并 await；② 同一批事件随交卷请求再发一次，
    // 服务端 append_events 用 INSERT OR IGNORE，重复不会出错。
    var settle = function () {
      return (S.flushPromise || Promise.resolve(null)).catch(function () { return null; });
    };

    return settle().then(function () {
      // 上一次上报已落库；若期间又攒下了新事件，再补发一次并等待
      var pending = S.outbox.slice(0, BATCH_MAX);
      S.outbox = S.outbox.slice(pending.length);
      var again = pending.length ? flush() : Promise.resolve(null);
      return again.catch(function () { return null; }).then(function () {
        return post('/api/sim/submit', {
          session_id: S.sessionId,
          reason: reason || 'user',
          events: pending          // 双保险：随交卷请求再带一次，服务端按 seq 去重
        });
      });
    }).then(function (d) {
      if (d && d.success) {
        showResult(d.result);
        return d.result;
      }
      showBanner('交卷失败，请立即联系老师（不要关闭页面）。', 'err');
      return null;
    });
  }

  /* ============================================================
   * 六、结果展示
   * ============================================================ */
  function showResult(res) {
    if (!res) return;
    var pass = res.normalized >= 60;
    var html = '<div class="sim-result ' + (pass ? 'pass' : 'fail') + '">';
    html += '<div class="sim-result-h">考试结束　成绩 <b>' + res.normalized + '</b> 分'
          + (pass ? '（合格）' : '（不合格）') + '</div>';
    html += '<div class="sim-result-sub">用时 ' + fmtSec(res.duration_sec)
          + '　切屏 ' + res.switch_count + ' 次　状态：'
          + (res.status === 'timeout' ? '到时自动交卷' : '主动交卷') + '</div>';
    html += '<table class="sim-steps"><tr><th>评分项</th><th>得分</th><th>说明</th></tr>';
    (res.steps || []).forEach(function (s) {
      html += '<tr class="' + (s.full ? 'ok' : (s.got > 0 ? 'part' : 'no')) + '">'
            + '<td>' + esc(s.name) + '</td>'
            + '<td>' + s.got + '/' + s.pts + '</td>'
            + '<td>' + (s.full ? '✔ 完成' : esc(s.tip || '')) + '</td></tr>';
    });
    html += '</table>';
    if (res.warnings && res.warnings.length) {
      html += '<div class="sim-warn">提示：' + res.warnings.map(esc).join('；') + '</div>';
    }
    html += '<div class="sim-tip">本页可关闭。如需重考请联系老师作废本次记录。</div></div>';

    var box = $('simResult');
    if (box) { box.innerHTML = html; box.style.display = ''; }
    else { document.body.insertAdjacentHTML('beforeend',
      '<div id="simResult" style="position:fixed;inset:0;z-index:9999;overflow:auto;' +
      'background:rgba(0,0,0,.62);display:flex;align-items:flex-start;justify-content:center;' +
      'padding:40px 16px">' + html + '</div>'); }
    if (global.scrollTo) global.scrollTo(0, 0);
  }

  function fmtSec(sec) {
    sec = sec || 0;
    return Math.floor(sec / 60) + ' 分 ' + (sec % 60) + ' 秒';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ============================================================
   * 七、顶部横幅（倒计时 / 提示）
   * ============================================================ */
  function ensureBar() {
    var bar = $('simBar');
    if (bar) { syncBarOffset(); return bar; }
    bar = document.createElement('div');
    bar.id = 'simBar';
    bar.className = 'sim-bar';
    bar.innerHTML = '<span class="sim-who"></span><span id="simClock" class="sim-clock"></span>';
    document.body.insertBefore(bar, document.body.firstChild);
    syncBarOffset();
    return bar;
  }

  /* 状态条与提示条是 fixed 的，会盖住页面顶部：WinPE 的桌面图标、
     BIOS 的题号栏都贴着页面顶端。这里按实际高度给 body 让出等高等的
     顶部留白，并把高度写进 --simbar-h 供各自样式使用。 */
  function syncBarOffset() {
    var h = 0;
    var bar = $('simBar');
    if (bar) h += bar.offsetHeight || 0;
    var tips = document.querySelectorAll('.sim-tipbar');
    for (var i = 0; i < tips.length; i++) h += tips[i].offsetHeight || 0;
    if (document.body) {
      document.body.classList.add('has-simbar');
      document.body.style.paddingTop = h + 'px';
    }
    try {
      document.documentElement.style.setProperty('--simbar-h', h + 'px');
    } catch (e) {}
  }

  function showBanner(html, kind) {
    var bar = ensureBar();
    var tip = document.createElement('div');
    tip.className = 'sim-tipbar ' + (kind || '');
    tip.innerHTML = html;
    bar.appendChild(tip);
    syncBarOffset();
  }

  function setWho(text) {
    var bar = ensureBar();
    var el = bar.querySelector('.sim-who');
    if (el) el.textContent = text;
  }

  /* ---------------- 对外接口 ---------------- */
  global.SimExam = {
    boot: boot,
    emit: emit,
    flush: flush,
    makeObservable: makeObservable,
    muteOn: muteOn,
    muteOff: muteOff,
    submit: submit,
    autoSubmit: autoSubmit,
    showBanner: showBanner,
    setWho: setWho,
    state: S,
    isExam: function () { return S.mode === 'exam'; },
    sessionId: function () { return S.sessionId; }
  };

})(window);
