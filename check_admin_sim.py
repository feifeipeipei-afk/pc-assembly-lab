# -*- coding: utf-8 -*-
"""教师端技能考试成绩页端到端校验：登录后台 → 汇总表 → 录实操分 → 明细抽屉 → 导出。"""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get('SMOKE_BASE', 'http://127.0.0.1:5099')
PWD = os.environ.get('ADMIN_PWD', 'admin123')
failed, errors = [], []


def check(name, cond, extra=''):
    print(('  OK  ' if cond else '  FAIL') + ' ' + name + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        failed.append(name)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1500, 'height': 950})
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))

    print('\n[1] 后台登录')
    page.goto(BASE + '/admin', wait_until='networkidle')
    if page.query_selector('#adminPwd') or page.query_selector('input[type="password"]'):
        sel = '#adminPwd' if page.query_selector('#adminPwd') else 'input[type="password"]'
        page.fill(sel, PWD)
        page.click('button:has-text("登"), button:has-text("确")')
        page.wait_for_timeout(1500)
    check('进入后台', '后台' in (page.title() or '') or page.query_selector('.tabs') is not None,
          page.title())

    print('\n[2] 技能考试成绩页')
    page.click('.tab[data-tab="sim"]')
    page.wait_for_timeout(1600)
    check('标签页已激活', 'active' in (page.get_attribute('#tab-sim', 'class') or ''))
    n = page.eval_on_selector_all('#simBody tr', 'e=>e.length')
    check('汇总表有数据行', n > 0, '%d 行' % n)
    check('统计卡已渲染', (page.inner_text('#simStat') or '').strip() != '',
          (page.inner_text('#simStat') or '').replace('\n', ' ')[:80])
    check('班级筛选已填充',
          page.eval_on_selector_all('#simClassFilter option', 'e=>e.length') > 1)

    print('\n[3] 行内录入实操分')
    first = page.query_selector('.manual-input')
    check('实操分输入框存在', first is not None)
    sid = first.get_attribute('data-sid') if first else None
    page.fill('.manual-input', '88')
    page.evaluate("() => document.querySelector('.manual-input').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(1400)
    val = page.eval_on_selector('.manual-input', 'e=>e.value')
    check('分数已保存并回填', val == '88', val)

    print('\n[4] 单人明细抽屉')
    # 挑一个真的考过试的学生，否则抽屉里只有"尚未参加考试"
    sid = page.evaluate("""() => {
        const r = (typeof simRows !== 'undefined' ? simRows : [])
                    .find(x => x.bios_score !== null || x.winpe_score !== null);
        return r ? r.student_id : null;
    }""")
    check('找到有成绩的考生', sid is not None, sid)
    page.evaluate("id => openSimDetail(id)", sid)
    page.wait_for_timeout(1600)
    check('抽屉已打开', 'show' in (page.get_attribute('#simDrawer', 'class') or ''))
    body = page.inner_text('#simDrawerBody') or ''
    check('含评分项表格', '评分项' in body or '操作时间轴' in body, body[:80].replace('\n', ' '))
    check('含作废按钮', page.query_selector('button:has-text("作废本次考试")') is not None)
    page.click('#simDrawer .modal-buttons button')
    page.wait_for_timeout(400)

    print('\n[5] 导出 Excel')
    with page.expect_download(timeout=25000) as dl:
        page.click('button:has-text("导出 Excel")')
    d = dl.value
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_export_check.xlsx')
    d.save_as(path)          # 另存为带扩展名的路径，便于 openpyxl 解析
    size = os.path.getsize(path) if os.path.exists(path) else 0
    check('下载到 xlsx', (d.suggested_filename or '').endswith('.xlsx'), d.suggested_filename)
    check('文件非空', size > 5000, '%d 字节' % size)

    # 校验 4 个 sheet 都有内容
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path)
        print('    sheets =', wb.sheetnames)
        check('含 4 个工作表', len(wb.sheetnames) == 4, wb.sheetnames)
        for ws in wb.worksheets:
            print('    %s: %d 行 x %d 列' % (ws.title, ws.max_row, ws.max_column))
        check('总评汇总有数据', wb.worksheets[0].max_row > 1)
    except Exception as e:
        check('解析 xlsx', False, str(e))

    b.close()

print('\n================')
if errors:
    print('JS 错误：')
    for e in errors[:6]:
        print('  - ' + e[:200])
print('失败 %d 项' % len(failed))
