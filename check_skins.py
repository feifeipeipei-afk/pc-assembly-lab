# -*- coding: utf-8 -*-
"""校验 BIOS 四种固件皮肤的渲染：布局类名、配色、按键栏、只读信息项。"""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get('SMOKE_BASE', 'http://127.0.0.1:5099')
failed = []
errors = []


def check(name, cond, extra=''):
    print(('  OK  ' if cond else '  FAIL') + ' ' + name + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        failed.append(name)


def login_first_available(page):
    page.goto(BASE + '/portal', wait_until='networkidle')
    page.wait_for_selector('#selClass option:not([value=""])', state='attached', timeout=8000)
    cls = page.eval_on_selector_all('#selClass option:not([value=""])', 'e=>e.map(x=>x.value)')
    page.select_option('#selClass', cls[1])
    page.wait_for_timeout(700)
    names = page.eval_on_selector_all('#selName option:not([value=""])', 'e=>e.map(x=>x.value)')
    page.evaluate("""async d => {
        await fetch('/login', {method:'POST',headers:{'Content-Type':'application/json'},
            body: JSON.stringify(d)});
    }""", {'name': names[0], 'class_name': cls[1]})


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(viewport={'width': 1280, 'height': 900}).new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))

    login_first_available(page)
    page.goto(BASE + '/sim/bios?mode=practice', wait_until='domcontentloaded')
    page.wait_for_timeout(1200)

    expect = {
        'phoenix': ('skin-classic', 'Lenovo G480', '2.05'),
        'award':   ('skin-dual', 'GIGABYTE', '6.00PG'),
        'ami':     ('skin-dual', 'ASUS P5B', '0502'),
        'uefi':    ('skin-uefi', 'ASUS TUF', '2.22.1281'),
    }

    for sid, (layout, vendor, ver) in expect.items():
        print('\n[%s]' % sid)
        page.evaluate("""s => {
            const el = document.querySelector('#skinBox .mode-opt[data-skin="'+s+'"]');
            if (el) el.click();
        }""", sid)
        page.wait_for_timeout(200)
        page.click('#startBtn')
        page.wait_for_timeout(900)

        root = page.query_selector('#biosRoot')
        cls = root.get_attribute('class') if root else ''
        check('布局类 %s' % layout, layout in (cls or ''), cls)

        vend = page.text_content('#biosVendor') or ''
        check('厂商名 %s' % vendor, vendor in vend, vend)

        body = page.inner_text('#biosList')
        check('只读信息随皮肤变化 (%s)' % ver, ver in body, body.split('\n')[2] if len(body.split('\n')) > 2 else body[:60])

        keys = page.inner_text('#biosKeys')
        check('按键栏非空', len(keys.strip()) > 10, keys.replace('\n', ' | ')[:90])

        # 配色确实不同：抓背景色
        bg = page.evaluate("() => getComputedStyle(document.querySelector('#biosRoot')).backgroundColor")
        check('背景色已应用', bg not in ('rgba(0, 0, 0, 0)', ''), bg)

        # 竖排 / 横排页签方向
        if layout == 'skin-dual':
            fd = page.evaluate("() => getComputedStyle(document.querySelector('.bios-tabs')).flexDirection")
            check('Award/AMI 页签竖排', fd == 'column', fd)
        else:
            fd = page.evaluate("() => getComputedStyle(document.querySelector('.bios-tabs')).flexDirection")
            check('%s 页签横排' % sid, fd == 'row', fd)

        # 回到登录页换下一个皮肤
        page.evaluate("() => { if (typeof backHome === 'function') backHome(); }")
        page.wait_for_timeout(500)
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(900)

    # UEFI 鼠标点选
    print('\n[UEFI 鼠标点选]')
    page.evaluate("""() => {
        const el = document.querySelector('#skinBox .mode-opt[data-skin="uefi"]'); if (el) el.click();
    }""")
    page.click('#startBtn')
    page.wait_for_timeout(800)
    before = page.evaluate("() => document.querySelector('.bios-tab.active').textContent")
    page.click('.bios-tab[data-i="3"]')          # 点 Boot 页签
    page.wait_for_timeout(400)
    after = page.evaluate("() => document.querySelector('.bios-tab.active').textContent")
    check('鼠标点击可切换页签', before != after, '%s -> %s' % (before, after))

    b.close()

print('\n================')
if errors:
    print('JS 错误：')
    for e in errors[:5]:
        print('  - ' + e[:200])
print('失败 %d 项' % len(failed))
