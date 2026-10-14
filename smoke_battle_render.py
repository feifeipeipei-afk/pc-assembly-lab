# -*- coding: utf-8 -*-
"""战斗渲染器冒烟：dom / three 两种渲染器各跑一遍完整战斗流程。

用途：战斗渲染体系每次改动后的回归验证。
  1. dom 模式 —— 确认未带参数时行为与重构前一致（canvas 隐藏、CSS 伪元素在位）
  2. three 模式 —— 确认 WebGL 舞台真的渲染出来了

three 模式做像素级校验：验证 StageScene 的着色器画出了
天空渐变 / 网格线 / 地面条三层结构，且颜色与旧 CSS 配色吻合，
而不是一片纯色或空白。

运行：py smoke_battle_render.py
无需预先起服务（脚本内置测试服务器）。
截图产物：smoke_battle_render_dom.png / smoke_battle_render_three.png
"""
import math
import os
import statistics
import sys
import threading

from PIL import Image
from werkzeug.serving import make_server

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
# 独立的测试库，不污染 quiz_app.db；已在 .gitignore 中忽略
os.environ['QUIZ_DB_PATH'] = os.path.join(ROOT, 'quiz_smoke_render.db')

import app as appmod  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 5098
BASE = f'http://127.0.0.1:{PORT}'
CLASS_NAME = 'P0测试班'
ROSTER_NAME = 'P0冒烟员'

failures = []
notes = []


def check(label, cond, extra=''):
    print(('  OK   ' if cond else '  FAIL ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        failures.append(label)


def login(page, name, url):
    """登录。花名册模式（默认开启）下从名单选姓名；关闭时自由填姓名。
    url 必须带上渲染器参数 —— 否则刷新后 resolveKind() 读不到。"""
    page.goto(url, wait_until='networkidle')
    page.wait_for_function("document.querySelector('#inputClass option:nth-child(2)')", timeout=10000)
    page.select_option('#inputClass', index=1)
    page.wait_for_timeout(400)
    if page.locator('#inputName').is_visible():
        page.fill('#inputName', name)
    else:
        page.wait_for_function("document.querySelector('#inputNameSelect option')", timeout=8000)
        # 注意 index=0 是空占位项「请选择你的姓名」，选它会触发 HTML5 required 校验
        page.select_option('#inputNameSelect', label=ROSTER_NAME)
    page.click('#loginForm button[type=submit]')
    # 登录成功后前端会 location.reload()，必须等重载完成再找欢迎页元素
    page.wait_for_load_state('networkidle')
    page.wait_for_function(
        "() => { const b = document.getElementById('arenaBtn');"
        " return b && b.offsetParent !== null; }", timeout=15000)


def enter_battle(page):
    page.click('#arenaBtn')
    page.wait_for_selector('#arenaBody .stage-tile', timeout=8000)
    page.locator('.stage-tile:not(.locked)').first.click()
    page.wait_for_selector('#battleView:not(.hidden) .bt-qcard', timeout=8000)
    page.wait_for_timeout(1200)   # 留出若干帧


def analyse_canvas(page, tag, view_h, scale):
    """截图 canvas 并做像素分析，验证天空/网格/地面三层都画出来了。

    取样坑：element screenshot 抓的是**合成后**的画面，DOM 覆盖层
    （名牌 / 血条 / 伤害飘字）会叠在 canvas 之上被一并截进来。
    所以取样必须避开中间的角色行与上下的 HUD 带，只在左右安全边距里采。
    """
    box = page.locator('#battleCanvas').bounding_box()
    if not box or box['width'] < 10 or box['height'] < 10:
        check(f'[{tag}] canvas 有可见尺寸', False, str(box))
        return None
    check(f'[{tag}] canvas 有可见尺寸', True,
          f"{box['width']:.0f}x{box['height']:.0f}")

    img = Image.open(__import__('io').BytesIO(page.locator('#battleCanvas').screenshot())).convert('RGB')
    w, h = img.size

    colors = img.getcolors(maxcolors=1 << 20) or []
    check(f'[{tag}] 画面非纯色（渐变/网格生效）', len(colors) > 20, f'{len(colors)} 种颜色')

    # 左侧安全边距（占宽 2%~14%）。角色站在中心 ±274*scale 处，
    # 1280 宽时角色左缘在 16.9% 处，所以 14% 以内是纯背景。
    x0, x1 = int(w * 0.02), int(w * 0.14)

    def region_avg(y_from, y_to):
        px = [img.getpixel((x, y))
              for y in range(max(0, y_from), min(h, y_to))
              for x in range(x0, x1, 2)]
        return tuple(statistics.mean(c[i] for c in px) for i in range(3))

    # 地面线在世界 y=0，高出视口下缘 GROUND_H；换算到画面像素需乘 scale
    ground_px = 74 * scale
    gy = int(h - ground_px)

    sky = region_avg(int(h * 0.28), int(h * 0.42))
    ground = region_avg(min(h - 2, gy + 3), min(h, gy + 10))
    notes.append(f'[{tag}] 天空RGB={tuple(round(v) for v in sky)} '
                 f'地面顶部RGB={tuple(round(v) for v in ground)} '
                 f'(地面线 y={gy}px / canvas 高 {h}px)')

    # 旧配色：天空 #24321f(G=50) 附近，地面顶部 #4a6a3a(G=106)
    check(f'[{tag}] 地面顶部显著亮于天空（两层都渲染了）', ground[1] > sky[1] + 25,
          f'sky.G={sky[1]:.0f} ground.G={ground[1]:.0f}')
    check(f'[{tag}] 地面色接近旧 CSS #4a6a3a', 85 <= ground[1] <= 118,
          f'ground.G={ground[1]:.0f}')
    check(f'[{tag}] 天空为深绿（暗于地面）', 35 <= sky[1] <= 85, f'sky.G={sky[1]:.0f}')

    # 网格线：在安全边距内逐像素扫一行，应有明显起伏
    y_grid = int(h * 0.35)
    samples = [img.getpixel((x, y_grid))[1] for x in range(x0, x1)]
    check(f'[{tag}] 存在网格线（行内亮度有起伏）',
          (max(samples) - min(samples)) >= 3, f'range={max(samples) - min(samples)}')

    # 地面条底部不应是天空色，确认地面条有垂直渐变
    g_bottom = region_avg(h - 6, h - 1)
    check(f'[{tag}] 地面条自上而下有渐变', g_bottom[1] < ground[1],
          f'底部.G={g_bottom[1]:.0f} < 顶部.G={ground[1]:.0f}')
    return img


def check_units_pixels(img, view_h, scale):
    """角色层像素校验：确认 canvas 上真的画出了角色，而不只是背景。

    判据：背景是绿色系（G 通道占优），勇者铠甲是蓝色系（B 通道占优）。
    只统计角色所在的高度带，避开上方的名牌（我方名牌是蓝色渐变）与
    下方的血条，否则会把 HUD 误判成角色。
    """
    w, h = img.size
    ground_px = 74 * scale
    feet = h - ground_px

    cx = w / 2
    half = 70 * scale
    y_top = int(feet - 120 * scale)
    y_bot = int(feet - 6 * scale)

    def count(pred):
        n = 0
        for side, sign in (('me', 1), ('foe', -1)):
            xc = cx + sign * 274 * scale
            for y in range(max(0, y_top), min(h, y_bot)):
                for x in range(int(xc - half), int(xc + half), 2):
                    if 0 <= x < w and pred(img.getpixel((x, y))):
                        n += 1
        return n

    blue = count(lambda c: c[2] > c[1] + 18 and c[2] > 60)      # 勇者铠甲
    red = count(lambda c: c[0] > c[1] + 24 and c[0] > 70)       # 魔王红纹 / 火焰剑
    notes.append(f'[角色] 取样带 y={y_top}..{y_bot}，蓝色像素={blue}，红色像素={red}')
    check('[角色] canvas 上出现勇者的蓝色铠甲像素', blue > 120, f'blue={blue}')
    check('[角色] canvas 上出现魔王的红色像素', red > 60, f'red={red}')


def sample_pose(page):
    """读取骨骼上几个关节的当前数值，用于验证待机呼吸在逐帧变化。"""
    return page.evaluate("""() => {
        const r = window.__battleFX && window.__battleFX.getActive();
        if (!r || !r.units || !r.units.me) return null;
        const me = r.units.me;
        const head = me.parts.find(p => p.name === 'head');
        const weapon = me.parts.find(p => p.name === 'weapon');
        return {
            rootX: me.root.position.x,
            rootY: me.root.position.y,
            rootRot: me.root.rotation.z,
            torsoScaleY: me.nodes.get('torso').scale.y,
            headRot: head ? head.node.rotation.z : 0,
            headY: head ? head.node.position.y : 0,
            weaponRot: weapon ? weapon.node.rotation.z : 0,
        };
    }""")


def sample_pose_series(page, count=7, gap_ms=90):
    """连续采样若干次。

    不能只比"两次采样的差值" —— 待机是正弦运动，若两次采样恰好落在
    波峰两侧的对称相位上，位移差值会巧合地接近 0（第一版就踩了这个坑：
    ΔrootY 恰好 0.0008 而实际摆幅有 5.5 世界单位）。
    改成取一串样本的极差，衡量的是"有没有在动"，与时序无关。
    """
    series = []
    for i in range(count):
        s = sample_pose(page)
        if s:
            series.append(s)
        if i < count - 1:
            page.wait_for_timeout(gap_ms)
    return series


def _now_timescale(page):
    """读取 three 渲染器当前 timeScale（演出结束后的恢复校验用）。"""
    return page.evaluate("""() => {
        const r = window.__battleFX && window.__battleFX.getActive();
        return r && r.host ? r.host.timeScale : null;
    }""")


def run_mode(pw, mode, name, shot_path):
    print(f'=== 模式：{mode} ===')
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = ctx.new_page()

    errors = []
    page.on('console', lambda m: errors.append(f'console:{m.text}') if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(f'pageerror:{e}'))
    page.on('requestfailed', lambda r: errors.append(f'reqfailed:{r.url} {r.failure}'))

    url = f'{BASE}/?renderer={mode}'
    login(page, name, url)
    enter_battle(page)

    hidden = page.locator('#battleCanvas').is_hidden()
    has_three_class = page.evaluate(
        "document.getElementById('battleStage').classList.contains('is-three')")
    sprite_hidden = page.evaluate(
        "getComputedStyle(document.getElementById('btMySprite')).visibility === 'hidden'")

    if mode == 'dom':
        check('[dom] canvas 保持隐藏（零影响）', hidden)
        check('[dom] 舞台上没有 is-three 类', not has_three_class)
        check('[dom] 角色仍由 DOM 精灵显示（visibility 可见）', not sprite_hidden)
        check('[dom] 未创建 three 渲染器实例',
              page.evaluate("!window.__battleFX || !window.__battleFX.getActive()"))
        # dom 模式下旧 CSS 背景必须在位
        check('[dom] 旧 CSS 网格伪元素未让位',
              page.evaluate("getComputedStyle(document.querySelector('.battle-stage'),'::before').display !== 'none'"))
        check('[dom] 底座仍在（WebGL 未接管）',
              page.evaluate("getComputedStyle(document.querySelector('.bt-pedestal')).visibility !== 'hidden'"))
    else:
        check('[three] canvas 已显示', not hidden)
        check('[three] 舞台已加 is-three 类', has_three_class)
        check('[three] 旧 CSS 伪元素已让位',
              page.evaluate("getComputedStyle(document.querySelector('.battle-stage'),'::before').display === 'none'"))

        # P1：骨骼就绪后 WebGL 接管角色本体
        ready = page.evaluate("""() => {
            const r = window.__battleFX && window.__battleFX.getActive();
            if (!r) return null;
            const ids = page => null;
            const me = r.units && r.units.me, foe = r.units && r.units.foe;
            return {
                unitsReady: !!r.unitsReady,
                unitsError: r.unitsError ? String(r.unitsError.message || r.unitsError) : null,
                meUnit: me ? me.unitName : null,
                foeUnit: foe ? foe.unitName : null,
                meParts: me ? me.parts.map(p => p.name) : null,
                foeParts: foe ? foe.parts.map(p => p.name) : null,
                meMetaParts: me && me.meta ? me.meta.parts.length : 0,
            };
        }""")
        check('[three] 骨骼资产加载成功', ready and ready['unitsError'] is None,
              (ready or {}).get('unitsError') or '')
        check('[three] 两个单位都已上屏', bool(ready and ready['unitsReady']))
        if ready:
            check('[three] 我方识别为 hero', ready['meUnit'] == 'hero', str(ready['meUnit']))
            check('[three] 敌方识别为 boss', ready['foeUnit'] == 'boss', str(ready['foeUnit']))
            check('[three] 我方部件数与 rig 定义一致',
                  len(ready['meParts'] or []) == ready['meMetaParts'],
                  f"{len(ready['meParts'] or [])} vs {ready['meMetaParts']}")
            for need in ('__base', 'torso', 'head', 'armL', 'weapon', 'legL', 'legR'):
                check(f"[three] 我方含部件 {need}", need in (ready['meParts'] or []))
        check('[three] DOM 精灵已让位给 WebGL', sprite_hidden)

        # P3：编排器与三件套（fx/镜头/HUD 覆盖层）已组装
        p3 = page.evaluate("""() => {
            const r = window.__battleFX && window.__battleFX.getActive();
            if (!r) return null;
            return {
                choreo: !!r.choreographer,
                fx: !!r.fx,
                camera: !!r.camera,
                hudLayer: !!r.hud,
                hudDom: !!document.querySelector('.battle-hud'),
                timeScale: r.host.timeScale,
            };
        }""")
        check('[three] P3 编排器已组装（choreographer/fx/camera/hud）',
              bool(p3 and p3['choreo'] and p3['fx'] and p3['camera']
                   and p3['hudLayer'] and p3['hudDom']), str(p3))

        info = page.evaluate("""() => {
            const r = window.__battleFX && window.__battleFX.getActive();
            if (!r) return null;
            const rect = r.container.getBoundingClientRect();
            return {
                calls: r.host.renderer.info.render.calls,
                triangles: r.host.renderer.info.render.triangles,
                dpr: r.host.renderer.getPixelRatio(),
                canvasW: r.canvas.width, canvasH: r.canvas.height,
                viewW: Math.round(r.host.view.viewW), viewH: Math.round(r.host.view.viewH),
                scale: r.host.view.scale,
                stageW: Math.round(rect.width), stageH: Math.round(rect.height),
                fps: Math.round(r.host.fps), enabled: r.enabled,
            };
        }""")
        check('[three] 渲染器实例已创建', info is not None, str(info))
        if info:
            # 舞台 1 + 我方(7 部件 + 阴影) + 敌方(7 部件 + 阴影) = 17 个 quad
            check('[three] 每帧有 draw call', info['calls'] >= 15, f"calls={info['calls']}")
            check('[three] 三角数符合部件规模（每个 quad 2 三角）',
                  info['triangles'] >= 30, f"tris={info['triangles']}")
            check('[three] DPR 已按预算钳制（<=2）', 0 < info['dpr'] <= 2, f"dpr={info['dpr']}")
            check('[three] canvas 后备缓冲已分配', info['canvasW'] > 100 and info['canvasH'] > 100,
                  f"{info['canvasW']}x{info['canvasH']}")
            check('[three] 帧循环已启用', info['enabled'])

            # P1 关键回归：世界单位必须等于 CSS 像素，否则角色大小随窗口漂移
            check('[three] 世界单位 = CSS 像素（scale==1）',
                  abs(info['scale'] - 1) < 1e-6, f"scale={info['scale']}")
            check('[three] 视口尺寸与舞台 CSS 尺寸一致',
                  abs(info['viewW'] - info['stageW']) <= 1 and abs(info['viewH'] - info['stageH']) <= 1,
                  f"view={info['viewW']}x{info['viewH']} stage={info['stageW']}x{info['stageH']}")
            check('[three] 舞台高度合理（战斗布局未塌陷）',
                  200 < info['stageH'] <= 900, f"stageH={info['stageH']}")

            img = analyse_canvas(page, 'three', info['viewH'], info['scale'])
            if img:
                check_units_pixels(img, info['viewH'], info['scale'])

        # 待机呼吸：连续采样一串，用极差判断（避免正弦相位巧合）
        series = sample_pose_series(page)
        check('[three] 可读取骨骼关节状态', len(series) >= 5, f'{len(series)} 个样本')
        if len(series) >= 5:
            def span(key):
                vals = [s[key] for s in series]
                return max(vals) - min(vals)
            spans = {k: span(k) for k in series[0]}
            notes.append('[待机] 关节摆幅（极差） ' +
                         ', '.join(f'{k}={v:.4f}' for k, v in spans.items()))
            check('[three] 待机呼吸在跑（根节点有位移摆幅）',
                  spans['rootY'] > 0.5, f"摆幅={spans['rootY']:.3f} 世界单位")
            check('[three] 根节点有微倾摆幅（对应旧 rotate(-1.2deg)）',
                  spans['rootRot'] > 0.004, f"摆幅={math.degrees(spans['rootRot']):.2f}度")
            check('[three] 躯干有呼吸缩放摆幅',
                  spans['torsoScaleY'] > 0.002, f"摆幅={spans['torsoScaleY']:.4f}")
            check('[three] 头部独立于根节点在动（分层滞后）',
                  spans['headY'] > 0.2 or spans['headRot'] > 0.002,
                  f"ΔheadY={spans['headY']:.3f} ΔheadRot={math.degrees(spans['headRot']):.2f}度")
            check('[three] 武器随手臂摆动（相位再滞后）',
                  spans['weaponRot'] > 0.002, f"摆幅={math.degrees(spans['weaponRot']):.2f}度")

    page.screenshot(path=shot_path, full_page=False)

    # ---- 出招演出验收（P3 核心） ----
    # 点第一题的选项，rAF 逐帧采样整个演出窗口（约 1.5s）：
    #   dom   → 旧路径回归：.bt-dmg 仍弹在 .bt-unit 里，无渲染器内部状态可读
    #   three → 骨骼突进 / 顿帧(timeScale→0) / 镜头推近+震屏 / 覆盖层飘字
    # 闯关模式里答对=我方砍敌方、答错=Boss 反击我方 —— 两条路都有完整命中演出，
    # 所以无需关心这一题碰巧对错。
    before = page.evaluate("document.querySelector('#battleQuest .bt-qmeta').innerText")
    page.locator('#battleQuest .bt-opt:not([disabled])').first.click()

    samples = page.evaluate("""(mode) => new Promise(resolve => {
        const out = {
            meXMin: 1e9, meXMax: -1e9, foeXMin: 1e9, foeXMax: -1e9,
            timeScaleMin: 1, zoomMax: 0, camXMin: 1e9, camXMax: -1e9,
            hudDmgMax: 0, domDmgMax: 0, frames: 0,
        };
        const start = performance.now();
        const step = () => {
            const r = mode === 'three' && window.__battleFX && window.__battleFX.getActive();
            if (r && r.units && r.units.me && r.units.foe) {
                out.meXMin = Math.min(out.meXMin, r.units.me.root.position.x);
                out.meXMax = Math.max(out.meXMax, r.units.me.root.position.x);
                out.foeXMin = Math.min(out.foeXMin, r.units.foe.root.position.x);
                out.foeXMax = Math.max(out.foeXMax, r.units.foe.root.position.x);
                out.timeScaleMin = Math.min(out.timeScaleMin, r.host.timeScale);
                out.zoomMax = Math.max(out.zoomMax, r.host.camera.zoom);
                out.camXMin = Math.min(out.camXMin, r.host.camera.position.x);
                out.camXMax = Math.max(out.camXMax, r.host.camera.position.x);
            }
            out.hudDmgMax = Math.max(out.hudDmgMax,
                document.querySelectorAll('.battle-hud .bt-dmg').length);
            out.domDmgMax = Math.max(out.domDmgMax,
                document.querySelectorAll('.bt-unit .bt-dmg').length);
            out.frames++;
            if (performance.now() - start < 1500) requestAnimationFrame(step);
            else resolve(out);
        };
        requestAnimationFrame(step);
    })""", mode)

    page.wait_for_timeout(1500)
    after = page.evaluate("document.querySelector('#battleQuest .bt-qmeta').innerText")
    check(f'[{mode}] 出招后自动进入下一回合', before != after, f'{before!r} -> {after!r}')

    if mode == 'three':
        me_span = samples['meXMax'] - samples['meXMin']
        foe_span = samples['foeXMax'] - samples['foeXMin']
        cam_span = samples['camXMax'] - samples['camXMin']
        notes.append(
            f"[演出] meX跨度={me_span:.1f} foeX跨度={foe_span:.1f} "
            f"timeScaleMin={samples['timeScaleMin']} zoomMax={samples['zoomMax']:.4f} "
            f"camX跨度={cam_span:.2f} HUD飘字={samples['hudDmgMax']} 帧数={samples['frames']}")
        check('[three] 攻击方骨骼有突进位移（命中时间轴在跑）',
              me_span > 3 or foe_span > 3, f'me={me_span:.1f} foe={foe_span:.1f}')
        check('[three] 命中瞬间触发顿帧（timeScale 归零）',
              samples['timeScaleMin'] <= 0.01, f"min={samples['timeScaleMin']}")
        check('[three] 顿帧后恢复（timeScale 回到 1）',
              samples['timeScaleMin'] >= 0 and abs(_now_timescale(page) - 1) < 1e-6,
              f"current={_now_timescale(page)}")
        check('[three] 镜头有推近冲击（zoom > 1）',
              samples['zoomMax'] > 1.0005, f"zoomMax={samples['zoomMax']:.4f}")
        check('[three] 镜头有震屏（x 向抖动）', cam_span > 1.5, f'跨度={cam_span:.2f}')
        check('[three] 伤害飘字出现在 HUD 覆盖层（worldToScreen 定位）',
              samples['hudDmgMax'] >= 1, f"max={samples['hudDmgMax']}")
        check('[three] 未走旧 DOM 飘字路径（两套渲染器互斥）',
              samples['domDmgMax'] == 0, f"旧路径飘字={samples['domDmgMax']}")

        # 出招演出结束后应回到静止姿态（位移归零；待机只有 ±5.5 的纵向浮动）
        page.wait_for_timeout(600)
        rest = sample_pose(page)
        check('[three] 演出结束后动作层归位（rootX 无残留）',
              rest is not None and abs(rest['rootX']) < 2,
              str(rest and round(rest['rootX'], 2)))
        check('[three] 演出结束后待机呼吸仍在（rootY 小幅浮动）',
              rest is not None and abs(rest['rootY']) < 25,
              str(rest and round(rest['rootY'], 2)))
    else:
        check('[dom] 旧路径飘字仍弹在 .bt-unit 内（回落未坏）',
              samples['domDmgMax'] >= 1, f"max={samples['domDmgMax']}")
        check('[dom] 未创建 HUD 覆盖层', samples['hudDmgMax'] == 0,
              f"hudDmg={samples['hudDmgMax']}")

    check(f'[{mode}] 战斗无 JS 报错', not errors, str(errors[:3]))

    browser.close()


# ---------------------------------------------------------------- 起服务
# app.py 的 init_db()/load_questions() 只在 __main__ 分支里调用，
# 以模块方式导入时必须自己补上，否则 /api/classes 会因缺表而 500。
appmod.init_db()
appmod.load_questions()

# 全新库里没有班级，登录表单的下拉是空的 —— 先造一个测试班级。
# 注意：花名册模式默认开启，登录必须从名单里选姓名；名单为空时
# <select required> 的空值会被浏览器 HTML5 校验拦下，表单根本不提交，
# 表现为"点了登录毫无反应、连错误提示都没有"，很不好排查。
with appmod.get_db() as _conn:
    _conn.execute("INSERT OR IGNORE INTO classes (class_name) VALUES (?)", (CLASS_NAME,))
    _conn.execute("INSERT OR IGNORE INTO students (name, class_name) VALUES (?, ?)", (ROSTER_NAME, CLASS_NAME))
    _conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('battle_enabled', '1')")
    _conn.commit()

srv = make_server('127.0.0.1', PORT, appmod.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

try:
    with sync_playwright() as pw:
        run_mode(pw, 'dom', 'P0冒烟甲', 'smoke_battle_render_dom.png')
        print()
        run_mode(pw, 'three', 'P0冒烟乙', 'smoke_battle_render_three.png')
finally:
    srv.shutdown()

print()
for n in notes:
    print('NOTE:', n)
if failures:
    print(f'结果：{len(failures)} 项失败 -> {failures}')
    sys.exit(1)
print('结果：P1 浏览器验收全部通过 ✅')
