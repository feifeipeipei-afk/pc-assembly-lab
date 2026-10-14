/**
 * 战斗动画体系 · 命中特效池（P3）
 * ============================================================
 * 消费 config.TIMING.impact 里预定义的四种命中反馈物：
 *
 *   slash  斩击弧光 —— 命中点横贯的白色弧形拖尾（旧 .slash-fx 的 WebGL 版）
 *   flash  命中闪光 —— 命中点的短促高亮圆斑，承担"拳拳到肉"的第一帧
 *   shock  冲击环   —— 从命中点扩散的描边圆环，交代力量的"重量"
 *   dust   扬尘     —— 沿地面向两侧溅开的碎屑粒子，交代"打在地上的实感"
 *
 * 实现取舍
 * --------
 * 1. slash / flash / shock 用**少量 quad 池**而不是粒子系统：
 *    它们是"一整块形状"，拆成粒子反而要几百个顶点才能拼出一条弧线。
 *    每类 4 个实例的池子足够覆盖"我方与影子对手同帧互相命中"的极端情况。
 *
 * 2. dust 用一个 THREE.Points 粒子池（CPU 更新位置/透明度）。
 *    BUDGET.maxParticlesBurst 限制的是"会心瞬间"的总粒子数 ——
 *    课堂核显机器上粒子超千就掉帧，这里常态 24/次、会心 40/次，远低于预算。
 *
 * 3. quad 各实例持有独立材质：uOpacity 是实例级状态，不能共享；
 *    几何体（单位平面）全池共享一份。
 *
 * 4. update(dtMs) 吃的是**缩放后**的 dt：顿帧（hit-stop）期间特效
 *    与角色一起冻结在命中的那一帧，这正是打击感的来源，不修。
 */

import * as THREE from 'three';
import { LAYERS, TIMING, EASE } from '../config.js';

/* ------------------------------------------------------------
 * 着色器
 * ------------------------------------------------------------ */
const BASIC_VERT = /* glsl */`
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

/* 弧光：以 quad 中心为原点，横贯的月牙形亮带（旧 .slash-fx 的形状语言） */
const SLASH_FRAG = /* glsl */`
uniform float uOpacity;
varying vec2 vUv;
void main() {
  vec2 p = vUv * 2.0 - 1.0;
  /* 月牙：越靠上下边缘越透明，中心一条亮带 */
  float band = 1.0 - smoothstep(0.0, 0.85, abs(p.y));
  /* 两端收尖 */
  float tip = 1.0 - smoothstep(0.55, 1.0, abs(p.x));
  float a = band * tip * uOpacity;
  if (a <= 0.02) discard;
  vec3 col = mix(vec3(1.0), vec3(1.0, 0.92, 0.6), abs(p.y));
  gl_FragColor = vec4(col, a);
}
`;

/* 圆斑/圆环共用：uRing=0 是实心软圆（闪光），1 是细描边环（冲击环） */
const ROUND_FRAG = /* glsl */`
uniform float uOpacity;
uniform float uRing;
uniform vec3  uColor;
varying vec2 vUv;
void main() {
  vec2 p = vUv * 2.0 - 1.0;
  float r = length(p);
  float a = uRing < 0.5
    ? smoothstep(1.0, 0.15, r)              /* 实心软圆 */
    : smoothstep(0.16, 0.0, abs(r - 0.78)); /* 细描边环 */
  a *= uOpacity;
  if (a <= 0.02) discard;
  gl_FragColor = vec4(uColor, a);
}
`;

/* 粒子：圆点，透明度/尺寸由顶点属性逐粒传入 */
const POINT_VERT = /* glsl */`
attribute float aAlpha;
attribute float aSize;
varying float vAlpha;
void main() {
  vAlpha = aAlpha;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  /* 正交相机 z 恒定，这里直接给像素级点径 */
  gl_PointSize = aSize;
  gl_Position = projectionMatrix * mv;
}
`;
const POINT_FRAG = /* glsl */`
uniform vec3 uColor;
varying float vAlpha;
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float r = length(p);
  float a = smoothstep(1.0, 0.2, r) * vAlpha;
  if (a <= 0.02) discard;
  gl_FragColor = vec4(uColor, a);
}
`;

/* ------------------------------------------------------------
 * 单实例特效（一个 mesh + 一段寿命曲线）
 * ------------------------------------------------------------ */
class FxInstance {
  constructor(mesh, material) {
    this.mesh = mesh;
    this.material = material;
    this.life = 0;      /* 已活 ms */
    this.total = 1;     /* 总寿命 ms */
    this.alive = false;
    /** @type {(t:number)=>void} 各类型自定的形状曲线（t∈[0,1]） */
    this.onTick = null;
    mesh.visible = false;
    mesh.frustumCulled = false;
  }

  spawn(lifeMs, tick) {
    this.life = 0;
    this.total = Math.max(1, lifeMs);
    this.onTick = tick;
    this.alive = true;
    this.mesh.visible = true;
    this.onTick(0); /* 首帧形状立即摆出，避免"延迟一帧才出现" */
  }

  update(dtMs) {
    if (!this.alive) return;
    this.life += dtMs;
    const t = Math.min(1, this.life / this.total);
    this.onTick(t);
    if (t >= 1) {
      this.alive = false;
      this.mesh.visible = false;
    }
  }
}

/* ------------------------------------------------------------
 * ImpactFX
 * ------------------------------------------------------------ */
export class ImpactFX {
  /**
   * @param {object} opts
   * @param {import('../renderer/RendererHost.js').RendererHost} opts.host
   */
  constructor({ host }) {
    this.host = host;
    this.group = new THREE.Group();
    this.group.name = 'fx';
    this.group.position.z = LAYERS.FX.z;
    host.scene.add(this.group);

    this._geo = new THREE.PlaneGeometry(1, 1);

    this._slashPool = this._makeQuadPool(4, SLASH_FRAG, { uOpacity: 1 });
    this._flashPool = this._makeQuadPool(4, ROUND_FRAG, {
      uOpacity: 1, uRing: 0, uColor: new THREE.Vector3(1, 1, 0.92),
    });
    this._shockPool = this._makeQuadPool(4, ROUND_FRAG, {
      uOpacity: 1, uRing: 1, uColor: new THREE.Vector3(1, 0.95, 0.8),
    });

    /* 粒子池：容量固定，超发直接丢弃 —— 这就是预算的意义 */
    this._pCapacity = 160;
    this._points = this._makePoints();
    /** @type {Array<{idx:number,p:THREE.Vector3,v:THREE.Vector3,life:number,total:number,size:number}>} */
    this._pFree = [];
    this._pUsed = [];
    for (let i = 0; i < this._pCapacity; i++) {
      this._pFree.push({
        idx: i,
        p: new THREE.Vector3(),
        v: new THREE.Vector3(),
        life: 0, total: 1, size: 3,
      });
    }

    this._quads = [...this._slashPool, ...this._flashPool, ...this._shockPool];
  }

  /* ---------------- 池构建 ---------------- */

  _makeQuadPool(n, frag, uniformSpecs) {
    const pool = [];
    for (let i = 0; i < n; i++) {
      /* 每实例一份材质：uOpacity 是实例级状态 */
      const uniforms = {};
      for (const [k, v] of Object.entries(uniformSpecs)) {
        uniforms[k] = { value: v instanceof THREE.Vector3 ? v.clone() : v };
      }
      const mat = new THREE.ShaderMaterial({
        vertexShader: BASIC_VERT,
        fragmentShader: frag,
        uniforms,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      const mesh = new THREE.Mesh(this._geo, mat);
      mesh.renderOrder = LAYERS.FX.renderOrder;
      this.group.add(mesh);
      pool.push(new FxInstance(mesh, mat));
    }
    return pool;
  }

  _makePoints() {
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(this._pCapacity * 3);
    const alpha = new Float32Array(this._pCapacity);
    const size = new Float32Array(this._pCapacity);
    for (let i = 0; i < this._pCapacity; i++) {
      size[i] = 3;
      pos[i * 3 + 1] = -9999; /* 未激活的粒子藏到画外 */
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('aAlpha', new THREE.BufferAttribute(alpha, 1));
    geo.setAttribute('aSize', new THREE.BufferAttribute(size, 1));

    const mat = new THREE.ShaderMaterial({
      vertexShader: POINT_VERT,
      fragmentShader: POINT_FRAG,
      uniforms: { uColor: { value: new THREE.Vector3(0.72, 0.64, 0.5) } },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.NormalBlending,
    });

    const points = new THREE.Points(geo, mat);
    points.renderOrder = LAYERS.FX_FRONT.renderOrder;
    points.frustumCulled = false;
    /* group 自身在 LAYERS.FX.z，粒子再往前压一层 */
    points.position.z = LAYERS.FX_FRONT.z - LAYERS.FX.z;
    this.group.add(points);
    return points;
  }

  /* ---------------- 对外：发射口 ---------------- */

  /**
   * 斩击弧光。
   * @param {{x:number, y:number}} at  命中点（世界坐标）
   * @param {number} dir              +1 我方砍向右 / -1 敌方砍向左
   * @param {number} [power]          强度（会心 > 1）
   */
  slash(at, dir, power = 1) {
    const inst = this._take(this._slashPool);
    if (!inst) return;
    inst.spawn(TIMING.impact.slashLife, (t) => {
      const m = inst.mesh;
      m.position.set(at.x, at.y, 0);
      /* 展开：0→0.35 快速拉满后缓慢收尾（对应旧 slashGo 的 40% 峰值） */
      const open = t < 0.35 ? EASE.cubicOut(t / 0.35) : 1 + (t - 0.35) * 0.12;
      m.scale.set((86 + 30 * (power - 1)) * open, 26 + 6 * (power - 1), 1);
      m.rotation.z = dir * -34 * (Math.PI / 180);
      inst.material.uniforms.uOpacity.value = t < 0.4 ? 1 : 1 - (t - 0.4) / 0.6;
    });
  }

  /** 命中闪光（第一帧高亮） */
  flash(at, power = 1) {
    const inst = this._take(this._flashPool);
    if (!inst) return;
    inst.spawn(TIMING.impact.flashLife, (t) => {
      const m = inst.mesh;
      m.position.set(at.x, at.y, 0);
      const s = (56 + 18 * (power - 1)) * (1 + 0.5 * EASE.cubicOut(Math.min(1, t * 2)));
      m.scale.set(s, s, 1);
      inst.material.uniforms.uOpacity.value = 0.95 * (1 - EASE.quadIn(t));
    });
  }

  /** 冲击环（力量感） */
  shock(at, power = 1) {
    const inst = this._take(this._shockPool);
    if (!inst) return;
    inst.spawn(TIMING.impact.shockLife, (t) => {
      const m = inst.mesh;
      m.position.set(at.x, at.y, 0);
      const s = (30 + 90 * EASE.cubicOut(t)) * power;
      m.scale.set(s, s, 1);
      inst.material.uniforms.uOpacity.value = 0.8 * (1 - t);
    });
  }

  /**
   * 扬尘：从落点沿地面向两侧溅开。
   * @param {{x:number, y:number}} ground 落点（世界坐标，y 取 0 附近）
   * @param {number} [power]
   */
  dust(ground, power = 1) {
    const want = Math.round((power > 1.2 ? 40 : 24) * Math.min(power, 1.6));
    const n = Math.min(this._pFree.length, want);
    for (let i = 0; i < n; i++) {
      const slot = this._pFree.pop();
      const side = Math.random() < 0.5 ? -1 : 1;
      const speed = (60 + Math.random() * 130) * power;
      const up = 40 + Math.random() * 120 * Math.min(power, 1.4);
      slot.p.set(ground.x + side * (6 + Math.random() * 18), (ground.y || 0) + 4, 0);
      slot.v.set(side * speed, up, 0);
      slot.life = 0;
      slot.total = TIMING.impact.dustLife * (0.7 + Math.random() * 0.5);
      slot.size = 2.5 + Math.random() * 3.5;
      this._pUsed.push(slot);
    }
  }

  /** 一整套命中反馈（编排器的常用组合） */
  burst(at, ground, dir, power = 1) {
    this.slash(at, dir, power);
    this.flash(at, power);
    this.shock(at, power);
    this.dust(ground, power);
  }

  /* ---------------- 内部 ---------------- */

  _take(pool) {
    for (const inst of pool) {
      if (!inst.alive) return inst;
    }
    /* 池满：抢占最老的实例 —— 命中反馈宁可打断也不能缺席 */
    let oldest = pool[0];
    for (const inst of pool) {
      if (inst.life > oldest.life) oldest = inst;
    }
    return oldest;
  }

  /* ---------------- 每帧 / 生命周期 ---------------- */

  /** @param {number} dtMs 缩放后的毫秒（顿帧期间特效一起冻结） */
  update(dtMs) {
    for (const inst of this._quads) inst.update(dtMs);

    if (this._pUsed.length === 0) return;
    const pos = this._points.geometry.attributes.position;
    const alpha = this._points.geometry.attributes.aAlpha;
    const size = this._points.geometry.attributes.aSize;

    for (let i = this._pUsed.length - 1; i >= 0; i--) {
      const s = this._pUsed[i];
      s.life += dtMs;
      if (s.life >= s.total) {
        alpha.array[s.idx] = 0;
        pos.array[s.idx * 3 + 1] = -9999;
        this._pUsed.splice(i, 1);
        this._pFree.push(s);
        continue;
      }
      /* 简单欧拉：重力 + 速度衰减，尘土"溅起来又落回去" */
      s.v.y -= 0.55 * dtMs;
      s.v.multiplyScalar(1 - 0.0016 * dtMs);
      s.p.addScaledVector(s.v, dtMs / 1000);
      if (s.p.y < 2) { s.p.y = 2; s.v.y *= -0.3; } /* 落地小弹跳 */

      pos.array[s.idx * 3] = s.p.x;
      pos.array[s.idx * 3 + 1] = s.p.y;
      const t = s.life / s.total;
      alpha.array[s.idx] = 0.7 * (1 - EASE.quadIn(t));
      size.array[s.idx] = s.size * (1 + t * 0.6);
    }
    pos.needsUpdate = true;
    alpha.needsUpdate = true;
    size.needsUpdate = true;
  }

  /** 立即清空全部特效（RESET 事件 / 退出战斗） */
  clear() {
    for (const inst of this._quads) {
      inst.alive = false;
      inst.mesh.visible = false;
    }
    const alpha = this._points.geometry.attributes.aAlpha;
    const pos = this._points.geometry.attributes.position;
    for (const s of this._pUsed) {
      alpha.array[s.idx] = 0;
      pos.array[s.idx * 3 + 1] = -9999;
      this._pFree.push(s);
    }
    this._pUsed.length = 0;
    alpha.needsUpdate = true;
    pos.needsUpdate = true;
  }

  dispose() {
    this.clear();
    for (const inst of this._quads) {
      inst.mesh.removeFromParent();
      inst.material.dispose();
    }
    this._quads.length = 0;
    this._slashPool = this._flashPool = this._shockPool = null;

    this._points.removeFromParent();
    this._points.geometry.dispose();
    this._points.material.dispose();

    this._geo.dispose();
    this.host.scene.remove(this.group);
  }
}
