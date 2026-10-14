# -*- coding: utf-8 -*-
"""
判分引擎单元测试。

为什么先测这里：判分是整套系统的信任根。
如果服务端算出来的分不对，后面所有功能（汇总表、导出、总评）都是错的数据。

运行：  .venv/Scripts/python.exe -m pytest tests/test_sim_grade.py -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim import grading as G
from sim import rubrics as R

# 日期时间题的"正确答案"，由服务端下发
CTX = {'exam_date': '10/13/2026', 'exam_time': '09:12:00'}


def ev(seq, t_ms, kind, target, value=None):
    """构造一条事件（value 会序列化成 JSON 字符串，与前端上报一致）。"""
    return {
        'seq': seq,
        't_ms': t_ms,
        'kind': kind,
        'target': target,
        'value': json.dumps(value if value is not None else {}, ensure_ascii=False),
    }


def setv(seq, t_ms, key, to, frm=None):
    return ev(seq, t_ms, 'set', key, {'from': frm, 'to': to})


def nav(seq, t_ms, target):
    return ev(seq, t_ms, 'nav', target)


def act(seq, t_ms, action):
    return ev(seq, t_ms, 'action', action)


def step(seq, t_ms, target, value=None):
    return ev(seq, t_ms, 'step', target, value or {})


# ==================== BIOS 测试用例 ====================
def _perfect_bios_events():
    """一个"全部做对"的学生：走完整流程，U盘第一启动，F10 保存退出。"""
    return [
        nav(1, 5000, 'tab:Main'),
        setv(2, 12000, 'sysDate', '10/13/2026', '01/01/2026'),
        setv(3, 20000, 'sysTime', '09:12:30', '12:00:00'),
        nav(4, 30000, 'tab:Advanced'),
        setv(5, 35000, 'secureBoot', 'Disabled', 'Enabled'),
        setv(6, 40000, 'csm', 'Enabled', 'Disabled'),
        setv(7, 45000, 'usbBiosSupport', 'Enabled'),
        nav(8, 50000, 'tab:Boot'),
        nav(9, 55000, 'submenu:__bootPriority'),
        setv(10, 60000, 'bootOrder',
             [R.BIOS_DEV['usb'], R.BIOS_DEV['hdd'], R.BIOS_DEV['cd'], R.BIOS_DEV['net']]),
        setv(11, 65000, 'usbBoot', 'Enabled'),
        nav(12, 70000, 'tab:Security'),
        setv(13, 75000, 'supervisorPassword', 'abc123', None),
        step(14, 76000, 'pwd.confirm', {'ok': True}),
        setv(15, 80000, 'passwordOnBoot', 'Disabled'),
        step(16, 85000, 'bootmenu.pick', {'device': R.BIOS_DEV['usb']}),
        step(17, 90000, 'post.detected'),
        step(18, 92000, 'post.handle', {'action': 'reseat'}),
        step(19, 95000, 'fault.answer', {'ok': True}),
        act(20, 100000, 'saveExit'),
        ev(21, 101000, 'key', 'F10'),
    ]


def test_bios_perfect_scores_100():
    """全对场景应得满分 100。"""
    res = G.sim_grade(_perfect_bios_events(), R.BIOS_V1, 'bios', ctx=CTX)
    assert res['max_score'] == 100
    assert res['score'] == 100, '应得满分，实际 %s；未得分项：%s' % (
        res['score'], [s['id'] for s in res['steps'] if not s['full']])
    assert res['normalized'] == 100.0
    assert not res['warnings']


def test_bios_empty_events_scores_zero():
    """一条事件都没有：0 分，并给出告警。"""
    res = G.sim_grade([], R.BIOS_V1, 'bios', ctx=CTX)
    assert res['score'] == 0
    assert any('未收到任何操作事件' in w for w in res['warnings'])


def test_bios_rubric_total_is_100():
    """rubric 各项分值之和必须等于 max_score，否则归一化会错。"""
    total = sum(i['pts'] for i in R.BIOS_V1_ITEMS)
    assert total == R.BIOS_V1['max_score'] == 100
    assert len(R.BIOS_V1_ITEMS) == 15


def test_bios_b3_partial_without_submenu():
    """
    U 盘设成了第一启动项，但没进过 Boot Device Priority 子菜单 → 只给部分分。
    这条考察的是"流程是否规范"，光结果对不算全对。
    """
    events = [
        nav(1, 1000, 'tab:Boot'),
        setv(2, 2000, 'bootOrder',
             [R.BIOS_DEV['usb'], R.BIOS_DEV['hdd'], R.BIOS_DEV['cd'], R.BIOS_DEV['net']]),
        act(3, 3000, 'saveExit'),
    ]
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    b2 = next(s for s in res['steps'] if s['id'] == 'b2')
    b3 = next(s for s in res['steps'] if s['id'] == 'b3')
    assert b2['got'] == 0, '没进子菜单不应得分'
    assert b3['got'] == 5, '跳过子菜单只能拿部分分，实际 %s' % b3['got']
    assert not b3['full']


def test_bios_time_partial_credit():
    """时间误差 20 分钟（在 30 分钟内但超过 5 分钟）→ 拿部分分 3 分。"""
    events = [setv(1, 1000, 'sysTime', '09:30:00', '12:00:00')]   # 与 09:12 相差 18 分钟
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    b9 = next(s for s in res['steps'] if s['id'] == 'b9')
    assert b9['got'] == 3, '误差超 5 分钟但在 30 分钟内应给部分分，实际 %s' % b9['got']


def test_bios_password_without_confirm():
    """设了管理员密码但没有二次确认 → 部分分 4 分。"""
    events = [setv(1, 1000, 'supervisorPassword', 'abc', None)]
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    b10 = next(s for s in res['steps'] if s['id'] == 'b10')
    assert b10['got'] == 4


def test_bios_password_with_confirm():
    """设了密码且二次确认通过 → 满分 8 分。"""
    events = [
        setv(1, 1000, 'supervisorPassword', 'abc', None),
        step(2, 1500, 'pwd.confirm', {'ok': True}),
    ]
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    b10 = next(s for s in res['steps'] if s['id'] == 'b10')
    assert b10['got'] == 8


def test_bios_overtime_events_dropped():
    """考试结束后补发的操作不计分（防"超时后再操作补交"）。"""
    events = _perfect_bios_events()
    # 时限设为 60 秒，把所有事件都挤到时限之后
    res = G.sim_grade(events, R.BIOS_V1, 'bios', deadline_ms=60000, ctx=CTX)
    late = [e for e in events if e['t_ms'] > 60000]
    assert late, '测试用例本身应有超时事件'
    assert res['score'] < 100, '超时事件应被剔除'
    assert any('考试结束之后' in w for w in res['warnings'])


def test_bios_duplicate_seq_deduped():
    """重复上报同一 seq 不会重复计分。"""
    events = _perfect_bios_events()
    doubled = events + events
    r1 = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    r2 = G.sim_grade(doubled, R.BIOS_V1, 'bios', ctx=CTX)
    assert r1['score'] == r2['score'], '重复事件不应改变得分'


def test_bios_time_rewind_dropped():
    """事件时间倒流（学生改系统时间）会被识别并告警。"""
    events = [
        nav(1, 100000, 'tab:Boot'),
        nav(2, 1000, 'tab:Advanced'),    # 时间倒流
    ]
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    assert any('时间倒流' in w for w in res['warnings'])


def test_bios_f9_defaults_resets_state():
    """按 F9 恢复出厂后，之前改过的设置应全部还原。"""
    events = [
        setv(1, 1000, 'secureBoot', 'Disabled', 'Enabled'),
        act(2, 2000, 'defaults'),
    ]
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    assert res['state']['secureBoot'] == 'Enabled', 'F9 之后应恢复默认'
    assert res['state']['loadedDefaults'] is True


def test_bios_snapshot_mismatch_only_warns():
    """前端快照与服务端重放不一致时只告警，不改分（避免误伤）。"""
    events = _perfect_bios_events()
    events.append(ev(99, 102000, 'snapshot', 'state',
                     {'secureBoot': 'Enabled', 'sysTime': '09:12:30'}))   # 与重放结果矛盾
    res = G.sim_grade(events, R.BIOS_V1, 'bios', ctx=CTX)
    assert res['score'] == 100, '快照不一致不应影响得分'
    assert any('快照' in w for w in res['warnings'])


# ==================== WinPE 测试用例 ====================
def test_winpe_rubric_total_is_100():
    total = sum(i['pts'] for i in R.WINPE_V1_ITEMS)
    assert total == R.WINPE_V1['max_score'] == 100


def _perfect_winpe_events():
    return [
        step(1, 5000, 'boot.pick_usb'),
        step(2, 15000, 'pe.loading_done'),
        step(3, 20000, 'pe.desktop_ready'),
        step(4, 40000, 'dg.quick', {'table': 'MBR', 'count': 3, 'firstGB': 100,
                                    'align4k': True, 'alignSectors': '4096'}),
        step(5, 60000, 'dg.quick', {'table': 'GUID', 'count': 4, 'firstGB': 80,
                                    'secondGB': 200, 'esp': True, 'msr': True,
                                    'align4k': True}),
        step(6, 80000, 'dg.delete', {'label': 'E盘', 'confirmed': True}),
        step(7, 100000, 'setup.install', {'boot': 'C', 'target': 'C', 'finished': True}),
        step(8, 120000, 'cdi.submit', {'verdict': '良好', 'c5': '0'}),
        step(9, 140000, 'cdm.submit', {'drive': 'C:', 'count': '5', 'size': '1GiB',
                                       'mode': 'All', 'done': True}),
        step(10, 160000, 'scr.submit', {'colors': ['红', '绿', '蓝', '白', '黑'],
                                        'verdict_correct': True}),
        step(11, 260000, 'burn.report', {'mode': 'Extreme', 'threads': '全部',
                                         'durationSec': 65, 'stopped': True}),
    ]


def test_winpe_perfect_scores_100():
    res = G.sim_grade(_perfect_winpe_events(), R.WINPE_V1, 'winpe')
    assert res['score'] == 100, '应得满分，实际 %s；未得分项：%s' % (
        res['score'], [(s['id'], s['got']) for s in res['steps'] if not s['full']])


def test_winpe_quick_partial_credit():
    """快速分区 5 个要点错 1 个 → 拿 4/5 分。"""
    events = [step(1, 1000, 'dg.quick', {'table': 'MBR', 'count': 3, 'firstGB': 100,
                                         'align4k': True, 'alignSectors': '2048'})]  # 对齐扇区错
    res = G.sim_grade(events, R.WINPE_V1, 'winpe')
    w2 = next(s for s in res['steps'] if s['id'] == 'w2')
    # 20 分 × 4/5 = 16 分（table/count/firstGB/align4k 对，alignSectors 错）
    assert abs(w2['got'] - 16.0) < 0.01, '实际 %s' % w2['got']


def test_winpe_burn_too_short():
    """烤机只跑了 30 秒 → 不得分（这是原系统的致命 Bug，等 2 秒就满分）。"""
    events = [step(1, 1000, 'burn.report', {'mode': 'Extreme', 'threads': '全部',
                                            'durationSec': 30, 'stopped': True})]
    res = G.sim_grade(events, R.WINPE_V1, 'winpe')
    w9 = next(s for s in res['steps'] if s['id'] == 'w9')
    assert w9['got'] == 0


def test_winpe_burn_60sec_passes():
    """烤机满 60 秒 → 得分。"""
    events = [step(1, 1000, 'burn.report', {'mode': 'Extreme', 'threads': '全部',
                                            'durationSec': 60, 'stopped': True})]
    res = G.sim_grade(events, R.WINPE_V1, 'winpe')
    w9 = next(s for s in res['steps'] if s['id'] == 'w9')
    assert w9['got'] == 6


def test_winpe_cdm_not_run_no_credit():
    """没真的跑测速就点提交 → 不得分（原系统 cdmDoneAll 全局不重置的 Bug）。"""
    events = [step(1, 1000, 'cdm.submit', {'drive': 'C:', 'count': '5', 'size': '1GiB',
                                           'mode': 'All', 'done': False})]
    res = G.sim_grade(events, R.WINPE_V1, 'winpe')
    w7 = next(s for s in res['steps'] if s['id'] == 'w7')
    assert w7['got'] == 0


# ==================== WinPE v2（含图吧工具箱硬件检测） ====================
def test_winpe_v2_rubric_total_is_100():
    total = sum(i['pts'] for i in R.WINPE_V2['items'])
    assert total == R.WINPE_V2['max_score'] == 100, '实际 %s' % total
    assert len(R.WINPE_V2['items']) == 13, 'v2 应含 13 个评分项（v1 的 9 项 + 4 个新增工具）'
    assert R.CURRENT_VERSION['winpe'] == 'winpe-v2'


def _perfect_winpe_v2_events():
    """在 v1 全对的基础上，补齐 4 个新增图吧工具箱检测项。"""
    events = _perfect_winpe_events()
    events += [
        step(12, 280000, 'aida.submit', {'board': 'B660M-PLUS', 'memGB': '16', 'cpuTemp': 45}),
        step(13, 300000, 'memtest.report', {'passes': 1, 'errors': 0, 'done': True}),
        step(14, 320000, 'kbd.submit', {'keys': ['a', 's', 'd', 'f', 'space'], 'done': True}),
        step(15, 340000, 'mouse.submit', {'left': True, 'right': True, 'wheel': True, 'dbl': True}),
    ]
    return events


def test_winpe_v2_perfect_scores_100():
    res = G.sim_grade(_perfect_winpe_v2_events(), R.WINPE_V2, 'winpe')
    assert res['score'] == 100, '应得满分，实际 %s；未得分项：%s' % (
        res['score'], [(s['id'], s['got']) for s in res['steps'] if not s['full']])
    assert res['normalized'] == 100.0
    assert not res['warnings']


def test_winpe_v2_aida_partial_and_wrong():
    """AIDA64：主板选对但内存/温度不对 → 部分分；主板选错 → 0 分。"""
    good_board = [step(1, 1000, 'aida.submit', {'board': 'B660M-PLUS', 'memGB': '8', 'cpuTemp': 200})]
    res = G.sim_grade(good_board, R.WINPE_V2, 'winpe')
    w10 = next(s for s in res['steps'] if s['id'] == 'w10')
    assert w10['got'] == 3, '主板对但读数错应给部分分，实际 %s' % w10['got']

    bad_board = [step(1, 1000, 'aida.submit', {'board': 'Z790-A', 'memGB': '16', 'cpuTemp': 45})]
    res = G.sim_grade(bad_board, R.WINPE_V2, 'winpe')
    w10 = next(s for s in res['steps'] if s['id'] == 'w10')
    assert w10['got'] == 0, '主板选错不应得分'


def test_winpe_v2_kbd_missing_key_no_credit():
    """键盘测试：缺少空格键 → 只有部分分，不算完成。"""
    events = [step(1, 1000, 'kbd.submit', {'keys': ['a', 's', 'd', 'f'], 'done': True})]
    res = G.sim_grade(events, R.WINPE_V2, 'winpe')
    w12 = next(s for s in res['steps'] if s['id'] == 'w12')
    assert w12['got'] == 3 and not w12['full']


def test_winpe_v2_memtest_no_pass_no_credit():
    """MemTest：提交了报告但没跑满 1 轮 → 只有部分分。"""
    events = [step(1, 1000, 'memtest.report', {'passes': 0, 'errors': 0, 'done': True})]
    res = G.sim_grade(events, R.WINPE_V2, 'winpe')
    w11 = next(s for s in res['steps'] if s['id'] == 'w11')
    assert w11['got'] == 3 and not w11['full']


def test_winpe_v2_mouse_incomplete_no_credit():
    """鼠标测试：少测滚轮/双击 → 不得分。"""
    events = [step(1, 1000, 'mouse.submit', {'left': True, 'right': True, 'wheel': False, 'dbl': False})]
    res = G.sim_grade(events, R.WINPE_V2, 'winpe')
    w13 = next(s for s in res['steps'] if s['id'] == 'w13')
    assert w13['got'] == 3, '只测左右键应给部分分，实际 %s' % w13['got']


# ==================== 通用特性 ====================
def test_events_hash_stable():
    """同样的事件序列应得到同样的哈希，用于事后复核。"""
    h1 = G.events_hash(_perfect_bios_events())
    h2 = G.events_hash(_perfect_bios_events())
    assert h1 == h2 and len(h1) == 32


def test_events_hash_differs_on_tamper():
    """篡改事件后哈希应变化。"""
    events = _perfect_bios_events()
    h1 = G.events_hash(events)
    events.append(act(999, 200000, 'saveExit'))
    assert G.events_hash(events) != h1


def test_all_rubric_items_have_tip_and_name():
    """每个评分项都要有名字和提示，否则教师端明细页会显示空白。"""
    for rub in (R.BIOS_V1, R.WINPE_V1, R.WINPE_V2):
        for it in rub['items']:
            assert it.get('name'), '评分项 %s 缺少 name' % it['id']
            assert it.get('tip'), '评分项 %s 缺少 tip' % it['id']
            assert it['pts'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
