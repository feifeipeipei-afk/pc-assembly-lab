/**
 * 战斗动画体系 · 镜头导演（P3）
 * ============================================================
 * 在 RendererHost 的正交相机上叠加两层镜头语言：
 *
 *   shake  震屏 —— 命中时的高频随机抖动（旧实现震的是整个 .battle-shell
 *                  DOM 容器，现在震的是真镜头，HUD 文字不再跟着糊成一团）
 *   punch  变焦冲击 —— 命中瞬间轻微 zoom-in 再回弹（TIMING.camera.zoomPunch），
 *                  幅度只有 3.5%，潜意识里"凑近看"却不打扰答题
 *
 * 与 RendererHost 的分工
 * ----------------------
 * Host 负责"基准相机"（视口、中心、updateProjectionMatrix），
 * 本模块只在其上做**每帧偏移**：
 *   position = base + shakeOffset
 *   zoom     = 1 + punchOffset
 * resize 后基准值由 host.onResize 回调重新取 —— 两边永远读同一个真源，
 * 不会出现"窗口一拖震屏基准就漂移"。
 *
 * update 吃未缩放 dt：hit-stop 冻结的是"世界"，镜头仍然活着
 * （抖动继续、回弹继续），否则顿帧会连镜头一起冻住，打击感反而变闷。
 */

import { TIMING } from '../config.js';

export class CameraDirector {
  /**
   * @param {object} opts
   * @param {import('../renderer/RendererHost.js').RendererHost} opts.host
   */
  constructor({ host }) {
    this.host = host;

    /* 基准位（host 的相机位置即基准，resize 会重算） */
    this._baseX = host.camera.position.x;
    this._baseY = host.camera.position.y;
    this._unsubResize = host.onResize(() => {
      this._baseX = host.camera.position.x;
      this._baseY = host.camera.position.y;
    });

    /* 震屏状态：幅度随时间指数衰减，方向逐帧随机 */
    this._shakeAmp = 0;
    this._shakeDecay = 0;      /* ms⁻¹，由时长反推 */
    /* 变焦冲击：in 段快进、out 段慢回（TIMING.camera.punchIn/punchOut） */
    this._punch = 0;
    this._punchPhase = 'idle'; /* 'in' | 'out' */

    this._dirty = false;
  }

  /** 触发震屏（幅度随 power 放大，上限防晕） */
  shake(power = 1) {
    const amp = Math.min(14, 7 * power);
    const ms = TIMING.camera.shake * Math.min(1.4, Math.max(0.8, power));
    /* 指数衰减：3 个时间常数后幅度降到 5%，视为结束 */
    this._shakeAmp = Math.max(this._shakeAmp, amp);
    this._shakeDecay = 3 / Math.max(1, ms);
  }

  /** 触发变焦冲击 */
  punch(power = 1) {
    this._punch = TIMING.camera.zoomPunch * Math.min(1.6, power);
    this._punchPhase = 'in';
    this._punchT = 0;
  }

  /**
   * @param {number} dtMs 未缩放的毫秒（镜头不受顿帧影响，见文件头）
   */
  update(dtMs) {
    const cam = this.host.camera;
    const dt = Math.min(dtMs, 100);
    let moved = false;

    /* ---- 震屏 ---- */
    let sx = 0, sy = 0;
    if (this._shakeAmp > 0.05) {
      /* 随机方向 × 当前幅度；幅度指数衰减 */
      const decay = Math.exp(-this._shakeDecay * dt);
      this._shakeAmp *= decay;
      sx = (Math.random() * 2 - 1) * this._shakeAmp;
      sy = (Math.random() * 2 - 1) * this._shakeAmp * 0.6;
      moved = true;
    } else {
      this._shakeAmp = 0;
    }

    /* ---- 变焦 ---- */
    let zoomOffset = 0;
    if (this._punchPhase !== 'idle') {
      this._punchT += dt;
      if (this._punchPhase === 'in') {
        const t = Math.min(1, this._punchT / TIMING.camera.punchIn);
        zoomOffset = this._punch * t;               /* 快速推近 */
        if (t >= 1) { this._punchPhase = 'out'; this._punchT = 0; }
      } else {
        const t = Math.min(1, this._punchT / TIMING.camera.punchOut);
        zoomOffset = this._punch * (1 - t);         /* 缓慢回弹 */
        if (t >= 1) { this._punchPhase = 'idle'; zoomOffset = 0; }
      }
      moved = true;
    }

    /* ---- 应用（只有动过才写相机，省 updateProjectionMatrix） ---- */
    if (moved || this._dirty) {
      cam.position.set(this._baseX + sx, this._baseY + sy, cam.position.z);
      const zoom = 1 + zoomOffset;
      if (Math.abs(cam.zoom - zoom) > 1e-6) {
        cam.zoom = zoom;
        cam.updateProjectionMatrix();
      }
      this._dirty = moved; /* 有活跃效果时下一帧也要复位判定 */
    }
  }

  /** 立即复位（RESET / dispose） */
  reset() {
    this._shakeAmp = 0;
    this._punch = 0;
    this._punchPhase = 'idle';
    const cam = this.host.camera;
    cam.position.set(this._baseX, this._baseY, cam.position.z);
    if (cam.zoom !== 1) {
      cam.zoom = 1;
      cam.updateProjectionMatrix();
    }
    this._dirty = false;
  }

  dispose() {
    this.reset();
    if (this._unsubResize) { this._unsubResize(); this._unsubResize = null; }
  }
}
