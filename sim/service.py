# -*- coding: utf-8 -*-
"""
模拟器考试 —— 业务逻辑层。

路由层（routes.py）只负责解析请求与拼响应，所有业务规则都在这里，
便于单元测试，也让 routes.py 保持薄。
"""

import json
import sqlite3
from datetime import timedelta

from . import config as C
from . import grading as G
from . import rubrics as R
from . import schema as S
from .ctx import get


# ==================== 写入重试 ====================
def _with_retry(fn, tries=6):
    """
    SQLite 写操作有限重试。

    为什么需要：教师机是普通 Windows PC，装了杀毒软件（如火绒）后，
    实时监控会短暂占用 quiz_app.db-wal 文件，此时 SQLite 会抛
    「attempt to write a readonly database」——注意它报的不是
    「database is locked」，所以加长 timeout 也拦不住。
    交卷 / 开考是考试主链路，一次失败就直接影响学生成绩，
    因此只对这几类「瞬时不可写 / 被锁」做有限重试，其它错误照常抛出。
    """
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if not any(k in msg for k in ('readonly', 'locked', 'busy', 'cannot')):
                raise
            last = exc
            time.sleep(0.15 * (i + 1))
    raise last


# ==================== 时间工具 ====================
def _now():
    return get('utcnow')()


def _now_str():
    return _now().strftime('%Y-%m-%d %H:%M:%S')


def _parse_dt(s):
    from datetime import datetime
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


def _ms_between(a_str, b_str):
    """两个 UTC 时间字符串相差多少毫秒（b - a）。"""
    a, b = _parse_dt(a_str), _parse_dt(b_str)
    if not a or not b:
        return 0
    return int((b - a).total_seconds() * 1000)


# ==================== 考试窗口 ====================
def check_window(conn, sim_type):
    """检查考试时段。未配置窗口则不限。返回 (ok, message)。"""
    start_key, end_key = C.WINDOW_KEY[sim_type]
    start = S.get_setting(conn, start_key, '')
    end = S.get_setting(conn, end_key, '')
    if not start and not end:
        return True, ''

    bj = get('beijing_now')()
    cur = bj.strftime('%Y-%m-%d %H:%M')
    if start and cur < start:
        return False, '考试尚未开始（开放时间：%s）' % start
    if end and cur > end:
        return False, '考试已结束（关闭时间：%s）' % end
    return True, ''


# ==================== 开考 / 续考 ====================
def start_session(student_id, sim_type, mode, ip='', ua=''):
    """开考（带写入重试）。"""
    return _with_retry(lambda: _start_session_once(student_id, sim_type, mode, ip, ua))


def _start_session_once(student_id, sim_type, mode, ip='', ua=''):
    """
    开考。已有 in_progress 会话则续考（不重置倒计时）；
    已有完成/超时的正式考试则返回 (None, error)。

    返回 (session_dict, error_message)
    """
    mode = mode if mode in (C.MODE_EXAM, C.MODE_PRACTICE) else C.MODE_EXAM

    with get('get_db')() as conn:
        if mode == C.MODE_EXAM:
            ok, msg = check_window(conn, sim_type)
            if not ok:
                return None, msg

            exist = conn.execute(
                'SELECT * FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=?',
                (student_id, sim_type, C.MODE_EXAM)
            ).fetchone()

            if exist:
                if exist['status'] == C.STATUS_IN_PROGRESS:
                    # 刷新页面 / 换机器继续考：沿用原倒计时，不给额外时间
                    return dict(exist), None
                return None, (
                    '你已参加过%s（得分 %.1f 分）。如需重考请联系老师作废本次记录。'
                    % (C.SIM_LABELS[sim_type], exist['normalized'] or 0)
                )

        minutes = S.get_minutes(conn, sim_type)
        now = _now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        deadline_str = (now + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        rubric = R.get_rubric(sim_type)

        try:
            cur = conn.execute(
                'INSERT INTO sim_sessions (student_id, sim_type, mode, paper_id, status, '
                'started_at, deadline, rubric_version, client_ip, user_agent) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (student_id, sim_type, mode, 'v1', C.STATUS_IN_PROGRESS,
                 now_str, deadline_str, rubric['version'] if rubric else '', ip, ua)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # 并发下唯一索引兜底：另一个请求刚插入成功
            exist = conn.execute(
                'SELECT * FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=?',
                (student_id, sim_type, C.MODE_EXAM)
            ).fetchone()
            return (dict(exist) if exist else None), '你已参加过本场考试。'

        row = conn.execute('SELECT * FROM sim_sessions WHERE id=?', (cur.lastrowid,)).fetchone()
        return dict(row), None


# ==================== 试卷下发 ====================
def build_paper(sim_type):
    """
    下发给前端的任务清单。**只含题干与步骤要求，绝不含答案或判分逻辑**。
    判分逻辑保留在服务端的 rubric 里，学生 F12 也看不到。
    """
    rubric = R.get_rubric(sim_type)
    bj = get('beijing_now')()

    items = [{
        'id': it['id'],
        'name': it['name'],
        'pts': it['pts'],
        'tip': it.get('tip', ''),
    } for it in rubric['items']]

    return {
        'version': rubric['version'],
        'title': rubric['title'],
        'max_score': rubric['max_score'],
        'items': items,
        # 日期时间题的"正确答案"由服务端下发，学生改本机系统时间无效
        'exam_date': bj.strftime('%m/%d/%Y'),
        'exam_time': bj.strftime('%H:%M:%S'),
    }


# ==================== 事件上报 ====================
def append_events(session_id, events, deadline_ms=None):
    """
    写入事件流。按 (session_id, seq) 去重，只接受 seq 大于已存最大值的新事件。
    返回 (accepted, last_seq)
    """
    if not events:
        return 0, 0

    with get('get_db')() as conn:
        row = conn.execute(
            'SELECT COALESCE(MAX(seq), 0) AS mx FROM sim_events WHERE session_id=?',
            (session_id,)).fetchone()
        max_seq = row['mx'] if row else 0

        batch, seen = [], set()
        for e in events:
            seq = G._safe_int(e.get('seq'), 0)
            if seq <= max_seq or seq in seen:
                continue
            seen.add(seq)
            batch.append((
                session_id, seq,
                G._safe_int(e.get('t_ms'), 0),
                (e.get('kind') or '')[:32],
                (e.get('target') or '')[:64],
                (e.get('value') or '')[:4000],
            ))

        if not batch:
            return 0, max_seq

        conn.executemany(
            'INSERT OR IGNORE INTO sim_events (session_id, seq, t_ms, kind, target, value) '
            'VALUES (?,?,?,?,?,?)', batch)
        conn.commit()
        return len(batch), max(max_seq, max(b[1] for b in batch))


def load_events(conn, session_id):
    rows = conn.execute(
        'SELECT seq, t_ms, kind, target, value FROM sim_events '
        'WHERE session_id=? ORDER BY seq', (session_id,)).fetchall()
    return [dict(r) for r in rows]


# ==================== 交卷判分 ====================
def submit_session(session_id, extra_events=None, reason='user'):
    """交卷（带写入重试）。实际逻辑见 _submit_session_once。"""
    return _with_retry(lambda: _submit_session_once(session_id, extra_events, reason))


def _submit_session_once(session_id, extra_events=None, reason='user'):
    """
    交卷。幂等：已完成/已超时的会话再次调用会直接返回已有成绩。

    流程：补发事件 → 服务端重放 → 按 rubric 判分 → 更新会话 → 汇总到 sim_scores
    """
    with get('get_db')() as conn:
        sess = conn.execute('SELECT * FROM sim_sessions WHERE id=?', (session_id,)).fetchone()
        if not sess:
            return None, '会话不存在'

        # 幂等：已经交过卷就不再重算
        if sess['status'] in (C.STATUS_COMPLETED, C.STATUS_TIMEOUT):
            return _result_of(conn, sess), None

        if extra_events:
            append_events(session_id, extra_events)

        deadline_ms = _ms_between(sess['started_at'], sess['deadline'])
        now_over = _now() > (_parse_dt(sess['deadline']) or _now())
        status = C.STATUS_TIMEOUT if (now_over or reason == 'timeout') else C.STATUS_COMPLETED

        rubric = R.get_rubric(sess['sim_type'], sess['rubric_version'])
        events = load_events(conn, session_id)

        # 超时交卷时，超过时限的事件不参与判分
        ctx = {}
        if sess['sim_type'] == 'bios':
            bj = get('beijing_now')()
            ctx = {'exam_date': bj.strftime('%m/%d/%Y'), 'exam_time': bj.strftime('%H:%M:%S')}

        res = G.sim_grade(events, rubric, sess['sim_type'],
                          deadline_ms=deadline_ms, ctx=ctx)

        now_str = _now_str()
        duration = _ms_between(sess['started_at'], now_str) // 1000

        conn.execute(
            'UPDATE sim_sessions SET status=?, submitted_at=?, duration_sec=?, '
            'raw_score=?, max_score=?, normalized=?, events_hash=? WHERE id=?',
            (status, now_str, duration, res['score'], res['max_score'],
             res['normalized'], res['events_hash'], session_id))
        conn.commit()

        if sess['mode'] == C.MODE_EXAM:
            recompute_student_scores(conn, sess['student_id'])

        sess2 = conn.execute('SELECT * FROM sim_sessions WHERE id=?', (session_id,)).fetchone()
        return _result_of(conn, sess2, res), None


def _result_of(conn, sess, res=None):
    """组装交卷结果（供学生端展示）。"""
    steps = (res or {}).get('steps') or []
    if not steps:
        # 已交过卷时重新读一次明细
        rubric = R.get_rubric(sess['sim_type'], sess['rubric_version'])
        events = load_events(conn, sess['id'])
        if rubric:
            res = G.sim_grade(events, rubric, sess['sim_type'])
            steps = res['steps']

    return {
        'session_id': sess['id'],
        'sim_type': sess['sim_type'],
        'status': sess['status'],
        'score': sess['raw_score'],
        'max_score': sess['max_score'],
        'normalized': sess['normalized'],
        'duration_sec': sess['duration_sec'],
        'switch_count': sess['switch_count'],
        'submitted_at': get('to_beijing')(sess['submitted_at']),
        'steps': steps,
        'warnings': (res or {}).get('warnings', []),
    }


# ==================== 成绩汇总 ====================
def recompute_student_scores(conn, student_id):
    """把该生最近一次有效正式考试的成绩汇总进 sim_scores，并重算考试分与总评。"""
    conn.execute(
        'INSERT OR IGNORE INTO sim_scores (student_id) VALUES (?)', (student_id,))

    for sim_type in C.SIM_TYPES:
        row = conn.execute(
            'SELECT * FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=? '
            'AND status IN (?,?) ORDER BY submitted_at DESC, id DESC LIMIT 1',
            (student_id, sim_type, C.MODE_EXAM, C.STATUS_COMPLETED, C.STATUS_TIMEOUT)
        ).fetchone()
        if not row:
            continue
        if sim_type == 'bios':
            conn.execute('UPDATE sim_scores SET bios_score=?, bios_session_id=?, bios_switch=? '
                         'WHERE student_id=?',
                         (row['normalized'], row['id'], row['switch_count'], student_id))
        else:
            conn.execute('UPDATE sim_scores SET winpe_score=?, winpe_session_id=?, winpe_switch=? '
                         'WHERE student_id=?',
                         (row['normalized'], row['id'], row['switch_count'], student_id))

    row = conn.execute('SELECT * FROM sim_scores WHERE student_id=?', (student_id,)).fetchone()
    regular = row['regular_score']
    if regular is None:
        # 未冻结：实时取刷题系统的平时分，保证与 /admin/levels 口径一致
        regular = get_regular_score(conn, student_id)

    exam = (C.W_MANUAL * (row['manual_score'] or 0)
            + C.W_BIOS * (row['bios_score'] or 0)
            + C.W_WINPE * (row['winpe_score'] or 0))
    final = C.W_REGULAR * (regular or 0) + exam

    conn.execute(
        'UPDATE sim_scores SET exam_score=?, final_score=?, updated_at=? WHERE student_id=?',
        (round(exam, 2), round(final, 2), _now_str(), student_id))
    conn.commit()


def _row_sid(r):
    """兼容两种主键命名：刷题系统的 _regular_score_rows 用 'id'。"""
    return r.get('student_id') or r.get('id')


def get_regular_score(conn, student_id):
    """平时分（等级折算 + 竞技场星级加成），与 /admin/levels 完全一致。"""
    return regular_map(conn).get(student_id, 0.0)


def regular_map(conn):
    """批量取平时分，避免逐人查询导致 N+1。"""
    rows_fn = get('regular_rows')
    out = {}
    if not rows_fn:
        return out
    for r in rows_fn(conn):
        sid = _row_sid(r)
        if sid is not None:
            out[sid] = r.get('regular_score') or 0.0
    return out


def build_summary(conn, class_name=None, keyword=None, only_missing=False, min_switch=0):
    """教师端汇总表数据。"""
    reg = regular_map(conn)
    frozen = S.get_setting(conn, C.K_REGULAR_FROZEN, '0') == '1'

    sql = ('SELECT s.id, s.name, s.class_name, s.student_no, sc.* '
           'FROM students s LEFT JOIN sim_scores sc ON sc.student_id = s.id')
    params = []
    where = []
    if class_name:
        where.append('s.class_name = ?')
        params.append(class_name)
    if keyword:
        where.append('(s.name LIKE ? OR s.student_no LIKE ?)')
        params.extend(['%%%s%%' % keyword, '%%%s%%' % keyword])
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY s.class_name, s.name'

    rows = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        sid = d['id']
        regular = d.get('regular_score') if frozen and d.get('regular_score') is not None \
            else reg.get(sid, 0.0)

        manual = d.get('manual_score')
        bios = d.get('bios_score') or 0
        winpe = d.get('winpe_score') or 0
        exam = (C.W_MANUAL * (manual or 0) + C.W_BIOS * bios + C.W_WINPE * winpe)
        final = C.W_REGULAR * (regular or 0) + exam

        item = {
            'student_id': sid,
            'student_no': d.get('student_no') or '',
            'name': d['name'],
            'class_name': d['class_name'],
            'regular_score': round(regular or 0, 1),
            'bios_score': round(bios, 1) if d.get('bios_score') is not None else None,
            'winpe_score': round(winpe, 1) if d.get('winpe_score') is not None else None,
            'manual_score': manual,
            'manual_note': d.get('manual_note') or '',
            'bios_switch': d.get('bios_switch') or 0,
            'winpe_switch': d.get('winpe_switch') or 0,
            'bios_session_id': d.get('bios_session_id'),
            'winpe_session_id': d.get('winpe_session_id'),
            'exam_score': round(exam, 2),
            'final_score': round(final, 2),
            'manual_missing': manual is None,
        }

        if only_missing and manual is not None:
            continue
        if min_switch and max(item['bios_switch'], item['winpe_switch']) < min_switch:
            continue
        rows.append(item)

    rows.sort(key=lambda x: -(x['final_score'] or 0))
    for idx, it in enumerate(rows, 1):
        it['rank'] = idx

    stat = {
        'total': len(rows),
        'bios_done': sum(1 for r in rows if r['bios_score'] is not None),
        'winpe_done': sum(1 for r in rows if r['winpe_score'] is not None),
        'manual_done': sum(1 for r in rows if r['manual_score'] is not None),
    }
    bios_list = [r['bios_score'] for r in rows if r['bios_score'] is not None]
    winpe_list = [r['winpe_score'] for r in rows if r['winpe_score'] is not None]
    stat['avg_bios'] = round(sum(bios_list) / len(bios_list), 1) if bios_list else 0
    stat['avg_winpe'] = round(sum(winpe_list) / len(winpe_list), 1) if winpe_list else 0

    return {'rows': rows, 'summary': stat, 'frozen': frozen, 'weights': C.WEIGHTS}


# ==================== 实操分录入 ====================
def set_manual_score(conn, student_id, score, note='', operator='admin'):
    """教师录入/修改实操装机分。0~100，超出范围拒绝。"""
    try:
        score = float(score)
    except (TypeError, ValueError):
        return False, '分数必须是数字'
    if score < 0 or score > 100:
        return False, '实操分必须在 0~100 之间'

    conn.execute('INSERT OR IGNORE INTO sim_scores (student_id) VALUES (?)', (student_id,))
    old = conn.execute('SELECT manual_score FROM sim_scores WHERE student_id=?',
                       (student_id,)).fetchone()
    old_val = old['manual_score'] if old else None

    conn.execute(
        'UPDATE sim_scores SET manual_score=?, manual_note=?, manual_at=? WHERE student_id=?',
        (score, note, _now_str(), student_id))
    conn.execute(
        'INSERT INTO sim_score_log (student_id, field, old_value, new_value, operator, reason) '
        'VALUES (?,?,?,?,?,?)',
        (student_id, 'manual_score', str(old_val), str(score), operator, note))
    conn.commit()

    recompute_student_scores(conn, student_id)
    row = conn.execute('SELECT exam_score, final_score FROM sim_scores WHERE student_id=?',
                       (student_id,)).fetchone()
    return True, {'exam_score': row['exam_score'], 'final_score': row['final_score']}


def set_manual_score_retry(student_id, score, note='', operator='admin'):
    """教师录入实操分（带写入重试）——教师端改分同样在主链路上。"""

    def run():
        with get('get_db')() as conn:
            return set_manual_score(conn, student_id, score, note, operator)
    return _with_retry(run)


# ==================== 作废 ====================
def void_session(conn, session_id, operator='admin'):
    """作废某次考试：mode 改为 voided，解除"限考 1 次"约束，同时保留记录可审计。"""
    row = conn.execute('SELECT * FROM sim_sessions WHERE id=?', (session_id,)).fetchone()
    if not row:
        return False, '记录不存在'
    if row['mode'] != C.MODE_EXAM:
        return False, '仅正式考试记录可作废'

    conn.execute('UPDATE sim_sessions SET mode=? WHERE id=?', (C.MODE_VOIDED, session_id))
    conn.execute(
        'INSERT INTO sim_score_log (student_id, field, old_value, new_value, operator, reason) '
        'VALUES (?,?,?,?,?,?)',
        (row['student_id'], 'void', row['sim_type'] + '#' + str(session_id), 'voided',
         operator, '教师作废，允许重考'))
    conn.commit()

    # 清掉该科成绩，重新汇总
    if row['sim_type'] == 'bios':
        conn.execute('UPDATE sim_scores SET bios_score=NULL, bios_session_id=NULL '
                     'WHERE student_id=?', (row['student_id'],))
    else:
        conn.execute('UPDATE sim_scores SET winpe_score=NULL, winpe_session_id=NULL '
                     'WHERE student_id=?', (row['student_id'],))
    conn.commit()
    recompute_student_scores(conn, row['student_id'])
    return True, '已作废，该生可重新参加本场考试'


# ==================== 超时会话清理 ====================
def expire_stale(student_id=None):
    """
    把到点未交卷的会话强制判分封存（惰性清理，任何 API 调用前触发）。

    注意：必须**先关闭查询连接**再调 submit_session。
    submit_session 内部会另开连接做写事务，若外层还持有连接未释放，
    SQLite 容易出现 database is locked。
    """
    now_str = _now_str()
    sql = 'SELECT id FROM sim_sessions WHERE status=? AND deadline < ?'
    params = [C.STATUS_IN_PROGRESS, now_str]
    if student_id:
        sql += ' AND student_id=?'
        params.append(student_id)

    with get('get_db')() as conn:
        ids = [r['id'] for r in conn.execute(sql, params).fetchall()]

    for sid in ids:
        try:
            submit_session(sid, reason='timeout')
        except Exception as exc:
            print('[sim] 超时会话 %s 自动交卷失败：%s' % (sid, exc))
    return len(ids)
