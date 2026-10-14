# -*- coding: utf-8 -*-
"""
统一考试系统浏览器冒烟测试。

验证三件事：
  1. 门户页能登录（名单来自刷题系统的 students 表）
  2. BIOS 模拟器能正常加载、身份注入成功、考试流程可走通
  3. 交卷后服务端确实返回了分数（而不是前端自己算的）

用法：先启动服务（PORT=5099 python app.py），再运行本脚本。
      .venv/Scripts/python.exe smoke_sim.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('SMOKE_BASE', 'http://127.0.0.1:5099')

errors = []      # 页面 JS 错误
failed = []


def check(name, cond, extra=''):
    print(('  ✔ ' if cond else '  ✘ ') + name + (('  → ' + str(extra)) if extra else ''))
    if not cond:
        failed.append(name)


def run(p):
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1280, 'height': 860})
    page = ctx.new_page()

    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append('console.error: ' + m.text)
            if m.type == 'error' else None)

    # ---------- 1. 门户页登录 ----------
    print('\n[1] 统一门户登录')
    page.goto(BASE + '/portal', wait_until='networkidle')
    check('门户页标题正确', '统一考试平台' in page.title() or '统一考试平台' in page.content())

    # option 元素在 Playwright 里不是 "visible"，必须用 attached 状态等待
    page.wait_for_selector('#selClass option:not([value=""])', timeout=8000, state='attached')
    cls = page.eval_on_selector_all(
        '#selClass option:not([value=""])', 'els => els.map(e => e.value)')
    check('班级下拉已加载', len(cls) > 0, '%d 个班' % len(cls))

    page.select_option('#selClass', index=1)
    page.wait_for_timeout(700)
    names = page.eval_on_selector_all(
        '#selName option:not([value=""])', 'els => els.map(e => e.value)')
    check('名单已按班级加载', len(names) > 0, '%d 人' % len(names))

    # 限考 1 次：自动挑一个「还没考过 BIOS」的学生，保证脚本可重复运行
    chosen_name, chosen_cls = None, page.eval_on_selector('#selClass', 'el => el.value')
    for nm in names:
        ok = page.evaluate("""async (d) => {
            const a = await fetch('/login', {method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify(d)});
            if (!(await a.json()).success) return false;
            const b = await fetch('/api/sim/result?type=bios');
            const j = await b.json();
            return !j.taken && !j.in_progress;
        }""", {'name': nm, 'class_name': chosen_cls})
        if ok:
            chosen_name = nm
            break
    check('找到未考过 BIOS 的考生', chosen_name is not None, chosen_name)
    if not chosen_name:
        raise SystemExit('该班所有人都已考过 BIOS，无法冒烟')
    print('    选择：%s / %s' % (chosen_cls, chosen_name))

    # 上面循环中最后一次登录成功的人就是 chosen_name，刷新即进入已登录态
    page.reload(wait_until='networkidle')
    page.wait_for_selector('#mainBox', state='visible', timeout=8000)
    page.wait_for_timeout(600)

    err = page.text_content('#errMsg') if page.query_selector('#errMsg') else ''
    if err and err.strip():
        print('    登录错误提示：' + err.strip())
    check('登录后显示姓名', bool((page.text_content('#whoName') or '').strip()),
          page.text_content('#whoName'))

    if not (page.text_content('#whoName') or '').strip():
        # 登录失败则打印服务端返回的原始信息，便于定位
        raw = page.evaluate("""async (d) => {
            const r = await fetch('/login', {method:'POST',
                headers:{'Content-Type':'application/json'}, body: JSON.stringify(d)});
            return {status:r.status, body: await r.text()};
        }""", {'name': chosen_name, 'class_name': chosen_cls})
        print('    直接调 /login →', raw)

    # ---------- 2. 进入 BIOS 模拟 ----------
    print('\n[2] BIOS 模拟器')
    page.goto(BASE + '/sim/bios', wait_until='domcontentloaded')
    page.wait_for_timeout(1200)

    boot = page.evaluate('() => window.SIM_BOOT || null')
    check('SIM_BOOT 已注入', boot is not None)
    check('身份来自服务端', bool(boot and boot.get('logged_in')), boot and boot.get('student_name'))
    check('时长已下发', bool(boot and boot.get('minutes')), boot and boot.get('minutes'))

    # 等待开考（POST 自检会先播放）
    page.wait_for_timeout(2500)
    has_post = page.query_selector('#simOverlay') is not None
    check('开机自检画面出现', has_post)

    # 处理 POST 内存报错：按 A（重新插拔）
    if has_post:
        page.wait_for_timeout(2600)
        if page.query_selector('.sim-choice li'):
            page.keyboard.press('a')
            page.wait_for_timeout(900)
            page.keyboard.press('Space')     # 关掉结果说明
            page.wait_for_timeout(2200)      # 等 "Press F2" 动画
    page.wait_for_timeout(1200)

    bios_visible = page.query_selector('#biosRoot') is not None and page.is_visible('#biosRoot')
    check('BIOS 主界面已显示', bios_visible)

    # 顶部考试条
    bar = page.query_selector('#simBar')
    check('顶部考试状态条存在', bar is not None)
    clock = page.text_content('#simClock') if page.query_selector('#simClock') else ''
    check('倒计时在走', '剩余' in (clock or ''), clock)

    # 任务清单
    tasks = page.eval_on_selector_all('.exam-tasks li', 'els => els.length') \
        if page.query_selector('.exam-tasks') else 0
    check('考试任务清单已渲染', tasks > 0, '%d 项' % tasks)

    # ---------- 3. 实际操作（键盘走完整流程） ----------
    print('\n[3] 模拟操作')
    def press(key, times=1, delay=90):
        for _ in range(times):
            page.keyboard.press(key)
            page.wait_for_timeout(delay)

    press('ArrowRight', 3)      # Main → Advanced
    press('ArrowDown', 6)       # 移动到 Secure Boot
    press('Enter')              # 关闭 Secure Boot（Enabled → Disabled）
    press('ArrowDown', 2)       # → CSM
    press('Enter')              # 开启 CSM
    press('ArrowRight', 1)      # → H/W Monitor
    press('ArrowRight', 1)      # → Exit（此时不改，回去）
    press('ArrowLeft', 2)       # 回到 Advanced
    press('ArrowRight', 1)      # → H/W Monitor
    press('ArrowRight', 1)      # → Exit

    # 触发故障判断问答
    press('ArrowDown', 3)
    for _ in range(6):
        cur = page.evaluate("""() => {
            const el = document.querySelector('#biosRoot');
            return el ? el.innerText.slice(0,0) : '';
        }""")
        press('ArrowDown', 1)

    page.wait_for_timeout(300)

    # 直接调用函数触发故障问答，保证埋点被覆盖
    page.evaluate('() => { if (typeof openFaultQuiz === "function") openFaultQuiz(); }')
    page.wait_for_timeout(500)
    if page.query_selector('.sim-choice li'):
        page.keyboard.press('a')          # 选 A（正确答案）
        page.wait_for_timeout(800)
        page.keyboard.press('Space')
        page.wait_for_timeout(600)

    # F12 启动菜单
    page.keyboard.press('F12')
    page.wait_for_timeout(600)
    if page.query_selector('.sim-choice li'):
        page.keyboard.press('3')          # 选 USB HDD
        page.wait_for_timeout(900)
        page.keyboard.press('Space')
        page.wait_for_timeout(600)

    # F10 保存退出 → 交卷
    print('\n[4] 交卷')
    page.keyboard.press('F10')
    page.wait_for_timeout(700)
    page.keyboard.press('y')
    page.wait_for_timeout(2500)

    result = page.query_selector('.sim-result')
    check('成绩单已展示', result is not None)
    if result:
        txt = result.inner_text()
        print('    ---- 成绩单摘要 ----')
        for line in txt.splitlines()[:6]:
            print('    ' + line)
        check('成绩单含分数', '分' in txt)

    # ---------- 5. 服务端确实记到了成绩 ----------
    print('\n[5] 服务端核对')
    api = page.evaluate("""async () => {
        const r = await fetch('/api/sim/result?type=bios');
        return await r.json();
    }""")
    check('服务端返回已考记录', bool(api.get('taken')), api.get('result', {}).get('normalized'))
    if api.get('taken'):
        res = api['result']
        check('服务端有逐项得分', len(res.get('steps', [])) == 15,
              '实际 %d 项' % len(res.get('steps', [])))
        got = [s for s in res['steps'] if s['got'] > 0]
        print('    得分项：' + ', '.join('%s=%s' % (s['id'], s['got']) for s in got))

    # ---------- 6. 限考 1 次 ----------
    page.goto(BASE + '/sim/bios', wait_until='networkidle')
    page.wait_for_timeout(1800)
    again = page.evaluate("""async () => {
        const r = await fetch('/api/sim/start', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({sim_type:'bios'})});
        return {status: r.status, body: await r.json()};
    }""")
    check('重复开考被拒绝(409)', again['status'] == 409,
          again['body'].get('message'))

    browser.close()


def main():
    with sync_playwright() as p:
        run(p)

    print('\n================ 结果 ================')
    real_errors = [e for e in errors if 'favicon' not in e.lower()]
    if real_errors:
        print('页面 JS 错误 %d 条：' % len(real_errors))
        for e in real_errors[:8]:
            print('   - ' + e[:220])
    else:
        print('无 JS 错误')

    if failed:
        print('失败检查项 %d 个：%s' % (len(failed), ', '.join(failed)))
        sys.exit(1)
    print('全部通过 ✔')


if __name__ == '__main__':
    main()
