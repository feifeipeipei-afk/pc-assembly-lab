/**
 * 战斗动画体系 · 最小补间运行时
 * ============================================================
 * 为什么需要它
 * ------------
 * 旧实现里的"动画"是这样写的：
 *
 *     el.classList.add('attack');
 *     setTimeout(() => { el.classList.remove('attack'); }, 520);
 *     setTimeout(() => { hurtEl.classList.add('hurt'); }, 300);
 *     setTimeout(() => { hurtEl.classList.remove('hurt'); }, 780);
 *
 * 这套写法有三个死穴：
 *   1. 时长由 CSS 与 setTimeout 各写一份，两边一旦不一致就"动画没播完就复位"；
 *   2. 定时器没人取消 —— 连点两下出招，前一次的 setTimeout 会把后一次的状态清掉；
 *   3. 只能播放"一个有名字的动画"，无法表达"从当前姿态平滑过渡到某姿态"，
 *      也无法叠加、无法打断、无法变速。
 *
 * Tween 提供最小的可组合时间片：给定时长与缓动，每帧回调一个 0..1 的进度。
 * 它是 P2 的 Timeline / UnitStateMachine 的地基 —— 那两层只负责"什么时候放什么"，
 * "怎么插值"全部复用这里，不重复实现。
 *
 * 设计取舍
 * --------
 * - 时间单位用**毫秒**，与 config.TIMING 保持一致，避免两套单位来回换算；
 * - 不持有任何 DOM / three 对象 —— onUpdate 拿到的是纯数字，由调用方决定怎么用，
 *   因此本模块可单测、可回放；
 * - 显式 `cancel()`，且 TweenGroup 会在 update 时安全摘除，杜绝"回调里增删自身"引发的遍历问题。
 */

/** 线性缓动（默认） */
const linear = (t) => t;

export class Tween {
  /**
   * @param {object} opts
   * @param {number}   [opts.duration] 毫秒；0 表示下一帧立即完成
   * @param {number}   [opts.delay]    毫秒
   * @param {(t:number)=>number} [opts.ease] 缓动，t∈[0,1]
   * @param {(e:number, raw:number)=>void} [opts.onUpdate] e 为缓动后进度
   * @param {()=>void} [opts.onStart]
   * @param {()=>void} [opts.onComplete]
   * @param {string}   [opts.tag]  分组标签，便于批量取消
   * @param {boolean}  [opts.loop] 完成后重新开始
   * @param {boolean}  [opts.yoyo] 完成后反向播放（隐含 loop）
   */
  constructor(opts = {}) {
    this.duration = Math.max(0, opts.duration || 0);
    this.delay = Math.max(0, opts.delay || 0);
    this.ease = opts.ease || linear;
    this.onUpdate = opts.onUpdate || null;
    this.onStart = opts.onStart || null;
    this.onComplete = opts.onComplete || null;
    this.tag = opts.tag || null;
    this.loop = !!opts.loop || !!opts.yoyo;
    this.yoyo = !!opts.yoyo;

    this.time = 0;
    this.direction = 1;
    this.cycles = 0;
    this._started = false;
    this._finished = false;
    this._cancelled = false;

    /** 最近的缓动后进度，便于外部读取当前状态 */
    this.value = 0;
  }

  get finished() { return this._finished || this._cancelled; }

  /** 整体进度（含 delay 段），0..1 */
  get progress() {
    if (this.duration <= 0) return this.time >= this.delay ? 1 : 0;
    return Math.min(1, Math.max(0, (this.time - this.delay) / this.duration));
  }

  /**
   * 推进一帧。
   * @param {number} dtMs 已按 timeScale 缩放过的毫秒数
   * @returns {boolean} 是否仍需继续推进
   */
  update(dtMs) {
    if (this.finished) return false;
    this.time += dtMs;

    if (this.time < this.delay) return true;

    if (!this._started) {
      this._started = true;
      if (this.onStart) this.onStart();
    }

    let raw = this.progress;
    this.value = this.ease(this.direction > 0 ? raw : 1 - raw);
    if (this.onUpdate) this.onUpdate(this.value, raw);

    if (raw >= 1) {
      this.cycles++;
      if (this.loop) {
        /* 回退到 delay 之后重新计时；yoyo 额外翻转方向 */
        if (this.yoyo) this.direction *= -1;
        this.time = this.delay;
      } else {
        this._finished = true;
        if (this.onComplete) this.onComplete();
        return false;
      }
    }
    return true;
  }

  cancel() {
    if (this._finished || this._cancelled) return;
    this._cancelled = true;
  }
}

/**
 * 一组补间。每帧 commit() 时统一推进，并把已完成/已取消的实例摘掉。
 */
export class TweenGroup {
  constructor() {
    /** @type {Set<Tween>} */
    this._items = new Set();
    this._scratch = [];
  }

  get size() { return this._items.size; }

  /**
   * @param {Tween|object} tween Tween 实例或构造参数
   * @returns {Tween}
   */
  add(tween) {
    const t = tween instanceof Tween ? tween : new Tween(tween);
    this._items.add(t);
    return t;
  }

  /** 立即完成某个补间（不触发 onComplete，用于打断） */
  cancel(tween) {
    if (tween) tween.cancel();
    return this;
  }

  /** 按标签批量取消 */
  cancelTag(tag) {
    for (const t of this._items) {
      if (t.tag === tag) t.cancel();
    }
    return this;
  }

  /**
   * 推进全部补间。
   * 先在快照上遍历、再统一摘除 —— 避免 onUpdate/onComplete 里回调
   * 又往集合里增删元素导致遍历行为不确定。
   * @param {number} dtMs
   */
  update(dtMs) {
    if (this._items.size === 0) return;
    this._scratch.length = 0;
    for (const t of this._items) this._scratch.push(t);

    for (let i = 0; i < this._scratch.length; i++) {
      const t = this._scratch[i];
      if (!t.update(dtMs)) this._items.delete(t);
    }
    /* update 期间新加入的实例留在集合里，下一帧再跑 */
    this._scratch.length = 0;
  }

  clear() {
    for (const t of this._items) t.cancel();
    this._items.clear();
  }
}
