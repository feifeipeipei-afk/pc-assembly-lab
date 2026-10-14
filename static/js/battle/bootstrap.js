/**
 * 战斗动画体系 · 入口与渲染器开关
 * ============================================================
 * 职责（只做这些）：
 *   1. 解析渲染器选择：URL 参数 ?renderer= > localStorage > 默认 dom
 *   2. WebGL 能力探测（在加载 three 之前）
 *   3. 按需动态 import 对应渲染器 —— 默认 dom 路径**不会下载 three**
 *   4. 挂载 / 卸载，探测失败自动回落 dom 且不报错不白屏
 *   5. 跟随战斗视图可见性启停帧循环（不可见就不出帧，省电）
 *
 * 公共接口：
 *   resolveKind()            当前选中的渲染器类型
 *   mountBattle(opts)        挂载，返回渲染器实例或 null
 *   unmountBattle()          卸载并释放
 *   getActive()              当前实例
 *   dispatchBattleEvent(evt) 派发演出事件（three 活着才返回 true）
 *   autoInit()               供模板胶水脚本一行调用
 */

import { RENDERER } from './config.js';
import { probeWebGL } from './renderer/probe.js';
import {
  hitEvent, critEvent, comboEvent, ghostEvent, verdictEvent, resetEvent,
} from './events.js';

/** @type {import('./renderer/ThreeRenderer.js').ThreeRenderer|null} */
let active = null;
let unmountVisibilityWatch = null;

/* ------------------------------------------------------------
 * 开关解析
 * ------------------------------------------------------------ */

/**
 * 解析应使用的渲染器类型。
 * 优先级：显式参数 > URL query > localStorage > 默认值(dom)。
 * 通过 URL 指定时会写入 localStorage，方便老师切一次后一直生效。
 * @param {string} [explicit]
 * @returns {'three'|'dom'}
 */
export function resolveKind(explicit) {
  if (explicit === RENDERER.THREE || explicit === RENDERER.DOM) return explicit;

  let qs = null;
  try {
    qs = new URLSearchParams(window.location.search).get(RENDERER.QUERY_KEY);
  } catch (err) { /* 极端环境下 location 不可读，忽略 */ }

  if (qs === RENDERER.THREE || qs === RENDERER.DOM) {
    try { localStorage.setItem(RENDERER.STORAGE_KEY, qs); } catch (err) { /* 隐私模式下可能抛错 */ }
    return qs;
  }

  let stored = null;
  try { stored = localStorage.getItem(RENDERER.STORAGE_KEY); } catch (err) { /* 同上 */ }
  if (stored === RENDERER.THREE || stored === RENDERER.DOM) return stored;

  return RENDERER.DEFAULT;
}

/* ------------------------------------------------------------
 * 可见性联动
 * ------------------------------------------------------------ */

/**
 * 跟随战斗视图的显隐启停渲染。
 * 用 MutationObserver 观察 class 变化而不是去改动模板内联逻辑 ——
 * P0 阶段要求最小侵入，内联脚本一行都不用动。
 * @param {HTMLElement} viewEl #battleView
 * @param {(visible:boolean)=>void} cb
 * @returns {()=>void} 取消观察
 */
function watchBattleVisibility(viewEl, cb) {
  if (!viewEl || typeof MutationObserver === 'undefined') return () => {};

  let last = null;
  const check = () => {
    /* class 切换与布局不在同一 tick 完成，延后到下一帧再量尺寸 */
    requestAnimationFrame(() => {
      const visible = !viewEl.classList.contains('hidden')
        && viewEl.getBoundingClientRect().width > 0;
      if (visible === last) return;
      last = visible;
      cb(visible);
    });
  };

  const mo = new MutationObserver(check);
  mo.observe(viewEl, { attributes: true, attributeFilter: ['class'] });
  check();

  return () => mo.disconnect();
}

/* ------------------------------------------------------------
 * 挂载 / 卸载
 * ------------------------------------------------------------ */

/**
 * 挂载战斗渲染器。
 * @param {object} [opts]
 * @param {HTMLElement} [opts.container] 默认取 #battleStage 的宿主 .battle-stage
 * @param {HTMLCanvasElement} [opts.canvas] 默认取 #battleCanvas
 * @param {HTMLElement} [opts.viewEl] 默认取 #battleView
 * @param {'three'|'dom'} [opts.renderer] 强制指定渲染器
 * @returns {Promise<object|null>} 渲染器实例；dom 路径返回 null（由模板内联实现接管）
 */
export async function mountBattle(opts = {}) {
  unmountBattle();

  const kind = resolveKind(opts.renderer);

  /* dom 路径：舞台由模板内联实现负责，这里不做任何事。
   * 这也保证了"不带参数时行为与重构前完全一致"。 */
  if (kind !== RENDERER.THREE) return null;

  const container = opts.container || document.getElementById('battleStage');
  const canvas = opts.canvas || document.getElementById('battleCanvas');
  if (!container || !canvas) {
    console.warn('[battle] 找不到 .battle-stage 或 #battleCanvas，跳过 three 渲染器挂载');
    return null;
  }

  /* 探测必须发生在 import three 之前（probe.js 零依赖，不触发下载） */
  const probe = probeWebGL();
  if (!probe.ok) {
    console.warn(`[battle] WebGL 不可用（${probe.reason}${probe.detail ? ': ' + probe.detail : ''}），回落 dom 渲染器`);
    canvas.hidden = true;
    container.classList.remove('is-three');
    return null;
  }

  let ThreeRenderer;
  try {
    /* 动态 import：只有走 three 路径时才下载 three 与 three.core（约 2MB） */
    ({ ThreeRenderer } = await import('./renderer/ThreeRenderer.js'));
  } catch (err) {
    console.error('[battle] three 渲染器加载失败，回落 dom 渲染器', err);
    canvas.hidden = true;
    container.classList.remove('is-three');
    return null;
  }

  try {
    active = new ThreeRenderer(container, canvas);
  } catch (err) {
    console.error('[battle] three 渲染器初始化失败，回落 dom 渲染器', err);
    canvas.hidden = true;
    container.classList.remove('is-three');
    return null;
  }

  /* 跟随战斗视图显隐启停（不可见时不出帧） */
  unmountVisibilityWatch = watchBattleVisibility(
    opts.viewEl || document.getElementById('battleView'),
    (visible) => { if (active) active.setEnabled(visible); },
  );

  return active;
}

/** 卸载并释放全部 GPU 资源 */
export function unmountBattle() {
  if (unmountVisibilityWatch) {
    unmountVisibilityWatch();
    unmountVisibilityWatch = null;
  }
  if (active) {
    try { active.dispose(); }
    catch (err) { console.error('[battle] 卸载 three 渲染器异常', err); }
    active = null;
  }
}

/** @returns {object|null} 当前渲染器实例 */
export function getActive() {
  return active;
}

/* ------------------------------------------------------------
 * 演出事件派发（业务层 → 渲染器的唯一通道）
 * ------------------------------------------------------------
 * 供 index.html 的经典脚本调用：three 渲染器活着且骨骼就绪时，
 * 把事件交给它并返回 true（业务层跳过旧 DOM 演出）；
 * 任何一步不成立都返回 false —— 业务层回落旧 DOM 动画路径，
 * 保证 dom 模式 / 资产缺失 / WebGL 失败时行为与历史版本一致。
 * events.js 零依赖，这里静态引入不会触发 three 下载。 */

/**
 * 派发一个演出事件给当前 three 渲染器。
 * @param {object} evt events.js 工厂产出的纯数据事件
 * @returns {boolean} 是否已被 three 渲染器消费
 */
export function dispatchBattleEvent(evt) {
  if (!active || !evt) return false;
  if (!active.enabled || !active.unitsReady) return false;
  try {
    active.play(evt);
    return true;
  } catch (err) {
    console.error('[battle] 演出事件派发失败，回落 DOM 演出', err);
    return false;
  }
}

/* ------------------------------------------------------------
 * 模板胶水用的便捷入口
 * ------------------------------------------------------------ */

/**
 * 页面加载后自动初始化。模板里只需一行：
 *   <script type="module">import { autoInit } from '/static/js/battle/bootstrap.js'; autoInit();</script>
 */
export function autoInit() {
  const boot = () => { mountBattle().catch((err) => console.error('[battle] 自动初始化失败', err)); };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
}

/* 调试与冒烟测试入口：dispatch/事件工厂供模板经典脚本调用 */
if (typeof window !== 'undefined') {
  window.__battleFX = {
    mountBattle, unmountBattle, getActive, resolveKind, autoInit,
    dispatch: dispatchBattleEvent,
    hitEvent, critEvent, comboEvent, ghostEvent, verdictEvent, resetEvent,
  };
}
