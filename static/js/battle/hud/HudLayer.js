/**
 * 战斗动画体系 · HUD 覆盖层（P3）
 * ============================================================
 * "文字永远留在 DOM"是本项目 HUD 分层的铁律（见模板内注释）——
 * 血条/名牌/题目卡如此，three 模式下的伤害飘字、会心横幅、连击提示也一样。
 * 好处：字体渲染与旧版逐像素一致、无 canvas 文字纹理的内存与清晰度问题、
 * 中文排版完全复用旧 CSS。
 *
 * 与旧实现的差别只有一点：**定位方式**。
 *   旧：.bt-dmg 挂在 .bt-unit 里，靠文档流摆位；
 *   新：挂在舞台覆盖层 .battle-hud 里，用 host.worldToScreen() 把
 *       **世界坐标命中点**投影成 CSS 像素 —— canvas 层与 DOM 层唯一的
 *       对齐通道（见 RendererHost.worldToScreen 注释）。
 * 飘字样式类完全复用（.bt-dmg / .bt-crit / #btCombo），观感不变。
 *
 * 覆盖层的尺寸/位置随舞台走（inset:0），不需要 resize 联动；
 * worldToScreen 每次发射时实时取 host.view，天然响应式。
 */

import { TIMING, HUD } from '../config.js';

export class HudLayer {
  /**
   * @param {object} opts
   * @param {import('../renderer/RendererHost.js').RendererHost} opts.host
   * @param {HTMLElement} opts.container .battle-stage（覆盖层挂这里）
   */
  constructor({ host, container }) {
    this.host = host;
    this.container = container;

    /* 覆盖层：绝对定位铺满舞台，永远不挡交互 */
    this.layer = document.createElement('div');
    this.layer.className = 'battle-hud';
    container.appendChild(this.layer);

    /** @type {Set<HTMLElement>} 在飞的飘字，dispose 时统一清 */
    this._pops = new Set();
    this._popTimers = new Set();
    this._comboTimer = null;
    this._critTimer = null;
  }

  /* ------------------------------------------------------------
   * 伤害飘字
   * ------------------------------------------------------------ */

  /**
   * 在世界坐标处弹出伤害/MISS 飘字。
   * @param {object} o
   * @param {'me'|'foe'} o.side   弹给哪一方（决定水平偏移极性与样式习惯）
   * @param {number} o.x          世界 x（一般传站位 x）
   * @param {number} o.y          世界 y（命中点高度）
   * @param {string} o.text       文本（数字或 'MISS'）
   * @param {''|'crit'|'miss'} [o.cls]
   */
  damageNumber({ side, x, y, text, cls = '' }) {
    const off = HUD.damageOffset[side] || { x: 0, y: 0 };
    const p = this.host.worldToScreen(x + off.x, y + off.y);

    const d = document.createElement('div');
    d.className = `${HUD.damageNumberClass} ${cls}`.trim();
    d.textContent = text;
    /* worldToScreen 给的是相对容器左上角的 CSS 像素，直接落到覆盖层 */
    d.style.left = `${Math.round(p.x)}px`;
    d.style.top = `${Math.round(p.y)}px`;
    this.layer.appendChild(d);
    this._pops.add(d);

    /* 动画总时长 dmgPop 1.05s + 余量；DOM 移除走真实计时器
     * （顿帧只冻演出，不冻 HUD —— 文字弹出属于"反馈"而非"世界"） */
    const timer = setTimeout(() => {
      d.remove();
      this._pops.delete(d);
      this._popTimers.delete(timer);
    }, TIMING.damageNumber.total);
    this._popTimers.add(timer);
  }

  /* ------------------------------------------------------------
   * 会心横幅（复用旧 .bt-crit 全屏样式，观感一致）
   * ------------------------------------------------------------ */

  critBanner() {
    const o = document.createElement('div');
    o.className = HUD.critBannerClass;
    o.innerHTML = '<span>会心一击！</span>';
    document.body.appendChild(o);
    const timer = setTimeout(() => {
      o.remove();
      this._critTimer = null;
    }, TIMING.crit.total);
    this._critTimer = timer;
  }

  /* ------------------------------------------------------------
   * 连击提示（复用 #btCombo 元素 —— 旧 DOM 本来就在那里）
   * ------------------------------------------------------------ */

  combo(n) {
    const el = document.getElementById(HUD.comboId);
    if (!el) return;
    el.textContent = n >= 2 ? `${n} 连击！` : '';
    if (this._comboTimer) clearTimeout(this._comboTimer);
    this._comboTimer = setTimeout(() => {
      el.textContent = '';
      this._comboTimer = null;
    }, TIMING.combo.total);
  }

  /* ------------------------------------------------------------
   * 生命周期
   * ------------------------------------------------------------ */

  /** 清空在飞 HUD（RESET / 退出战斗） */
  clear() {
    for (const t of this._popTimers) clearTimeout(t);
    this._popTimers.clear();
    for (const d of this._pops) d.remove();
    this._pops.clear();

    if (this._comboTimer) { clearTimeout(this._comboTimer); this._comboTimer = null; }
    if (this._critTimer) { clearTimeout(this._critTimer); this._critTimer = null; }

    const el = document.getElementById(HUD.comboId);
    if (el) el.textContent = '';
  }

  dispose() {
    this.clear();
    this.layer.remove();
  }
}
