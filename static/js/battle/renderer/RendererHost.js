/**
 * 战斗动画体系 · 渲染宿主
 * ============================================================
 * 职责：把 Three.js 跑起来，并且**只做这一件事**。
 *   - WebGLRenderer 引导（像素风参数：关抗锯齿、NearestFilter 由资源层负责）
 *   - 正交相机与视口（固定高度 / 横向钳制 / 不失真，见 config.computeViewport）
 *   - DPR 处理（旧实现完全没有 → 125%/150% 缩放下像素图被插值糊掉）
 *   - rAF 帧循环 + 单一 dt 时间源（旧实现零 rAF，全靠 CSS 时长与 setTimeout）
 *   - ResizeObserver 响应式（容器尺寸变化也要响应，不只是 window）
 *   - 失焦暂停 / 资源回收
 *
 * 不做：动画编排（那是 anim/* 的事）、场景内容（那是 StageScene 的事）。
 */

import * as THREE from 'three';
import { computeViewport, BUDGET } from '../config.js';
import { probeWebGL } from './probe.js';

/** 单帧最大 dt，防止切回标签页时动画"瞬移" */
const MAX_DT = 0.1;

export class RendererHost {
  /**
   * WebGL 可用性探测（复用 probe.js，保证与 bootstrap 的判断一致）。
   * 注意：bootstrap 走的是 probe.js 的零依赖版本 —— 因为这里已经静态
   * import 了 three，若只在 bootstrap 用本方法，探测前就得先下载 2MB。
   * @returns {{ok: boolean, reason?: string, detail?: string}}
   */
  static probe() {
    return probeWebGL();
  }

  /**
   * @param {HTMLElement} container 承载 canvas 的容器（会读取其 CSS 尺寸）
   * @param {HTMLCanvasElement} canvas 已存在于 DOM 的 canvas（由模板提供，便于 HUD 分层）
   */
  constructor(container, canvas) {
    if (!container) throw new Error('RendererHost: container 不能为空');
    if (!canvas) throw new Error('RendererHost: canvas 不能为空');

    this.container = container;
    this.canvas = canvas;

    this.scene = new THREE.Scene();

    /* 正交相机：初值占位，resize() 会按容器实际尺寸重算 */
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
    this.camera.position.set(0, 0, 100);
    this.camera.lookAt(0, 0, 0);

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      /* 像素风不要抗锯齿：会把像素边缘糊掉，且是纯浪费 */
      antialias: false,
      /* 天空由 StageScene 自己画，这里留透明以便将来做画布叠加 */
      alpha: true,
      premultipliedAlpha: false,
      powerPreference: 'high-performance',
      stencil: false,
      /* depth 保持开启：当前靠 renderOrder 分层，但后续 P5 接入
       * EffectComposer 后处理时，缺深度缓冲会出现意外遮挡问题。 */
      depth: true,
    });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.autoClear = true;

    /* ---- 帧循环状态 ---- */
    this._frameCbs = new Set();
    this._rafId = null;
    this._lastTs = 0;
    this._running = false;
    /** 时间缩放：顿帧 hit-stop 通过把它压到 0 实现（P3 使用） */
    this.timeScale = 1;
    /** 累计运行时间（秒，已受 timeScale 影响） */
    this.elapsed = 0;

    /* ---- 帧率采样（供降档判断） ---- */
    this.fps = 60;
    this._fpsAcc = 0;
    this._fpsFrames = 0;

    /* ---- 当前视口信息（HUD 反投影要用） ---- */
    this.view = computeViewport(1, 1);

    /* ---- 响应式 ---- */
    this._onResize = this._onResize.bind(this);
    this._observer = null;
    if (typeof ResizeObserver !== 'undefined') {
      this._observer = new ResizeObserver(this._onResize);
      this._observer.observe(container);
    } else {
      /* 兜底：老浏览器没有 ResizeObserver */
      window.addEventListener('resize', this._onResize);
    }

    /* ---- 失焦暂停 ---- */
    this._onVisibility = this._onVisibility.bind(this);
    document.addEventListener('visibilitychange', this._onVisibility);

    /* 首帧尺寸 */
    this._onResize();
  }

  /* ============================================================
   * 尺寸与视口
   * ============================================================ */

  _onResize() {
    const rect = this.container.getBoundingClientRect();
    /* 取整：非整数尺寸会让像素图产生额外的重采样模糊 */
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));

    if (w === this._cssW && h === this._cssH) return;
    this._cssW = w;
    this._cssH = h;

    this.view = computeViewport(w, h);

    const { viewW, viewH, centerY } = this.view;
    const halfW = viewW / 2;
    const halfH = viewH / 2;

    this.camera.left = -halfW;
    this.camera.right = halfW;
    this.camera.top = halfH;
    this.camera.bottom = -halfH;
    /* 相机垂直居中于可视范围，同时保持 ground line 被锚定 */
    this.camera.position.set(0, centerY, 100);
    this.camera.lookAt(0, centerY, 0);
    this.camera.updateProjectionMatrix();

    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, BUDGET.maxDpr));
    /* updateStyle=false：canvas 的 CSS 尺寸由样式表控制，不让 three 覆写 */
    this.renderer.setSize(w, h, false);

    this._emitResize();
  }

  /** 供外部（StageScene / HudLayer / CameraDirector）订阅尺寸变化 */
  onResize(cb) {
    return this._sub('_resizeCbs', cb);
  }

  _emitResize() {
    if (!this._resizeCbs) return;
    for (const cb of this._resizeCbs) {
      try { cb(this.view, this._cssW, this._cssH); }
      catch (err) { console.error('[RendererHost] resize 回调异常', err); }
    }
  }

  /* ============================================================
   * 帧循环
   * ============================================================ */

  /**
   * 注册每帧回调
   * @param {(dt:number, dtMs:number, elapsed:number)=>void} cb
   * @returns {()=>void} 取消订阅
   */
  onFrame(cb) {
    this._frameCbs.add(cb);
    return () => this._frameCbs.delete(cb);
  }

  _sub(field, cb) {
    if (!this[field]) this[field] = new Set();
    this[field].add(cb);
    return () => this[field].delete(cb);
  }

  start() {
    if (this._running) return;
    this._running = true;
    this._lastTs = 0;
    this._rafId = requestAnimationFrame(this._loop);
  }

  stop() {
    this._running = false;
    if (this._rafId !== null) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
  }

  _loop = (ts) => {
    if (!this._running) return;
    this._rafId = requestAnimationFrame(this._loop);

    /* 首帧或长时间暂停后 dt 记 0，避免把一大段空档算进动画 */
    if (this._lastTs === 0) this._lastTs = ts;
    let dt = (ts - this._lastTs) / 1000;
    this._lastTs = ts;
    if (dt > MAX_DT) dt = MAX_DT;

    /* 帧率采样 */
    this._fpsAcc += dt;
    this._fpsFrames++;
    if (this._fpsFrames >= BUDGET.sampleWindow) {
      this.fps = this._fpsFrames / Math.max(this._fpsAcc, 1e-6);
      this._fpsAcc = 0;
      this._fpsFrames = 0;
    }

    const scaled = dt * this.timeScale;
    this.elapsed += scaled;

    for (const cb of this._frameCbs) {
      try { cb(scaled, dt * 1000, this.elapsed); }
      catch (err) { console.error('[RendererHost] 帧回调异常', err); }
    }

    this.renderer.render(this.scene, this.camera);
  };

  /* ============================================================
   * 顿帧 / 失焦
   * ============================================================ */

  /** 设置时间缩放（0 = 冻结动画但继续出帧，用于 hit-stop） */
  setTimeScale(v) {
    this.timeScale = Math.max(0, v);
  }

  _onVisibility() {
    if (document.hidden) {
      this.stop();
    } else {
      /* 恢复时清空时间基准，避免把暂停时长算进 dt */
      this._lastTs = 0;
      this.start();
    }
  }

  /* ============================================================
   * 世界坐标 → 屏幕坐标
   * ============================================================ */

  /**
   * 把世界坐标投影到容器内的 CSS 像素坐标。
   * HudLayer 用它定位伤害飘字等 DOM 元素 —— 这是 canvas 层与 DOM 层
   * 唯一的对齐通道，务必与 computeViewport 保持同一套数学。
   * @param {number} wx
   * @param {number} wy
   * @returns {{x:number, y:number}} 相对容器左上角的 CSS 像素
   */
  worldToScreen(wx, wy) {
    const { viewW, viewH, centerY } = this.view;
    const w = this._cssW || 1;
    const h = this._cssH || 1;
    return {
      x: (wx + viewW / 2) / viewW * w,
      /* 世界 y 向上，屏幕 y 向下，故取反 */
      y: (centerY + viewH / 2 - wy) / viewH * h,
    };
  }

  /* ============================================================
   * 释放
   * ============================================================ */

  dispose() {
    this.stop();

    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    } else {
      window.removeEventListener('resize', this._onResize);
    }
    document.removeEventListener('visibilitychange', this._onVisibility);

    this._frameCbs.clear();
    if (this._resizeCbs) this._resizeCbs.clear();

    /* 场景内几何体/材质/贴图由各自模块负责 dispose，
     * 这里只回收渲染器本身与 GL 上下文。 */
    this.renderer.dispose();
    const lose = this.renderer.getContext().getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
  }
}
