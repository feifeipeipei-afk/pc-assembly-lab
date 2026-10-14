# -*- coding: utf-8 -*-
"""校验 WinPE 右键菜单：桌面空白处、桌面图标、DiskGenius 分区行。"""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get('SMOKE_BASE', 'http://127.0.0.1:5099')
failed, errors = [], []


def check(name, cond, extra=''):
    print(('  OK  ' if cond else '  FAIL') + ' ' + name + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        failed.append(name)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(viewport={'width': 1360, 'height': 900}).new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))

    # 登录（练习模式下 WinPE 会直接进桌面）
    page.goto(BASE + '/portal', wait_until='networkidle')
    page.wait_for_selector('#selClass option:not([value=""])', state='attached', timeout=8000)
    cls = page.eval_on_selector_all('#selClass option:not([value=""])', 'e=>e.map(x=>x.value)')
    page.select_option('#selClass', cls[1])
    page.wait_for_timeout(700)
    names = page.eval_on_selector_all('#selName option:not([value=""])', 'e=>e.map(x=>x.value)')
    # 挑一个还没考过 WinPE 的，避免被"限考 1 次"的提示条挡住
    who = None
    for nm in names:
        ok = page.evaluate("""async d => {
            const a = await fetch('/login', {method:'POST',
                headers:{'Content-Type':'application/json'}, body: JSON.stringify(d)});
            if (!(await a.json()).success) return false;
            const b = await fetch('/api/sim/result?type=winpe');
            return !(await b.json()).taken;
        }""", {'name': nm, 'class_name': cls[1]})
        if ok:
            who = nm
            break
    print('    考生：%s / %s' % (cls[1], who))
    assert who, '该班所有人都已考过 WinPE'

    page.goto(BASE + '/sim/winpe?mode=practice', wait_until='domcontentloaded')
    page.wait_for_timeout(900)

    print('\n[桌面右键]')
    page.mouse.click(900, 400, button='right')
    page.wait_for_timeout(300)
    check('桌面右键菜单出现', page.query_selector('.ctx-menu') is not None)
    txt = page.inner_text('.ctx-menu') if page.query_selector('.ctx-menu') else ''
    check('含刷新/打开 DiskGenius', '刷新' in txt and 'DiskGenius' in txt, txt.replace('\n', ' | ')[:100])

    # 关闭
    page.mouse.click(200, 700)
    page.wait_for_timeout(200)
    check('点击别处可关闭菜单', page.query_selector('.ctx-menu') is None)

    print('\n[桌面图标右键]')
    box = page.query_selector('.dicon[data-id="dg"]').bounding_box()
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, button='right')
    page.wait_for_timeout(300)
    t2 = page.inner_text('.ctx-menu') if page.query_selector('.ctx-menu') else ''
    check('图标右键含打开/属性', '打开' in t2 and '属性' in t2, t2.replace('\n', ' | ')[:80])
    page.mouse.click(200, 700)
    page.wait_for_timeout(200)

    print('\n[DiskGenius 分区右键]')
    page.dblclick('.dicon[data-id="dg"]')
    page.wait_for_timeout(700)
    check('DiskGenius 窗口已打开', page.query_selector('#dgTable') is not None)

    row = page.query_selector('#dgTable tr:nth-child(2)')
    check('分区表有数据行', row is not None)
    if row:
        row.click(button='right')
        page.wait_for_timeout(300)
        t3 = page.inner_text('.ctx-menu') if page.query_selector('.ctx-menu') else ''
        check('分区右键含删除当前分区', '删除当前分区' in t3, t3.replace('\n', ' | ')[:110])

        before = page.eval_on_selector_all('#dgTable tr', 'e=>e.length')
        page.click('.ctx-menu .ctx-item:has-text("删除当前分区")')
        page.wait_for_timeout(400)
        dlg = page.query_selector('.dlg-mask')
        check('弹出 DiskGenius 确认框', dlg is not None)
        if dlg:
            dlg.query_selector('[data-a="ok"]').click()
            page.wait_for_timeout(400)
            after = page.eval_on_selector_all('#dgTable tr', 'e=>e.length')
            check('右键删除后分区数 -1', after == before - 1, '%d -> %d' % (before, after))

    b.close()

print('\n================')
if errors:
    print('JS 错误：')
    for e in errors[:5]:
        print('  - ' + e[:200])
print('失败 %d 项' % len(failed))
