/**
 * 战斗动画体系 · 战斗编排器（P3 的核心）
 * ============================================================
 * ThreeRenderer.play(evt) 的真正实现者。它把一个演出事件展开成
 * 「谁在什么时候做什么」的时间轴：
 *
 *   HIT(correct)
 *     t=0            攻击方 attack()（windup 蓄力 → strike 突进 → recover 收招）
 *     t=impactAt     命中帧：斩击/闪光/冲击环 + 镜头震屏/推近 + 顿帧
 *     t=impactAt+停  受击方 hurt() + 伤害飘字 + 扬尘（世界"解冻"后才反应）
 *
 * impactAt 不是 windup 的终点而是 strike 中段 —— 顿帧要冻结在
 * "突进已出、拳锋刚触到"的那一帧，而不是"还站在原地蓄力"的那一帧，
 * 这是打击感对与错的分界线。
 *
 * 两条时间线（刻意分开）
 * ----------------------
 *   世界线（缩放 dt）：UnitView 骨骼、ImpactFX 特效 —— 顿帧时全部冻结；
 *   镜头线（原始 dt）：CameraDirector 震屏/回弹 —— 顿帧时继续微颤，
 *                     "世界停了、镜头还活着"才是标准的 hit-stop 观感。
 * 调度器自身跑在原始 dt 上（用真实时间排程，否则"解冻"这件事
 * 自己也会被冻住）。
 *
 * 打断语义
 * --------
 * 快速连点时旧 setTimeout 方案会互相踩（见 Tween.js 文件头）。
 * 这里：UnitView.playTrack 的 tag 机制保证新动作覆盖旧动作；
 * 顿帧用令牌（_hitStopToken）保证只有最后一次冻结有权解冻；
 * RESET 清空全部待办并立即解冻。
 */

import { EV, SIDE } from '../events.js';
import {
  TIMING, UNIT_X, SLOT_SIDE, UNIT_SIZE,
} from '../config.js';

/** 命中点：受击方内侧身位、胸口高度 */
function hitPoint(defSide) {
  return {
    x: SLOT_SIDE[defSide] * (UNIT_X - 38),
    y: UNIT_SIZE * 0.56,
  };
}

/** 攻击方向：我方(+1)向左砍 / 敌方(-1)向右砍（影响弧光倾角） */
function attackDir(atkSide) {
  return atkSide === SIDE.ME ? 1 : -1;
}

/** 命中帧 = 蓄力结束 + 突进进行到 40%（接触发生的一瞬） */
function impactDelay() {
  return TIMING.attack.windup + Math.round(TIMING.attack.strike * 0.4);
}

export class BattleChoreographer {
  /**
   * @param {object} opts
   * @param {import('../renderer/RendererHost.js').RendererHost} opts.host
   * @param {import('../renderer/StageScene.js').StageScene} opts.stage
   * @param {{me:import('../units/UnitView.js').UnitView, foe:import('../units/UnitView.js').UnitView}} opts.units
   * @param {import('../fx/ImpactFX.js').ImpactFX} opts.fx
   * @param {import('../fx/CameraDirector.js').CameraDirector} opts.camera
   * @param {import('../hud/HudLayer.js').HudLayer} opts.hud
   */
  constructor({ host, stage, units, fx, camera, hud }) {
    this.host = host;
    this.stage = stage;
    this.units = units;   /* ThreeRenderer.units 的活引用（身份切换不改引用） */
    this.fx = fx;
    this.camera = camera;
    this.hud = hud;

    /* 调度器（原始时间） */
    this._now = 0;
    /** @type {Array<{at:number, fn:()=>void}>} */
    this._pending = [];

    /* 顿帧令牌 */
    this._hitStopToken = 0;

    /* 最近一次命中的快照（调试/冒烟断言用） */
    this.lastImpact = null;
  }

  /* ============================================================
   * 调度原语（原始时间线）
   * ============================================================ */

  _schedule(delayMs, fn) {
    this._pending.push({ at: this._now + Math.max(0, delayMs), fn });
  }

  _runDue() {
    if (this._pending.length === 0) return;
    /* 快照遍历：回调里可能再 _schedule（例如链式演出） */
    const due = [];
    const keep = [];
    for (const it of this._pending) {
      (it.at <= this._now ? due : keep).push(it);
    }
    this._pending = keep;
    for (const it of due) {
      try { it.fn(); }
      catch (err) { console.error('[battle] 编排回调异常', err); }
    }
  }

  /** 顿帧：冻结世界线，ms 后由持令牌者解冻 */
  _hitStop(ms) {
    this.host.setTimeScale(0);
    const token = ++this._hitStopToken;
    this._schedule(ms, () => {
      if (token === this._hitStopToken) this.host.setTimeScale(1);
    });
  }

  /* ============================================================
   * 事件入口（ThreeRenderer.play 委托到这里）
   * ============================================================ */

  /**
   * @param {object} evt 见 events.js
   */
  play(evt) {
    if (!evt) return;
    switch (evt.type) {
      case EV.HIT:      this._onHit(evt); break;
      case EV.GHOST_HIT: this._onGhostHit(evt); break;
      case EV.CRIT:     this.hud.critBanner(); break;
      case EV.COMBO:    this.hud.combo(evt.combo); break;
      case EV.VERDICT:  break;   /* 结算演出由结算页接管，舞台侧暂无动作 */
      case EV.RESET:    this.reset(); break;
      default: break;
    }
  }

  /* ---------------- 我方出招 ---------------- */

  _onHit(evt) {
    if (evt.correct) {
      this._strike(SIDE.ME, SIDE.FOE, {
        power: evt.crit ? 1.35 : 1,
        hitStop: evt.crit ? TIMING.hitStop.crit : TIMING.hitStop.normal,
        damage: evt.damage,
        crit: evt.crit,
      });
      return;
    }

    if (evt.counter) {
      /* 闯关答错：Boss 反击我方 */
      this._strike(SIDE.FOE, SIDE.ME, {
        power: 1,
        hitStop: TIMING.hitStop.normal,
        damage: evt.damage,
      });
      return;
    }

    /* PVP 答错：出招落空（挥空拳，没有命中反馈） */
    const me = this.units[SIDE.ME];
    if (me) me.attack({ power: 0.8 });
    this._schedule(impactDelay(), () => {
      this.hud.damageNumber({
        side: SIDE.ME, ...hitPoint(SIDE.ME), text: 'MISS', cls: 'miss',
      });
    });
  }

  /* ---------------- 影子对手出招 ---------------- */

  _onGhostHit(evt) {
    if (evt.correct) {
      this._strike(SIDE.FOE, SIDE.ME, {
        power: 1,
        hitStop: TIMING.hitStop.normal,
        damage: evt.damage,
      });
    } else {
      const foe = this.units[SIDE.FOE];
      if (foe) foe.attack({ power: 0.7 });
      this._schedule(impactDelay(), () => {
        this.hud.damageNumber({
          side: SIDE.FOE, ...hitPoint(SIDE.FOE), text: 'MISS', cls: 'miss',
        });
      });
    }
  }

  /* ---------------- 命中编排（所有攻击共用） ---------------- */

  /**
   * @param {'me'|'foe'} atkSide 攻击方
   * @param {'me'|'foe'} defSide 受击方
   * @param {object} o
   * @param {number} o.power    强度（会心 >1）
   * @param {number} o.hitStop  顿帧时长 ms
   * @param {number} [o.damage] 伤害数字（>0 才弹飘字）
   * @param {boolean} [o.crit]
   */
  _strike(atkSide, defSide, { power, hitStop, damage, crit = false }) {
    const attacker = this.units[atkSide];
    const defender = this.units[defSide];
    const at = hitPoint(defSide);
    const dir = attackDir(atkSide);

    if (attacker) attacker.attack({ power });

    const t0 = this._now;
    this.lastImpact = { at: t0 + impactDelay(), side: defSide, power, crit };

    this._schedule(impactDelay(), () => {
      /* ---- 命中帧 ---- */
      this.fx.slash(at, dir, power);
      this.fx.flash(at, power);
      this.fx.shock(at, power);
      this.camera.shake(power);
      this.camera.punch(crit ? power * 1.15 : power);
      this._hitStop(hitStop);
    });

    this._schedule(impactDelay() + hitStop, () => {
      /* ---- 解冻帧：世界开始反应 ---- */
      if (defender) defender.hurt({ power });
      this.fx.dust({ x: at.x, y: 0 }, power);
      if (damage > 0) {
        this.hud.damageNumber({
          side: defSide, ...at,
          text: String(damage),
          cls: crit ? 'crit' : '',
        });
      }
    });
  }

  /* ============================================================
   * 每帧 / 生命周期
   * ============================================================ */

  /**
   * @param {number} scaledMs 世界线 dt（顿帧时为 0）
   * @param {number} rawMs    原始 dt（调度与镜头用）
   */
  update(scaledMs, rawMs) {
    this._now += rawMs;
    this._runDue();
    this.fx.update(scaledMs);
    this.camera.update(rawMs);
  }

  /** 清空时间轴并复位（进/出战斗、RESET 事件） */
  reset() {
    this._pending.length = 0;
    this._hitStopToken++;
    this.host.setTimeScale(1);
    this.fx.clear();
    this.camera.reset();
    this.hud.clear();
    this.lastImpact = null;
  }

  dispose() {
    this.reset();
  }
}
