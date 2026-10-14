/**
 * 战斗动画体系 · 演出事件契约
 * ============================================================
 * 这层是「业务判定」与「动画演出」之间的唯一接口。
 *
 * 重构背景：
 *   旧实现里 resolveBattleHit() 既算伤害/连击/血量，又直接调 animOnce()、
 *   直接 appendChild 特效、直接 setTimeout 排时序 —— 判定与演出完全焊死在
 *   一个函数里，导致改动画必碰判定逻辑。
 *
 *   现在：业务层只负责「产出事件」，渲染器只负责「消费事件」。
 *   事件对象是纯数据，不含 DOM、不含 three 对象，可测试、可回放、可录制。
 *
 * 后端对齐：影子事件由 app.py 的 _build_shadow / _dummy_shadow 生成，
 *   经 battle_meta.ghost = { events: [{ i, t_ms, correct }], total_time_ms } 下发。
 *   t_ms 为相对开考的毫秒数 —— 本文件提供 fromGhost() 做适配。
 */

/** 事件类型枚举 */
export const EV = {
  /** 我方出招命中/落空 */
  HIT: 'hit',
  /** 影子（异步 PVP 对手）出手 */
  GHOST_HIT: 'ghost_hit',
  /** 会心一击横幅 */
  CRIT: 'crit',
  /** 连击提示刷新 */
  COMBO: 'combo',
  /** 胜负结算演出 */
  VERDICT: 'verdict',
  /** 清空舞台（进/出战斗时调用） */
  RESET: 'reset',
};

/** 出招方 */
export const SIDE = { ME: 'me', FOE: 'foe' };

/** 结算结果 */
export const VERDICT = { WIN: 'win', LOSE: 'lose', DRAW: 'draw', RECORD: 'record' };

/**
 * 我方出招事件
 * @param {object} o
 * @param {boolean} o.correct   是否答对
 * @param {number}  o.damage    本次伤害数值（已四舍五入）
 * @param {number}  [o.combo]   当前连击数
 * @param {boolean} [o.crit]    是否会心一击
 * @param {'battle'|'challenge'|'record'} [o.mode] 战斗模式（决定答错时 Boss 是否反击）
 * @param {number}  [o.index]   第几题（0 基），用于调试与回放
 * @returns {object} 演出事件
 */
export function hitEvent({ correct, damage, combo = 0, crit = false, mode = 'battle', index = -1 }) {
  return {
    type: EV.HIT,
    correct: !!correct,
    damage: Math.max(0, Math.round(damage) || 0),
    combo,
    crit: !!crit,
    mode,
    index,
    /* 答错时：闯关模式 Boss 反击我方；PVP 模式只是出招落空 */
    counter: !correct && mode === 'battle',
    miss: !correct && mode !== 'battle',
  };
}

/**
 * 把后端影子事件适配成演出事件
 * @param {{i:number, t_ms:number, correct:boolean}} ev 后端原始事件
 * @param {number} damage 影子出手的伤害
 * @returns {object} 演出事件
 */
export function ghostEvent(ev, damage) {
  return {
    type: EV.GHOST_HIT,
    correct: !!(ev && ev.correct),
    damage: Math.max(0, Math.round(damage) || 0),
    tMs: ev ? ev.t_ms : 0,
    index: ev ? ev.i : -1,
    miss: !(ev && ev.correct),
  };
}

/**
 * 会心一击事件
 * @param {number} combo 触发时的连击数（旧逻辑在 3/5/8/10 触发）
 */
export function critEvent(combo) {
  return { type: EV.CRIT, combo };
}

/**
 * 连击提示事件
 * @param {number} combo 连击数；<2 表示清空
 */
export function comboEvent(combo) {
  return { type: EV.COMBO, combo };
}

/**
 * 结算事件
 * @param {object} o
 * @param {'win'|'lose'|'draw'|'record'} o.result
 * @param {number} [o.stars] 闯关星级 0-3
 */
export function verdictEvent({ result, stars = 0 }) {
  return { type: EV.VERDICT, result, stars };
}

/** 清空事件 */
export function resetEvent() {
  return { type: EV.RESET };
}

/**
 * 渲染器需实现的接口（契约文档，非运行时校验）
 * ------------------------------------------------------------
 * DomRenderer 与 RendererHost 必须提供同签名方法，bootstrap 才能互换：
 *
 *   play(evt)                 消费一个演出事件
 *   reset()                   清空舞台
 *   setUnits({ me, foe })     设置双方外观身份（名称/图片/影子态）
 *   setEnabled(bool)          启用/停用
 *   dispose()                 释放资源
 *
 * 注意：事件只是「意图」，渲染器有权按自身能力降级表现
 * （例如 DOM 渲染器无法做顿帧与粒子，就只做位移+闪白）。
 */
export const RENDERER_INTERFACE = ['play', 'reset', 'setUnits', 'setEnabled', 'dispose'];
