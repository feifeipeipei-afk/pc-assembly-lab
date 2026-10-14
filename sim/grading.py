# -*- coding: utf-8 -*-
"""
模拟器考试 —— 判分引擎。

核心安全设计：**服务端独立重放，绝不相信前端传来的分数或状态快照**。

学生在浏览器里可以 F12 改任何 JS 变量。如果前端报什么分就记什么分，
等于把成绩本交给学生自己填。所以：

    前端只上报"我做了什么"（操作事件序列）
    服务端自己重放出"做完之后状态是什么"，再按 rubric 算分

本模块是纯函数集合：不读数据库、不发网络请求，可以脱离 Flask 直接 pytest。
"""

import copy
import json
import hashlib

from . import config as C
from . import rubrics as R


# ==================== 工具函数 ====================
def _safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_value(v):
    """事件的 value 字段是 JSON 字符串，容错解析。"""
    if v is None or v == '':
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return {}


# ==================== 事件清洗 ====================
def sanitize_events(events, deadline_ms=None, warnings=None):
    """
    清洗事件序列：去重、时间单调校验、超时裁剪。

    三条防作弊规则：
      1. seq 去重        —— 前端重复上报不会重复计分
      2. t_ms 必须非递减 —— 学生改系统时间造出"倒流"事件的，直接丢弃
      3. t_ms > 时限     —— 交卷超时后再补发的操作一律不计分
    """
    warnings = warnings if warnings is not None else []
    out, seen, last_t = [], set(), None

    for e in sorted(events or [], key=lambda x: _safe_int(x.get('seq'), 0)):
        seq = _safe_int(e.get('seq'), 0)

        if seq <= 0 or seq in seen:
            continue
        seen.add(seq)

        t = _safe_int(e.get('t_ms'), 0)
        if t < 0 or t > C.EVENT_MAX_T_MS:
            warnings.append('事件 #%d 的时间戳超出合理范围，已忽略' % seq)
            continue

        if last_t is not None and t < last_t - 1000:   # 容忍 1 秒时钟抖动
            warnings.append('事件 #%d 时间倒流（%dms < 上一事件 %dms），已忽略'
                            % (seq, t, last_t))
            continue
        last_t = t if last_t is None else max(last_t, t)

        if deadline_ms is not None and t > deadline_ms:
            warnings.append('事件 #%d 发生在考试结束之后（%dms > 时限 %dms），不计分'
                            % (seq, t, deadline_ms))
            continue

        out.append(e)

    return out


def events_hash(events):
    """事件序列指纹，入库留痕，事后可复核成绩是否被篡改。"""
    payload = '|'.join(
        '%s:%s:%s:%s' % (e.get('seq'), e.get('t_ms'), e.get('kind'), e.get('target'))
        for e in (events or [])
    )
    return hashlib.md5(payload.encode('utf-8')).hexdigest()


# ==================== 状态重放 ====================
def replay_state(events, sim_type):
    """
    从默认状态出发，按事件序列重放出最终状态与操作标记。

    返回 (state, flags)。
    flags 记录"做过什么动作"，用于判定那些光看最终状态看不出来的评分项，
    例如"是否进过 Boot Device Priority 子菜单""有没有按 F10 保存退出"。
    """
    if sim_type == 'bios':
        state = copy.deepcopy(R.BIOS_DEFAULTS)
    else:
        state = copy.deepcopy(R.PE_DEFAULTS)

    flags = {
        'tabs': [],          # 访问过的页签（有序）
        'submenus': [],      # 进入过的子菜单
        'keys': [],          # 用过的快捷键
        'actions': [],       # Exit 类动作
        'steps': [],         # WinPE 关键步骤
        'suspects': [],      # 可疑行为
        'bootmenu_pick': None,
        'post_detected': False,
        'post_handle': None,
        'fault_answer_ok': False,
        '_pwd_confirm': False,
        'changed': [],      # 被学生真正修改过的字段名
    }

    for e in events:
        kind = e.get('kind') or ''
        target = e.get('target') or ''
        value = _parse_value(e.get('value'))

        if kind == C.KIND_SET:
            # Proxy 自动埋点：{'from': 旧值, 'to': 新值}
            if target and target in state:
                state[target] = value.get('to', value)
                if target not in flags['changed']:
                    flags['changed'].append(target)

        elif kind == C.KIND_ACTION:
            if target not in flags['actions']:
                flags['actions'].append(target)
            if target == 'defaults':
                # F9 恢复出厂：整体重置（前端用 SIM.mute 包住，只发一条 action）
                state = copy.deepcopy(R.BIOS_DEFAULTS)
                state['loadedDefaults'] = True

        elif kind == C.KIND_NAV:
            if target.startswith('tab:'):
                name = target[4:]
                if name not in flags['tabs']:
                    flags['tabs'].append(name)
            elif target.startswith('submenu:'):
                name = target[8:]
                if name not in flags['submenus']:
                    flags['submenus'].append(name)

        elif kind == C.KIND_KEY:
            if target not in flags['keys']:
                flags['keys'].append(target)

        elif kind == C.KIND_SWITCH:
            pass   # 切屏次数由 sim_sessions.switch_count 单独维护

        elif kind == C.KIND_SUSPECT:
            if target not in flags['suspects']:
                flags['suspects'].append(target)

        elif kind == C.KIND_STEP:
            _apply_step(state, flags, target, value)

        elif kind == C.KIND_SNAPSHOT:
            # 兜底快照：只用于和重放结果对账，绝不作为判分依据
            flags['snapshot'] = value

    return state, flags


def _apply_step(state, flags, target, value):
    """应用一个关键操作步骤。WinPE 的判分数据都挂在这里。"""
    if target not in flags['steps']:
        flags['steps'].append(target)

    mapping = {
        'dg.quick': ('lastQuick', True),
        'dg.delete': ('lastDelete', False),
        'setup.install': ('lastInstall', False),
        'cdi.submit': ('lastCdi', False),
        'cdm.submit': ('lastCdm', False),
        'scr.submit': ('lastScreenTest', False),
        'burn.report': ('lastBurn', False),
        'aida.submit': ('lastAida', False),
        'memtest.report': ('lastMemtest', False),
        'kbd.submit': ('lastKbd', False),
        'mouse.submit': ('lastMouse', False),
    }
    if target in mapping:
        key, keep_history = mapping[target]
        state[key] = value
        if keep_history:
            state.setdefault('quicks', [])
            state['quicks'].append(value)
        return

    if target == 'boot.pick_usb':
        state['bootPicked'] = 'usb'
    elif target == 'pe.desktop_ready':
        state['peReady'] = True
    elif target == 'bootmenu.pick':
        flags['bootmenu_pick'] = value.get('device') or value.get('to')
    elif target == 'post.detected':
        flags['post_detected'] = True
    elif target == 'post.handle':
        flags['post_handle'] = value.get('action')
    elif target == 'fault.answer':
        flags['fault_answer_ok'] = bool(value.get('ok'))
    elif target == 'pwd.confirm':
        if value.get('ok'):
            flags['_pwd_confirm'] = True


# ==================== 评分 ====================
def _check_require(req, flags, passed):
    """
    前置依赖判定。
      - 以 '_' 开头：查 flags 里的布尔标记（如 '_pwd_confirm'）
      - 否则：查另一个 rubric 项是否已拿满分（如 'b2'）
    """
    if isinstance(req, (list, tuple)):
        return all(_check_require(r, flags, passed) for r in req)
    if not isinstance(req, str):
        return True
    if req.startswith('_'):
        return bool(flags.get(req))
    return bool(passed.get(req))


def _watched(watch, flags):
    """watch 指定的字段是否被真正修改过（防止"什么都不做却因为默认值恰好满足而得分"）。"""
    if not watch:
        return True
    keys = [watch] if isinstance(watch, str) else list(watch)
    changed = flags.get('changed') or []
    return all(k in changed for k in keys)


def _grade_item(item, state, flags, ctx, passed):
    """给单个评分项打分。"""
    pts = float(item['pts'])
    partial = float(item.get('partial', pts / 2.0))

    # 必须先"动过手"：默认状态恰好符合要求的不算数
    if not _watched(item.get('watch'), flags):
        return 0.0

    try:
        res = item['check'](state, flags, ctx)
    except Exception:
        res = False

    # check 可直接返回数值（比例分，如快速分区错一项扣 1/5）
    if isinstance(res, (int, float)) and not isinstance(res, bool):
        return max(0.0, min(pts, float(res)))

    if res:
        req = item.get('require')
        if req and not _check_require(req, flags, passed):
            return partial          # 做对了但流程不对：给部分分
        return pts

    pc = item.get('partial_check')
    if pc:
        try:
            if pc(state, flags, ctx):
                return partial      # 次优解：给部分分
        except Exception:
            pass

    return 0.0


def sim_grade(events, rubric, sim_type='bios', deadline_ms=None, ctx=None):
    """
    判分主入口。

    Parameters
    ----------
    events : list[dict]
        操作事件序列，字段 seq / t_ms / kind / target / value
    rubric : dict
        评分细则，见 sim/rubrics.py
    sim_type : str
        'bios' | 'winpe'
    deadline_ms : int | None
        本场时限（毫秒）。不为 None 时，超时后的事件不参与判分。
    ctx : dict
        额外上下文，如 {'exam_date': '10/13/2026', 'exam_time': '09:12:00'}

    Returns
    -------
    dict
        score / max_score / normalized / version / steps / state / warnings
    """
    ctx = ctx or {}
    warnings = []

    clean = sanitize_events(events, deadline_ms, warnings)
    state, flags = replay_state(clean, sim_type)

    steps, passed, total = [], {}, 0.0

    for item in rubric['items']:
        pts = float(item['pts'])
        got = _grade_item(item, state, flags, ctx, passed)
        got = round(max(0.0, min(pts, got)), 2)
        total += got
        passed[item['id']] = got >= pts - 1e-6

        steps.append({
            'id': item['id'],
            'name': item['name'],
            'pts': pts,
            'got': got,
            'full': passed[item['id']],
            'tip': item.get('tip', ''),
        })

    # 兜底快照对账：前端上报的 state 与服务端重放结果不一致时告警（不改分）
    snap = flags.get('snapshot')
    if isinstance(snap, dict) and snap:
        diff = _snapshot_diff(state, snap)
        if diff:
            warnings.append('前端状态快照与服务端重放结果不一致：%s（以服务端重放为准）'
                            % '、'.join(diff[:5]))

    if not clean:
        warnings.append('未收到任何操作事件，得分为 0')

    max_score = float(rubric.get('max_score') or sum(i['pts'] for i in rubric['items']))
    total = round(total, 2)

    return {
        'score': total,
        'max_score': max_score,
        'normalized': round(total / max_score * 100, 1) if max_score else 0.0,
        'version': rubric.get('version', ''),
        'steps': steps,
        'state': state,
        'warnings': warnings,
        'event_count': len(clean),
        'events_hash': events_hash(clean),
    }


def _snapshot_diff(state, snap, limit=5):
    """对比重放状态与前端快照，返回不一致的字段名（最多 limit 个）。"""
    diff = []
    for k, v in (snap or {}).items():
        if k not in state:
            continue
        sv = state[k]
        # 数字/字符串做宽松比较，避免 JSON 序列化差异误报
        if isinstance(v, (int, float)) or isinstance(sv, (int, float)):
            try:
                if abs(float(v) - float(sv)) > 1e-6:
                    diff.append(k)
            except (TypeError, ValueError):
                if str(v) != str(sv):
                    diff.append(k)
        elif isinstance(v, list) or isinstance(sv, list):
            if [str(x) for x in (v or [])] != [str(x) for x in (sv or [])]:
                diff.append(k)
        elif str(v) != str(sv):
            diff.append(k)
        if len(diff) >= limit:
            break
    return diff
