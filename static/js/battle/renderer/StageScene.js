/**
 * 战斗动画体系 · 舞台场景
 * ============================================================
 * 职责：搭出战斗舞台的静态部分，并管理图层次序。
 *
 * 本文件用「1 个全屏 quad + 1 个片元着色器」替代旧 CSS 的 3 条规则：
 *   - .battle-shell 的 3 段线性渐变背景  → 着色器里的天空渐变
 *   - .battle-stage::before 的 44px 网格 → 着色器里的程序化网格线
 *   - .battle-stage::after 的地面条       → 着色器里的地面条 + 3px 顶边线
 * 3 条 CSS 规则 + 2 个伪元素 → 1 次 draw call。
 *
 * 颜色取向：刻意用 srgbTriplet() 取原始 sRGB 分量而非 THREE.Color，
 * 以与旧 CSS 颜色逐字节一致（原因见 config.srgbTriplet 注释）。
 */

import * as THREE from 'three';
import {
  COLORS, LAYERS, GROUND_H, GRID_SIZE,
  UNIT_X, SLOT_SIDE, srgbTriplet,
} from '../config.js';

/* ------------------------------------------------------------
 * 着色器
 * ------------------------------------------------------------ */
const VERT = /* glsl */`
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const FRAG = /* glsl */`
varying vec2 vUv;

uniform vec3  uSkyTop;
uniform vec3  uSkyMid;
uniform vec3  uSkyBottom;
uniform vec3  uGroundTop;
uniform vec3  uGroundMid;
uniform vec3  uGroundBottom;
uniform vec3  uGroundEdge;
uniform vec3  uGridColor;

uniform float uGridAlpha;
uniform float uGridSize;
uniform float uViewW;
uniform float uViewH;
uniform float uBottom;
uniform float uGroundH;
uniform float uGroundEdgeW;
uniform float uWorldPerPx;

/* 三段渐变：stops 为 [0, a, 1] */
vec3 ramp3(vec3 c0, vec3 c1, vec3 c2, float t, float a) {
  return t < a ? mix(c0, c1, t / a) : mix(c1, c2, (t - a) / (1.0 - a));
}

void main() {
  /* 由 uv 还原世界坐标（quad 被缩放到视口尺寸并居中） */
  float wx = (vUv.x - 0.5) * uViewW;
  float wy = uBottom + vUv.y * uViewH;

  vec3 col;

  if (wy > 0.0) {
    /* ---- 天空 ---- */
    float topY = uBottom + uViewH;
    float tSky = clamp((topY - wy) / max(topY, 1.0), 0.0, 1.0);  /* 0=顶端 1=地面线 */
    col = ramp3(uSkyTop, uSkyMid, uSkyBottom, tSky, 0.45);

    /* ---- 网格线 ---- */
    /* 距离用**像素**度量，而不是世界单位。
     * 坑（P0 遗留）：若直接拿世界单位做 smoothstep(0, 0.5, dist)，线宽正好 1 像素；
     * 而网格落在整数世界坐标、像素中心在 x+0.5 处，于是每个像素到最近线的距离
     * 恒为 0.5 —— 白线全被判成 0，整张网格消失。P0 时 pxPerUnit≈1.029 的相位
     * 漂移掩盖了这个问题，改成 1:1 后立刻暴露。
     *
     * 换算成像素距离后，最近像素到线的距离必然 ≤ 0.5，所以在 0.4~0.85 之间做
     * 羽化：相位对齐时峰值 1.0，最差相位仍有 0.88 —— 既保住 1 像素的细线（与旧
     * CSS 的 '1px' 网格等宽），又不会因亚像素相位而整条消失。
     * （早先取 0.3~1.0 是能出线，但线宽变成 2 像素，视觉上明显重于旧 CSS。） */
    vec2 d = abs(fract((vec2(wx, wy) + uGridSize * 0.5) / uGridSize) - 0.5) * uGridSize;
    float pxDist = min(d.x, d.y) / max(uWorldPerPx, 1e-4);
    float line = 1.0 - smoothstep(0.4, 0.85, pxDist);
    col = mix(col, uGridColor, line * uGridAlpha);
  } else {
    /* ---- 地面条 ---- */
    float t = clamp((wy - uBottom) / uGroundH, 0.0, 1.0);        /* 0=底 1=地面线 */
    col = ramp3(uGroundBottom, uGroundMid, uGroundTop, t, 0.5);

    /* 顶边线（旧 border-top: 3px solid #23351c），只向地面内侧延伸 */
    float edge = 1.0 - smoothstep(0.0, max(uWorldPerPx * uGroundEdgeW, 1e-4), -wy);
    col = mix(col, uGroundEdge, edge);
  }

  gl_FragColor = vec4(col, 1.0);
}
`;

export class StageScene {
  /**
   * @param {import('./RendererHost.js').RendererHost} host
   */
  constructor(host) {
    this.host = host;

    this.group = new THREE.Group();
    this.group.name = 'stage';
    host.scene.add(this.group);

    this._buildSky();
    this._buildSlotMarkers();

    this._unsub = host.onResize((view) => this._layout(view));
    this._layout(host.view);
  }

  /* ------------------------------------------------------------
   * 天空 / 网格 / 地面（单个全屏 quad）
   * ------------------------------------------------------------ */
  _buildSky() {
    const skyTop = srgbTriplet(COLORS.skyTop);
    const skyMid = srgbTriplet(COLORS.skyMid);
    const skyBottom = srgbTriplet(COLORS.skyBottom);
    const gTop = srgbTriplet(COLORS.groundTop);
    const gMid = srgbTriplet(COLORS.groundMid);
    const gBottom = srgbTriplet(COLORS.groundBottom);
    const gEdge = srgbTriplet(COLORS.groundEdge);
    const grid = srgbTriplet(COLORS.grid);

    this.skyUniforms = {
      uSkyTop: { value: new THREE.Vector3(...skyTop) },
      uSkyMid: { value: new THREE.Vector3(...skyMid) },
      uSkyBottom: { value: new THREE.Vector3(...skyBottom) },
      uGroundTop: { value: new THREE.Vector3(...gTop) },
      uGroundMid: { value: new THREE.Vector3(...gMid) },
      uGroundBottom: { value: new THREE.Vector3(...gBottom) },
      uGroundEdge: { value: new THREE.Vector3(...gEdge) },
      uGridColor: { value: new THREE.Vector3(...grid) },
      uGridAlpha: { value: COLORS.gridEffectiveAlpha },
      uGridSize: { value: GRID_SIZE },
      uViewW: { value: 1 },
      uViewH: { value: 1 },
      uBottom: { value: 0 },
      uGroundH: { value: GROUND_H },
      uGroundEdgeW: { value: COLORS.groundEdgeW },
      uWorldPerPx: { value: 1 },
    };

    this.skyGeometry = new THREE.PlaneGeometry(1, 1);
    this.skyMaterial = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: this.skyUniforms,
      /* 不透明背景层：不写深度、不做深度测试，靠 renderOrder 排在最前 */
      transparent: false,
      depthWrite: false,
      depthTest: false,
    });

    this.sky = new THREE.Mesh(this.skyGeometry, this.skyMaterial);
    this.sky.name = 'stage-sky';
    this.sky.renderOrder = LAYERS.SKY.renderOrder;
    this.sky.position.z = LAYERS.SKY.z;
    /* 缩放后的包围球会过期，关掉视锥剔除免得被误剔除 */
    this.sky.frustumCulled = false;
    this.group.add(this.sky);
  }

  /* ------------------------------------------------------------
   * 单位站位标记（P1 角色上场时直接复用，避免两处各写一套坐标）
   * ------------------------------------------------------------ */
  _buildSlotMarkers() {
    this.slots = new THREE.Group();
    this.slots.name = 'slots';
    this.slots.position.z = LAYERS.UNIT.z;
    this.group.add(this.slots);

    /** @type {{me: THREE.Object3D, foe: THREE.Object3D}} */
    this.slotNodes = {
      me: this._makeSlot('me', SLOT_SIDE.ME),
      foe: this._makeSlot('foe', SLOT_SIDE.FOE),
    };
  }

  _makeSlot(name, side) {
    const node = new THREE.Group();
    node.name = `slot-${name}`;
    /* 脚底落在地面线 y=0；朝向：我方朝左(-1)，敌方朝右(+1) */
    node.position.set(side * UNIT_X, 0, 0);
    node.userData.side = side;
    this.slots.add(node);
    return node;
  }

  /**
   * 取某一阵位的容器节点（P1 的 UnitView 挂到这里）
   * @param {'me'|'foe'} which
   * @returns {THREE.Object3D}
   */
  getSlot(which) {
    return this.slotNodes[which];
  }

  /* ------------------------------------------------------------
   * 布局
   * ------------------------------------------------------------ */
  _layout(view) {
    const { viewW, viewH, centerY, pxPerUnit } = view;

    this.sky.scale.set(viewW, viewH, 1);
    this.sky.position.set(0, centerY, LAYERS.SKY.z);

    const u = this.skyUniforms;
    u.uViewW.value = viewW;
    u.uViewH.value = viewH;
    u.uBottom.value = view.bottom;
    u.uWorldPerPx.value = pxPerUnit > 0 ? 1 / pxPerUnit : 0.001;
  }

  /* ------------------------------------------------------------
   * 释放
   * ------------------------------------------------------------ */
  dispose() {
    if (this._unsub) { this._unsub(); this._unsub = null; }

    this.host.scene.remove(this.group);

    this.skyGeometry.dispose();
    /* ShaderMaterial 无贴图，直接 dispose；uniform 里的 Vector3 由 GC 回收 */
    this.skyMaterial.dispose();

    this.group.clear();
    this.slotNodes = null;
  }
}
