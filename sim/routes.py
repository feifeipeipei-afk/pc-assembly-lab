# -*- coding: utf-8 -*-
"""
模拟器考试 —— 路由层（Blueprint）。

职责：解析请求、校验身份、调用 service、拼响应。**不含业务规则**。

关于 admin_required：
    宿主 app.py 里的装饰器未登录时返回 302 重定向到登录页。
    这对页面跳转没问题，但 fetch 请求拿到的是一段 HTML，前端会静默失败。
    所以这里对 /api/ 前缀的接口单独做 401 JSON 处理。
"""

import os
import io
import json

from flask import Blueprint, request, jsonify, session, render_template, Response, send_file

from . import config as C
from . import service as SV
from . import rubrics as R
from . import schema as S
from .ctx import get

bp = Blueprint('sim', __name__)

SIM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'static', 'sim')

HTML_FILES = {'bios': 'bios.html', 'winpe': 'winpe.html'}


# ==================== 工具 ====================
def _json_err(msg, code=400):
    return jsonify({'success': False, 'message': msg}), code


def _student_id():
    return session.get('student_id')


def _require_student():
    sid = _student_id()
    if not sid:
        return None, _json_err('请先从首页登录后再进入模拟考试。', 401)
    return sid, None


def _admin_ok():
    return bool(session.get('is_admin'))


def _admin_guard():
    """教师接口鉴权：API 返回 401 JSON（而不是 302 到登录页）。"""
    if _admin_ok():
        return None
    return jsonify({'success': False, 'message': '请先登录教师账号',
                    'need_login': True}), 401


# ==================== 页面 ====================
@bp.route('/portal')
def portal():
    """统一入口：三个模块的导航页。"""
    return render_template('portal.html',
                           student_name=session.get('student_name'),
                           class_name=session.get('class_name'),
                           logged_in=bool(_student_id()))


@bp.route('/sim/<sim_type>')
def sim_page(sim_type):
    """
    模拟器页面。读取静态 HTML 并注入身份与配置（window.SIM_BOOT）。

    为什么不走 Jinja 模板：两个 HTML 是一千多行的纯静态单文件，
    内含大量 `{` `}` 与 JS 模板字符串，交给 Jinja 渲染极易冲突。
    直接读文件 + 尾部注入是最省事也最安全的做法。
    """
    if sim_type not in HTML_FILES:
        return '未知的模拟器类型', 404

    path = os.path.join(SIM_DIR, HTML_FILES[sim_type])
    if not os.path.exists(path):
        return '模拟器文件缺失：%s' % HTML_FILES[sim_type], 500

    with open(path, 'r', encoding='utf-8') as f:      # 必须显式 utf-8，Windows 默认 cp936
        html = f.read()

    sid = _student_id()
    # mode=practice：只进练习，不开考、不计时、不计分。
    # 模拟考试限考 1 次，必须给学生一条"先练手"的安全通道。
    req_mode = (request.args.get('mode') or '').lower()
    boot = {
        'logged_in': bool(sid),
        'mode': C.MODE_PRACTICE if req_mode == C.MODE_PRACTICE else C.MODE_EXAM,
        'student_id': sid,
        'student_name': session.get('student_name') or '',
        'class_name': session.get('class_name') or '',
        'sim_type': sim_type,
        'minutes': None,
        'server_now': get('utcnow')().strftime('%Y-%m-%d %H:%M:%S'),
    }

    if sid:
        with get('get_db')() as conn:
            boot['minutes'] = S.get_minutes(conn, sim_type)

    inject = ('<script>window.SIM_BOOT = %s;</script>\n' % json.dumps(boot, ensure_ascii=False))

    # 只替换**最后一个**结束标签。
    # 若用 replace() 会替换全文所有匹配——页面 JS 注释里一旦出现同样的字面量
    # （例如说明"注入到页面末尾"时被写成 HTML 结束标签），注入脚本就会被插进
    # 注释中间，直接把代码撑坏，浏览器报 "Invalid or unexpected token"。
    idx = html.rfind('</body>')
    if idx >= 0:
        html = html[:idx] + inject + html[idx:]
    else:
        html += inject

    return Response(html, mimetype='text/html; charset=utf-8')


# ==================== 学生端 API ====================
@bp.route('/api/sim/start', methods=['POST'])
def api_start():
    """开考 / 续考。"""
    sid, err = _require_student()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    sim_type = data.get('sim_type') or ''
    mode = data.get('mode') or C.MODE_EXAM
    if sim_type not in C.SIM_TYPES:
        return _json_err('模拟器类型无效')

    SV.expire_stale(sid)

    sess, error = SV.start_session(
        sid, sim_type, mode,
        ip=request.headers.get('X-Forwarded-For', request.remote_addr or ''),
        ua=(request.user_agent.string or '')[:200])

    if error:
        return jsonify({'success': False, 'message': error}), 409

    with get('get_db')() as conn:
        events = SV.load_events(conn, sess['id'])

    return jsonify({
        'success': True,
        'session_id': sess['id'],
        'mode': sess['mode'],
        'started_at': sess['started_at'],
        'deadline': sess['deadline'],
        'duration_ms': SV._ms_between(sess['started_at'], sess['deadline']),
        'server_now': SV._now_str(),
        'resumed': bool(events),
        'last_seq': (events[-1]['seq'] if events else 0),
        'switch_count': sess['switch_count'],
    })


@bp.route('/api/sim/paper')
def api_paper():
    """下发包。只含任务要求，不含答案与判分逻辑。"""
    _, err = _require_student()
    if err:
        return err
    sim_type = request.args.get('type') or ''
    if sim_type not in C.SIM_TYPES:
        return _json_err('模拟器类型无效')
    return jsonify({'success': True, 'paper': SV.build_paper(sim_type)})


@bp.route('/api/sim/event', methods=['POST'])
def api_event():
    """批量上报操作事件。"""
    sid, err = _require_student()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    events = data.get('events') or []
    if not session_id:
        return _json_err('缺少 session_id')
    if len(events) > C.EVENT_BATCH_MAX:
        events = events[:C.EVENT_BATCH_MAX]

    # 校验会话归属，防止学生 A 往学生 B 的会话里塞事件
    with get('get_db')() as conn:
        row = conn.execute('SELECT student_id, deadline FROM sim_sessions WHERE id=?',
                           (session_id,)).fetchone()
    if not row or row['student_id'] != sid:
        return _json_err('会话无效', 403)

    accepted, last_seq = SV.append_events(session_id, events)
    return jsonify({'success': True, 'accepted': accepted, 'last_seq': last_seq})


@bp.route('/api/sim/switch', methods=['POST'])
def api_switch():
    """切屏上报。3 秒去抖由前端完成，这里只累加计数。"""
    sid, err = _require_student()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return _json_err('缺少 session_id')

    with get('get_db')() as conn:
        row = conn.execute('SELECT student_id FROM sim_sessions WHERE id=?',
                           (session_id,)).fetchone()
        if not row or row['student_id'] != sid:
            return _json_err('会话无效', 403)
        conn.execute('UPDATE sim_sessions SET switch_count = switch_count + 1 WHERE id=?',
                     (session_id,))
        conn.execute(
            'INSERT INTO sim_events (session_id, seq, t_ms, kind, target, value) '
            'SELECT ?, COALESCE(MAX(seq),0)+1, ?, ?, ?, ? FROM sim_events WHERE session_id=?',
            (session_id, int(data.get('t_ms') or 0), C.KIND_SWITCH,
             data.get('reason') or 'blur', '{}', session_id))
        conn.commit()
        cnt = conn.execute('SELECT switch_count FROM sim_sessions WHERE id=?',
                           (session_id,)).fetchone()['switch_count']

    return jsonify({'success': True, 'count': cnt})


@bp.route('/api/sim/heartbeat', methods=['POST'])
def api_heartbeat():
    """心跳。同时用于校准学生机时钟——倒计时以服务端时间为准，改本机时间无效。"""
    sid, err = _require_student()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return _json_err('缺少 session_id')

    SV.expire_stale(sid)

    with get('get_db')() as conn:
        row = conn.execute('SELECT deadline, status FROM sim_sessions WHERE id=?',
                           (session_id,)).fetchone()
    if not row:
        return _json_err('会话不存在', 404)
    if row['status'] != C.STATUS_IN_PROGRESS:
        return jsonify({'success': True, 'finished': True, 'server_now': SV._now_str()})

    remain = SV._ms_between(SV._now_str(), row['deadline'])
    return jsonify({'success': True, 'remain_ms': max(0, remain),
                    'server_now': SV._now_str()})


@bp.route('/api/sim/resume')
def api_resume():
    """刷新/断网后恢复：返回会话与已存事件，前端重放还原界面状态。"""
    sid, err = _require_student()
    if err:
        return err

    sim_type = request.args.get('type') or ''
    if sim_type not in C.SIM_TYPES:
        return _json_err('模拟器类型无效')

    SV.expire_stale(sid)

    with get('get_db')() as conn:
        row = conn.execute(
            'SELECT * FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=? '
            'ORDER BY id DESC LIMIT 1', (sid, sim_type, C.MODE_EXAM)).fetchone()
        if not row:
            return jsonify({'success': True, 'session_id': None})
        events = SV.load_events(conn, row['id'])

    return jsonify({
        'success': True,
        'session_id': row['id'],
        'status': row['status'],
        'deadline': row['deadline'],
        'duration_ms': SV._ms_between(row['started_at'], row['deadline']),
        'server_now': SV._now_str(),
        'last_seq': (events[-1]['seq'] if events else 0),
        'events': events[-300:],       # 只回传最近 300 条，够还原状态即可
    })


@bp.route('/api/sim/submit', methods=['POST'])
def api_submit():
    """交卷。服务端重算分数，前端报的分数一律丢弃。"""
    sid, err = _require_student()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return _json_err('缺少 session_id')

    with get('get_db')() as conn:
        row = conn.execute('SELECT student_id FROM sim_sessions WHERE id=?',
                           (session_id,)).fetchone()
    if not row or row['student_id'] != sid:
        return _json_err('会话无效', 403)

    result, error = SV.submit_session(session_id, data.get('events'),
                                      reason=data.get('reason') or 'user')
    if error:
        return _json_err(error, 404)
    return jsonify({'success': True, 'result': result})


@bp.route('/api/sim/result')
def api_result():
    """学生自查成绩。"""
    sid, err = _require_student()
    if err:
        return err

    sim_type = request.args.get('type') or ''
    if sim_type not in C.SIM_TYPES:
        return _json_err('模拟器类型无效')

    with get('get_db')() as conn:
        row = conn.execute(
            'SELECT * FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=? '
            'ORDER BY id DESC LIMIT 1', (sid, sim_type, C.MODE_EXAM)).fetchone()
        if not row:
            return jsonify({'success': True, 'taken': False})
        result = SV._result_of(conn, row)
        # 开考了但还没交卷：不算"已考"，学生应能继续（限考记录仍然存在）
        if row['status'] == C.STATUS_IN_PROGRESS:
            return jsonify({'success': True, 'taken': False,
                            'in_progress': True, 'result': result})

    return jsonify({'success': True, 'taken': True, 'result': result})


# ==================== 教师端 API ====================
@bp.route('/admin/sim/summary')
def admin_summary():
    """成绩汇总表。"""
    guard = _admin_guard()
    if guard:
        return guard

    with get('get_db')() as conn:
        data = SV.build_summary(
            conn,
            class_name=request.args.get('class_name') or None,
            keyword=request.args.get('q') or None,
            only_missing=request.args.get('only_missing') == '1',
            min_switch=int(request.args.get('min_switch') or 0),
        )
        classes = [r['class_name'] for r in
                   conn.execute('SELECT class_name FROM classes ORDER BY class_name').fetchall()]
    data['classes'] = classes
    return jsonify({'success': True, **data})


@bp.route('/admin/sim/student/<int:student_id>')
def admin_student(student_id):
    """单人明细：操作时间轴 + 逐项得分 + 改分日志。"""
    guard = _admin_guard()
    if guard:
        return guard

    to_bj = get('to_beijing')
    out = {'bios': None, 'winpe': None, 'manual': None, 'logs': []}

    with get('get_db')() as conn:
        stu = conn.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
        if not stu:
            return _json_err('学生不存在', 404)

        score = conn.execute('SELECT * FROM sim_scores WHERE student_id=?',
                             (student_id,)).fetchone()

        for sim_type in C.SIM_TYPES:
            sess = conn.execute(
                'SELECT * FROM sim_sessions WHERE student_id=? AND sim_type=? AND mode=? '
                'ORDER BY id DESC LIMIT 1', (student_id, sim_type, C.MODE_EXAM)).fetchone()
            if not sess:
                continue
            events = SV.load_events(conn, sess['id'])
            rubric = R.get_rubric(sim_type, sess['rubric_version'])
            res = None
            if rubric:
                ctx = {}
                if sim_type == 'bios':
                    bj = get('beijing_now')()
                    ctx = {'exam_date': bj.strftime('%m/%d/%Y'),
                           'exam_time': bj.strftime('%H:%M:%S')}
                res = SV.G.sim_grade(events, rubric, sim_type, ctx=ctx)

            out[sim_type] = {
                'session_id': sess['id'],
                'status': sess['status'],
                'score': sess['raw_score'],
                'normalized': sess['normalized'],
                'duration_sec': sess['duration_sec'],
                'switch_count': sess['switch_count'],
                'started_at': to_bj(sess['started_at']),
                'submitted_at': to_bj(sess['submitted_at']),
                'steps': (res or {}).get('steps', []),
                'warnings': (res or {}).get('warnings', []),
                'timeline': [{
                    't_ms': e['t_ms'],
                    'kind': e['kind'],
                    'target': e['target'],
                    'value': e['value'],
                } for e in events[:200]],
            }

        if score:
            out['manual'] = {
                'score': score['manual_score'],
                'note': score['manual_note'],
                'at': to_bj(score['manual_at']),
                'regular_score': score['regular_score'],
                'exam_score': score['exam_score'],
                'final_score': score['final_score'],
            }

        out['logs'] = [{
            'field': r['field'], 'old': r['old_value'], 'new': r['new_value'],
            'operator': r['operator'], 'reason': r['reason'], 'at': to_bj(r['created_at']),
        } for r in conn.execute(
            'SELECT * FROM sim_score_log WHERE student_id=? ORDER BY id DESC LIMIT 50',
            (student_id,)).fetchall()]

    out['student'] = {'id': stu['id'], 'name': stu['name'],
                      'class_name': stu['class_name'],
                      'student_no': stu['student_no'] if 'student_no' in stu.keys() else ''}
    return jsonify({'success': True, **out})


@bp.route('/admin/sim/manual', methods=['POST'])
def admin_manual():
    """录入 / 修改实操装机分。"""
    guard = _admin_guard()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    student_id = data.get('student_id')
    if not student_id:
        return _json_err('缺少 student_id')

    ok, payload = SV.set_manual_score_retry(student_id, data.get('score'),
                                            data.get('note') or '')
    if not ok:
        return _json_err(payload)
    return jsonify({'success': True, 'message': '已保存实操分',
                    'exam_score': payload['exam_score'],
                    'final_score': payload['final_score']})


@bp.route('/admin/sim/manual/bulk', methods=['POST'])
def admin_manual_bulk():
    """批量导入实操分。每行格式：姓名 分数  或  姓名,分数"""
    guard = _admin_guard()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    text = data.get('text') or ''
    class_name = data.get('class_name') or None

    added, skipped = 0, []
    with get('get_db')() as conn:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.replace(',', ' ').replace('\t', ' ').split()
                     if p.strip()]
            if len(parts) < 2:
                skipped.append(line)
                continue
            name, score = parts[0], parts[-1]
            sql = 'SELECT id, name FROM students WHERE name=?'
            params = [name]
            if class_name:
                sql += ' AND class_name=?'
                params.append(class_name)
            row = conn.execute(sql, params).fetchone()
            if not row:
                skipped.append('%s（名单中查无此人）' % name)
                continue
            ok, _ = SV.set_manual_score(conn, row['id'], score, '批量导入')
            if ok:
                added += 1
            else:
                skipped.append('%s（分数无效）' % name)

    return jsonify({'success': True, 'added': added, 'skipped': skipped})


@bp.route('/admin/sim/void', methods=['POST'])
def admin_void():
    """作废某次考试，允许该生重考。"""
    guard = _admin_guard()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return _json_err('缺少 session_id')

    with get('get_db')() as conn:
        ok, msg = SV.void_session(conn, session_id)
    if not ok:
        return _json_err(msg)
    return jsonify({'success': True, 'message': msg})


@bp.route('/admin/sim/freeze_regular', methods=['POST'])
def admin_freeze():
    """冻结 / 解冻平时分快照。冻结后学生继续刷题不会影响已定成绩。"""
    guard = _admin_guard()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    freeze = bool(data.get('freeze', True))

    with get('get_db')() as conn:
        if freeze:
            reg = SV.regular_map(conn)
            for sid, val in reg.items():
                conn.execute('INSERT OR IGNORE INTO sim_scores (student_id) VALUES (?)', (sid,))
                conn.execute('UPDATE sim_scores SET regular_score=?, regular_snapshot_at=? '
                             'WHERE student_id=?', (val, SV._now_str(), sid))
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
                         (C.K_REGULAR_FROZEN, '1'))
            conn.commit()
            count = len(reg)
        else:
            conn.execute('UPDATE sim_scores SET regular_score=NULL, regular_snapshot_at=NULL')
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
                         (C.K_REGULAR_FROZEN, '0'))
            conn.commit()
            count = 0

    return jsonify({'success': True, 'frozen': freeze, 'count': count})


@bp.route('/admin/sim/live')
def admin_live():
    """实时监控：谁在考、剩余多久、切屏几次。"""
    guard = _admin_guard()
    if guard:
        return guard

    with get('get_db')() as conn:
        rows = conn.execute(
            'SELECT ss.id, ss.sim_type, ss.status, ss.started_at, ss.deadline, '
            'ss.switch_count, s.name, s.class_name '
            'FROM sim_sessions ss JOIN students s ON s.id = ss.student_id '
            "WHERE ss.mode = ? AND ss.status = ? ORDER BY ss.started_at DESC LIMIT 200",
            (C.MODE_EXAM, C.STATUS_IN_PROGRESS)).fetchall()

        out = [{
            'session_id': r['id'],
            'name': r['name'],
            'class_name': r['class_name'],
            'sim_type': r['sim_type'],
            'remain_sec': max(0, SV._ms_between(SV._now_str(), r['deadline']) // 1000),
            'switch_count': r['switch_count'],
            'started_at': get('to_beijing')(r['started_at']),
        } for r in rows]

    return jsonify({'success': True, 'sessions': out,
                    'server_time': get('to_beijing')(SV._now_str())})


@bp.route('/admin/sim/export')
def admin_export():
    """导出 Excel：总评 / BIOS 明细 / WinPE 明细 / 异常记录。"""
    guard = _admin_guard()
    if guard:
        return guard

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    HF = Font(bold=True, size=11, color='FFFFFF')
    HFILL = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    HA = Alignment(horizontal='center', vertical='center', wrap_text=True)
    CA = Alignment(horizontal='center', vertical='center')
    BD = Border(left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin'))

    def write_sheet(ws, headers, rows, widths=None):
        ws.append(headers)
        for i, _ in enumerate(headers, 1):
            c = ws.cell(row=1, column=i)
            c.font, c.fill, c.alignment, c.border = HF, HFILL, HA, BD
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment, c.border = CA, BD
        for i, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = 'A2'

    class_name = request.args.get('class_name') or None
    wb = Workbook()

    with get('get_db')() as conn:
        data = SV.build_summary(conn, class_name=class_name)
        rows = data['rows']

        # Sheet1 总评汇总
        ws1 = wb.active
        ws1.title = '总评汇总'
        write_sheet(ws1,
                    ['排名', '学号', '姓名', '班级', '平时分(50%)', 'BIOS(12.5%)',
                     'WinPE(12.5%)', '实操(25%)', '考试分(50%)', '总评', '切屏(B/W)', '状态'],
                    [[r['rank'], r['student_no'], r['name'], r['class_name'],
                      r['regular_score'],
                      r['bios_score'] if r['bios_score'] is not None else '未考',
                      r['winpe_score'] if r['winpe_score'] is not None else '未考',
                      r['manual_score'] if r['manual_score'] is not None else '未录入',
                      r['exam_score'], r['final_score'],
                      '%d/%d' % (r['bios_switch'], r['winpe_switch']),
                      '实操未录入' if r['manual_missing'] else '']
                     for r in rows],
                    [6, 12, 10, 22, 12, 13, 13, 12, 12, 10, 10, 12])

        # Sheet2/3 各科明细
        rubric_steps = {}
        for sim_type in C.SIM_TYPES:
            rub = R.get_rubric(sim_type)
            rubric_steps[sim_type] = rub['items']

        for sim_type, title in (('bios', 'BIOS明细'), ('winpe', 'WinPE明细')):
            ws = wb.create_sheet(title)
            items = rubric_steps[sim_type]
            headers = ['姓名', '班级', '总分', '用时(秒)', '切屏'] + \
                      [it['name'][:16] for it in items] + ['异常提示']
            body = []
            for r in rows:
                if r.get('%s_score' % sim_type) is None:
                    continue
                sess = conn.execute(
                    'SELECT * FROM sim_sessions WHERE id=?',
                    (r.get('%s_session_id' % sim_type),)).fetchone()
                if not sess:
                    continue
                events = SV.load_events(conn, sess['id'])
                ctx = {}
                if sim_type == 'bios':
                    bj = get('beijing_now')()
                    ctx = {'exam_date': bj.strftime('%m/%d/%Y'),
                           'exam_time': bj.strftime('%H:%M:%S')}
                res = SV.G.sim_grade(events, R.get_rubric(sim_type), sim_type, ctx=ctx)
                got = {s['id']: s['got'] for s in res['steps']}
                body.append([r['name'], r['class_name'], sess['normalized'],
                             sess['duration_sec'], sess['switch_count']] +
                            [got.get(it['id'], 0) for it in items] +
                            ['；'.join(res['warnings'][:2])])
            write_sheet(ws, headers, body,
                        [10, 22, 8, 10, 8] + [10] * len(items) + [30])

        # Sheet4 异常与切屏
        ws4 = wb.create_sheet('异常与切屏')
        abody = []
        for r in rows:
            if r['bios_switch'] or r['winpe_switch']:
                abody.append([r['name'], r['class_name'],
                              'BIOS切屏 %d 次' % r['bios_switch'],
                              'WinPE切屏 %d 次' % r['winpe_switch']])
        write_sheet(ws4, ['姓名', '班级', 'BIOS', 'WinPE'], abody, [12, 24, 20, 20])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    fname = '技能考试成绩_%s.xlsx' % get('beijing_now')().strftime('%Y%m%d_%H%M%S')
    return send_file(output, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
