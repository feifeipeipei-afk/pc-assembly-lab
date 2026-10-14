/**
 * 战斗动画体系 · Three.js 渲染器（组合根）
 * ============================================================
 * 把 RendererHost（帧循环/相机）、StageScene（舞台）、UnitView（角色骨骼）
 * 组合成一个符合统一契约的渲染器：play / reset / setUnits / setEnabled / dispose
 * （契约见 events.js 的 RENDERER_INTERFACE）。
 *
 * ------------------------------------------------------------
 * 阶段进度
 *   P0：舞台背景进 WebGL。角色仍由 DOM 渲染（刻意保留，否则会变成"有背景没角色"）。
 *   P1：角色上屏。从 DOM 读取身份 → 建切图骨骼 → 待机呼吸；
 *       骨骼就绪后才隐藏 DOM 精灵（`has-webgl-units`），
 *       资产缺失或 WebGL 失败时保持 DOM 精灵可见 —— 任何情况下都不白屏。
 *   P2：动画运行时（Tween / playTrack 姿势轨道 / tag 打断语义）。
 *   P3（当前）：play() 交给 BattleChoreographer 编排 ——
 *       命中时间轴（蓄力→命中帧→顿帧→解冻→受击）、
 *       ImpactFX 命中特效、CameraDirector 震屏与推近、
 *       HudLayer 伤害飘字/会心横幅/连击（DOM 覆盖层，worldToScreen 定位）。
 *       业务侧（index.html 的 resolveBattleHit / ghostHit）只产出
 *       events.js 里的纯数据事件，经 bootstrap.dispatchBattleEvent 派发到这里；
 *       three 未接管时自动回落旧 DOM 演出，两套渲染器互斥不叠加。
 * ------------------------------------------------------------
 *
 * 为什么身份从 DOM 读、而不是让模板传参
 * ------------------------------------
 * 旧模板已经在维护 `#btMySprite.src` / `#btFoeSprite.src` 以及影子对手的
 * `scrim-shadow` class，那才是"当前该显示谁"的唯一事实来源。
 * 若在 three 侧再传一份，两处一旦不同步就会出现"名字是魔王、画的是勇者"。
 * 所以这里用 MutationObserver 跟随 DOM 属性变化，模板零改动。
 */

import { RendererHost } from './RendererHost.js';
import { StageScene } from './StageScene.js';
import { RigSet } from '../units/RigLoader.js';
import { UnitView, disposeSharedShadow } from '../units/UnitView.js';
import { BattleChoreographer } from '../anim/Choreographer.js';
import { ImpactFX } from '../fx/ImpactFX.js';
import { CameraDirector } from '../fx/CameraDirector.js';
import { HudLayer } from '../hud/HudLayer.js';
import { EV, SIDE } from '../events.js';

/** DOM 精灵文件名 → rig 角色名 */
function unitNameFromSrc(src) {
  const s = String(src || '');
  if (s.includes('boss')) return 'boss';
  if (s.includes('dummy')) return 'dummy';
  if (s.includes('hero')) return 'hero';
  return null;
}

export class ThreeRenderer {
  /**
   * @param {HTMLElement} container .battle-stage 元素
   * @param {HTMLCanvasElement} canvas 模板中的 #battleCanvas
   */
  constructor(container, canvas) {
    this.container = container;
    this.canvas = canvas;

    this.host = new RendererHost(container, canvas);
    this.stage = new StageScene(this.host);

    this.enabled = false;
    this._started = false;
    this._unsubFrame = null;

    /** @type {RigSet|null} */
    this.rigSet = null;
    /** @type {{me: UnitView|null, foe: UnitView|null}} */
    this.units = { me: null, foe: null };
    /** 骨骼是否已就绪；未就绪时 DOM 精灵继续负责显示角色 */
    this.unitsReady = false;
    this.unitsError = null;

    /* P3：演出编排器与它的三件套（fx / 镜头 / HUD），随骨骼一起创建 */
    /** @type {BattleChoreographer|null} */
    this.choreographer = null;
    /** @type {ImpactFX|null} */
    this.fx = null;
    /** @type {CameraDirector|null} */
    this.camera = null;
    /** @type {HudLayer|null} */
    this.hud = null;

    this._unitCbs = new Set();
    this._idCbs = new Set();
    this._domWatches = [];

    /* three 模式接管舞台：隐藏旧 CSS 伪元素（网格与地面条），
     * 改由 StageScene 的着色器绘制，避免两份背景叠在一起。 */
    container.classList.add('is-three');
    canvas.hidden = false;

    this._bindDomIdentity();
    this.readyPromise = this._initUnits();
  }

  /* ============================================================
   * 角色骨骼初始化
   * ============================================================ */

  async _initUnits() {
    try {
      this.rigSet = await RigSet.load();
    } catch (err) {
      /* 资产缺失（忘记跑构建脚本）不该让战斗画面坏掉 —— 保持 DOM 精灵即可 */
      this.unitsError = err;
      console.warn('[battle] 切图骨骼资产不可用，角色继续由 DOM 精灵渲染:', err.message);
      return false;
    }

    if (this._disposed) return false;

    const me = new UnitView({ rigSet: this.rigSet, side: SIDE.ME, phase: 0 });
    const foe = new UnitView({ rigSet: this.rigSet, side: SIDE.FOE, phase: 0.37 });
    this.units.me = me;
    this.units.foe = foe;

    const id = this._readIdentity();
    try {
      me.setIdentity({ unit: id.me.unit, ghost: id.me.ghost });
      foe.setIdentity({ unit: id.foe.unit, ghost: id.foe.ghost });
    } catch (err) {
      this.unitsError = err;
      console.warn('[battle] 角色骨骼构建失败，回落 DOM 精灵:', err.message);
      me.dispose();
      foe.dispose();
      this.units.me = null;
      this.units.foe = null;
      return false;
    }

    me.attachTo(this.stage.getSlot(SIDE.ME));
    foe.attachTo(this.stage.getSlot(SIDE.FOE));

    /* P3：骨骼就绪 → 组装编排器三件套 + 编排器本体 */
    this.fx = new ImpactFX({ host: this.host });
    this.camera = new CameraDirector({ host: this.host });
    this.hud = new HudLayer({ host: this.host, container: this.container });
    this.choreographer = new BattleChoreographer({
      host: this.host,
      stage: this.stage,
      units: this.units,
      fx: this.fx,
      camera: this.camera,
      hud: this.hud,
    });

    /* 每帧驱动。
     * 注意：onFrame 回调的三个参数是 (缩放秒, 原始毫秒, 缩放累计秒) ——
     * 骨骼/特效必须吃**缩放后**的 dt（顿帧时冻结），
     * 编排器调度与镜头要吃**原始** dt（顿帧时继续走时）。 */
    this._unsubFrame = this.host.onFrame((dtSec, dtMs, elapsedSec) => {
      this._tick(dtSec * 1000, dtMs, elapsedSec * 1000);
    });

    this.unitsReady = true;
    this._applyDomVisibility();
    for (const cb of this._unitCbs) {
      try { cb(this.units); } catch (err) { console.error('[battle] unitReady 回调异常', err); }
    }
    return true;
  }

  _tick(scaledMs, rawMs, elapsedMs) {
    if (this.choreographer) this.choreographer.update(scaledMs, rawMs);
    if (this.units.me) this.units.me.update(scaledMs, elapsedMs);
    if (this.units.foe) this.units.foe.update(scaledMs, elapsedMs);
    for (const cb of this._unitCbs) {
      try { cb(this.units, scaledMs, elapsedMs); } catch (err) { console.error('[battle] tick 回调异常', err); }
    }
  }

  /** 骨骼就绪回调（P3 的编排器会挂这里） */
  onUnitsReady(cb) {
    this._unitCbs.add(cb);
    if (this.unitsReady) {
      try { cb(this.units); } catch (err) { console.error(err); }
    }
    return () => this._unitCbs.delete(cb);
  }

  /* ============================================================
   * 身份跟随 DOM
   * ============================================================ */

  _spriteEl(side) {
    return document.getElementById(side === SIDE.ME ? 'btMySprite' : 'btFoeSprite');
  }

  /** 从既有 DOM 读出双方应显示的角色类型与影子态 */
  _readIdentity() {
    const read = (side) => {
      const el = this._spriteEl(side);
      const src = el ? el.getAttribute('src') : null;
      const ghost = !!(el && el.classList.contains('scrim-shadow'));
      /* 兜底：我方默认勇者、敌方默认魔王（与模板初值一致） */
      const fallback = side === SIDE.ME ? 'hero' : 'boss';
      const unit = unitNameFromSrc(src) || (this.rigSet && this.rigSet.has(fallback) ? fallback : null);
      return { unit: unit || this._firstUnit(), ghost };
    };
    return { me: read(SIDE.ME), foe: read(SIDE.FOE) };
  }

  _firstUnit() {
    const names = this.rigSet ? this.rigSet.unitNames : [];
    return names.includes('hero') ? 'hero' : (names[0] || 'hero');
  }

  _bindDomIdentity() {
    for (const side of [SIDE.ME, SIDE.FOE]) {
      const el = this._spriteEl(side);
      if (!el) continue;
      const apply = () => {
        if (!this.unitsReady || !this.units[side]) return;
        const id = this._readIdentity()[side];
        const view = this.units[side];
        if (view.unitName === id.unit
          && view._saturate === (id.ghost ? 0 : 1)) return;
        try {
          view.setIdentity(id);
          for (const cb of this._idCbs) cb(side, id);
        } catch (err) {
          console.warn('[battle] 切换角色骨骼失败:', err.message);
        }
      };
      const mo = new MutationObserver(apply);
      mo.observe(el, { attributes: true, attributeFilter: ['src', 'class'] });
      this._domWatches.push(() => mo.disconnect());
    }

    /* 骨骼就绪后补一次同步 */
    const un = this.onUnitsReady(() => {
      const id = this._readIdentity();
      for (const side of [SIDE.ME, SIDE.FOE]) {
        const view = this.units[side];
        if (!view) continue;
        try { view.setIdentity({ unit: id[side].unit, ghost: id[side].ghost }); }
        catch (err) { console.warn('[battle] 初始化角色骨骼失败:', err.message); }
      }
    });
    this._domWatches.push(un);
  }

  /** 身份变化回调（测试用） */
  onIdentityChange(cb) {
    this._idCbs.add(cb);
    return () => this._idCbs.delete(cb);
  }

  /**
   * 骨骼就绪 → 隐藏 DOM 精灵与底座（WebGL 接管）。
   * 未就绪则保持可见 —— 这是"任何情况下都不白屏"的保证。
   */
  _applyDomVisibility() {
    if (this.unitsReady) this.container.classList.add('has-webgl-units');
    else this.container.classList.remove('has-webgl-units');
  }

  /* ============================================================
   * 生命周期
   * ============================================================ */

  setEnabled(on) {
    const next = !!on;
    if (next === this.enabled) return;
    this.enabled = next;

    if (next) {
      this.host.start();
      this._started = true;
      this.container.classList.add('is-three');
      this.canvas.hidden = false;
    } else {
      this.canvas.hidden = true;
      /* 战斗视图不可见时停帧（省电承诺）：只藏 canvas 不停 rAF
       * 的话每帧仍会跑一整趟 render，白烧 GPU。 */
      this.host.stop();
    }
  }

  /* ============================================================
   * 演出事件消费
   * ============================================================ */

  /**
   * 消费一个演出事件（P3：全部交给 BattleChoreographer 编排）。
   * @param {object} evt 见 events.js
   */
  play(evt) {
    if (!this.enabled || !evt) return;

    if (evt.type === EV.RESET) {
      this.reset();
      return;
    }

    if (this.choreographer) {
      this.choreographer.play(evt);
    }
  }

  /**
   * 设置双方外观身份。
   * @param {{me?: object, foe?: object}} units
   */
  setUnits(units) {
    if (!units) return;
    for (const side of [SIDE.ME, SIDE.FOE]) {
      const id = units[side];
      const view = this.units[side];
      if (!id || !view) continue;
      try { view.setIdentity(id); }
      catch (err) { console.warn('[battle] setUnits 失败:', err.message); }
    }
  }

  /** 清空舞台（进/出战斗时调用） */
  reset() {
    if (this.units.me) this.units.me.reset();
    if (this.units.foe) this.units.foe.reset();
    if (this.choreographer && this.choreographer.reset) this.choreographer.reset();
  }

  /* ============================================================
   * 释放
   * ============================================================ */

  dispose() {
    this._disposed = true;

    for (const off of this._domWatches) {
      try { off(); } catch (err) { /* 忽略 */ }
    }
    this._domWatches.length = 0;
    this._unitCbs.clear();
    this._idCbs.clear();

    if (this._unsubFrame) { this._unsubFrame(); this._unsubFrame = null; }

    /* 编排器先走（内部会解冻时间线、清 HUD） */
    if (this.choreographer) { this.choreographer.dispose(); this.choreographer = null; }

    for (const side of [SIDE.ME, SIDE.FOE]) {
      const view = this.units[side];
      if (view) { view.dispose(); this.units[side] = null; }
    }
    this.unitsReady = false;

    if (this.fx) { this.fx.dispose(); this.fx = null; }
    if (this.camera) { this.camera.dispose(); this.camera = null; }
    if (this.hud) { this.hud.dispose(); this.hud = null; }

    /* 顺序要求：先 UnitView（已在上一步释放），再 RigSet */
    if (this.rigSet) { this.rigSet.dispose(); this.rigSet = null; }
    disposeSharedShadow();

    this.container.classList.remove('has-webgl-units');
    this.container.classList.remove('is-three');
    this.canvas.hidden = true;

    if (this.stage) { this.stage.dispose(); this.stage = null; }
    if (this.host) { this.host.dispose(); this.host = null; }

    this._started = false;
    this.enabled = false;
  }
}
