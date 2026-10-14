/**
 * 战斗动画体系 · WebGL 可用性探测
 * ============================================================
 * 本文件**刻意不 import three**。
 *
 * 原因：默认渲染器是 dom，如果探测逻辑写在 RendererHost 里，
 * bootstrap 就必须先 import RendererHost → 连带加载 three 与 three.core
 * （合计约 2MB），默认路径平白多下载 2MB 且可能因 WebGL 不可用而白费。
 * 因此把探测独立成零依赖小模块，bootstrap 先探测、通过了再动态 import three。
 */

/**
 * @returns {{ok: boolean, reason?: string, detail?: string}}
 */
export function probeWebGL() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return { ok: false, reason: 'no-dom' };
  }
  if (typeof WebGLRenderingContext === 'undefined') {
    return { ok: false, reason: 'no-webgl-api' };
  }

  let gl = null;
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (!gl) return { ok: false, reason: 'no-context' };
  } catch (err) {
    return { ok: false, reason: 'exception', detail: String(err && err.message || err) };
  } finally {
    /* 必须主动释放：浏览器对同时存在的 WebGL 上下文有数量上限（通常 16），
     * 探测用的上下文若泄漏，会导致真正的渲染器创建失败 —— 这类问题
     * 只在反复进出战斗若干次后才暴露，非常难查。 */
    if (gl) {
      try {
        const lose = gl.getExtension('WEBGL_lose_context');
        if (lose) lose.loseContext();
      } catch (err) { /* 释放失败不影响探测结论 */ }
    }
  }
  return { ok: true };
}
