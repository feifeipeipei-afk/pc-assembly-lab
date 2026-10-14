/**
 * 战斗动画体系 · 全局配置
 * ============================================================
 * 这里是所有"魔法数字"的唯一出处。
 *
 * 重构背景：旧实现把时序参数（300 / 400 / 520 / 900 / 1100 / 1400 / 2200 …）
 * 硬编码散落在 resolveBattleHit() 与 ghostHit() 里，改一次节奏要动好几处。
 * 现统一收敛到本文件，调参只改这里。
 *
 * 依赖：无（纯常量，不 import three）
 * 被依赖：battle/ 下几乎所有模块
 */

/* ------------------------------------------------------------
 * 一、世界坐标系与视口
 * ------------------------------------------------------------
 * **1 世界单位 = 1 CSS 像素**（在 scale=1 时）。
 *
 * 为什么不能用"固定设计高度 + 按 aspect 展开"（P0 的做法）
 * --------------------------------------------------------
 * P0 曾把视口高度钉在 DESIGN_H、宽度按 aspect 展开并钳制到 1400，
 * 于是 pxPerUnit = 容器宽 / 1400 —— 角色大小会随窗口宽度漂移：
 *   窗口 1000px → 角色 143px；1440px → 206px；1920px → 274px
 * 而旧 CSS 里 `.bt-sprite` 恒为 200x200。背景是纯渐变，缩放看不出来，
 * 所以 P0 阶段这个缺陷是隐形的；角色一上屏就立刻暴露成"大小对不上"。
 *
 * 改成 1:1 之后：
 *   - 角色 = 200 CSS 像素，与旧 `.bt-sprite` 完全一致；
 *   - 地面条 = GROUND_H(74) 像素，与旧 `.battle-stage::after` 完全一致；
 *   - 站位 ±UNIT_X(274)，与旧 `.battle-units(max-width:720px)` 完全一致；
 *   - canvas 与 DOM 覆盖层天然对齐，HUD 定位不需要任何补偿。
 *
 * 窄屏时整体等比缩小（scale < 1），避免角色被挤出舞台。
 */
export const GROUND_H = 74;        // 地面条高度，对应旧 .battle-stage::after
export const GRID_SIZE = 44;       // 网格线间距，对应旧 background-size:44px 44px

/** 舞台设计宽度：旧 `.battle-units` 的 max-width:720 + 两侧 padding 14*2 */
export const STAGE_W_DESIGN = 748;
/** 窄屏最小缩放，再小就不缩了（宁可裁切也不要角色变成蚂蚁） */
export const MIN_STAGE_SCALE = 0.62;

/* 保留旧名以免外部引用断裂；新代码请直接用上面三个常量 */
export const DESIGN_W = STAGE_W_DESIGN;
export const DESIGN_H = 562;

/** 视口下缘：恒为 -GROUND_H，保证地面线永远贴住舞台底部 */
export const VIEW_BOTTOM_Y = -GROUND_H;

/**
 * 计算当前容器尺寸下的正交视口。
 * ------------------------------------------------------------
 * 规则：
 *   1. scale = clamp(容器宽 / STAGE_W_DESIGN, MIN_STAGE_SCALE, 1)
 *      —— 宽屏恒为 1（1 世界单位 = 1 CSS 像素），窄屏整体等比缩小；
 *   2. 视口尺寸 = 容器尺寸 / scale，因此 pxPerUnit 恒等于 scale；
 *   3. 视口下缘恒锚定 VIEW_BOTTOM_Y → 高度变化时地面线不动，
 *      角色始终"踩在地上"，只是天空可见范围伸缩。
 *
 * RendererHost（投影）与 HUD 层（反投影）必须共用本函数，
 * 否则 canvas 与 DOM 覆盖层会对不齐 —— 这是唯一的投影真源。
 *
 * @param {number} stageW 容器 CSS 宽度（px）
 * @param {number} stageH 容器 CSS 高度（px）
 * @returns {{viewW:number, viewH:number, bottom:number, top:number,
 *            centerY:number, scale:number, pxPerUnit:number}}
 */
export function computeViewport(stageW, stageH) {
  const w = Math.max(1, stageW);
  const h = Math.max(1, stageH);

  const scale = Math.min(1, Math.max(MIN_STAGE_SCALE, w / STAGE_W_DESIGN));

  const viewW = w / scale;
  const viewH = h / scale;

  const bottom = VIEW_BOTTOM_Y;
  const top = bottom + viewH;

  return {
    viewW,
    viewH,
    bottom,
    top,
    centerY: (top + bottom) / 2,
    scale,
    /* 1 世界单位对应多少 CSS 像素 —— HUD 定位时要用 */
    pxPerUnit: scale,
  };
}

/* 单位站位（对应旧 .battle-units max-width:720px + space-between）
 * 720 行内，foe/me 两个 .bt-unit(172px) 贴边 → 中心距中心 360-86=274 */
export const UNIT_X = 274;
export const SLOT_SIDE = { ME: 1, FOE: -1 };
export const UNIT_SIZE = 200;      // 角色精灵显示尺寸（对应旧 .bt-sprite 200x200）

/* ------------------------------------------------------------
 * 三、图层（z 深度 + renderOrder）
 * ------------------------------------------------------------
 * z 越小越靠后。renderOrder 在同一 z 下决定绘制次序。
 */
export const LAYERS = {
  SKY:        { z: -100, renderOrder: 0 },
  GRID:       { z: -95,  renderOrder: 1 },
  GROUND:     { z: -90,  renderOrder: 2 },
  SHADOW:     { z: -80,  renderOrder: 3 },
  UNIT_BACK:  { z: -20,  renderOrder: 10 },
  UNIT:       { z: 0,    renderOrder: 20 },
  FX_BACK:    { z: 10,   renderOrder: 30 },
  FX:         { z: 20,   renderOrder: 40 },
  FX_FRONT:   { z: 30,   renderOrder: 50 },
};

/* ------------------------------------------------------------
 * 四、配色（全部取自旧战斗 CSS，保证换渲染器后视觉延续）
 * ------------------------------------------------------------ */
export const COLORS = {
  skyTop:    0x24321f,
  skyMid:    0x2e4026,
  skyBottom: 0x1a2416,
  grid:      0x3a582e,       // 旧 rgba(58,88,46,.35)
  gridAlpha: 0.35,
  /* 旧 .battle-stage::before 自带 opacity:.5，这里给出乘算后的有效值 */
  gridEffectiveAlpha: 0.175,
  groundTop:    0x4a6a3a,
  groundMid:    0x3a5430,
  groundBottom: 0x2a3f22,
  groundEdge:   0x23351c,
  groundEdgeW:  3,           // 旧 border-top: 3px
  hpHigh: 0x7cef9a,
  hpLow:  0xd43c3c,
  gold:   0xffd76e,
  goldDim: 0xd8b04a,
};

/**
 * 取色的原始 sRGB 分量（0..1），**绕过 Three.js 颜色管理**。
 * ------------------------------------------------------------
 * 坑：THREE.ColorManagement 默认开启，`new THREE.Color(0x24321f)` 会把
 * hex 当成 sRGB 并转成 Linear-sRGB 存起来（r≈0.016 而不是 0.141）。
 * 我们的背景是自定义 ShaderMaterial，没有 include three 的
 * colorspace_fragment 转换块 → 直接写 gl_FragColor 就是最终帧缓冲值。
 *
 * 因此：若用 THREE.Color 的线性分量，画面会比旧 CSS 暗一大截；
 * 用本函数取原始 sRGB 分量，则与旧 CSS 颜色**逐字节一致**，
 * 迁移期间新旧两版背景肉眼无差。
 *
 * @param {number} hex 0xRRGGBB
 * @returns {[number, number, number]} sRGB 分量 0..1
 */
export function srgbTriplet(hex) {
  return [
    ((hex >> 16) & 0xff) / 255,
    ((hex >> 8) & 0xff) / 255,
    (hex & 0xff) / 255,
  ];
}

/* ------------------------------------------------------------
 * 五、时序（单位：毫秒）
 * ------------------------------------------------------------
 * 每项末尾的 total 是「整段演出时长」，Timeline 以它为调度基准。
 * 旧值已标注在注释里，便于对照回归。
 */
export const TIMING = {
  /* 顿帧 hit-stop：命中瞬间冻结时间，制造打击感。
   * 旧实现完全没有这一层，这是"打击感廉价"的主因之一。 */
  hitStop: { normal: 55, crit: 110 },

  /* 出招：蓄力 → 挥击 → 收招（旧：整体 520ms 单段位移） */
  attack: { windup: 120, strike: 180, recover: 200, total: 500 },

  /* 受击：后仰 → 回弹 → 复位（旧：btHurt .45s） */
  hurt: { knock: 90, recoil: 180, recover: 210, total: 480 },

  /* 命中反馈物 */
  impact: {
    slashLife:  400,   // 旧：slash setTimeout 400
    flashLife:  260,
    shockLife:  520,
    dustLife:   700,
  },

  /* 伤害飘字（旧：dmgPop 1.05s + setTimeout remove 1100） */
  damageNumber: { rise: 780, hold: 180, fade: 240, total: 1200 },

  /* 会心一击横幅（旧：critPop .85s + setTimeout remove 900） */
  crit: { bannerIn: 180, bannerHold: 480, bannerOut: 240, total: 900 },

  /* 连击提示（旧：flashCombo 2200ms 后清空） */
  combo: { show: 300, hold: 1600, fade: 300, total: 2200 },

  /* 镜头 */
  camera: { shake: 380, punchIn: 220, punchOut: 360, zoomPunch: 0.035 },

  /* 流程节奏 */
  advanceDelay: 1400,   // 旧：scheduleBattleAdvance 硬编码 1400
  submitDelay:  1500,   // 旧：answered>=total 后 1500 才交卷
  verdictIn:     700,   // 旧：critPop2 .7s

  /* 影子回放轮询粒度。
   * 旧实现 startGhostEngine 用 setInterval(...,1000) 且 ghostElapsed += 1000，
   * 导致对手连对时"整步掉血"。真实 t_ms 是毫秒级，这里提到 50ms。 */
  ghostPollMs: 50,

  /* 待机呼吸（旧：btIdle 2.2s infinite） */
  idleBreath: 2200,
};

/* ------------------------------------------------------------
 * 六、缓动函数
 * ------------------------------------------------------------
 * 取代旧 CSS 里的 cubic-bezier 魔法值。
 * 带注释的是与旧 keyframes 的对应关系，便于视觉回归。
 */
export const EASE = {
  linear: (t) => t,

  quadIn:  (t) => t * t,
  quadOut: (t) => 1 - (1 - t) * (1 - t),

  cubicIn:  (t) => t * t * t,
  cubicOut: (t) => 1 - Math.pow(1 - t, 3),

  /* 对应旧 bt-hpfill / sb-me 的 cubic-bezier(.2,.8,.3,1) */
  smoothOut: (t) => 1 - Math.pow(1 - t, 2.4),

  /* 对应旧 btLunge 的 cubic-bezier(.3,1.4,.5,1) —— 带过冲，突进更"冲" */
  backOut: (t) => {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },

  /* 对应旧 starPop 的 cubic-bezier(.2,1.6,.4,1) —— 弹性回弹 */
  backOutStrong: (t) => {
    const c1 = 2.9;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },

  inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
};

/* ------------------------------------------------------------
 * 七、性能预算与降级
 * ------------------------------------------------------------ */
export const BUDGET = {
  maxDpr: 2,              // 课堂机核显友好；也避免像素图被过度放大
  maxParticles: 600,      // 常态同屏粒子上限
  maxParticlesBurst: 1200,// 会心等爆发瞬间上限
  degradeFps: 45,         // 低于此帧率触发降档
  recoverFps: 57,         // 高于此帧率尝试回档
  sampleWindow: 90,       // 帧率采样窗口（帧数）
};

/* ------------------------------------------------------------
 * 八、渲染器开关
 * ------------------------------------------------------------ */
export const RENDERER = {
  THREE: 'three',
  DOM: 'dom',
  /** 默认 dom：安全上线，不带参数时行为与重构前完全一致 */
  DEFAULT: 'dom',
  /** URL 参数名：?renderer=three */
  QUERY_KEY: 'renderer',
  STORAGE_KEY: 'quizBattleRenderer',
};

/* ------------------------------------------------------------
 * 九、HUD
 * ------------------------------------------------------------ */
export const HUD = {
  damageNumberClass: 'bt-dmg',   // 复用旧样式，保证文字观感不变
  critBannerClass: 'bt-crit',
  comboId: 'btCombo',
  /** 伤害飘字相对命中点的世界坐标偏移 */
  damageOffset: { foe: { x: 0, y: UNIT_SIZE + 4 }, me: { x: 0, y: UNIT_SIZE + 4 } },
};

/* ------------------------------------------------------------
 * 十、角色切图骨骼（rig）
 * ------------------------------------------------------------
 * 资产由 `py tools/build_battle_assets.py` 生成：
 *   static/battle/atlas/battle_atlas.png/.json
 * 元数据里每个部件带 rect（源图像素矩形）、region（图集像素矩形）、
 * pivot（关节位置，源图像素）、parent、z。运行时的换算全在 UnitView 里。
 */
export const RIG = {
  atlasUrl: '/static/battle/atlas/battle_atlas.png',
  metaUrl: '/static/battle/atlas/battle_atlas.json',

  /**
   * 旧 `.bt-sprite` 是 200x200 的框 + `object-fit:contain`，
   * 源图 372x372 因此等比缩放 → 世界单位/源像素 = 200/372 = 0.5376。
   * 沿用这个比例，三只角色在新旧渲染器下的相对大小关系完全一致。
   */
  unitBox: 200,

  /**
   * 这三张源图**不是像素画**：372x372 里有 18839 种颜色、138384 像素中
   * 112902 个是半透明 —— 是带抗锯齿柔边的平滑插画。
   * 所以不能用 NearestFilter（会把柔边切成锯齿），必须线性过滤；
   * 也因此不需要做整数像素对齐（对平滑图没有意义）。
   */
  filter: 'linear',
  mipmap: true,
  anisotropy: 4,
  /** 丢弃近乎全透明的像素，省一半片元着色 */
  alphaTest: 0.04,

  /**
   * 待机呼吸 —— 取代旧 `@keyframes btIdle`（2.2s / translateY(-5px) / rotate(-1.2deg)）。
   * 旧版把这套变换施加在整张图上，所以只有"整体上下浮 + 整体微倾"一种表现。
   * 新版拆成「根 + 躯干 + 头 + 双臂」四层，各自相位错开，看起来才像活的。
   */
  idle: {
    period: 2200,        // 与旧 btIdle 同周期，便于对照
    bodyLift: 5,         // 世界单位；旧 translateY(-5px)
    bodyTilt: 1.2,       // 度；旧 rotate(-1.2deg)
    rootShare: 0.55,     // 浮动量中分给根节点的比例（其余给躯干）
    headLag: 0.14,       // 头部相位滞后（周期比例）
    headExtra: 0.75,     // 头部额外摆幅倍数
    headLift: 0.8,       // 头部额外位移（世界单位）
    armLag: 0.22,
    armSwing: 1.8,       // 度
    weaponLag: 0.28,
    weaponSwing: 2.4,    // 度
    breatheY: 0.010,     // 躯干纵向缩放 ±1.0%
    breatheX: -0.006,    // 横向反向，保持体积感
  },

  /**
   * 部件旋转幅度上限（度）。这不是硬性钳制，而是给 P2/P3 编排时的参考量级 ——
   * 超出这些角度，切图 rig 的关节处就会露出明显形变。
   */
  limits: { head: 16, torso: 14, arm: 80, weapon: 210, leg: 24 },

  /** 受击闪白与击退（P1 的基础反馈；完整演出由 P3 的编排器接管） */
  react: {
    flashLife: 200,      // ms，旧 btHurt 用 filter:brightness 闪 450ms
    knockback: 16,       // 世界单位
    knockbackMs: 320,
  },
};

/* ------------------------------------------------------------
 * 十一、命名姿势（P1 的调试/校验用）
 * ------------------------------------------------------------
 * 全部是「加法增量」，叠加在待机层之上。角度单位为度，
 * 位移单位为世界单位。leanSign / armSign 来自 rig 元数据 ——
 * 勇者朝左、魔王朝右，同一个"向后退"在两套美术里旋转方向相反。
 *
 * P3 的 BattleChoreographer 会用时间轴编排这些姿势，本表是它的素材。
 */
export const POSES = {
  rest: {},

  /** 蓄力：重心后坐、持械臂抬起 */
  windup: {
    torso: { rot: -6, y: -1.5 },
    head: { rot: 4 },
    arm: { rot: 32, y: 2 },
    weapon: { rot: 40 },
    leg: { sx: 0.01, sy: -0.008 },
  },

  /** 挥击：重心前压、持械臂抡下 */
  strike: {
    torso: { rot: 9, y: 1.5, sx: 0.02, sy: -0.015 },
    head: { rot: -6 },
    arm: { rot: -30, y: -1 },
    weapon: { rot: -46 },
  },

  /** 受击：后仰、头甩、短暂僵直 */
  hurt: {
    torso: { rot: -11, y: -2, sy: 0.03, sx: 0.02 },
    head: { rot: 13 },
    arm: { rot: 14 },
    weapon: { rot: 18 },
  },

  /** 会心：大幅前压 + 全身拉伸 */
  crit: {
    torso: { rot: 13, y: 3, sx: -0.03, sy: 0.05 },
    head: { rot: -9, y: 2 },
    arm: { rot: -42, y: -2 },
    weapon: { rot: -64 },
    leg: { sx: -0.02, sy: 0.04 },
  },

  /** 收势：略微下沉，呼吸还没接上来的那一瞬 */
  settle: {
    torso: { rot: 3, y: -1, sx: 0.015, sy: -0.02 },
    head: { rot: 2 },
    arm: { rot: -6 },
    weapon: { rot: -8 },
  },
};
