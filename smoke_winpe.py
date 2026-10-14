# -*- coding: utf-8 -*-
"""
WinPE 考试全流程冒烟：真实操作 → 服务端重放判分。

覆盖：U 盘引导(w1) → 快速分区(w2) → 删除 E 盘(w4) → 安装系统(w5) → 交卷。
重点验证"系统按操作步骤自动判定"确实能给出非零分。
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get('SMOKE_BASE', 'http://127.0.0.1:5099')
failed, errors = [], []


def check(name, cond, extra=''):
    print(('  OK  ' if cond else '  FAIL') + ' ' + name + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        failed.append(name)


def pick_student(page):
    """挑一个还没考过 WinPE 的学生并登录。"""
    page.goto(BASE + '/portal', wait_until='networkidle')
    page.wait_for_selector('#selClass option:not([value=""])', state='attached', timeout=8000)
    cls = page.eval_on_selector_all('#selClass option:not([value=""])', 'e=>e.map(x=>x.value)')
    page.select_option('#selClass', cls[1])
    page.wait_for_timeout(700)
    names = page.eval_on_selector_all('#selName option:not([value=""])', 'e=>e.map(x=>x.value)')
    for nm in names:
        ok = page.evaluate("""async d => {
            const a = await fetch('/login', {method:'POST',
                headers:{'Content-Type':'application/json'}, body: JSON.stringify(d)});
            if (!(await a.json()).success) return false;
            const r = await fetch('/api/sim/result?type=winpe');
            const j = await r.json();
            return !j.taken && !j.in_progress;   // 连"开考未交卷"的也要跳过
        }""", {'name': nm, 'class_name': cls[1]})
        if ok:
            return cls[1], nm
    return cls[1], None


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(viewport={'width': 1400, 'height': 950}).new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('dialog', lambda d: d.accept())     # 交卷二次确认

    print('\n[1] 登录并进入 WinPE 考试')
    cls, who = pick_student(page)
    check('找到未考过 WinPE 的考生', who is not None, '%s / %s' % (cls, who))
    if not who:
        sys.exit(1)

    page.goto(BASE + '/sim/winpe', wait_until='domcontentloaded')
    page.wait_for_function("() => !!document.querySelector('#peBoot')", timeout=20000)
    page.wait_for_function("() => !document.querySelector('#peBoot')", timeout=30000)
    page.wait_for_timeout(700)
    check('U 盘引导动画已播放完毕', page.query_selector('#peBoot') is None)
    check('PE 桌面就绪', page.query_selector('.dicon[data-id="dg"]') is not None)

    print('\n[2] 快速分区（MBR / 3 区 / C 盘 100GB / 4K 4096）')
    page.dblclick('.dicon[data-id="dg"]')
    page.wait_for_timeout(600)
    check('DiskGenius 已打开', page.query_selector('#dgTable') is not None)

    page.click('.dg-btn:has-text("快速分区")')
    page.wait_for_timeout(500)
    check('快速分区对话框已弹出', page.query_selector('#qTable') is not None)

    page.select_option('#qTable', 'MBR')
    page.select_option('#qCount', '3')
    page.click('#qReset')                      # 按新数量重建分区输入框
    page.wait_for_timeout(300)
    page.eval_on_selector_all('.qsz', 'els => { if(els[0]) els[0].value = "100"; }')
    page.check('#qAlign')
    page.select_option('#qAlignN', '4096')
    page.click('.dlg-mask [data-a="ok"]')      # 第一步：确定
    page.wait_for_timeout(500)
    check('弹出二次确认', page.query_selector('.dlg-mask .dlg .dt') is not None,
          page.text_content('.dlg-mask .dlg .dt') if page.query_selector('.dlg-mask .dlg .dt') else '')
    page.click('.dlg-mask [data-a="ok"]')      # 第二步：确认执行
    page.wait_for_timeout(700)

    parts = page.eval_on_selector_all('#dgTable tr td:first-child', 'e=>e.map(x=>x.textContent)')
    check('已重建为 3 个分区', len(parts) == 3, parts)

    print('\n[3] 删除 E 盘（右键 → 删除当前分区）')
    idx = parts.index('E盘') if 'E盘' in parts else -1
    check('找到 E 盘', idx >= 0, parts)
    if idx >= 0:
        # tr[0] 是表头，数据行要往后挪一位
        row = page.query_selector('#dgTable tr:nth-child(%d)' % (idx + 2))
        row.click(button='right')
        page.wait_for_timeout(300)
        page.click('.ctx-menu .ctx-item:has-text("删除当前分区")')
        page.wait_for_timeout(400)
        page.click('.dlg-mask [data-a="ok"]')
        page.wait_for_timeout(500)
        left = page.eval_on_selector_all('#dgTable tr td:first-child', 'e=>e.map(x=>x.textContent)')
        check('E 盘已删除', 'E盘' not in left, left)

    print('\n[4] 安装系统（引导分区 / 安装分区均选 C 盘）')
    page.dblclick('.dicon[data-id="setup"]')
    page.wait_for_timeout(600)
    check('Windows 安装器已打开', page.query_selector('#iGo') is not None)
    if page.query_selector('input[name="boot"][value="C"]'):
        page.check('input[name="boot"][value="C"]')
        page.check('input[name="target"][value="C"]')
        page.click('#iGo')
        # 安装进度是随机步长的定时器，轮询 state 比等 DOM 稳定
        page.wait_for_function(
            "() => !!(typeof state !== 'undefined' && state.lastInstall && state.lastInstall.finished)",
            timeout=40000)
        page.wait_for_timeout(500)
        check('安装完成', '安装完成' in (page.text_content('#iDone') or ''),
              page.text_content('#iDone'))
        check('完成提示可见', page.is_visible('#iDone'))
    else:
        check('存在 C 盘选项', False)

    print('\n[5] 交卷')
    page.evaluate("() => { if(typeof submitWinpeExam === 'function') submitWinpeExam(); }")
    page.wait_for_timeout(3000)
    res = page.query_selector('.sim-result')
    check('成绩单已展示', res is not None)
    if res:
        print('    ' + '\n    '.join(res.inner_text().splitlines()[:4]))

    api = page.evaluate("""async () => {
        const r = await fetch('/api/sim/result?type=winpe');
        return await r.json();
    }""")
    check('服务端记到成绩', bool(api.get('taken')))
    if api.get('taken'):
        r = api['result']
        got = {s['id']: s['got'] for s in r['steps']}
        print('    总分 =', r.get('score'), ' 各项 =', got)
        check('U 盘引导得分(w1)', got.get('w1', 0) > 0, got.get('w1'))
        check('快速分区得分(w2)', got.get('w2', 0) > 0, got.get('w2'))
        check('删除 E 盘得分(w4)', got.get('w4', 0) > 0, got.get('w4'))
        check('安装系统得分(w5)', got.get('w5', 0) > 0, got.get('w5'))
        check('总分 > 0', (r.get('score') or 0) > 0, r.get('score'))

    b.close()

print('\n================')
if errors:
    print('JS 错误：')
    for e in errors[:6]:
        print('  - ' + e[:220])
print('失败 %d 项' % len(failed))
sys.exit(1 if failed else 0)
