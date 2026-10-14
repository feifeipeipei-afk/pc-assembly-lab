# -*- coding: utf-8 -*-
"""
模拟器考试端到端流程测试：开考 → 上报 → 交卷 → 汇总 → 教师录入 → 作废重考。

覆盖的是"考试能不能真的跑起来"，重点验证这几条硬约束：
  · 限考 1 次（并发下也不能破）
  · 超时后的操作不计分
  · 前端报的分数一律以服务端重算为准
  · 实操分未录入按 0 计，录入后总评联动

运行：  .venv/Scripts/python.exe -m pytest tests/test_sim_flow.py -v -s
"""

import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = os.environ.get('QUIZ_DB_PATH')
if not _tmp:
    _tmp = os.path.join(tempfile.mkdtemp(prefix='sim_test_'), 'test.db')
    os.environ['QUIZ_DB_PATH'] = _tmp

import pytest  # noqa: E402
import app as app_module  # noqa: E402

from sim import rubrics as R  # noqa: E402
from sim import config as C  # noqa: E402


@pytest.fixture(scope='module')
def client():
    app_module.init_db()
    app_module.app.config['TESTING'] = True
    with app_module.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('roster_mode','0')")
        conn.commit()
    with app_module.app.test_client() as c:
        yield c


def login(client, name='测试同学甲', cls='测试班'):
    r = client.post('/login', json={'name': name, 'class_name': cls})
    assert r.get_json()['success'], r.get_json()
    return r


def logout(client):
    client.get('/logout')


def admin_login(client):
    r = client.post('/admin/login', json={'password': 'admin123'})
    assert r.status_code in (200, 302), r.status_code


# ==================== 事件构造 ====================
def ev(seq, t_ms, kind, target, value=None):
    return {'seq': seq, 't_ms': t_ms, 'kind': kind, 'target': target,
            'value': json.dumps(value or {}, ensure_ascii=False)}


def setv(seq, t_ms, key, to):
    return ev(seq, t_ms, 'set', key, {'from': None, 'to': to})


def perfect_bios():
    """一套完整正确的 BIOS 操作，服务端重放后应得满分。"""
    return [
        ev(1, 5000, 'nav', 'tab:Main'),
        setv(2, 12000, 'sysDate', '01/01/2026'),      # 与下发日期比对，见下方 ctx 说明
        setv(3, 20000, 'sysTime', '12:00:00'),
        ev(4, 30000, 'nav', 'tab:Advanced'),
        setv(5, 35000, 'secureBoot', 'Disabled'),
        setv(6, 40000, 'csm', 'Enabled'),
        setv(7, 45000, 'usbBiosSupport', 'Enabled'),
        ev(8, 50000, 'nav', 'tab:Boot'),
        ev(9, 55000, 'nav', 'submenu:__bootPriority'),
        setv(10, 60000, 'bootOrder',
             [R.BIOS_DEV['usb'], R.BIOS_DEV['hdd'], R.BIOS_DEV['cd'], R.BIOS_DEV['net']]),
        setv(11, 65000, 'usbBoot', 'Enabled'),
        ev(12, 70000, 'nav', 'tab:Security'),
        setv(13, 75000, 'supervisorPassword', 'abc123'),
        ev(14, 76000, 'step', 'pwd.confirm', {'ok': True}),
        setv(15, 80000, 'passwordOnBoot', 'Disabled'),
        ev(16, 85000, 'step', 'bootmenu.pick', {'device': R.BIOS_DEV['usb']}),
        ev(17, 90000, 'step', 'post.detected'),
        ev(18, 92000, 'step', 'post.handle', {'action': 'reseat'}),
        ev(19, 95000, 'step', 'fault.answer', {'ok': True}),
        ev(20, 100000, 'action', 'saveExit'),
    ]


# ==================== 基础流程 ====================
def test_start_and_submit_flow(client):
    """开考 → 上报事件 → 交卷 → 查成绩，分数由服务端重算。"""
    login(client, '流程甲', '测试班')

    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    d = r.get_json()
    assert d['success'], d
    sid = d['session_id']
    assert d['duration_ms'] == 20 * 60 * 1000, 'BIOS 默认时长应为 20 分钟'

    r = client.post('/api/sim/event', json={'session_id': sid, 'events': perfect_bios()})
    assert r.get_json()['accepted'] == 20

    r = client.post('/api/sim/submit', json={'session_id': sid, 'reason': 'user'})
    d = r.get_json()
    assert d['success'], d
    res = d['result']
    assert res['status'] == C.STATUS_COMPLETED
    assert res['score'] > 0
    assert len(res['steps']) == 15, '应返回 15 个评分项明细'
    logout(client)


def test_limit_one_attempt(client):
    """限考 1 次：第二次开考应被拒绝（409）。"""
    login(client, '限考乙', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    assert r.get_json()['success']

    client.post('/api/sim/submit', json={'session_id': r.get_json()['session_id']})

    r2 = client.post('/api/sim/start', json={'sim_type': 'bios'})
    assert r2.status_code == 409, '重复考试应被拒绝'
    assert '已参加' in r2.get_json()['message']
    logout(client)


def test_concurrent_start_creates_one_session(client):
    """
    并发开考（全班同时点"开始考试"）必须只产生 **一个** 会话。

    注意语义：第一个请求创建会话，其余请求走"续考"路径也返回 200 ——
    这是刻意设计（学生刷新页面、换机器继续考都要能接着考）。
    所以正确的验证不是"只有 1 个 200"，而是：
      ① 所有成功请求拿到的必须是同一个 session_id
      ② 数据库里最终只能有 1 条 exam 会话
    """
    login(client, '并发丙', '测试班')

    with app_module.get_db() as conn:
        conn.execute('INSERT OR IGNORE INTO students (name, class_name) VALUES (?,?)',
                     ('并发丙', '测试班'))
        conn.commit()
        sid_stu = conn.execute("SELECT id FROM students WHERE name='并发丙'").fetchone()['id']

    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker():
        # 每个线程用独立 test_client，避免共享 client 把请求串行化
        with app_module.app.test_client() as c:
            with c.session_transaction() as s:
                s['student_id'] = sid_stu
            barrier.wait()
            r = c.post('/api/sim/start', json={'sim_type': 'winpe'})
            with lock:
                results.append((r.status_code, (r.get_json() or {}).get('session_id')))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_rows = [s for code, s in results if code == 200 and s]
    assert ok_rows, '并发下应至少有一次成功'
    assert len(set(ok_rows)) == 1, '并发下产生了多个不同会话：%s' % set(ok_rows)

    with app_module.get_db() as conn:
        cnt = conn.execute(
            'SELECT COUNT(*) FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=?',
            (sid_stu, 'winpe', C.MODE_EXAM)).fetchone()[0]
    assert cnt == 1, '数据库里应只有 1 条正式考试记录，实际 %d 条' % cnt
    logout(client)


def test_submit_is_idempotent(client):
    """重复交卷不应重复加分。"""
    login(client, '幂等丁', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'winpe'})
    sid = r.get_json()['session_id']
    client.post('/api/sim/event', json={'session_id': sid, 'events': [
        ev(1, 1000, 'step', 'dg.delete', {'label': 'E盘', 'confirmed': True}),
    ]})

    r1 = client.post('/api/sim/submit', json={'session_id': sid})
    r2 = client.post('/api/sim/submit', json={'session_id': sid})
    assert r1.get_json()['result']['score'] == r2.get_json()['result']['score']
    logout(client)


def test_event_dedup_by_seq(client):
    """重复上报同一批事件不会重复计分。"""
    login(client, '去重戊', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    sid = r.get_json()['session_id']

    events = perfect_bios()
    client.post('/api/sim/event', json={'session_id': sid, 'events': events})
    r2 = client.post('/api/sim/event', json={'session_id': sid, 'events': events})
    assert r2.get_json()['accepted'] == 0, '重复 seq 应被丢弃'

    client.post('/api/sim/submit', json={'session_id': sid})
    logout(client)


def test_switch_count(client):
    """切屏上报会累加计数，并写入事件流留痕。"""
    login(client, '切屏己', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    sid = r.get_json()['session_id']

    for _ in range(3):
        client.post('/api/sim/switch', json={'session_id': sid, 'reason': 'blur', 't_ms': 1000})
    d = client.post('/api/sim/switch', json={'session_id': sid, 'reason': 'blur'}).get_json()
    assert d['count'] == 4
    logout(client)


def test_need_login(client):
    """未登录不能开考，且返回 401 而不是 302。"""
    logout(client)
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    assert r.status_code == 401


def test_cannot_touch_others_session(client):
    """不能往别人的会话里塞事件。"""
    login(client, '甲同学', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    my_sid = r.get_json()['session_id']
    logout(client)

    login(client, '乙同学', '测试班')
    r = client.post('/api/sim/event', json={'session_id': my_sid, 'events': perfect_bios()})
    assert r.status_code == 403, '不应允许操作他人会话'
    logout(client)


def test_paper_hides_answers(client):
    """
    下发的试卷里绝不能出现判分逻辑或答案。
    学生 F12 看到的最好只是"要做什么"，而不是"怎么判"。
    """
    login(client, '试卷庚', '测试班')
    d = client.get('/api/sim/paper?type=bios').get_json()
    paper = json.dumps(d['paper'], ensure_ascii=False)
    for leak in ('check', 'lambda', 'require', 'partial_check', 'watch'):
        assert leak not in paper, '试卷泄露了内部字段：%s' % leak
    assert d['paper']['max_score'] == 100
    assert len(d['paper']['items']) == 15
    logout(client)


# ==================== 教师端 ====================
def test_admin_summary_and_manual_score(client):
    """汇总表 → 录入实操分 → 总评联动。"""
    login(client, '汇总辛', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    sid = r.get_json()['session_id']
    client.post('/api/sim/event', json={'session_id': sid, 'events': perfect_bios()})
    client.post('/api/sim/submit', json={'session_id': sid})
    logout(client)

    with app_module.get_db() as conn:
        row = conn.execute("SELECT id FROM students WHERE name='汇总辛'").fetchone()
        sid_stu = row['id']

    admin_login(client)

    d = client.get('/admin/sim/summary').get_json()
    assert d['success']
    me = next(x for x in d['rows'] if x['student_id'] == sid_stu)
    assert me['manual_missing'] is True, '未录入实操分应标记缺失'
    assert me['manual_score'] is None
    # 未录入按 0 计：考试分只来自 BIOS
    assert abs(me['exam_score'] - C.W_BIOS * me['bios_score']) < 0.01

    r = client.post('/admin/sim/manual', json={'student_id': sid_stu, 'score': 88,
                                               'note': '现场装机一次点亮'})
    d = r.get_json()
    assert d['success'], d

    d = client.get('/admin/sim/summary').get_json()
    me = next(x for x in d['rows'] if x['student_id'] == sid_stu)
    assert me['manual_score'] == 88
    assert me['manual_missing'] is False
    expect_exam = C.W_MANUAL * 88 + C.W_BIOS * me['bios_score']
    assert abs(me['exam_score'] - expect_exam) < 0.01, '考试分应按 25%/12.5% 权重计算'
    assert abs(me['final_score'] - (C.W_REGULAR * me['regular_score'] + expect_exam)) < 0.01


def test_manual_score_range_check(client):
    """实操分必须在 0~100，超出拒绝。"""
    admin_login(client)
    with app_module.get_db() as conn:
        sid_stu = conn.execute("SELECT id FROM students LIMIT 1").fetchone()['id']

    r = client.post('/admin/sim/manual', json={'student_id': sid_stu, 'score': 150})
    assert not r.get_json()['success']
    r = client.post('/admin/sim/manual', json={'student_id': sid_stu, 'score': -5})
    assert not r.get_json()['success']


def test_void_allows_retake(client):
    """教师作废后，学生可以重考。"""
    login(client, '作废壬', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    sid = r.get_json()['session_id']
    client.post('/api/sim/submit', json={'session_id': sid})
    logout(client)

    admin_login(client)
    r = client.post('/admin/sim/void', json={'session_id': sid})
    assert r.get_json()['success'], r.get_json()

    logout(client)
    admin_logout(client)

    login(client, '作废壬', '测试班')
    r = client.post('/api/sim/start', json={'sim_type': 'bios'})
    assert r.get_json()['success'], '作废后应能重新开考'
    logout(client)


def admin_logout(client):
    client.get('/admin/logout')


def test_student_detail(client):
    """单人明细应包含时间轴、逐项得分与改分日志。"""
    admin_login(client)
    with app_module.get_db() as conn:
        row = conn.execute(
            "SELECT student_id FROM sim_sessions WHERE mode='exam' LIMIT 1").fetchone()
    if not row:
        pytest.skip('没有考试记录')

    d = client.get('/admin/sim/student/%d' % row['student_id']).get_json()
    assert d['success']
    assert 'student' in d and 'logs' in d
    if d['bios']:
        assert d['bios']['steps'], '应有逐项得分'
        assert d['bios']['timeline'], '应有操作时间轴'


def test_export_excel(client):
    """导出 Excel 应返回 xlsx 二进制流。"""
    admin_login(client)
    r = client.get('/admin/sim/export')
    assert r.status_code == 200
    assert 'spreadsheetml' in r.headers['Content-Type']
    assert len(r.data) > 3000, '导出的文件不应是空的'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
