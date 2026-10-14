# -*- coding: utf-8 -*-
"""战斗竞技场 UI 冒烟：登录 → 竞技场 → 闯关 → 答题 → 结算。"""
import sys
from playwright.sync_api import sync_playwright

BASE = 'http://localhost:5099'
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(str(e)))

    page.goto(BASE)
    page.wait_for_load_state('networkidle')

    # 自由注册登录
    page.fill('#inputName', 'UI冒烟员')
    page.wait_for_function("document.querySelector('#inputClass option:nth-child(2)')", timeout=8000)
    page.select_option('#inputClass', label='UI冒烟班')
    page.click('#loginForm button[type=submit]')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('#arenaBtn', timeout=5000)

    # 进入竞技场
    page.click('#arenaBtn')
    page.wait_for_selector('#arenaBody .stage-tile', timeout=5000)
    page.screenshot(path='smoke_arena.png', full_page=True)
    print('ARENA_TABS:', page.locator('.arena-tab').count())
    print('STAGE_TILES:', page.locator('.stage-tile').count())

    # 切换对战大厅 / 天梯榜
    page.click('.arena-tab[data-atab=pvp]')
    page.wait_for_timeout(300)
    print('PVP_DUMMY_TILES:', page.locator('.dummy-tile').count())
    page.screenshot(path='smoke_pvp.png', full_page=True)
    page.click('.arena-tab[data-atab=ladder]')
    page.wait_for_timeout(300)
    page.screenshot(path='smoke_ladder.png', full_page=True)

    # 回闯关并开第一关
    page.click('.arena-tab[data-atab=stages]')
    page.wait_for_timeout(300)
    page.locator('.stage-tile:not(.locked)').first.click()
    page.wait_for_selector('#battleView:not(.hidden) .bt-qcard', timeout=5000)
    page.wait_for_timeout(400)
    page.screenshot(path='smoke_battle_start.png', full_page=True)
    print('BATTLE_FOE:', page.locator('#btFoeName').inner_text())

    # 连答 10 题：点第一个选项，等自动跳题 + 反馈锁定
    for i in range(10):
        btn = page.locator('#battleQuest .bt-opt:not([disabled])').first
        if btn.count() == 0:
            page.wait_for_timeout(800)  # 跳题动画余量，再确认一次
            btn = page.locator('#battleQuest .bt-opt:not([disabled])').first
            if btn.count() == 0:
                break
        btn.click()
        page.wait_for_timeout(2000)
    page.wait_for_timeout(3000)  # 等自动交卷 + 结算动画
    page.screenshot(path='smoke_battle_result.png', full_page=True)
    verdict = page.locator('.bt-verdict')
    if verdict.count():
        print('VERDICT:', verdict.inner_text())
        print('STARS_SHOWN:', page.locator('.bt-stars .bt-rstar').count())
    else:
        print('NO_BATTLE_RESULT_VIEW — check generic results')

    browser.close()

print('CONSOLE_ERRORS:', errors if errors else 'none')
sys.exit(1 if errors else 0)
