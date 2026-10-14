/**
 * 战斗动画体系 · 单位视图（切图骨骼）
 * ============================================================
 * 一个 UnitView = 一个可动的角色实体。它把 RigLoader 给的静态部件
 * 组装成「骨骼链」，并负责每帧把姿势解算到各个关节上。
 *
 * 旧实现 vs 新实现
 * ----------------
 * 旧：一张 PNG，`.bt-sprite` 上挂 CSS animation。
 *     攻击 = 整张图 translateX(±44px)；受击 = 整张图 brightness 闪白。
 *     → 角色像一块被推来推去的纸板，没有任何一个关节在动。
 *
 * 新：7 个部件各自挂在 joint 节点下，每个节点有独立的位置/旋转/缩放。
 *     攻击 = 躯干前压 + 肩关节抡臂 + 武器绕握把甩出去，同时根节点前冲。
 *     → 同一个动作里有 4 个不同节奏的关节在动，这才是"手感"的来源。
 *
 * 加法分层（additive layers）
 * --------------------------
 * 最终姿势 = base + idle + action 三层相加：
 *   base   : rig 自带的静止姿态（各部件位移只来自 pivot 差值）
 *   idle   : 每帧程序化生成的呼吸/摆动，永远在跑
 *   action : 演出层，由姿势轨道（tween）写入，P3 的编排器接管
 *
 * 分开的好处：出招时呼吸不会被打断，回位后呼吸自然接上，
 * 不需要写"动作播完再恢复待机"这种状态胶水 —— 旧 CSS 方案正是因为
 * 没有分层，才只能靠 setTimeout 硬切。
 *
 * 姿态数值约定
 * ------------
 *   rot : 度（正 = 屏幕逆时针，因为世界 y 轴向上）
 *   x/y : 世界单位
 *   sx/sy: 缩放增量（0 表示原始大小）
 */

import * as THREE from 'three';
import { RIG, LAYERS, POSES, EASE, TIMING } from '../config.js';
import { TweenGroup } from '../anim/Tween.js';

const DEG = Math.PI / 180;

/* 每层姿势的字段模板 */
function zeroDelta() {
  return { rot: 0, x: 0, y: 0, sx: 0, sy: 0 };
}

/* ------------------------------------------------------------
 * 地面接触阴影（所有单位共用一份，无实例状态）
 * ------------------------------------------------------------ */
let SHADOW_GEO = null;
let SHADOW_MAT = null;

function shadowResources() {
  if (SHADOW_GEO) return { geo: SHADOW_GEO, mat: SHADOW_MAT };

  SHADOW_GEO = new THREE.PlaneGeometry(1, 1);
  SHADOW_MAT = new THREE.ShaderMaterial({
    uniforms: { uOpacity: { value: 1 } },
    vertexShader: /* glsl */`
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */`
      uniform float uOpacity;
      varying vec2 vUv;
      void main() {
        vec2 d = vUv * 2.0 - 1.0;
        /* 椭圆软边：中心实、边缘化开。用两次方衰减压暗外圈 */
        float r = length(d);
        float a = smoothstep(1.0, 0.1, r);
        gl_FragColor = vec4(0.0, 0.0, 0.0, a * a * 0.55 * uOpacity);
      }
    `,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  });
  return { geo: SHADOW_GEO, mat: SHADOW_MAT };
}

export function disposeSharedShadow() {
  if (SHADOW_GEO) { SHADOW_GEO.dispose(); SHADOW_GEO = null; }
  if (SHADOW_MAT) { SHADOW_MAT.dispose(); SHADOW_MAT = null; }
}

/* ============================================================ */

export class UnitView {
  /**
   * @param {object} opts
   * @param {import('./RigLoader.js').RigSet} opts.rigSet
   * @param {'me'|'foe'} opts.side        阵位（决定被击退的方向）
   * @param {number} [opts.phase]         待机相位偏移 0..1，避免双方同频呼吸
   */
  constructor({ rigSet, side, phase = 0 }) {
    this.rigSet = rigSet;
    this.side = side;
    /** 击退方向：我方在右、敌方在左，被打时向外推 */
    this.pushDir = side === 'me' ? 1 : -1;
    this.phase = phase;

    this.root = new THREE.Group();
    this.root.name = `unit-${side}`;

    /** 每个部件：{ name, parentName, node, mesh, rest } */
    this.parts = [];
    this.nodes = new Map();

    this.material = null;
    this.shadow = null;

    this._unitName = null;
    this.meta = null;

    /** 三层姿势 */
    this.idle = { __root: zeroDelta() };
    this.action = { __root: zeroDelta() };

    this.tweens = new TweenGroup();

    /** 非满饱度（影子对手用 0） */
    this._saturate = 1;
    this._flash = 0;
    this._opacity = 1;
  }

  /* ============================================================
   * 构建 / 换装
   * ============================================================ */

  /**
   * 换上某个角色的骨骼（hero / boss / dummy）。重复调用同一角色是空操作。
   * @param {string} unitName
   */
  setUnit(unitName) {
    if (this._unitName === unitName) return;
    this._teardownParts();

    const meta = this.rigSet.unit(unitName);
    this._unitName = unitName;
    this.meta = meta;

    if (!this.material) this.material = this.rigSet.material();

    /* 按 z 升序构建；父部件一定先于子部件出现（builder 已保证 z 与层级一致） */
    const list = this.rigSet.partsOf(unitName);
    for (const p of list) {
      const node = new THREE.Group();
      node.name = `${unitName}-${p.name}`;

      const mesh = new THREE.Mesh(this.rigSet.geometry(unitName, p.name), this.material);
      const off = this.rigSet.meshOffset(unitName, p.name);
      mesh.position.set(off.x, off.y, 0);
      /* 不变量：所有部件的绘制次序只由 renderOrder 决定 */
      mesh.renderOrder = LAYERS.UNIT.renderOrder + p.z;
      mesh.frustumCulled = false;
      node.add(mesh);

      const delta = this.rigSet.pivotDelta(unitName, p.name);
      node.position.set(delta.x, delta.y, 0);

      const parentNode = p.parent ? this.nodes.get(p.parent) : this.root;
      if (!parentNode) {
        throw new Error(`角色「${unitName}」部件「${p.name}」的父部件「${p.parent}」未先于它构建`);
      }
      parentNode.add(node);

      const rec = {
        name: p.name,
        parentName: p.parent || null,
        node,
        mesh,
        rest: { x: delta.x, y: delta.y },
        z: p.z,
      };
      this.parts.push(rec);
      this.nodes.set(p.name, node);
    }

    /* 本轮涉及的部件名，用于姿势解算（含虚拟的 __root） */
    this._slots = ['__root', ...this.parts.map((p) => p.name)];
    for (const k of this._slots) {
      if (!this.idle[k]) this.idle[k] = zeroDelta();
      if (!this.action[k]) this.action[k] = zeroDelta();
    }

    /* 武器臂 / 腿部件组（姿势表里的 arm / leg 是逻辑名，需要展开成实际部件名） */
    this._armPart = meta.weaponArm || null;
    this._legParts = this.parts
      .filter((p) => p.name.startsWith('leg'))
      .map((p) => p.name);
    if (this._legParts.length === 0 && this.nodes.has('post')) this._legParts = ['post'];

    this._ensureShadow();
    this._apply();
  }

  _ensureShadow() {
    if (this.shadow) return;
    const { geo, mat } = shadowResources();
    this.shadow = new THREE.Mesh(geo, mat);
    this.shadow.name = `shadow-${this.side}`;
    this.shadow.renderOrder = LAYERS.SHADOW.renderOrder;
    this.shadow.frustumCulled = false;
    const w = RIG.unitBox * 0.62;
    const h = w * 0.22;
    this.shadow.scale.set(w, h, 1);
    /* 落在地面线**内侧**：角色脚底在世界 y=0，地面条是 y∈[-74,0] 的一块
     * 浅色地板。阴影若放在 y>0 就画到天空上去了（几乎看不见），
     * 放在略小于 0 的位置才是"投在地板上的影子"。 */
    this.shadow.position.set(0, -7, 0);
  }

  /** 把 shadow 挂到目标容器（与 root 同级，这样它不会被角色的缩放/旋转带歪） */
  attachTo(parent) {
    if (this.root.parent !== parent) parent.add(this.root);
    if (this.shadow && this.shadow.parent !== parent) parent.add(this.shadow);
  }

  /**
   * 设置外观身份。
   * @param {object} id
   * @param {string} id.unit     角色类型（hero/boss/dummy）
   * @param {boolean} [id.ghost] 是否为影子对手（去色）
   * @param {number} [id.phase]
   */
  setIdentity(id = {}) {
    const unit = id.unit || this._unitName || 'hero';
    this.setUnit(unit);
    this.setSaturate(id.ghost ? 0 : 1);
    if (typeof id.phase === 'number') this.phase = id.phase;
  }

  _teardownParts() {
    for (const rec of this.parts) {
      rec.node.remove(rec.mesh);
      /* 几何体由图集缓存共享，这里不能 dispose */
      rec.node.removeFromParent();
    }
    this.parts.length = 0;
    this.nodes.clear();
    this._slots = ['__root'];
  }

  /* ============================================================
   * 姿势解算
   * ============================================================ */

  /**
   * 把"逻辑姿势"展开成"实际部件增量"。
   * 姿势表里用的是 arm / leg 这类逻辑名，且旋转方向要按角色朝向取符号 ——
   * 勇者面朝左、魔王朝右，同一个"向后仰"在两套美术里的旋转方向是相反的，
   * 所以符号从 rig 元数据的 leanSign / armSign 读，不在这里硬编码。
   */
  _expandPose(pose, intensity = 1) {
    const out = {};
    const m = this.meta || {};
    const push = (part, d) => {
      if (!this.nodes.has(part)) return;
      const cur = out[part] || (out[part] = zeroDelta());
      cur.rot += d.rot; cur.x += d.x; cur.y += d.y; cur.sx += d.sx; cur.sy += d.sy;
    };

    for (const [key, raw] of Object.entries(pose || {})) {
      const d = {
        rot: (raw.rot || 0) * intensity,
        x: (raw.x || 0) * intensity,
        y: (raw.y || 0) * intensity,
        sx: (raw.sx || 0) * intensity,
        sy: (raw.sy || 0) * intensity,
      };
      const lean = m.leanSign || 1;
      const arm = m.armSign || 1;

      if (key === 'arm') {
        if (!this._armPart) continue;
        d.rot *= arm;
        push(this._armPart, d);
      } else if (key === 'weapon') {
        if (!this.nodes.has('weapon')) continue;
        d.rot *= arm;
        push('weapon', d);
      } else if (key === 'leg') {
        d.rot *= lean;
        for (const name of this._legParts) push(name, d);
      } else if (key === 'torso' || key === 'head') {
        d.rot *= lean;
        push(key, d);
      } else {
        push(key, d);
      }
    }
    return out;
  }

  /** 生成一个全零的、覆盖所有部件 + __root 的姿势容器 */
  _zeroAction() {
    const out = {};
    for (const k of this._slots) out[k] = zeroDelta();
    return out;
  }

  _snapshot() {
    const out = {};
    for (const k of this._slots) out[k] = { ...this.action[k] };
    return out;
  }

  _blend(from, to, v) {
    for (const k of this._slots) {
      const a = this.action[k];
      const f = from[k] || a;
      const t = to[k] || f;
      a.rot = f.rot + (t.rot - f.rot) * v;
      a.x = f.x + (t.x - f.x) * v;
      a.y = f.y + (t.y - f.y) * v;
      a.sx = f.sx + (t.sx - f.sx) * v;
      a.sy = f.sy + (t.sy - f.sy) * v;
    }
  }

  /**
   * 摆出一个命名姿势（立即生效，不补间）。调试与校验用。
   * @param {keyof POSES} name
   * @param {number} [intensity]
   */
  setPose(name, intensity = 1) {
    const target = this._zeroAction();
    const expanded = this._expandPose(POSES[name] || {}, intensity);
    for (const k of this._slots) {
      if (expanded[k]) Object.assign(target[k], expanded[k]);
    }
    for (const k of this._slots) Object.assign(this.action[k], target[k]);
    this._apply();
  }

  /**
   * 播放一段姿势轨道（关键帧序列），这是 P3 编排器的执行原语。
   *
   * @param {Array<{pose:string, dur:number, ease?:Function, intensity?:number, rootX?:number}>} segments
   * @param {object} [opts]
   * @param {string} [opts.tag]       轨道标签，同标签的新轨道会打断旧轨道
   * @param {number} [opts.intensity] 整段强度倍率
   */
  playTrack(segments, opts = {}) {
    const tag = opts.tag || 'pose';
    const intensity = opts.intensity ?? 1;
    this.tweens.cancelTag(tag);

    let from = this._snapshot();
    let delay = 0;
    for (const seg of segments) {
      const to = this._zeroAction();
      const expanded = this._expandPose(POSES[seg.pose] || {}, seg.intensity ?? intensity);
      for (const k of this._slots) {
        if (expanded[k]) Object.assign(to[k], expanded[k]);
      }
      if (seg.rootX) to.__root.x += seg.rootX;
      if (seg.rootY) to.__root.y += seg.rootY;

      this.tweens.add({
        delay,
        duration: Math.max(0, seg.dur || 0),
        ease: seg.ease || EASE.quadOut,
        tag,
        onUpdate: (v) => this._blend(from, to, v),
      });

      from = to;
      delay += seg.dur || 0;
    }
  }

  /* ============================================================
   * 受击反馈（P1 的基础版；完整演出由 P3 编排器接管）
   * ============================================================ */

  /**
   * 闪白。旧实现用 `filter: brightness()` 作用于整张图，
   * 这里改成片元着色器插值到白色，不受图片本身明暗影响，且能和去色叠加。
   * @param {number} [ms]
   */
  hitFlash(ms = RIG.react.flashLife) {
    this.setFlash(0.85);
    this.tweens.cancelTag('flash');
    this.tweens.add({
      duration: Math.max(1, ms),
      tag: 'flash',
      ease: EASE.quadOut,
      onUpdate: (v) => this.setFlash(0.85 * (1 - v)),
      onComplete: () => this.setFlash(0),
    });
  }

  /**
   * 受击：闪白 + 后仰 + 击退 + 回弹。
   * 时序取 TIMING.hurt（knock 90 / recoil 180 / recover 210），
   * 编排器在"解冻帧"调用本方法，与顿帧正好衔接。
   * @param {object} [opts]
   * @param {number} [opts.power] 强度倍率
   */
  hurt(opts = {}) {
    const power = opts.power ?? 1;
    this.hitFlash(RIG.react.flashLife);
    const knock = this.pushDir * RIG.react.knockback * power;
    const T = TIMING.hurt;
    this.playTrack([
      { pose: 'hurt', dur: T.knock, ease: EASE.cubicOut, rootX: knock },
      { pose: 'hurt', dur: T.recoil, ease: EASE.quadOut, rootX: knock * 0.55 },
      { pose: 'rest', dur: T.recover, ease: EASE.smoothOut },
    ], { tag: 'pose', intensity: power });
  }

  /**
   * 出招：蓄力 → 突进 → 收势 → 归位。
   * 时序取 TIMING.attack（windup 120 / strike 180 / recover 200），
   * 编排器以 windup+strike*0.4 为命中帧 —— 顿帧冻结在"拳锋刚触到"的一瞬。
   * @param {object} [opts]
   * @param {number} [opts.power] 强度倍率
   */
  attack(opts = {}) {
    const power = opts.power ?? 1;
    const T = TIMING.attack;
    const lunge = this.pushDir * -RIG.unitBox * 0.10 * power;
    this.playTrack([
      { pose: 'windup', dur: T.windup, ease: EASE.quadOut, rootX: lunge * 0.25 },
      { pose: 'strike', dur: T.strike, ease: EASE.cubicOut, rootX: lunge },
      { pose: 'settle', dur: Math.round(T.recover * 0.6), ease: EASE.quadOut },
      { pose: 'rest', dur: Math.round(T.recover * 0.4), ease: EASE.smoothOut },
    ], { tag: 'pose', intensity: power });
  }

  /* ============================================================
   * 待机呼吸
   * ============================================================ */

  /**
   * 程序化生成待机层。旧 `btIdle` 只有"整体上浮 + 整体微倾"两个自由度；
   * 这里拆成根 / 躯干 / 头 / 双臂四层，相位依次错开 ——
   * 头部滞后于躯干、手臂再滞后，视觉上才有"身体带动肢体"的重量感。
   */
  _updateIdle(elapsedMs) {
    if (!this._unitName) return;
    const cfg = RIG.idle;
    const m = this.meta || {};
    const lean = m.leanSign || 1;
    const armSign = m.armSign || 1;

    /* 相位：用 side 给的偏移，让双方不同频 */
    const base = (elapsedMs / cfg.period + this.phase) * Math.PI * 2;
    const breath = Math.sin(base);
    const headB = Math.sin(base - cfg.headLag * Math.PI * 2);
    const armB = Math.sin(base - cfg.armLag * Math.PI * 2);
    const weaponB = Math.sin(base - cfg.weaponLag * Math.PI * 2);

    const idle = this.idle;
    for (const k of this._slots) {
      const d = idle[k];
      d.rot = 0; d.x = 0; d.y = 0; d.sx = 0; d.sy = 0;
    }

    /* 根：承担大部分浮动与整体微倾（对应旧 translateY(-5px) / rotate(-1.2deg)） */
    const rootD = idle.__root;
    rootD.y = cfg.bodyLift * cfg.rootShare * breath;
    rootD.rot = -cfg.bodyTilt * breath * lean;

    if (idle.torso) {
      idle.torso.y = cfg.bodyLift * (1 - cfg.rootShare) * breath;
      idle.torso.sy = cfg.breatheY * breath;
      idle.torso.sx = cfg.breatheX * breath;
    }
    if (idle.head) {
      idle.head.rot = -cfg.bodyTilt * cfg.headExtra * headB * lean;
      idle.head.y = cfg.headLift * headB;
    }
    if (this._armPart && idle[this._armPart]) {
      idle[this._armPart].rot = cfg.armSwing * armB * armSign;
    }
    if (idle.weapon) {
      idle.weapon.rot = cfg.weaponSwing * weaponB * armSign;
    }
  }

  /* ============================================================
   * 应用到 three 对象
   * ============================================================ */

  _apply() {
    if (!this._unitName) return;

    const rootD = this._sum('__root');
    this.root.position.set(rootD.x, rootD.y, 0);
    this.root.rotation.z = rootD.rot * DEG;
    this.root.scale.set(1 + rootD.sx, 1 + rootD.sy, 1);

    for (const rec of this.parts) {
      const d = this._sum(rec.name);
      rec.node.position.set(rec.rest.x + d.x, rec.rest.y + d.y, 0);
      rec.node.rotation.z = d.rot * DEG;
      rec.node.scale.set(1 + d.sx, 1 + d.sy, 1);
    }

    if (this.shadow) {
      /* 阴影跟随横向位移（打滑的感觉），但不跟着上下浮动 */
      this.shadow.position.x = this.root.position.x * 0.6;
      const lift = Math.max(0, rootD.y);
      const squish = 1 - Math.min(0.35, lift * 0.012);
      const w = RIG.unitBox * 0.62 * squish;
      this.shadow.scale.set(w, w * 0.22, 1);
    }
  }

  _sum(part) {
    const a = this.action[part];
    const i = this.idle[part];
    if (!i) return a;
    return {
      rot: a.rot + i.rot,
      x: a.x + i.x,
      y: a.y + i.y,
      sx: a.sx + i.sx,
      sy: a.sy + i.sy,
    };
  }

  /* ============================================================
   * 外观参数
   * ============================================================ */

  setFlash(v) {
    this._flash = Math.max(0, Math.min(1, v));
    if (this.material) this.material.uniforms.uFlash.value = this._flash;
  }

  setSaturate(v) {
    this._saturate = Math.max(0, Math.min(1, v));
    if (this.material) this.material.uniforms.uSaturate.value = this._saturate;
  }

  setOpacity(v) {
    this._opacity = Math.max(0, Math.min(1, v));
    if (this.material) this.material.uniforms.uOpacity.value = this._opacity;
  }

  /** 当前是否已上屏（用于测试断言） */
  get ready() {
    return !!this._unitName && this.parts.length > 0;
  }

  get unitName() { return this._unitName; }

  /* ============================================================
   * 每帧
   * ============================================================ */

  update(dtMs, elapsedMs) {
    if (!this._unitName) return;
    this.tweens.update(dtMs);
    this._updateIdle(elapsedMs);
    this._apply();
  }

  /** 立刻回到静止状态（进/出战斗时用） */
  reset() {
    this.tweens.clear();
    for (const k of this._slots) {
      Object.assign(this.action[k], zeroDelta());
      Object.assign(this.idle[k], zeroDelta());
    }
    this.setFlash(0);
    this.setOpacity(1);
    this._apply();
  }

  /* ============================================================ */

  dispose() {
    this.tweens.clear();
    this._teardownParts();
    if (this.root.parent) this.root.removeFromParent();
    if (this.shadow && this.shadow.parent) this.shadow.removeFromParent();
    this.shadow = null;
    if (this.material) {
      this.rigSet.releaseMaterial(this.material);
      this.material = null;
    }
    this.meta = null;
    this._unitName = null;
  }
}
