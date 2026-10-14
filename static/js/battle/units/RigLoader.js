/**
 * 战斗动画体系 · 切图骨骼资源加载
 * ============================================================
 * 负责把 `tools/build_battle_assets.py` 产出的图集与元数据变成
 * three 侧的可用对象：一张纹理 + 每个部件一块几何体 + 材质工厂。
 *
 * 关键设计
 * --------
 * 1. **部件矩形烘进 UV**，而不是用 uniform 传图集区域。
 *    这样所有部件可以共用同一个材质（一份 uniform），
 *    既少一次 draw call 的状态切换，也让"整只角色闪白"只需改一个 uniform。
 *
 * 2. **几何体按 (角色, 部件) 缓存并共享**。同名角色同时出现两个实例
 *    （例如两个学生都是"勇者"）时不会重复上传顶点数据。
 *
 * 3. **纹理原样直通，不做色彩空间转换**。
 *    背景着色器（StageScene）已验证过：自定义 ShaderMaterial 不会被 three
 *    追加 colorspace 转换块，gl_FragColor 就是最终帧缓冲值。
 *    因此这里把 texture.colorSpace 设为 NoColorSpace —— 既避免 GPU 侧的
 *    sRGB 解码，也避免内部格式被换成 SRGB8_ALPHA8，最终像素与 PNG 逐字节一致。
 *
 * 4. **网络解码结果做进程内缓存**（_assetsPromise），重复挂载不重复下载；
 *    GPU 资源（纹理/几何体）随 RigSet 一起释放。
 *
 * 释放顺序要求：先 dispose 所有 UnitView，再 dispose RigSet。
 */

import * as THREE from 'three';
import { RIG, LAYERS } from '../config.js';

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
uniform sampler2D uMap;
uniform vec3  uTint;       // 叠加色调（默认纯白 = 不改变原图）
uniform float uFlash;      // 受击闪白 0..1
uniform float uOpacity;
uniform float uAlphaTest;

varying vec2 vUv;

void main() {
  vec4 texel = texture2D(uMap, vUv);
  if (texel.a <= uAlphaTest) discard;

  vec3 rgb = texel.rgb * uTint;
  rgb = mix(rgb, vec3(1.0), uFlash);

  gl_FragColor = vec4(rgb, texel.a * uOpacity);
}
`;

/* ------------------------------------------------------------
 * 资源获取（带进程内缓存）
 * ------------------------------------------------------------ */
let _assetsPromise = null;

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`图集图片加载失败：${url}（是否忘了跑 tools/build_battle_assets.py？）`));
    img.src = url;
  });
}

function fetchAssets() {
  return (async () => {
    const res = await fetch(RIG.metaUrl, { cache: 'force-cache' });
    if (!res.ok) {
      throw new Error(`图集元数据加载失败：HTTP ${res.status}（是否忘了跑 tools/build_battle_assets.py？）`);
    }
    const doc = await res.json();
    const image = await loadImage(doc.atlas && doc.atlas.url ? doc.atlas.url : RIG.atlasUrl);
    return { doc, image };
  })();
}

/* ------------------------------------------------------------
 * RigSet
 * ------------------------------------------------------------ */
export class RigSet {
  /**
   * 加载（或复用缓存的）图集资源。
   * @returns {Promise<RigSet>}
   */
  static async load() {
    if (!_assetsPromise) _assetsPromise = fetchAssets();
    /* 失败时清掉缓存，允许下次重试（例如老师忘了构建资产、补跑后再刷新） */
    let assets;
    try {
      assets = await _assetsPromise;
    } catch (err) {
      _assetsPromise = null;
      throw err;
    }
    return new RigSet(assets.doc, assets.image);
  }

  /** 丢掉进程内缓存（测试用；不影响已创建实例） */
  static clearCache() {
    _assetsPromise = null;
  }

  constructor(doc, image) {
    this.doc = doc;
    this.image = image;

    this.texture = new THREE.Texture(image);
    this._configureTexture(this.texture);

    /** @type {Map<string, THREE.BufferGeometry>} */
    this._geo = new Map();
    /** @type {Set<THREE.ShaderMaterial>} */
    this._mats = new Set();
    this._disposed = false;
  }

  _configureTexture(tex) {
    if (RIG.filter === 'nearest') {
      tex.magFilter = THREE.NearestFilter;
      tex.minFilter = THREE.NearestFilter;
      tex.generateMipmaps = false;
    } else {
      /* 源图是平滑插画（见 config.RIG.filter 注释），必须线性过滤；
       * 缩放比约 0.54，开启 mipmap 才不会在运动时闪烁。 */
      tex.magFilter = THREE.LinearFilter;
      tex.minFilter = RIG.mipmap ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
      tex.generateMipmaps = !!RIG.mipmap;
    }
    /* 图集内相邻区域靠 4px 透明边距隔开，钳制寻址避免跨区域串色 */
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.wrapT = THREE.ClampToEdgeWrapping;
    tex.anisotropy = RIG.anisotropy;
    /* 原样直通：见文件头注释第 3 条 */
    tex.colorSpace = THREE.NoColorSpace;
    tex.needsUpdate = true;
  }

  /* ---------------- 元数据查询 ---------------- */

  unit(unitName) {
    const u = this.doc.units && this.doc.units[unitName];
    if (!u) throw new Error(`图集里没有角色「${unitName}」`);
    return u;
  }

  has(unitName) {
    return !!(this.doc.units && this.doc.units[unitName]);
  }

  /** 所有角色名 */
  get unitNames() { return Object.keys(this.doc.units || {}); }

  part(unitName, partName) {
    const u = this.unit(unitName);
    const p = u.parts.find((q) => q.name === partName);
    if (!p) throw new Error(`角色「${unitName}」没有部件「${partName}」`);
    return p;
  }

  /** 世界单位 / 源像素 */
  scaleOf(unitName) {
    const u = this.unit(unitName);
    const box = this.doc.unitBox || RIG.unitBox;
    return box / u.sourceSize[0];
  }

  /** 按 z 升序（先画的在后）返回部件列表 */
  partsOf(unitName) {
    return this.unit(unitName).parts.slice().sort((a, b) => a.z - b.z);
  }

  /** 源图坐标 → 该角色根节点下的世界坐标 */
  toWorld(unitName, sx, sy) {
    const u = this.unit(unitName);
    const s = this.scaleOf(unitName);
    return {
      x: (sx - u.anchor[0]) * s,
      y: (u.anchor[1] - sy) * s,
    };
  }

  /* ---------------- 几何体 ---------------- */

  /**
   * 取部件几何体（缓存共享）。
   * 平面尺寸 = 部件矩形 × 缩放；UV 重映射到图集区域。
   * 平面中心位于矩形中心，pivot 由 UnitView 负责对齐。
   */
  geometry(unitName, partName) {
    const key = `${unitName}/${partName}`;
    const hit = this._geo.get(key);
    if (hit) return hit;

    const p = this.part(unitName, partName);
    const s = this.scaleOf(unitName);
    const [rx, ry, rw, rh] = p.rect;
    const [ax, ay, aw, ah] = p.region;

    const geo = new THREE.PlaneGeometry(rw * s, rh * s);
    const W = this.doc.atlas.width;
    const H = this.doc.atlas.height;

    /* 图集 v 轴：three 的 Texture 默认 flipY=true，uv 的 v=0 对应图像底部 */
    const u0 = ax / W;
    const u1 = (ax + aw) / W;
    const v0 = 1 - (ay + ah) / H;
    const v1 = 1 - ay / H;

    const uv = geo.attributes.uv;
    for (let i = 0; i < uv.count; i++) {
      uv.setXY(i, u0 + uv.getX(i) * (u1 - u0), v0 + uv.getY(i) * (v1 - v0));
    }
    uv.needsUpdate = true;
    geo.userData.part = { name: partName, rect: p.rect, region: p.region, pivot: p.pivot };

    this._geo.set(key, geo);
    return geo;
  }

  /**
   * 部件相对其 pivot 的偏移（世界单位）。
   * UnitView 用它把平面中心摆到正确位置。
   */
  meshOffset(unitName, partName) {
    const p = this.part(unitName, partName);
    const s = this.scaleOf(unitName);
    const [rx, ry, rw, rh] = p.rect;
    const [px, py] = p.pivot;
    return {
      x: ((rx + rw / 2) - px) * s,
      y: -((ry + rh / 2) - py) * s,
    };
  }

  /** 部件 pivot 相对父部件 pivot 的局部位移（世界单位） */
  pivotDelta(unitName, partName) {
    const p = this.part(unitName, partName);
    const s = this.scaleOf(unitName);
    let parentId = null;
    if (p.parent) parentId = this.part(unitName, p.parent);
    const [px, py] = p.pivot;
    const bx = parentId ? parentId.pivot[0] : this.unit(unitName).anchor[0];
    const by = parentId ? parentId.pivot[1] : this.unit(unitName).anchor[1];
    return { x: (px - bx) * s, y: -(py - by) * s };
  }

  /* ---------------- 材质 ---------------- */

  /** 新建一个材质（每个角色实例一份，因为 flash/tint/opacity 是实例级的） */
  material() {
    const mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uMap: { value: this.texture },
        uTint: { value: new THREE.Vector3(1, 1, 1) },
        uFlash: { value: 0 },
        uSaturate: { value: 1 },
        uOpacity: { value: 1 },
        uAlphaTest: { value: RIG.alphaTest },
      },
      transparent: true,
      depthWrite: false,
      /* 2D 舞台：绘制次序完全由 renderOrder 决定，不参与深度测试 */
      depthTest: false,
      side: THREE.FrontSide,
    });
    this._mats.add(mat);
    return mat;
  }

  /** 释放材质（UnitView 销毁时调用） */
  releaseMaterial(mat) {
    if (!mat) return;
    this._mats.delete(mat);
    mat.dispose();
  }

  /* ---------------- 释放 ---------------- */

  dispose() {
    if (this._disposed) return;
    this._disposed = true;

    for (const geo of this._geo.values()) geo.dispose();
    this._geo.clear();

    for (const mat of this._mats) mat.dispose();
    this._mats.clear();

    this.texture.dispose();
  }
}

export { LAYERS };
