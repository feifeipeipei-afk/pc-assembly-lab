"""
《计算机安装与维修》在线刷题系统
面向中职一年级学生的在线考试与练习平台
"""
# Fix stdout encoding for Windows GBK consoles
import sys, io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import io
import json
import time
import hashlib
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=3)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('QUIZ_DB_PATH', os.path.join(BASE_DIR, 'quiz_app.db'))
QUESTIONS_PATH = os.path.join(BASE_DIR, 'questions.json')
SECRET_KEY_PATH = os.path.join(BASE_DIR, '.secret_key')

QUIZ_DURATION_MINUTES = 90
QUIZ_QUESTION_COUNT = 50
PRACTICE_MAX_COUNT = 50
PRACTICE_DEADLINE_HOURS = 6
DEFAULT_ADMIN_PASSWORD = os.environ.get('QUIZ_ADMIN_PASSWORD', 'admin123')

# ==================== 战斗竞技场（课间训练用，不计入考试统计） ====================
BATTLE_QUESTIONS_PER_STAGE = 10   # 闯关每关 / 竞技场每场题数
BATTLE_DEADLINE_MINUTES = 60      # 战斗会话限时（分钟）
BATTLE_STAR_3 = 0.9               # 正确率 ≥90% 三星
BATTLE_STAR_2 = 0.7               # ≥70% 两星
BATTLE_PASS = 0.6                 # ≥60% 一星通关，低于则战败
BATTLE_LABEL_PREFIX = '闯关 · '
BATTLE_MODES = ('battle', 'pvp')
LADDER_POINTS = {'win': 5, 'draw': 2, 'loss': 1}   # 负方也有参与分，保护积极性
DUMMY_PROFILES = [
    {'tier': 1, 'name': '训练假人·青铜', 'correct': 4},
    {'tier': 2, 'name': '训练假人·白银', 'correct': 6},
    {'tier': 3, 'name': '训练假人·黄金', 'correct': 8},
]

# ==================== 经验与等级系统 ====================
XP_BASE = 10            # 每题答对的基础经验
XP_DAILY_FULL = 15      # 当日答对前 15 题：100% 经验
XP_DAILY_HALF = 30      # 第 16~30 题：50%；之后：10%
XP_DAILY_FLOOR = 0.1
XP_REPEAT_FACTORS = [1.0, 0.3, 0.0]   # 同一题第 1 / 2 / 3+ 次答对的经验系数
QUALIFY_LEVEL = 20      # 达到该等级视为平时成绩合格

LEVEL_NAMES = (
    '青铜Ⅳ', '青铜Ⅲ', '青铜Ⅱ', '青铜Ⅰ',
    '白银Ⅳ', '白银Ⅲ', '白银Ⅱ', '白银Ⅰ',
    '黄金Ⅳ', '黄金Ⅲ', '黄金Ⅱ', '黄金Ⅰ',
    '铂金Ⅳ', '铂金Ⅲ', '铂金Ⅱ', '铂金Ⅰ',
    '钻石Ⅳ', '钻石Ⅲ', '钻石Ⅱ', '钻石Ⅰ',
    '星耀Ⅳ', '星耀Ⅲ', '星耀Ⅱ', '星耀Ⅰ',
    '王者Ⅳ', '王者Ⅲ', '王者Ⅱ', '王者Ⅰ',
    '荣耀王者', '最强王者',
)
MAX_LEVEL = len(LEVEL_NAMES)


def xp_for_level(level):
    """从 level 级升到 level+1 级所需经验。"""
    return 15 * level


def total_xp_for_level(level):
    """从 1 级升到 level 级所需的总经验。"""
    return sum(xp_for_level(lv) for lv in range(1, max(int(level), 1)))


def score_from_level(level, qualify_level):
    """等级折算平时成绩：1 级 0 分，合格等级 60 分，满级 100 分。"""
    if level <= 1:
        return 0
    if level >= MAX_LEVEL:
        return 100
    if level <= qualify_level:
        return round(60 * (level - 1) / max(qualify_level - 1, 1))
    return round(60 + 40 * (level - qualify_level) / max(MAX_LEVEL - qualify_level, 1))


def level_from_xp(total_xp, qualify_level=QUALIFY_LEVEL):
    """由总经验计算等级信息（含合格判定与平时成绩折算分）。"""
    level, remaining = 1, total_xp or 0
    while level < MAX_LEVEL and remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    need = xp_for_level(level) if level < MAX_LEVEL else 0
    return {
        'level': level,
        'name': LEVEL_NAMES[level - 1],
        'xp_into_level': remaining,
        'xp_next_level': need,
        'total_xp': total_xp or 0,
        'qualified': level >= qualify_level,
        'regular_score': score_from_level(level, qualify_level),
    }


def get_qualify_level(conn):
    """从 settings 读取合格等级（教师可在后台调整，默认 20 级）。"""
    row = conn.execute("SELECT value FROM settings WHERE key='qualify_level'").fetchone()
    if row:
        try:
            lv = int(row[0])
            if 2 <= lv <= MAX_LEVEL:
                return lv
        except (TypeError, ValueError):
            pass
    return QUALIFY_LEVEL


def get_roster_mode(conn):
    """花名册模式：学生只能用老师添加的账号登录（默认开启，后台可关闭）。"""
    row = conn.execute("SELECT value FROM settings WHERE key='roster_mode'").fetchone()
    return not (row and row[0] == '0')


def get_battle_enabled(conn):
    """战斗竞技场开关：默认开启，老师可在后台关闭（如期末考试期间）。"""
    row = conn.execute("SELECT value FROM settings WHERE key='battle_enabled'").fetchone()
    return not (row and row[0] == '0')


def get_exam_window(conn):
    """考试开放时段（北京时间 'YYYY-MM-DD HH:MM'，空串表示不限）。"""
    def _get(key):
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return (row[0] or '').strip() if row else ''
    return _get('exam_window_start'), _get('exam_window_end')


def exam_window_state(conn):
    """返回考试窗口状态：('open'/'before'/'after'/None, 提示文本)。"""
    start, end = get_exam_window(conn)
    if not start and not end:
        return None, ''
    now = beijing_now()
    if start and now < datetime.strptime(start, '%Y-%m-%d %H:%M'):
        return 'before', f'考试 {start} 开放，现在还未开始'
    if end and now > datetime.strptime(end, '%Y-%m-%d %H:%M'):
        return 'after', f'考试已于 {end} 结束'
    return 'open', f'考试窗口：{start or "不限"} ~ {end or "不限"}'


def get_exam_max_attempts(conn):
    """考试次数上限（0 = 不限）。"""
    row = conn.execute("SELECT value FROM settings WHERE key='exam_max_attempts'").fetchone()
    if row:
        try:
            n = int(row[0])
            if n >= 0:
                return n
        except (TypeError, ValueError):
            pass
    return 0


def load_secret_key():
    """持久化 secret key，重启不掉登录状态。"""
    try:
        with open(SECRET_KEY_PATH, 'rb') as f:
            key = f.read().strip()
            if key:
                return key
    except FileNotFoundError:
        pass
    key = os.urandom(32)
    with open(SECRET_KEY_PATH, 'wb') as f:
        f.write(key)
    return key


app.secret_key = load_secret_key()


def utcnow():
    """naive UTC 时间（避免 datetime.utcnow 在新版本 Python 中弃用）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ==================== 北京时间（课堂固定东八区） ====================
# 数据库内部统一存 UTC；所有"给人看"的时间与经验归属日都用北京时间。
BEIJING_OFFSET = timedelta(hours=8)


def beijing_now():
    """当前北京时间（naive）。"""
    return utcnow() + BEIJING_OFFSET


def to_beijing(ts_str):
    """把数据库中的 UTC 时间字符串转成北京时间字符串；空值或格式异常原样返回。"""
    if not ts_str:
        return ts_str
    try:
        dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return ts_str
    return (dt + BEIJING_OFFSET).strftime('%Y-%m-%d %H:%M:%S')


@contextmanager
def get_db():
    # timeout=15：全班同时开考/交卷时会有并发写，默认 5 秒太短会报 database is locked
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                class_name TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, class_name)
            );

            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                q_type TEXT NOT NULL,
                question TEXT NOT NULL,
                options TEXT,
                answer TEXT NOT NULL,
                explanation TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                question_ids TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deadline TIMESTAMP,
                submitted_at TIMESTAMP,
                status TEXT DEFAULT 'in_progress',
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                student_answer TEXT,
                is_correct INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES quiz_sessions(id),
                FOREIGN KEY (question_id) REFERENCES questions(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS xp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                xp INTEGER DEFAULT 0,
                gain_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS battle_progress (
                student_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                stars INTEGER DEFAULT 0,
                best_accuracy REAL DEFAULT 0,
                times INTEGER DEFAULT 0,
                updated_at TIMESTAMP,
                UNIQUE(student_id, category)
            );

            CREATE TABLE IF NOT EXISTS battle_results (
                session_id INTEGER PRIMARY KEY,
                student_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                stars INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pvp_shadows (
                student_id INTEGER UNIQUE,
                question_ids TEXT NOT NULL,
                events TEXT NOT NULL,
                correct_count INTEGER DEFAULT 0,
                total_time_ms INTEGER DEFAULT 0,
                category TEXT DEFAULT '',
                updated_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pvp_ladder (
                student_id INTEGER UNIQUE,
                points INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS pvp_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER UNIQUE,
                challenger_id INTEGER NOT NULL,
                defender_id INTEGER,
                defender_name TEXT DEFAULT '',
                defender_correct INTEGER,
                defender_time_ms INTEGER,
                ghost_events TEXT,
                challenger_correct INTEGER,
                result TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_student ON quiz_sessions(student_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_status ON quiz_sessions(status);
            CREATE INDEX IF NOT EXISTS idx_answers_session ON answers(session_id);
            CREATE INDEX IF NOT EXISTS idx_xp_student_date ON xp_log(student_id, gain_date);
            CREATE INDEX IF NOT EXISTS idx_xp_question ON xp_log(student_id, question_id);
            CREATE INDEX IF NOT EXISTS idx_battle_progress_student ON battle_progress(student_id);
            CREATE INDEX IF NOT EXISTS idx_matches_challenger ON pvp_matches(challenger_id);
            CREATE INDEX IF NOT EXISTS idx_matches_defender ON pvp_matches(defender_id);
        ''')
        # 增量同步所需的列（老库迁移）
        _add_column(conn, 'questions', 'content_hash', 'TEXT')
        _add_column(conn, 'quiz_sessions', 'mode', "TEXT DEFAULT 'exam'")
        _add_column(conn, 'quiz_sessions', 'label', "TEXT DEFAULT ''")
        _add_column(conn, 'quiz_sessions', 'switch_count', 'INTEGER DEFAULT 0')
        _add_column(conn, 'quiz_sessions', 'opponent_id', 'INTEGER')
        _add_column(conn, 'answers', 'answered_at', 'TIMESTAMP')
        # 管理员密码哈希（首次默认，后台可修改）
        # 用 INSERT OR IGNORE：多进程/多 worker 同时首次启动时，
        # "先查再插"的写法会因 key 是主键而抛 IntegrityError。
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('admin_password_hash', ?)",
                     (generate_password_hash(DEFAULT_ADMIN_PASSWORD),))
        conn.commit()


def _add_column(conn, table, column, col_type):
    """SQLite 无 ADD COLUMN IF NOT EXISTS，检查后添加。"""
    cols = [r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')


def _total_xp(conn, student_id):
    row = conn.execute('SELECT COALESCE(SUM(xp), 0) FROM xp_log WHERE student_id = ?',
                       (student_id,)).fetchone()
    return row[0]


def _daily_xp_factor(correct_today):
    """每日疲劳：当天答对越多，单题经验越低。"""
    if correct_today < XP_DAILY_FULL:
        return 1.0
    if correct_today < XP_DAILY_HALF:
        return 0.5
    return XP_DAILY_FLOOR


def _grant_session_xp(conn, student_id, session_id):
    """按疲劳规则给本次会话答对的题发放经验，返回本次获得的总经验。

    每日疲劳按当天累计答对题数分档；同一题只要此前做错过也算"做过"，
    重复做题经验逐次衰减到 0（防止先乱答看答案、再重刷拿满经验）。
    每个会话只发放一次（重复调用直接跳过）。"""
    already = conn.execute('SELECT 1 FROM xp_log WHERE session_id = ? LIMIT 1',
                           (session_id,)).fetchone()
    if already:
        return 0

    today = beijing_now().strftime('%Y-%m-%d')
    correct_rows = conn.execute(
        'SELECT question_id FROM answers WHERE session_id = ? AND is_correct = 1 ORDER BY id',
        (session_id,)).fetchall()

    daily_count = conn.execute(
        'SELECT COUNT(*) FROM xp_log WHERE student_id = ? AND gain_date = ?',
        (student_id, today)).fetchone()[0]

    total_xp = 0
    for r in correct_rows:
        repeats = conn.execute(
            'SELECT COUNT(DISTINCT a.session_id) FROM answers a '
            'JOIN quiz_sessions qs ON qs.id = a.session_id '
            'WHERE qs.student_id = ? AND a.question_id = ? AND a.session_id != ?',
            (student_id, r['question_id'], session_id)).fetchone()[0]
        repeat_factor = XP_REPEAT_FACTORS[min(repeats, len(XP_REPEAT_FACTORS) - 1)]
        daily_factor = _daily_xp_factor(daily_count)
        xp = round(XP_BASE * repeat_factor * daily_factor)
        conn.execute(
            'INSERT INTO xp_log (student_id, session_id, question_id, xp, gain_date) '
            'VALUES (?, ?, ?, ?, ?)',
            (student_id, session_id, r['question_id'], xp, today))
        total_xp += xp
        daily_count += 1
    return total_xp


def question_hash(q):
    payload = json.dumps([q.get('category', ''), q.get('q_type', ''), q.get('question', ''),
                          q.get('options', []), q.get('answer', ''), q.get('explanation', '')],
                         ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode('utf-8')).hexdigest()


def answers_match(q_type, student, correct):
    """判分：multi 按字母集合判等（与顺序无关），其余题型保持精确比较。"""
    s = (student or '').strip().upper()
    c = (correct or '').strip().upper()
    if q_type == 'multi':
        return bool(s) and set(s) == set(c)
    return s == c


def _valid_answer(q_type, answer):
    """校验学员提交的答案格式。

    multi：2~4 个已排序去重的 A-D 字母（如 "ABC"）；
    其余：单个 A-F 字母，或空串（未作答）。
    """
    if answer == '':
        return True
    if q_type == 'multi':
        return (2 <= len(answer) <= 4
                and answer == ''.join(sorted(set(answer)))
                and set(answer) <= set('ABCD'))
    return answer in ('A', 'B', 'C', 'D', 'E', 'F')


def load_questions():
    """增量同步题库到 SQLite：按内容哈希新增/删除，保留学生成绩与答题记录。"""
    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        questions = json.load(f)

    json_hash = hashlib.md5(json.dumps(questions, sort_keys=True).encode()).hexdigest()

    with get_db() as conn:
        stored = conn.execute("SELECT value FROM settings WHERE key='questions_hash'").fetchone()
        if stored and stored[0] == json_hash:
            return {'skipped': True}

        # 为老库中缺少哈希的行补算
        rows = conn.execute(
            'SELECT id, category, q_type, question, options, answer, explanation, content_hash FROM questions'
        ).fetchall()
        for row in rows:
            if row['content_hash']:
                continue
            opts = json.loads(row['options']) if row['options'] else []
            h = question_hash({'category': row['category'], 'q_type': row['q_type'],
                               'question': row['question'], 'options': opts,
                               'answer': row['answer'], 'explanation': row['explanation']})
            conn.execute('UPDATE questions SET content_hash = ? WHERE id = ?', (h, row['id']))

        existing = {row['content_hash']: row['id'] for row in
                    conn.execute('SELECT id, content_hash FROM questions WHERE content_hash IS NOT NULL').fetchall()}

        added = 0
        for q in questions:
            h = question_hash(q)
            if h in existing:
                continue
            conn.execute(
                'INSERT INTO questions (category, q_type, question, options, answer, explanation, content_hash) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (q['category'], q['q_type'], q['question'],
                 json.dumps(q.get('options', []), ensure_ascii=False),
                 q['answer'], q.get('explanation', ''), h))
            added += 1

        # 删除题库中已不存在、且未被任何答题记录引用的题（保留历史成绩详情）
        # 题库规模已超 SQLITE_MAX_VARIABLE_NUMBER（本机 SQLite 3.31.1 实测上限 999），
        # 因此改为在 Python 侧比对哈希，删除时按 500 个 id 一批分块执行
        file_hashes = {question_hash(q) for q in questions}
        rows = conn.execute('''
            SELECT q.id, q.content_hash,
                   EXISTS (SELECT 1 FROM answers a WHERE a.question_id = q.id) AS referenced
            FROM questions q WHERE q.content_hash IS NOT NULL
        ''').fetchall()
        stale_ids = [r['id'] for r in rows
                     if r['content_hash'] not in file_hashes and not r['referenced']]
        for i in range(0, len(stale_ids), 500):
            chunk = stale_ids[i:i + 500]
            conn.execute('DELETE FROM questions WHERE id IN (%s)'
                         % ','.join('?' * len(chunk)), chunk)

        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('questions_hash', ?)", (json_hash,))
        conn.commit()
        total = conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        print(f"✅ 题库已同步：新增 {added} 题，移除 {len(stale_ids)} 题，当前共 {total} 题")
        return {'skipped': False, 'added': added, 'removed': len(stale_ids), 'total': total}


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ==================== 管理员登录限流 ====================
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = 60


def _check_login_throttle(ip):
    with LOGIN_LOCK:
        attempts = LOGIN_ATTEMPTS.get(ip, [])
        now = time.time()
        attempts = [t for t in attempts if now - t < ATTEMPT_WINDOW]
        LOGIN_ATTEMPTS[ip] = attempts
        return len(attempts) >= MAX_ATTEMPTS


def _record_failed_login(ip):
    with LOGIN_LOCK:
        LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


# ==================== 公共API ====================

@app.route('/api/classes')
def get_classes():
    with get_db() as conn:
        classes = conn.execute('SELECT id, class_name FROM classes ORDER BY class_name').fetchall()
        roster_mode = get_roster_mode(conn)
    return jsonify({'classes': [dict(c) for c in classes], 'roster_mode': roster_mode})


@app.route('/api/roster')
def get_roster():
    """花名册模式下，登录页按班级拉取学生名单供选择。"""
    class_name = (request.args.get('class_name') or '').strip()
    if not class_name:
        return jsonify({'students': []})
    with get_db() as conn:
        rows = conn.execute(
            'SELECT name FROM students WHERE class_name = ? ORDER BY name', (class_name,)).fetchall()
    return jsonify({'students': [r['name'] for r in rows]})


@app.route('/api/categories')
def get_categories():
    with get_db() as conn:
        rows = conn.execute(
            'SELECT category, COUNT(*) AS count FROM questions GROUP BY category ORDER BY category'
        ).fetchall()
    return jsonify({'categories': [dict(r) for r in rows]})


@app.route('/api/leaderboard')
def get_leaderboard():
    """班级等级榜：按总经验排序，考试与练习的答题都计入经验。"""
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        student = conn.execute('SELECT id, class_name FROM students WHERE id = ?', (student_id,)).fetchone()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})

        qualify_level = get_qualify_level(conn)
        rows = conn.execute(
            '''
            SELECT
                s.id,
                s.name,
                (SELECT COALESCE(SUM(x.xp), 0) FROM xp_log x WHERE x.student_id = s.id) AS total_xp,
                (SELECT COUNT(*) FROM quiz_sessions qs WHERE qs.student_id = s.id
                   AND qs.status IN ('completed', 'timeout')
                   AND (qs.mode IS NULL OR qs.mode = 'exam')) AS attempts,
                (SELECT ROUND(AVG(CAST(qs.score AS FLOAT) / qs.total * 100), 1) FROM quiz_sessions qs
                   WHERE qs.student_id = s.id AND qs.status IN ('completed', 'timeout')
                   AND qs.total > 0 AND (qs.mode IS NULL OR qs.mode = 'exam')) AS avg_score
            FROM students s
            WHERE s.class_name = ?
            ''',
            (student['class_name'],)
        ).fetchall()

    leaderboard = []
    for r in rows:
        item = dict(r)
        # 没做过任何题的学生不上榜（自己除外，保证能看到自己的排名）
        if item['total_xp'] <= 0 and item['attempts'] == 0 and item['id'] != student_id:
            continue
        lv = level_from_xp(item['total_xp'], qualify_level)
        item['level'] = lv['level']
        item['level_name'] = lv['name']
        item['qualified'] = lv['qualified']
        item['is_current'] = item['id'] == student_id
        leaderboard.append(item)

    leaderboard.sort(key=lambda r: (
        -(r['total_xp'] or 0),
        -(r['avg_score'] or 0),
        r['name']
    ))

    current_rank = None
    for idx, item in enumerate(leaderboard, 1):
        item['rank'] = idx
        if item['is_current']:
            current_rank = idx

    return jsonify({
        'success': True,
        'class_name': student['class_name'],
        'metric': 'total_xp',
        'qualify_level': qualify_level,
        'current_rank': current_rank,
        'leaderboard': leaderboard[:50]
    })


@app.route('/api/profile')
def student_profile():
    """学生个人等级信息：经验、段位、班级排名、平时成绩折算分、距合格进度。"""
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        student = conn.execute('SELECT id, class_name FROM students WHERE id = ?',
                               (student_id,)).fetchone()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})
        qualify_level = get_qualify_level(conn)
        total_xp = _total_xp(conn, student_id)
        classmates = conn.execute(
            'SELECT s.id, (SELECT COALESCE(SUM(x.xp), 0) FROM xp_log x WHERE x.student_id = s.id) AS xp '
            'FROM students s WHERE s.class_name = ?',
            (student['class_name'],)
        ).fetchall()
        star = _star_bonus(conn, student_id)

    rank = 1 + sum(1 for c in classmates if c['xp'] > total_xp)
    lv = level_from_xp(total_xp, qualify_level)

    return jsonify({
        'success': True,
        'class_name': student['class_name'],
        'total_xp': lv['total_xp'],
        'level': lv['level'],
        'level_name': lv['name'],
        'xp_into_level': lv['xp_into_level'],
        'xp_next_level': lv['xp_next_level'],
        'qualified': lv['qualified'],
        'regular_score': min(100, round(lv['regular_score'] + star['bonus'], 1)),
        'star_bonus': star,
        'rank': rank,
        'class_total': len(classmates),
        'qualify_level': qualify_level,
        'qualify_level_name': LEVEL_NAMES[qualify_level - 1],
        'xp_to_qualify': max(total_xp_for_level(qualify_level) - total_xp, 0),
    })


def get_wrong_question_ids(conn, student_id):
    """汇总学生答错过的题目（含未作答），考试与练习都计入错题本。"""
    rows = conn.execute(
        '''
        SELECT DISTINCT a.question_id
        FROM answers a
        JOIN quiz_sessions qs ON qs.id = a.session_id
        WHERE qs.student_id = ?
          AND qs.status IN ('completed', 'timeout')
          AND a.is_correct = 0
        ''',
        (student_id,)
    ).fetchall()
    raw_ids = [r['question_id'] for r in rows]
    return latest_question_ids(conn, raw_ids)


def latest_question_ids(conn, ids):
    """把题目 id 映射到同题干的最新版本（题库增量更新后旧记录仍指向旧版行）。"""
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    text_rows = conn.execute(
        f'SELECT id, question FROM questions WHERE id IN ({ph})', ids).fetchall()
    text_of = {r['id']: r['question'] for r in text_rows}
    texts = list({t for t in text_of.values() if t})

    latest = {}
    for i in range(0, len(texts), 400):  # 分块避免参数数量限制
        chunk = texts[i:i + 400]
        cph = ','.join('?' * len(chunk))
        for r in conn.execute(
                f'SELECT id, question FROM questions WHERE question IN ({cph})', chunk):
            if r['question'] not in latest or r['id'] > latest[r['question']]:
                latest[r['question']] = r['id']

    seen, result = set(), []
    for qid in ids:
        new_id = latest.get(text_of.get(qid), qid)
        if new_id not in seen:
            seen.add(new_id)
            result.append(new_id)
    return result


@app.route('/api/wrong_stats')
def wrong_stats():
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        wrong_ids = get_wrong_question_ids(conn, student_id)
        if not wrong_ids:
            return jsonify({'success': True, 'total': 0, 'categories': [], 'questions': []})

        placeholders = ','.join('?' * len(wrong_ids))
        rows = conn.execute(
            f'SELECT id, category, q_type, question, options, answer, explanation '
            f'FROM questions WHERE id IN ({placeholders})',
            wrong_ids
        ).fetchall()

    cat_counter = {}
    questions = []
    for r in rows:
        q = dict(r)
        cat_counter[q['category']] = cat_counter.get(q['category'], 0) + 1
        if q['options']:
            q['options'] = json.loads(q['options'])
        questions.append(q)
    questions.sort(key=lambda x: x['id'])

    return jsonify({
        'success': True,
        'total': len(questions),
        'categories': [{'category': c, 'count': n} for c, n in
                       sorted(cat_counter.items(), key=lambda x: -x[1])],
        'questions': questions
    })


# ==================== 学生端路由 ====================

@app.route('/')
def index():
    student = None
    last_score = None
    battle_enabled = True
    if session.get('student_id'):
        with get_db() as conn:
            battle_enabled = get_battle_enabled(conn)
            student = conn.execute('SELECT * FROM students WHERE id = ?', (session['student_id'],)).fetchone()
            if student:
                last = conn.execute(
                    'SELECT score, total, submitted_at FROM quiz_sessions '
                    'WHERE student_id = ? AND status = ? ORDER BY submitted_at DESC LIMIT 1',
                    (session['student_id'], 'completed')
                ).fetchone()
                if last:
                    last_score = dict(last)
                    last_score['submitted_at'] = to_beijing(last_score['submitted_at'])
    return render_template('index.html', student=student, last_score=last_score,
                           duration=QUIZ_DURATION_MINUTES, question_count=QUIZ_QUESTION_COUNT,
                           battle_enabled=battle_enabled)


@app.route('/login', methods=['POST'])
def student_login():
    data = request.get_json()
    name = data.get('name', '').strip()
    class_name = data.get('class_name', '').strip()

    if not name or not class_name:
        return jsonify({'success': False, 'message': '请选择班级并输入姓名'})
    if len(name) > 20 or len(class_name) > 40:
        return jsonify({'success': False, 'message': '姓名或班级名过长'})

    with get_db() as conn:
        roster_mode = get_roster_mode(conn)
        student = conn.execute('SELECT * FROM students WHERE name = ? AND class_name = ?',
                               (name, class_name)).fetchone()
        if student:
            student_id = student['id']
        elif roster_mode:
            return jsonify({'success': False,
                            'message': '名单中没有找到你，请联系老师把你加入班级名单'})
        else:
            try:
                cursor = conn.execute('INSERT INTO students (name, class_name) VALUES (?, ?)',
                                      (name, class_name))
                conn.commit()
                student_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                # 并发注册竞态：另一请求已插入
                student = conn.execute('SELECT * FROM students WHERE name = ? AND class_name = ?',
                                       (name, class_name)).fetchone()
                if not student:
                    return jsonify({'success': False, 'message': '登录失败，请重试'})
                student_id = student['id']

    session['student_id'] = student_id
    session['student_name'] = name
    session['class_name'] = class_name
    session.permanent = True

    return jsonify({'success': True, 'message': f'欢迎，{name}！'})


def _expire_stale_session(conn, quiz_row):
    """把超时未交卷的会话按已保存答案自动判分封存。"""
    now = utcnow()
    deadline = datetime.strptime(quiz_row['deadline'], '%Y-%m-%d %H:%M:%S')
    if now < deadline:
        return False
    _finalize_timeout(conn, quiz_row)
    return True


def _finalize_timeout(conn, quiz_row):
    deadline = datetime.strptime(quiz_row['deadline'], '%Y-%m-%d %H:%M:%S')
    question_ids = json.loads(quiz_row['question_ids'])
    answered_ids = {r['question_id'] for r in conn.execute(
        'SELECT question_id FROM answers WHERE session_id = ?', (quiz_row['id'],)).fetchall()}
    for qid in question_ids:
        if qid not in answered_ids:
            conn.execute(
                'INSERT INTO answers (session_id, question_id, student_answer, is_correct) VALUES (?, ?, ?, ?)',
                (quiz_row['id'], qid, '', 0))
    # 超时也按已保存的答案判分并发放经验，否则超时会话成绩恒为 0
    answers = conn.execute(
        'SELECT a.id, a.student_answer, q.answer, q.q_type FROM answers a '
        'JOIN questions q ON a.question_id = q.id WHERE a.session_id = ?',
        (quiz_row['id'],)).fetchall()
    score = 0
    for ans in answers:
        is_correct = 1 if answers_match(ans['q_type'], ans['student_answer'], ans['answer']) else 0
        score += is_correct
        conn.execute('UPDATE answers SET is_correct = ? WHERE id = ?', (is_correct, ans['id']))
    conn.execute('UPDATE quiz_sessions SET score = ?, submitted_at = ?, status = ? WHERE id = ?',
                 (score, deadline.strftime('%Y-%m-%d %H:%M:%S'), 'timeout', quiz_row['id']))
    _finalize_battle(conn, quiz_row, score, quiz_row['total'])
    _grant_session_xp(conn, quiz_row['student_id'], quiz_row['id'])
    conn.commit()


# ==================== 战斗竞技场核心逻辑 ====================

def _battle_stage_order(conn):
    """关卡顺序：按分类题量降序编号（题量最少的压轴）。"""
    rows = conn.execute(
        "SELECT category, COUNT(*) AS count FROM questions "
        "WHERE q_type IN ('mc','tf') "
        "GROUP BY category ORDER BY COUNT(*) DESC, category").fetchall()
    return [(i + 1, r['category'], r['count']) for i, r in enumerate(rows)]


def _stars_for(score, total):
    """闯关星级：≥90% 三星、≥70% 两星、≥60% 一星通关，低于即战败 0 星。"""
    if not total:
        return 0
    acc = score / total
    if acc >= BATTLE_STAR_3:
        return 3
    if acc >= BATTLE_STAR_2:
        return 2
    if acc >= BATTLE_PASS:
        return 1
    return 0


def _dummy_shadow(tier, all_ids):
    """固定种子生成训练假人影子：节奏 8~15 秒/题，按档位定正确数。"""
    profile = next((d for d in DUMMY_PROFILES if d['tier'] == tier), None)
    if not profile or len(all_ids) < BATTLE_QUESTIONS_PER_STAGE:
        return None
    rng = random.Random(1000 + tier)
    qids = rng.sample(all_ids, BATTLE_QUESTIONS_PER_STAGE)
    correct_marks = [True] * profile['correct'] + [False] * (BATTLE_QUESTIONS_PER_STAGE - profile['correct'])
    rng.shuffle(correct_marks)
    events, t = [], 0
    for i, ok in enumerate(correct_marks):
        t += rng.randint(8000, 15000)
        events.append({'i': i, 't_ms': t, 'correct': ok})
    return {
        'question_ids': qids, 'events': events,
        'correct_count': profile['correct'], 'total_time_ms': t,
        'name': profile['name'],
    }


def _build_shadow(conn, quiz_row):
    """由已判分的战斗会话生成幽灵回放事件轴（服务器时间，可防客户端篡改）。

    返回 (events, correct_count, total_time_ms)；事件按题序排列，
    t_ms 为相对开考的毫秒数，缺失时间戳按 8 秒间隔顺次兜底。"""
    question_ids = json.loads(quiz_row['question_ids'])
    order = {qid: i for i, qid in enumerate(question_ids)}
    start = datetime.strptime(quiz_row['started_at'], '%Y-%m-%d %H:%M:%S')
    rows = conn.execute(
        'SELECT question_id, is_correct, answered_at FROM answers WHERE session_id = ? ORDER BY id',
        (quiz_row['id'],)).fetchall()
    answered = {r['question_id']: r for r in rows}

    events, missing = [], []
    for qid in question_ids:
        r = answered.get(qid)
        if not r or not r['answered_at']:
            if r:
                missing.append(qid)
            continue
        try:
            t = datetime.strptime(r['answered_at'], '%Y-%m-%d %H:%M:%S')
            t_ms = int((t - start).total_seconds() * 1000)
        except (ValueError, TypeError):
            missing.append(qid)
            continue
        events.append({'i': order[qid], 't_ms': max(t_ms, 1000), 'correct': bool(r['is_correct'])})

    if missing:
        base = max((e['t_ms'] for e in events), default=0)
        for k, qid in enumerate(missing):
            events.append({'i': order[qid], 't_ms': base + 8000 * (k + 1),
                           'correct': bool(answered[qid]['is_correct'])})

    events.sort(key=lambda e: e['i'])
    total_time = max((e['t_ms'] for e in events), default=0)
    correct_count = sum(1 for e in events if e['correct'])
    return events, correct_count, total_time


def _star_bonus(conn, student_id):
    """PVE 星级加成：三星关数按占比折算平时成绩加分（全部三星 +5 分封顶）。"""
    total = conn.execute('SELECT COUNT(DISTINCT category) FROM questions').fetchone()[0]
    star3 = conn.execute(
        'SELECT COUNT(*) FROM battle_progress WHERE student_id = ? AND stars = 3',
        (student_id,)).fetchone()[0]
    bonus = round(min(star3 / total, 1.0) * 5, 1) if total else 0
    return {'star3': star3, 'stages': total, 'bonus': bonus}


def _apply_ladder(conn, challenger_id, defender_id, result):
    """按胜负增量更新双方天梯（胜+5/平+2/负+1），镜像记胜负平场次。"""
    flip = {'win': 'loss', 'loss': 'win', 'draw': 'draw'}
    for sid, r in ((challenger_id, result), (defender_id, flip[result])):
        conn.execute('INSERT OR IGNORE INTO pvp_ladder (student_id) VALUES (?)', (sid,))
        conn.execute(
            'UPDATE pvp_ladder SET points = points + ?, wins = wins + ?, '
            'losses = losses + ?, draws = draws + ? WHERE student_id = ?',
            (LADDER_POINTS[r], r == 'win', r == 'loss', r == 'draw', sid))
    return LADDER_POINTS[result]


def _finalize_battle(conn, quiz_row, score, total):
    """战斗模式结算钩子：闯关星级落库 / 录影子 / PVP 判胜负与天梯。

    幂等：battle_results 主键闸、pvp_matches 仅 pending 态可结算。
    返回结算信息并入交卷响应（非战斗模式返回 None）。"""
    mode = quiz_row['mode'] or ''
    if mode not in BATTLE_MODES:
        return None
    accuracy = round(score / total * 100, 1) if total else 0

    if mode == 'battle':
        label = quiz_row['label'] or ''
        category = label[len(BATTLE_LABEL_PREFIX):] if label.startswith(BATTLE_LABEL_PREFIX) else label
        stars = _stars_for(score, total)
        cur = conn.execute(
            'INSERT OR IGNORE INTO battle_results '
            '(session_id, student_id, category, score, total, stars, accuracy) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (quiz_row['id'], quiz_row['student_id'], category, score, total, stars, accuracy))
        if cur.rowcount == 0:
            return None
        prev = conn.execute(
            'SELECT best_accuracy FROM battle_progress WHERE student_id = ? AND category = ?',
            (quiz_row['student_id'], category)).fetchone()
        conn.execute(
            'INSERT INTO battle_progress (student_id, category, stars, best_accuracy, times, updated_at) '
            'VALUES (?, ?, ?, ?, 1, ?) '
            'ON CONFLICT(student_id, category) DO UPDATE SET '
            'stars = MAX(stars, excluded.stars), best_accuracy = MAX(best_accuracy, excluded.best_accuracy), '
            'times = times + 1, updated_at = excluded.updated_at',
            (quiz_row['student_id'], category, stars, accuracy,
             utcnow().strftime('%Y-%m-%d %H:%M:%S')))
        return {'type': 'battle', 'stars': stars, 'accuracy': accuracy,
                'new_best': not prev or accuracy > prev['best_accuracy']}

    # PVP：录影子或对局结算
    match = conn.execute('SELECT * FROM pvp_matches WHERE session_id = ?',
                         (quiz_row['id'],)).fetchone()

    if match is None:
        # 录影子：单人排位赛交卷时生成/覆盖影子
        events, correct_count, total_time = _build_shadow(conn, quiz_row)
        label = quiz_row['label'] or ''
        category = label.split('·', 1)[1].strip() if '·' in label else ''
        conn.execute(
            'INSERT INTO pvp_shadows (student_id, question_ids, events, correct_count, '
            'total_time_ms, category, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(student_id) DO UPDATE SET question_ids = excluded.question_ids, '
            'events = excluded.events, correct_count = excluded.correct_count, '
            'total_time_ms = excluded.total_time_ms, category = excluded.category, '
            'updated_at = excluded.updated_at',
            (quiz_row['student_id'], quiz_row['question_ids'], json.dumps(events),
             correct_count, total_time, category, utcnow().strftime('%Y-%m-%d %H:%M:%S')))
        conn.execute(
            'INSERT OR IGNORE INTO pvp_matches '
            '(session_id, challenger_id, defender_id, challenger_correct, result) '
            'VALUES (?, ?, NULL, ?, ?)',
            (quiz_row['id'], quiz_row['student_id'], score, 'record'))
        return {'type': 'record', 'correct': correct_count, 'total_time_ms': total_time}

    if match['result'] != 'pending':
        return None

    defender_id = match['defender_id']
    defender_correct = match['defender_correct'] or 0
    if score > defender_correct:
        result = 'win'
    elif score < defender_correct:
        result = 'loss'
    else:
        # 同分比总用时（挑战者最后一个作答时刻），用时相同判平
        events, _, my_time = _build_shadow(conn, quiz_row)
        result = 'draw'
        if my_time < (match['defender_time_ms'] or 0):
            result = 'win'
        elif my_time > (match['defender_time_ms'] or 0):
            result = 'loss'

    cur = conn.execute(
        'UPDATE pvp_matches SET challenger_correct = ?, result = ? '
        'WHERE session_id = ? AND result = ?',
        (score, result, quiz_row['id'], 'pending'))
    if cur.rowcount != 1:
        return None

    points_delta = 0
    if defender_id and defender_id > 0:
        points_delta = _apply_ladder(conn, quiz_row['student_id'], defender_id, result)
    return {'type': 'challenge', 'result': result, 'score': score,
            'opponent_score': defender_correct, 'points_delta': points_delta,
            'opponent_name': match['defender_name'] or '',
            'is_dummy': bool(defender_id and defender_id < 0)}


@app.route('/api/arena')
def arena_info():
    """竞技场首页数据：闯关地图（含解锁状态）、可挑战影子、训练假人、天梯榜。"""
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        if not get_battle_enabled(conn):
            return jsonify({'success': False, 'message': '战斗竞技场暂时关闭', 'disabled': True})

        me = conn.execute('SELECT class_name FROM students WHERE id = ?', (student_id,)).fetchone()
        my_class = me['class_name'] if me else ''

        stages = []
        progress = {r['category']: r for r in conn.execute(
            'SELECT category, stars, best_accuracy, times FROM battle_progress WHERE student_id = ?',
            (student_id,)).fetchall()}
        prev_passed = True
        for no, category, count in _battle_stage_order(conn):
            p = progress.get(category)
            stars = p['stars'] if p else 0
            stages.append({
                'no': no, 'category': category, 'count': count, 'stars': stars,
                'best_accuracy': round(p['best_accuracy'] or 0, 1) if p else 0,
                'times': p['times'] if p else 0, 'unlocked': prev_passed,
            })
            prev_passed = stars >= 1

        shadows = conn.execute(
            'SELECT sh.student_id, sh.correct_count, sh.total_time_ms, sh.category, s.name '
            'FROM pvp_shadows sh JOIN students s ON s.id = sh.student_id '
            'WHERE sh.student_id != ? AND s.class_name = ? '
            'ORDER BY sh.correct_count DESC, sh.total_time_ms ASC',
            (student_id, my_class)).fetchall()
        opponents = [{'student_id': r['student_id'], 'name': r['name'],
                      'correct_count': r['correct_count'], 'total_time_ms': r['total_time_ms'],
                      'category': r['category'] or '综合'} for r in shadows]

        ladder_rows = conn.execute(
            'SELECT l.student_id, l.points, l.wins, l.losses, l.draws, s.name '
            'FROM pvp_ladder l JOIN students s ON s.id = l.student_id '
            'WHERE s.class_name = ? ORDER BY l.points DESC, l.wins DESC',
            (my_class,)).fetchall()
        ladder, my_rank, my_row = [], None, None
        for idx, r in enumerate(ladder_rows, 1):
            if r['student_id'] == student_id:
                my_rank, my_row = idx, r
            if len(ladder) < 10:
                ladder.append({'rank': idx, 'name': r['name'], 'points': r['points'],
                               'wins': r['wins'], 'losses': r['losses'], 'draws': r['draws'],
                               'is_me': r['student_id'] == student_id})

        star = _star_bonus(conn, student_id)
        my_shadow = conn.execute(
            'SELECT correct_count, total_time_ms, updated_at FROM pvp_shadows WHERE student_id = ?',
            (student_id,)).fetchone()

    return jsonify({
        'success': True,
        'stages': stages,
        'opponents': opponents,
        'dummies': [{'tier': d['tier'], 'name': d['name'], 'correct': d['correct']}
                    for d in DUMMY_PROFILES],
        'ladder': ladder,
        'my_ladder': {'rank': my_rank,
                      'points': my_row['points'] if my_row else 0,
                      'wins': my_row['wins'] if my_row else 0,
                      'losses': my_row['losses'] if my_row else 0,
                      'draws': my_row['draws'] if my_row else 0},
        'my_shadow': ({'correct_count': my_shadow['correct_count'],
                       'total_time_ms': my_shadow['total_time_ms']}
                      if my_shadow else None),
        'star_bonus': star,
    })


@app.route('/start_battle', methods=['POST'])
def start_battle():
    """战斗竞技场开局：闯关 / 挑战同学影子 / 训练假人 / 排位赛（录影子）。"""
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    data = request.get_json() or {}
    btype = data.get('type')

    with get_db() as conn:
        if not get_battle_enabled(conn):
            return jsonify({'success': False, 'message': '战斗竞技场暂时关闭，先去做做练习吧'})

        existing = conn.execute(
            'SELECT * FROM quiz_sessions WHERE student_id = ? AND status = ?',
            (student_id, 'in_progress')).fetchone()
        if existing and not _expire_stale_session(conn, existing):
            session['quiz_session_id'] = existing['id']
            return jsonify({'success': True, 'message': '继续上次的答题', 'session_id': existing['id'],
                            'mode': existing['mode'] or 'exam', 'label': existing['label'] or ''})

        now = utcnow()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        deadline_str = (now + timedelta(minutes=BATTLE_DEADLINE_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')

        if btype == 'stage':
            category = (data.get('category') or '').strip()
            order = _battle_stage_order(conn)
            idx = next((i for i, (_, c, _) in enumerate(order) if c == category), None)
            if idx is None:
                return jsonify({'success': False, 'message': '关卡不存在'})
            # 顺序解锁：前一关至少 1 星才能挑战本关
            if idx > 0:
                prev = conn.execute(
                    'SELECT stars FROM battle_progress WHERE student_id = ? AND category = ?',
                    (student_id, order[idx - 1][1])).fetchone()
                if not prev or prev['stars'] < 1:
                    return jsonify({'success': False,
                                    'message': f'先通关「{order[idx - 1][1]}」才能解锁本关'})
            pool = [r['id'] for r in conn.execute(
                "SELECT id FROM questions WHERE category = ? AND q_type IN ('mc','tf') ORDER BY id",
                (category,)).fetchall()]
            if len(pool) < BATTLE_QUESTIONS_PER_STAGE:
                return jsonify({'success': False, 'message': '该关卡题量不足，请联系老师'})
            qids = random.sample(pool, BATTLE_QUESTIONS_PER_STAGE)
            cursor = conn.execute(
                'INSERT INTO quiz_sessions (student_id, question_ids, total, started_at, deadline, status, mode, label) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (student_id, json.dumps(qids), len(qids), now_str, deadline_str,
                 'in_progress', 'battle', BATTLE_LABEL_PREFIX + category))
            conn.commit()
            session['quiz_session_id'] = cursor.lastrowid
            return jsonify({'success': True, 'message': f'「{category}」之战开始！',
                            'session_id': cursor.lastrowid})

        if btype == 'dummy':
            try:
                tier = int(data.get('tier', 1))
            except (TypeError, ValueError):
                tier = 1
            profile = next((d for d in DUMMY_PROFILES if d['tier'] == tier), None)
            if not profile:
                return jsonify({'success': False, 'message': '训练假人不存在'})
            all_ids = [r['id'] for r in conn.execute(
                "SELECT id FROM questions WHERE q_type IN ('mc','tf') ORDER BY id").fetchall()]
            shadow = _dummy_shadow(tier, all_ids)
            if not shadow:
                return jsonify({'success': False, 'message': '题库题目不足'})
            cursor = conn.execute(
                'INSERT INTO quiz_sessions (student_id, question_ids, total, started_at, deadline, status, mode, label) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (student_id, json.dumps(shadow['question_ids']), len(shadow['question_ids']),
                 now_str, deadline_str, 'in_progress', 'pvp', '竞技场 · 训练假人'))
            sid = cursor.lastrowid
            conn.execute(
                'INSERT INTO pvp_matches (session_id, challenger_id, defender_id, defender_name, '
                'defender_correct, defender_time_ms, ghost_events, result) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (sid, student_id, -tier, profile['name'], shadow['correct_count'],
                 shadow['total_time_ms'], json.dumps(shadow['events']), 'pending'))
            conn.commit()
            session['quiz_session_id'] = sid
            return jsonify({'success': True, 'message': f'对战「{profile["name"]}」开始！', 'session_id': sid})

        if btype == 'challenge':
            try:
                defender_id = int(data.get('defender_id', 0))
            except (TypeError, ValueError):
                defender_id = 0
            shadow = conn.execute('SELECT * FROM pvp_shadows WHERE student_id = ?',
                                  (defender_id,)).fetchone()
            if not shadow or defender_id == student_id:
                return jsonify({'success': False, 'message': '该同学还没有留下影子'})
            defender = conn.execute('SELECT name FROM students WHERE id = ?',
                                    (defender_id,)).fetchone()
            if not defender:
                return jsonify({'success': False, 'message': '对手不存在'})
            qids = json.loads(shadow['question_ids'])
            category = shadow['category'] or '综合'
            cursor = conn.execute(
                'INSERT INTO quiz_sessions (student_id, question_ids, total, started_at, deadline, status, mode, label) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (student_id, json.dumps(qids), len(qids), now_str, deadline_str,
                 'in_progress', 'pvp', '竞技场 · ' + category))
            sid = cursor.lastrowid
            conn.execute(
                'INSERT INTO pvp_matches (session_id, challenger_id, defender_id, defender_name, '
                'defender_correct, defender_time_ms, ghost_events, result) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (sid, student_id, defender_id, defender['name'], shadow['correct_count'],
                 shadow['total_time_ms'], shadow['events'], 'pending'))
            conn.commit()
            session['quiz_session_id'] = sid
            return jsonify({'success': True, 'message': f'对战 {defender["name"]} 的影子！', 'session_id': sid})

        if btype == 'record':
            all_ids = [r['id'] for r in conn.execute(
                "SELECT id FROM questions WHERE q_type IN ('mc','tf') ORDER BY id").fetchall()]
            if len(all_ids) < BATTLE_QUESTIONS_PER_STAGE:
                return jsonify({'success': False, 'message': '题库题目不足'})
            qids = random.sample(all_ids, BATTLE_QUESTIONS_PER_STAGE)
            cursor = conn.execute(
                'INSERT INTO quiz_sessions (student_id, question_ids, total, started_at, deadline, status, mode, label) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (student_id, json.dumps(qids), len(qids), now_str, deadline_str,
                 'in_progress', 'pvp', '竞技场 · 排位赛'))
            conn.commit()
            session['quiz_session_id'] = cursor.lastrowid
            return jsonify({'success': True, 'message': '排位赛开始，这局表现会留成你的影子！',
                            'session_id': cursor.lastrowid})

    return jsonify({'success': False, 'message': '未知的战斗类型'})


@app.route('/start_quiz', methods=['POST'])
def start_quiz():
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        existing = conn.execute(
            'SELECT * FROM quiz_sessions WHERE student_id = ? AND status = ?',
            (student_id, 'in_progress')
        ).fetchone()
        if existing and not _expire_stale_session(conn, existing):
            if (existing['mode'] or 'exam') in BATTLE_MODES:
                return jsonify({'success': False,
                                'message': '你有一场对战正在进行，请到「战斗竞技场」完成或认输后再开考'})
            session['quiz_session_id'] = existing['id']
            return jsonify({'success': True, 'message': '继续上次未完成的答题',
                            'session_id': existing['id']})

        # 考试开放时段校验（不影响已在窗口内开考、尚未交卷的续答）
        state, hint = exam_window_state(conn)
        if state == 'before':
            return jsonify({'success': False, 'message': f'{hint}，现在可以先做分类练习'})
        if state == 'after':
            return jsonify({'success': False, 'message': f'{hint}，还可以继续做分类练习'})

        # 考试次数上限校验
        max_attempts = get_exam_max_attempts(conn)
        if max_attempts > 0:
            done = conn.execute(
                "SELECT COUNT(*) FROM quiz_sessions WHERE student_id = ? "
                "AND status IN ('completed', 'timeout') AND (mode IS NULL OR mode = 'exam')",
                (student_id,)).fetchone()[0]
            if done >= max_attempts:
                return jsonify({'success': False,
                                'message': f'考试次数已达上限（{max_attempts} 次）'})

        all_ids = [r['id'] for r in conn.execute('SELECT id FROM questions ORDER BY id').fetchall()]
        if len(all_ids) < QUIZ_QUESTION_COUNT:
            return jsonify({'success': False, 'message': '题库题目不足，请联系老师'})

        selected_ids = random.sample(all_ids, QUIZ_QUESTION_COUNT)
        now = utcnow()
        deadline = now + timedelta(minutes=QUIZ_DURATION_MINUTES)
        cursor = conn.execute(
            'INSERT INTO quiz_sessions (student_id, question_ids, total, started_at, deadline, status, mode, label) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (student_id, json.dumps(selected_ids), QUIZ_QUESTION_COUNT,
             now.strftime('%Y-%m-%d %H:%M:%S'), deadline.strftime('%Y-%m-%d %H:%M:%S'),
             'in_progress', 'exam', '随机抽题'))
        conn.commit()
        session_id = cursor.lastrowid

    session['quiz_session_id'] = session_id
    return jsonify({'success': True, 'message': '测验已开始', 'session_id': session_id})


@app.route('/start_practice', methods=['POST'])
def start_practice():
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    data = request.get_json() or {}
    source = data.get('source', 'category')
    count = data.get('count', 20)
    try:
        count = max(5, min(int(count), PRACTICE_MAX_COUNT))
    except (TypeError, ValueError):
        count = 20

    with get_db() as conn:
        existing = conn.execute(
            'SELECT * FROM quiz_sessions WHERE student_id = ? AND status = ?',
            (student_id, 'in_progress')
        ).fetchone()
        if existing and not _expire_stale_session(conn, existing):
            if (existing['mode'] or 'exam') in BATTLE_MODES:
                return jsonify({'success': False,
                                'message': '你有一场对战正在进行，请到「战斗竞技场」完成或认输后再开始练习'})
            session['quiz_session_id'] = existing['id']
            return jsonify({'success': True, 'message': '继续上次未完成的答题',
                            'session_id': existing['id'],
                            'mode': existing['mode'] or 'exam',
                            'label': existing['label'] or ''})

        if source == 'wrong':
            pool = get_wrong_question_ids(conn, student_id)
            label = '错题重练'
            if not pool:
                return jsonify({'success': False, 'message': '暂时没有历史错题，先去做一套题吧'})
        else:
            category = (data.get('category') or '').strip()
            pool = [r['id'] for r in conn.execute(
                'SELECT id FROM questions WHERE category = ? ORDER BY id', (category,)).fetchall()]
            label = category or '分类练习'
            if not pool:
                return jsonify({'success': False, 'message': '该分类下暂无题目'})

        selected_ids = random.sample(pool, min(count, len(pool)))
        now = utcnow()
        deadline = now + timedelta(hours=PRACTICE_DEADLINE_HOURS)
        cursor = conn.execute(
            'INSERT INTO quiz_sessions (student_id, question_ids, total, started_at, deadline, status, mode, label) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (student_id, json.dumps(selected_ids), len(selected_ids),
             now.strftime('%Y-%m-%d %H:%M:%S'), deadline.strftime('%Y-%m-%d %H:%M:%S'),
             'in_progress', 'practice', label))
        conn.commit()
        session_id = cursor.lastrowid

    session['quiz_session_id'] = session_id
    return jsonify({'success': True, 'message': '练习已开始', 'session_id': session_id,
                    'mode': 'practice', 'label': label})


@app.route('/get_questions')
def get_questions():
    student_id = session.get('student_id')
    session_id = session.get('quiz_session_id')
    if not student_id or not session_id:
        return jsonify({'success': False, 'message': '请先开始答题'})

    with get_db() as conn:
        quiz = conn.execute('SELECT * FROM quiz_sessions WHERE id = ? AND student_id = ?',
                            (session_id, student_id)).fetchone()
        if not quiz:
            return jsonify({'success': False, 'message': '答题会话不存在'})

        now = utcnow()
        deadline = datetime.strptime(quiz['deadline'], '%Y-%m-%d %H:%M:%S')

        if now >= deadline:
            _finalize_timeout(conn, quiz)
            return jsonify({'success': False, 'message': '本次答题已超时，已自动交卷', 'timeout': True})

        if quiz['status'] != 'in_progress':
            return jsonify({'success': False, 'message': '本次答题已结束'})

        question_ids = json.loads(quiz['question_ids'])
        placeholders = ','.join('?' * len(question_ids))
        questions = conn.execute(
            f'SELECT id, category, q_type, question, options FROM questions WHERE id IN ({placeholders})',
            question_ids
        ).fetchall()

        q_map = {q['id']: dict(q) for q in questions}
        ordered_questions = []
        for qid in question_ids:
            if qid in q_map:
                q = q_map[qid]
                if q['options']:
                    q['options'] = json.loads(q['options'])
                ordered_questions.append(q)

        saved_answers = conn.execute(
            'SELECT question_id, student_answer FROM answers WHERE session_id = ?',
            (session_id,)
        ).fetchall()
        answer_map = {a['question_id']: a['student_answer'] for a in saved_answers}

        # 恢复信息：练习/闯关带回正确答案与解析供前端还原即时反馈；
        # PVP 只回已作答题的对错（绝不泄露答案文本，防止抄对手同套题的答案）
        mode = quiz['mode'] or 'exam'
        feedback_map = None
        if mode in ('practice', 'battle', 'pvp'):
            fb_rows = conn.execute(
                f'SELECT id, answer, explanation, q_type FROM questions WHERE id IN ({placeholders})',
                question_ids
            ).fetchall()
            fb_map = {r['id']: r for r in fb_rows}
            if mode == 'pvp':
                feedback_map = {}
                for qid, ans in answer_map.items():
                    q = fb_map.get(qid)
                    if q and ans:
                        feedback_map[qid] = {'correct': answers_match(q['q_type'], ans, q['answer'])}
            else:
                feedback_map = {r['id']: {'answer': r['answer'], 'explanation': r['explanation'] or ''}
                                for r in fb_rows}

        # 战斗元信息：闯关类型 / 录影子 / 挑战（含幽灵事件轴与已耗时，供刷新恢复）
        battle_meta = None
        if mode == 'battle':
            battle_meta = {'type': 'battle'}
        elif mode == 'pvp':
            m = conn.execute('SELECT * FROM pvp_matches WHERE session_id = ?',
                             (session_id,)).fetchone()
            elapsed_ms = int((utcnow() - datetime.strptime(
                quiz['started_at'], '%Y-%m-%d %H:%M:%S')).total_seconds() * 1000)
            if m and m['defender_id'] is not None:
                battle_meta = {'type': 'challenge', 'defender_name': m['defender_name'] or '',
                               'is_dummy': m['defender_id'] < 0,
                               'elapsed_ms': max(elapsed_ms, 0),
                               'ghost': {'events': json.loads(m['ghost_events'] or '[]'),
                                         'total_time_ms': m['defender_time_ms'] or 0}}
            else:
                battle_meta = {'type': 'record', 'elapsed_ms': max(elapsed_ms, 0)}

    return jsonify({
        'success': True,
        'questions': ordered_questions,
        'deadline': quiz['deadline'],
        'server_time': utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'saved_answers': answer_map,
        'mode': mode,
        'label': quiz['label'] or '',
        'feedback': feedback_map,
        'battle_meta': battle_meta
    })


@app.route('/save_answer', methods=['POST'])
def save_answer():
    student_id = session.get('student_id')
    session_id = session.get('quiz_session_id')
    if not student_id or not session_id:
        return jsonify({'success': False})

    data = request.get_json()
    question_id = data.get('question_id')
    answer = data.get('answer', '')

    with get_db() as conn:
        quiz = conn.execute('SELECT * FROM quiz_sessions WHERE id = ? AND student_id = ?',
                            (session_id, student_id)).fetchone()
        if not quiz or quiz['status'] != 'in_progress':
            return jsonify({'success': False, 'message': '答题已结束或不存在'})

        deadline = datetime.strptime(quiz['deadline'], '%Y-%m-%d %H:%M:%S')
        if utcnow() >= deadline:
            _finalize_timeout(conn, quiz)
            return jsonify({'success': False, 'message': '答题已超时', 'timeout': True})

        question_ids = json.loads(quiz['question_ids'])
        if question_id not in question_ids:
            return jsonify({'success': False, 'message': '题目不属于当前答题'})

        qrow = conn.execute('SELECT q_type FROM questions WHERE id = ?',
                            (question_id,)).fetchone()
        q_type = qrow['q_type'] if qrow else 'mc'
        if q_type == 'multi':
            answer = ''.join(sorted(set(answer)))   # 规范化：去重 + 排序
        if not _valid_answer(q_type, answer):
            return jsonify({'success': False, 'message': '答案格式错误'})

        existing = conn.execute(
            'SELECT id FROM answers WHERE session_id = ? AND question_id = ?',
            (session_id, question_id)
        ).fetchone()

        if existing:
            conn.execute('UPDATE answers SET student_answer = ?, answered_at = ? WHERE id = ?',
                         (answer, utcnow().strftime('%Y-%m-%d %H:%M:%S'), existing['id']))
        else:
            conn.execute(
                'INSERT INTO answers (session_id, question_id, student_answer, answered_at) '
                'VALUES (?, ?, ?, ?)',
                (session_id, question_id, answer, utcnow().strftime('%Y-%m-%d %H:%M:%S'))
            )
        conn.commit()

        # 练习/闯关：立即返回判分与解析；PVP 只回对错（绝不回传答案，防抄对手同套题）；
        # 考试模式绝不回传答案
        mode = quiz['mode'] or 'exam'
        if mode in ('practice', 'battle', 'pvp') and answer:
            q = conn.execute('SELECT answer, explanation, q_type FROM questions WHERE id = ?',
                             (question_id,)).fetchone()
            if q:
                if mode == 'pvp':
                    return jsonify({'success': True, 'battle_feedback': {
                        'correct': answers_match(q['q_type'], answer, q['answer'])
                    }})
                return jsonify({'success': True, 'practice_feedback': {
                    'correct': answers_match(q['q_type'], answer, q['answer']),
                    'answer': q['answer'],
                    'explanation': q['explanation'] or ''
                }})

    return jsonify({'success': True})


@app.route('/report_switch', methods=['POST'])
def report_switch():
    """考试切屏上报：前端检测到页面隐藏/失焦时静默计数（仅考试模式）。"""
    student_id = session.get('student_id')
    session_id = session.get('quiz_session_id')
    if not student_id or not session_id:
        return jsonify({'success': False})

    with get_db() as conn:
        quiz = conn.execute('SELECT id, status, mode FROM quiz_sessions WHERE id = ? AND student_id = ?',
                            (session_id, student_id)).fetchone()
        if not quiz or quiz['status'] != 'in_progress' or (quiz['mode'] or 'exam') != 'exam':
            return jsonify({'success': False})
        conn.execute('UPDATE quiz_sessions SET switch_count = COALESCE(switch_count, 0) + 1 WHERE id = ?',
                     (session_id,))
        conn.commit()
    return jsonify({'success': True})


def _session_details(conn, session_id):
    details = conn.execute(
        'SELECT a.question_id, a.student_answer, a.is_correct, q.category, q.question, q.answer, '
        'q.explanation, q.q_type, q.options '
        'FROM answers a JOIN questions q ON a.question_id = q.id WHERE a.session_id = ?',
        (session_id,)
    ).fetchall()
    result = []
    for d in details:
        item = dict(d)
        if item['options']:
            item['options'] = json.loads(item['options'])
        result.append(item)
    return result


@app.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    student_id = session.get('student_id')
    session_id = session.get('quiz_session_id')
    if not student_id or not session_id:
        return jsonify({'success': False, 'message': '请先开始答题'})

    with get_db() as conn:
        quiz = conn.execute('SELECT * FROM quiz_sessions WHERE id = ? AND student_id = ?',
                            (session_id, student_id)).fetchone()
        if not quiz or quiz['status'] != 'in_progress':
            return jsonify({'success': False, 'message': '答题已结束或不存在'})

        deadline = datetime.strptime(quiz['deadline'], '%Y-%m-%d %H:%M:%S')
        if utcnow() >= deadline:
            _finalize_timeout(conn, quiz)
            session.pop('quiz_session_id', None)
            return jsonify({'success': False, 'message': '答题已超时，已自动交卷', 'timeout': True})

        answers = conn.execute(
            'SELECT a.id, a.question_id, a.student_answer, q.answer, q.q_type FROM answers a '
            'JOIN questions q ON a.question_id = q.id WHERE a.session_id = ?',
            (session_id,)
        ).fetchall()

        score = 0
        for ans in answers:
            is_correct = 1 if answers_match(ans['q_type'], ans['student_answer'], ans['answer']) else 0
            if is_correct:
                score += 1
            conn.execute('UPDATE answers SET is_correct = ? WHERE id = ?', (is_correct, ans['id']))

        question_ids = json.loads(quiz['question_ids'])
        answered_ids = {ans['question_id'] for ans in answers}
        for qid in question_ids:
            if qid not in answered_ids:
                conn.execute(
                    'INSERT INTO answers (session_id, question_id, student_answer, is_correct) VALUES (?, ?, ?, ?)',
                    (session_id, qid, '', 0)
                )

        total = quiz['total']
        now = utcnow().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            'UPDATE quiz_sessions SET score = ?, submitted_at = ?, status = ? WHERE id = ?',
            (score, now, 'completed', session_id)
        )
        battle_summary = _finalize_battle(conn, quiz, score, total)
        conn.commit()

        # 交卷后发放经验（考试与练习都计），并计算升级情况
        xp_before = _total_xp(conn, student_id)
        xp_gained = _grant_session_xp(conn, student_id, session_id)
        conn.commit()
        xp_after = _total_xp(conn, student_id)
        qualify_level = get_qualify_level(conn)
        lv_before = level_from_xp(xp_before, qualify_level)
        lv_after = level_from_xp(xp_after, qualify_level)
        xp_summary = {
            'gained': xp_gained,
            'total': xp_after,
            'level_before': lv_before['level'],
            'level': lv_after['level'],
            'level_name': lv_after['name'],
            'level_up': lv_after['level'] > lv_before['level'],
            'qualified': lv_after['qualified'],
            'just_qualified': lv_after['qualified'] and not lv_before['qualified'],
            'xp_into_level': lv_after['xp_into_level'],
            'xp_next_level': lv_after['xp_next_level'],
            'regular_score_before': lv_before['regular_score'],
            'regular_score': lv_after['regular_score'],
        }

        result_details = _session_details(conn, session_id)

    session.pop('quiz_session_id', None)

    return jsonify({
        'success': True,
        'score': score,
        'total': total,
        'percentage': round(score / total * 100, 1) if total > 0 else 0,
        'mode': quiz['mode'] or 'exam',
        'label': quiz['label'] or '',
        'details': result_details,
        'xp': xp_summary,
        'battle': battle_summary
    })


@app.route('/quiz_result/<int:session_id>')
def quiz_result(session_id):
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        quiz = conn.execute('SELECT * FROM quiz_sessions WHERE id = ? AND student_id = ?',
                            (session_id, student_id)).fetchone()
        if not quiz:
            return jsonify({'success': False, 'message': '记录不存在'})
        if quiz['status'] not in ('completed', 'timeout'):
            return jsonify({'success': False, 'message': '本次答题尚未提交'})
        details = _session_details(conn, session_id)

    return jsonify({
        'success': True,
        'score': quiz['score'],
        'total': quiz['total'],
        'percentage': round(quiz['score'] / quiz['total'] * 100, 1) if quiz['total'] else 0,
        'mode': quiz['mode'] or 'exam',
        'label': quiz['label'] or '',
        'submitted_at': to_beijing(quiz['submitted_at']),
        'details': details
    })


@app.route('/my_scores')
def my_scores():
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '请先登录'})

    with get_db() as conn:
        scores = conn.execute(
            'SELECT id, score, total, started_at, submitted_at, status, mode, label FROM quiz_sessions '
            'WHERE student_id = ? AND status IN (?, ?) ORDER BY submitted_at DESC',
            (student_id, 'completed', 'timeout')
        ).fetchall()

    result = []
    for s in scores:
        item = dict(s)
        item['started_at'] = to_beijing(item['started_at'])
        item['submitted_at'] = to_beijing(item['submitted_at'])
        result.append(item)

    return jsonify({'success': True, 'scores': result})


@app.route('/logout')
def student_logout():
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('class_name', None)
    session.pop('quiz_session_id', None)
    return redirect(url_for('index'))


# ==================== 管理员路由 ====================

@app.route('/admin')
@admin_required
def admin_panel():
    return render_template('admin.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('admin_login.html')

    ip = request.remote_addr or 'unknown'
    if _check_login_throttle(ip):
        return jsonify({'success': False, 'message': '尝试次数过多，请稍后再试'}), 429

    data = request.get_json() if request.is_json else request.form
    password = data.get('password', '')

    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
    ok = bool(row) and check_password_hash(row['value'] or '', password)

    if ok:
        session['is_admin'] = True
        return jsonify({'success': True}) if request.is_json else redirect(url_for('admin_panel'))
    _record_failed_login(ip)
    return (jsonify({'success': False, 'message': '密码错误'}) if request.is_json
            else render_template('admin_login.html', error='密码错误'))


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin/change_password', methods=['POST'])
def admin_change_password():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': '请先登录'})
    data = request.get_json() or {}
    old_pwd = data.get('old_password', '')
    new_pwd = data.get('new_password', '')
    if len(new_pwd) < 6:
        return jsonify({'success': False, 'message': '新密码至少 6 位'})

    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
        if not row or not check_password_hash(row['value'] or '', old_pwd):
            return jsonify({'success': False, 'message': '原密码错误'})
        conn.execute("UPDATE settings SET value = ? WHERE key = 'admin_password_hash'",
                     (generate_password_hash(new_pwd),))
        conn.commit()
    return jsonify({'success': True, 'message': '密码已更新'})


@app.route('/admin/settings', methods=['GET'])
@admin_required
def admin_get_settings():
    with get_db() as conn:
        qualify_level = get_qualify_level(conn)
        roster_mode = get_roster_mode(conn)
        battle_enabled = get_battle_enabled(conn)
        window_start, window_end = get_exam_window(conn)
        max_attempts = get_exam_max_attempts(conn)
    return jsonify({
        'success': True,
        'qualify_level': qualify_level,
        'default_qualify_level': QUALIFY_LEVEL,
        'max_level': MAX_LEVEL,
        'qualify_level_name': LEVEL_NAMES[qualify_level - 1],
        'max_level_name': LEVEL_NAMES[-1],
        'qualify_xp': total_xp_for_level(qualify_level),
        'roster_mode': roster_mode,
        'battle_enabled': battle_enabled,
        'exam_window_start': window_start,
        'exam_window_end': window_end,
        'exam_max_attempts': max_attempts,
        'xp_rules': {
            'base': XP_BASE,
            'daily_full': XP_DAILY_FULL,
            'daily_half': XP_DAILY_HALF,
            'repeat_factors': XP_REPEAT_FACTORS,
        }
    })


def _valid_window_value(v):
    """时段值校验：空串或 'YYYY-MM-DD HH:MM'。"""
    v = (v or '').strip()
    if not v:
        return ''
    try:
        datetime.strptime(v, '%Y-%m-%d %H:%M')
        return v
    except ValueError:
        return None


@app.route('/admin/settings', methods=['POST'])
@admin_required
def admin_update_settings():
    data = request.get_json() or {}

    # 花名册模式开关（可单独提交）
    if 'roster_mode' in data and 'qualify_level' not in data and 'exam_window_start' not in data:
        enabled = str(data.get('roster_mode')).lower() in ('1', 'true', 'on')
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('roster_mode', ?)",
                         ('1' if enabled else '0',))
            conn.commit()
        return jsonify({'success': True,
                        'message': '花名册模式已开启，学生只能用名单内账号登录' if enabled
                        else '花名册模式已关闭，学生可自由注册登录'})

    # 战斗竞技场开关（可单独提交）
    if 'battle_enabled' in data and 'qualify_level' not in data and 'exam_window_start' not in data:
        enabled = str(data.get('battle_enabled')).lower() in ('1', 'true', 'on')
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('battle_enabled', ?)",
                         ('1' if enabled else '0',))
            conn.commit()
        return jsonify({'success': True,
                        'message': '战斗竞技场已开启，学生可在课间进行闯关与天梯对战' if enabled
                        else '战斗竞技场已关闭，学生只能进行考试与练习'})

    # 考试管控设置（开放时段 + 次数上限）
    if 'exam_window_start' in data or 'exam_max_attempts' in data:
        start = _valid_window_value(data.get('exam_window_start'))
        end = _valid_window_value(data.get('exam_window_end'))
        if start is None or end is None:
            return jsonify({'success': False, 'message': '时间格式应为 YYYY-MM-DD HH:MM'})
        if start and end and start > end:
            return jsonify({'success': False, 'message': '开始时间不能晚于结束时间'})
        try:
            max_attempts = int(data.get('exam_max_attempts', 0) or 0)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': '考试次数上限必须是整数'})
        if not 0 <= max_attempts <= 99:
            return jsonify({'success': False, 'message': '考试次数上限需在 0~99 之间（0 表示不限）'})
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('exam_window_start', ?)", (start,))
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('exam_window_end', ?)", (end,))
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('exam_max_attempts', ?)",
                         (str(max_attempts),))
            conn.commit()
        parts = []
        if start or end:
            parts.append(f'考试时段 {start or "不限"} ~ {end or "不限"}')
        else:
            parts.append('考试时段不限')
        parts.append(f'次数上限 {"不限" if max_attempts == 0 else str(max_attempts) + " 次"}')
        return jsonify({'success': True, 'message': '已保存：' + '，'.join(parts)})

    try:
        lv = int(data.get('qualify_level'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '合格等级必须是整数'})
    if not 2 <= lv <= MAX_LEVEL:
        return jsonify({'success': False, 'message': f'合格等级需在 2 ~ {MAX_LEVEL} 级之间'})
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('qualify_level', ?)",
                     (str(lv),))
        conn.commit()
    return jsonify({'success': True, 'message': f'合格等级已设为 {lv} 级（{LEVEL_NAMES[lv - 1]}）'})


def _regular_score_rows(conn):
    """
    全体学生平时分（等级折算 + 竞技场星级加成），口径与 /admin/levels 完全一致。

    模拟器考试模块（sim）也通过依赖注入调用本函数取平时分，
    保证「总评 = 平时 50% + 考试 50%」里的平时分与教师端平时成绩表同一个数。
    若两处各算一遍，迟早会算出不同结果，教师会对不上账。

    返回字段需保持稳定：id/name/class_name/total_xp/level/level_name/qualified/
    star3/stage_total/star_bonus/regular_score/class_rank
    """
    qualify_level = get_qualify_level(conn)
    rows = conn.execute(
        '''
        SELECT s.id, s.name, s.class_name,
               (SELECT COALESCE(SUM(x.xp), 0) FROM xp_log x WHERE x.student_id = s.id) AS total_xp
        FROM students s
        '''
    ).fetchall()
    stage_total = conn.execute('SELECT COUNT(DISTINCT category) FROM questions').fetchone()[0]
    star_rows = conn.execute(
        'SELECT student_id, COUNT(*) AS star3 FROM battle_progress '
        'WHERE stars = 3 GROUP BY student_id').fetchall()
    star3_map = {r['student_id']: r['star3'] for r in star_rows}

    by_class = {}
    for r in rows:
        item = dict(r)
        lv = level_from_xp(item['total_xp'], qualify_level)
        item['level'] = lv['level']
        item['level_name'] = lv['name']
        item['qualified'] = lv['qualified']
        item['star3'] = star3_map.get(item['id'], 0)
        item['stage_total'] = stage_total
        item['star_bonus'] = round(min(item['star3'] / stage_total, 1.0) * 5, 1) if stage_total else 0
        item['regular_score'] = min(100, round(lv['regular_score'] + item['star_bonus'], 1))
        by_class.setdefault(item['class_name'], []).append(item)

    students = []
    for items in by_class.values():
        items.sort(key=lambda x: -x['total_xp'])
        for idx, it in enumerate(items, 1):
            it['class_rank'] = idx
        students.extend(items)
    students.sort(key=lambda x: (x['class_name'], x['class_rank']))
    return students


@app.route('/admin/levels')
@admin_required
def admin_levels():
    """全体学生平时成绩总表：经验、等级、班级排名、折算分数。"""
    with get_db() as conn:
        qualify_level = get_qualify_level(conn)
        students = _regular_score_rows(conn)

    return jsonify({
        'success': True,
        'qualify_level': qualify_level,
        'qualify_level_name': LEVEL_NAMES[qualify_level - 1],
        'qualified_count': sum(1 for s in students if s['qualified']),
        'students': students
    })


@app.route('/admin/data')
@admin_required
def admin_data():
    with get_db() as conn:
        students = conn.execute('SELECT * FROM students ORDER BY class_name, name').fetchall()
        sessions = conn.execute(
            'SELECT qs.*, s.name, s.class_name FROM quiz_sessions qs '
            'JOIN students s ON qs.student_id = s.id WHERE qs.status IN (?, ?) '
            'ORDER BY qs.submitted_at DESC',
            ('completed', 'timeout')
        ).fetchall()

        total_students = conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        completed_count = conn.execute(
            'SELECT COUNT(DISTINCT student_id) FROM quiz_sessions '
            "WHERE status = 'completed' AND (mode IS NULL OR mode = 'exam')"
        ).fetchone()[0]
        avg_score = conn.execute(
            "SELECT AVG(CAST(score AS FLOAT)/total*100) FROM quiz_sessions "
            "WHERE status = 'completed' AND (mode IS NULL OR mode = 'exam')"
        ).fetchone()[0]
        question_count = conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]

    sessions_out = []
    for s in sessions:
        item = dict(s)
        item['started_at'] = to_beijing(item['started_at'])
        item['submitted_at'] = to_beijing(item['submitted_at'])
        sessions_out.append(item)

    return jsonify({
        'students': [dict(s) for s in students],
        'sessions': sessions_out,
        'stats': {
            'total_students': total_students,
            'completed_count': completed_count,
            'avg_score': round(avg_score, 1) if avg_score else 0,
            'question_count': question_count
        }
    })


@app.route('/admin/statistics')
@admin_required
def admin_statistics():
    with get_db() as conn:
        score_distribution = {}
        for label in ['0-59', '60-69', '70-79', '80-89', '90-100']:
            score_distribution[label] = 0

        all_sessions = conn.execute(
            "SELECT score, total FROM quiz_sessions "
            "WHERE status = 'completed' AND total > 0 AND (mode IS NULL OR mode = 'exam')"
        ).fetchall()
        for s in all_sessions:
            pct = round(s['score'] / s['total'] * 100)
            if pct < 60:
                score_distribution['0-59'] += 1
            elif pct < 70:
                score_distribution['60-69'] += 1
            elif pct < 80:
                score_distribution['70-79'] += 1
            elif pct < 90:
                score_distribution['80-89'] += 1
            else:
                score_distribution['90-100'] += 1

        class_stats = conn.execute(
            'SELECT s.class_name, COUNT(DISTINCT s.id) as student_count, '
            'COUNT(qs.id) as session_count, '
            'ROUND(AVG(CASE WHEN qs.status = ? THEN CAST(qs.score AS FLOAT)/qs.total*100 END), 1) as avg_score '
            'FROM students s '
            'LEFT JOIN quiz_sessions qs ON s.id = qs.student_id '
            '    AND qs.status IN (?, ?) AND (qs.mode IS NULL OR qs.mode = ?) '
            'GROUP BY s.class_name ORDER BY s.class_name',
            ('completed', 'completed', 'timeout', 'exam')
        ).fetchall()

        daily_trend = conn.execute(
            "SELECT DATE(submitted_at, '+8 hours') as date, "
            "ROUND(AVG(CAST(score AS FLOAT)/total*100), 1) as avg_score, "
            "COUNT(*) as count FROM quiz_sessions "
            "WHERE status = 'completed' AND submitted_at IS NOT NULL AND (mode IS NULL OR mode = 'exam') "
            "GROUP BY DATE(submitted_at, '+8 hours') ORDER BY date DESC LIMIT 30"
        ).fetchall()

        total_students = conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        completed_students = conn.execute(
            "SELECT COUNT(DISTINCT student_id) FROM quiz_sessions "
            "WHERE status = 'completed' AND (mode IS NULL OR mode = 'exam')"
        ).fetchone()[0]

    return jsonify({
        'score_distribution': score_distribution,
        'class_stats': [dict(c) for c in class_stats],
        'daily_trend': [dict(d) for d in daily_trend],
        'completion': {
            'completed': completed_students,
            'not_completed': total_students - completed_students
        }
    })


# ==================== 班级管理 ====================

@app.route('/admin/classes', methods=['GET'])
@admin_required
def get_classes_admin():
    with get_db() as conn:
        classes = conn.execute(
            'SELECT c.id, c.class_name, c.created_at, COUNT(s.id) as student_count '
            'FROM classes c LEFT JOIN students s ON c.class_name = s.class_name '
            'GROUP BY c.id ORDER BY c.class_name'
        ).fetchall()
    return jsonify({'classes': [dict(c) for c in classes]})


@app.route('/admin/classes', methods=['POST'])
@admin_required
def add_class():
    data = request.get_json()
    class_name = data.get('class_name', '').strip()
    if not class_name:
        return jsonify({'success': False, 'message': '请输入班级名称'})
    if len(class_name) > 40:
        return jsonify({'success': False, 'message': '班级名称过长'})

    with get_db() as conn:
        try:
            conn.execute('INSERT INTO classes (class_name) VALUES (?)', (class_name,))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'message': '该班级已存在'})
    return jsonify({'success': True, 'message': f'班级"{class_name}"添加成功'})


@app.route('/admin/classes/<int:class_id>', methods=['PUT'])
@admin_required
def update_class(class_id):
    data = request.get_json()
    new_name = data.get('class_name', '').strip()
    if not new_name:
        return jsonify({'success': False, 'message': '请输入班级名称'})

    with get_db() as conn:
        old = conn.execute('SELECT class_name FROM classes WHERE id = ?', (class_id,)).fetchone()
        if not old:
            return jsonify({'success': False, 'message': '班级不存在'})

        try:
            conn.execute('UPDATE classes SET class_name = ? WHERE id = ?', (new_name, class_id))
            conn.execute('UPDATE students SET class_name = ? WHERE class_name = ?',
                         (new_name, old['class_name']))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'message': '该班级名已存在'})
    return jsonify({'success': True, 'message': '班级名称已更新'})


@app.route('/admin/classes/<int:class_id>', methods=['DELETE'])
@admin_required
def delete_class(class_id):
    with get_db() as conn:
        cls = conn.execute('SELECT class_name FROM classes WHERE id = ?', (class_id,)).fetchone()
        if not cls:
            return jsonify({'success': False, 'message': '班级不存在'})

        student_count = conn.execute('SELECT COUNT(*) FROM students WHERE class_name = ?',
                                     (cls['class_name'],)).fetchone()[0]
        if student_count > 0:
            return jsonify({'success': False,
                            'message': f'该班级下还有{student_count}名学生，不能删除'})

        conn.execute('DELETE FROM classes WHERE id = ?', (class_id,))
        conn.commit()
    return jsonify({'success': True, 'message': '班级已删除'})


# ==================== 学生管理（花名册） ====================

@app.route('/admin/students')
@admin_required
def admin_students():
    """全体学生花名册：等级、经验、考试次数、最近活跃。"""
    with get_db() as conn:
        qualify_level = get_qualify_level(conn)
        roster_mode = get_roster_mode(conn)
        rows = conn.execute(
            '''
            SELECT s.id, s.name, s.class_name, s.created_at,
                   (SELECT COALESCE(SUM(x.xp), 0) FROM xp_log x WHERE x.student_id = s.id) AS total_xp,
                   (SELECT COUNT(*) FROM quiz_sessions qs WHERE qs.student_id = s.id
                      AND qs.status IN ('completed', 'timeout')
                      AND (qs.mode IS NULL OR qs.mode = 'exam')) AS exam_count,
                   (SELECT MAX(qs.submitted_at) FROM quiz_sessions qs
                      WHERE qs.student_id = s.id AND qs.submitted_at IS NOT NULL) AS last_active
            FROM students s ORDER BY s.class_name, s.name
            '''
        ).fetchall()

    students = []
    for r in rows:
        item = dict(r)
        lv = level_from_xp(item['total_xp'], qualify_level)
        item.update(level=lv['level'], level_name=lv['name'],
                    qualified=lv['qualified'], created_at=to_beijing(item['created_at']),
                    last_active=to_beijing(item['last_active']))
        students.append(item)
    return jsonify({'success': True, 'students': students, 'roster_mode': roster_mode})


@app.route('/admin/students', methods=['POST'])
@admin_required
def admin_add_student():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    class_name = (data.get('class_name') or '').strip()
    if not name or not class_name:
        return jsonify({'success': False, 'message': '请填写姓名和班级'})
    if len(name) > 20 or len(class_name) > 40:
        return jsonify({'success': False, 'message': '姓名或班级名过长'})
    with get_db() as conn:
        try:
            conn.execute('INSERT INTO students (name, class_name) VALUES (?, ?)',
                         (name, class_name))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'message': f'{class_name} 已有学生"{name}"，如需区分请用不同姓名（如姓名后加数字）'})
    return jsonify({'success': True, 'message': f'已添加 {class_name} · {name}'})


@app.route('/admin/students/bulk', methods=['POST'])
@admin_required
def admin_bulk_add_students():
    """批量导入：每行一个姓名，忽略空行与已有学生。"""
    data = request.get_json() or {}
    class_name = (data.get('class_name') or '').strip()
    names_raw = data.get('names') or []
    if not class_name:
        return jsonify({'success': False, 'message': '请选择班级'})
    if isinstance(names_raw, str):
        names_raw = names_raw.splitlines()
    names, seen = [], set()
    for n in names_raw:
        n = n.strip()
        if n and len(n) <= 20 and n not in seen:
            seen.add(n)
            names.append(n)
    if not names:
        return jsonify({'success': False, 'message': '没有有效的姓名（每行一个）'})

    added, skipped = 0, []
    with get_db() as conn:
        existing = {r['name'] for r in conn.execute(
            'SELECT name FROM students WHERE class_name = ?', (class_name,)).fetchall()}
        for n in names:
            if n in existing:
                skipped.append(n)
                continue
            conn.execute('INSERT INTO students (name, class_name) VALUES (?, ?)', (n, class_name))
            existing.add(n)
            added += 1
        conn.commit()
    msg = f'已导入 {added} 人'
    if skipped:
        msg += f'，跳过已存在 {len(skipped)} 人：{"、".join(skipped[:5])}{"等" if len(skipped) > 5 else ""}'
    return jsonify({'success': True, 'message': msg, 'added': added, 'skipped': skipped})


@app.route('/admin/students/<int:student_id>', methods=['PUT'])
@admin_required
def admin_update_student(student_id):
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    class_name = (data.get('class_name') or '').strip()
    if not name or not class_name:
        return jsonify({'success': False, 'message': '请填写姓名和班级'})
    if len(name) > 20 or len(class_name) > 40:
        return jsonify({'success': False, 'message': '姓名或班级名过长'})
    with get_db() as conn:
        student = conn.execute('SELECT * FROM students WHERE id = ?', (student_id,)).fetchone()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})
        try:
            conn.execute('UPDATE students SET name = ?, class_name = ? WHERE id = ?',
                         (name, class_name, student_id))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'message': f'{class_name} 已有学生"{name}"'})
    return jsonify({'success': True, 'message': '学生信息已更新'})


@app.route('/admin/students/<int:student_id>', methods=['DELETE'])
@admin_required
def admin_delete_student(student_id):
    """删除学生账号并级联清理其答题记录与经验（不可恢复）。"""
    with get_db() as conn:
        student = conn.execute('SELECT name, class_name FROM students WHERE id = ?',
                               (student_id,)).fetchone()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})
        conn.execute('DELETE FROM answers WHERE session_id IN '
                     '(SELECT id FROM quiz_sessions WHERE student_id = ?)', (student_id,))
        conn.execute('DELETE FROM xp_log WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM battle_progress WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM battle_results WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM pvp_shadows WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM pvp_ladder WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM pvp_matches WHERE challenger_id = ? OR defender_id = ?',
                     (student_id, student_id))
        conn.execute('DELETE FROM quiz_sessions WHERE student_id = ?', (student_id,))
        conn.execute('DELETE FROM students WHERE id = ?', (student_id,))
        conn.commit()
    return jsonify({'success': True, 'message': f'已删除 {student["class_name"]} · {student["name"]}（含全部记录）'})


@app.route('/admin/students/<int:student_id>/reset_xp', methods=['POST'])
@admin_required
def admin_reset_student_xp(student_id):
    """清零学生经验（答题记录保留，仅清经验流水）。"""
    with get_db() as conn:
        student = conn.execute('SELECT name FROM students WHERE id = ?', (student_id,)).fetchone()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})
        deleted = conn.execute('DELETE FROM xp_log WHERE student_id = ?', (student_id,)).rowcount
        conn.commit()
    return jsonify({'success': True, 'message': f'已清零 {student["name"]} 的经验（删除 {deleted} 条记录）'})


@app.route('/admin/students/merge', methods=['POST'])
@admin_required
def admin_merge_students():
    """把 source 账号的全部记录并入 target 账号，用于合并重复账号。"""
    data = request.get_json() or {}
    try:
        source_id = int(data.get('source_id'))
        target_id = int(data.get('target_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '参数错误'})
    if source_id == target_id:
        return jsonify({'success': False, 'message': '不能合并同一个账号'})

    with get_db() as conn:
        source = conn.execute('SELECT * FROM students WHERE id = ?', (source_id,)).fetchone()
        target = conn.execute('SELECT * FROM students WHERE id = ?', (target_id,)).fetchone()
        if not source or not target:
            return jsonify({'success': False, 'message': '账号不存在'})
        if source['name'] == target['name'] and source['class_name'] == target['class_name']:
            return jsonify({'success': False, 'message': '两个账号同名同班，无法区分'})
        conn.execute('UPDATE quiz_sessions SET student_id = ? WHERE student_id = ?',
                     (target_id, source_id))
        conn.execute('UPDATE xp_log SET student_id = ? WHERE student_id = ?',
                     (target_id, source_id))
        # 战斗竞技场：UNIQUE 冲突时保留 target 已有行，再清 source 残余
        for t in ('battle_progress', 'pvp_shadows', 'pvp_ladder'):
            conn.execute(f'UPDATE OR IGNORE {t} SET student_id = ? WHERE student_id = ?',
                         (target_id, source_id))
            conn.execute(f'DELETE FROM {t} WHERE student_id = ?', (source_id,))
        conn.execute('UPDATE battle_results SET student_id = ? WHERE student_id = ?',
                     (target_id, source_id))
        conn.execute('UPDATE pvp_matches SET challenger_id = ? WHERE challenger_id = ?',
                     (target_id, source_id))
        conn.execute('UPDATE pvp_matches SET defender_id = ? WHERE defender_id = ?',
                     (target_id, source_id))
        conn.execute('DELETE FROM students WHERE id = ?', (source_id,))
        conn.commit()
    return jsonify({'success': True,
                    'message': f'已将「{source["class_name"]}·{source["name"]}」的全部记录并入「{target["class_name"]}·{target["name"]}」'})


# ==================== Excel导出 ====================

@app.route('/admin/sync_questions', methods=['POST'])
@admin_required
def admin_sync_questions():
    """手动/定时任务合并新题后，无需重启服务器即可同步题库到数据库。"""
    try:
        result = load_questions()
    except Exception as e:
        return jsonify({'success': False, 'message': f'同步失败: {e}'}), 500
    if result.get('skipped'):
        with get_db() as conn:
            total = conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        return jsonify({'success': True, 'skipped': True, 'total': total,
                        'message': f'题库无变化，当前共 {total} 题'})
    return jsonify({'success': True, 'skipped': False, 'added': result['added'],
                    'removed': result['removed'], 'total': result['total'],
                    'message': f"同步完成：新增 {result['added']} 题，移除 {result['removed']} 题，当前共 {result['total']} 题"})


@app.route('/admin/export')
@admin_required
def export_excel():
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    with get_db() as conn:
        all_sessions = conn.execute(
            'SELECT s.name, s.class_name, qs.score, qs.total, qs.mode, qs.label, '
            'qs.started_at, qs.submitted_at, qs.status, qs.switch_count, '
            'ROUND(CAST(qs.score AS FLOAT) / qs.total * 100, 1) as percentage '
            'FROM quiz_sessions qs JOIN students s ON qs.student_id = s.id '
            'WHERE qs.status IN (?, ?) '
            'ORDER BY s.class_name, s.name, qs.submitted_at',
            ('completed', 'timeout')
        ).fetchall()

        all_students = conn.execute(
            'SELECT name, class_name FROM students ORDER BY class_name, name'
        ).fetchall()

        qualify_level = get_qualify_level(conn)
        xp_rows = conn.execute(
            '''
            SELECT s.id, s.name, s.class_name,
                   (SELECT COALESCE(SUM(x.xp), 0) FROM xp_log x WHERE x.student_id = s.id) AS total_xp
            FROM students s
            '''
        ).fetchall()
        export_stage_total = conn.execute(
            'SELECT COUNT(DISTINCT category) FROM questions').fetchone()[0]
        export_star3 = {r['student_id']: r['star3'] for r in conn.execute(
            'SELECT student_id, COUNT(*) AS star3 FROM battle_progress '
            'WHERE stars = 3 GROUP BY student_id').fetchall()}

    header_font = Font(bold=True, size=11, color='FFFFFF')
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    wb = openpyxl.Workbook()

    # Sheet 1: 成绩汇总（仅正式考试）
    ws1 = wb.active
    ws1.title = '成绩汇总'
    headers1 = ['姓名', '班级', '考试次数', '平均分(%)', '最高分', '最低分', '最近一次分数', '最近考试时间']
    for col, header in enumerate(headers1, 1):
        cell = ws1.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    student_sessions = {}
    for s in all_sessions:
        if (s['mode'] or 'exam') != 'exam':
            continue
        key = (s['name'], s['class_name'])
        student_sessions.setdefault(key, []).append(dict(s))

    row = 2
    for student in all_students:
        key = (student['name'], student['class_name'])
        ws1.cell(row=row, column=1, value=student['name']).alignment = cell_align
        ws1.cell(row=row, column=2, value=student['class_name']).alignment = cell_align

        if key in student_sessions:
            sessions = student_sessions[key]
            count = len(sessions)
            scores_pct = [float(s['percentage']) for s in sessions]
            avg_pct = round(sum(scores_pct) / len(scores_pct), 1)
            max_score = max(s['score'] for s in sessions)
            min_score = min(s['score'] for s in sessions)
            latest = sessions[-1]

            ws1.cell(row=row, column=3, value=count).alignment = cell_align
            ws1.cell(row=row, column=4, value=avg_pct).alignment = cell_align
            ws1.cell(row=row, column=5, value=max_score).alignment = cell_align
            ws1.cell(row=row, column=6, value=min_score).alignment = cell_align
            ws1.cell(row=row, column=7, value=f"{latest['score']}/{latest['total']}").alignment = cell_align
            ws1.cell(row=row, column=8, value=to_beijing(latest['submitted_at']) or '').alignment = cell_align
        else:
            for col in range(3, 9):
                ws1.cell(row=row, column=col, value='-').alignment = cell_align

        for col in range(1, 9):
            ws1.cell(row=row, column=col).border = thin_border
        row += 1

    for i, w in enumerate([12, 12, 10, 12, 10, 10, 14, 22], 1):
        ws1.column_dimensions[chr(64 + i)].width = w
    ws1.freeze_panes = 'A2'

    # Sheet 2: 详细记录（含练习）
    ws2 = wb.create_sheet('详细记录')
    headers2 = ['姓名', '班级', '类型', '练习范围', '得分', '总分', '正确率(%)',
                '开始时间', '提交时间', '用时(分钟)', '状态', '切屏次数']
    for col, header in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    row = 2
    for s in all_sessions:
        key = (s['name'], s['class_name'])
        ws2.cell(row=row, column=1, value=key[0]).alignment = cell_align
        ws2.cell(row=row, column=2, value=key[1]).alignment = cell_align
        mode_label = {'exam': '考试', 'practice': '练习', 'battle': '闯关', 'pvp': '竞技场'}
        ws2.cell(row=row, column=3,
                 value=mode_label.get(s['mode'] or 'exam', '练习')).alignment = cell_align
        ws2.cell(row=row, column=4, value=s['label'] or '').alignment = cell_align
        ws2.cell(row=row, column=5, value=s['score']).alignment = cell_align
        ws2.cell(row=row, column=6, value=s['total']).alignment = cell_align
        ws2.cell(row=row, column=7, value=float(s['percentage'])).alignment = cell_align
        ws2.cell(row=row, column=8, value=to_beijing(s['started_at']) or '').alignment = cell_align
        ws2.cell(row=row, column=9, value=to_beijing(s['submitted_at']) or '').alignment = cell_align

        duration = ''
        if s['started_at'] and s['submitted_at']:
            try:
                start = datetime.strptime(s['started_at'], '%Y-%m-%d %H:%M:%S')
                end = datetime.strptime(s['submitted_at'], '%Y-%m-%d %H:%M:%S')
                duration = round((end - start).total_seconds() / 60, 1)
            except ValueError:
                pass
        ws2.cell(row=row, column=10, value=duration).alignment = cell_align
        status_text = '已完成' if s['status'] == 'completed' else '已超时'
        ws2.cell(row=row, column=11, value=status_text).alignment = cell_align
        is_exam = (s['mode'] or 'exam') == 'exam'
        switch_val = s['switch_count'] if is_exam and s['switch_count'] else (0 if is_exam else '-')
        ws2.cell(row=row, column=12, value=switch_val).alignment = cell_align

        for col in range(1, 13):
            ws2.cell(row=row, column=col).border = thin_border
        row += 1

    for i, w in enumerate([12, 12, 8, 14, 8, 8, 12, 22, 22, 12, 10, 10], 1):
        ws2.column_dimensions[chr(64 + i)].width = w
    ws2.freeze_panes = 'A2'

    # Sheet 3: 平时成绩（等级折算 + 竞技场星级加成）
    ws3 = wb.create_sheet('平时成绩')
    headers3 = ['姓名', '班级', '班级排名', '等级', '段位', '总经验', '三星关数', '星级加成', '平时成绩', '是否达标']
    for col, header in enumerate(headers3, 1):
        cell = ws3.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    level_items = []
    by_class = {}
    for r in xp_rows:
        item = dict(r)
        lv = level_from_xp(item['total_xp'], qualify_level)
        item.update(level=lv['level'], level_name=lv['name'],
                    qualified=lv['qualified'], regular_score=lv['regular_score'])
        item['star3'] = export_star3.get(item['id'], 0)
        item['star_bonus'] = round(min(item['star3'] / export_stage_total, 1.0) * 5, 1) \
            if export_stage_total else 0
        item['final_score'] = min(100, round(lv['regular_score'] + item['star_bonus'], 1))
        by_class.setdefault(item['class_name'], []).append(item)
    for items in by_class.values():
        items.sort(key=lambda x: -x['total_xp'])
        for idx, it in enumerate(items, 1):
            it['class_rank'] = idx
        level_items.extend(items)
    level_items.sort(key=lambda x: (x['class_name'], x['class_rank']))

    row = 2
    for it in level_items:
        values = [it['name'], it['class_name'], it['class_rank'], it['level'],
                  it['level_name'], it['total_xp'], it['star3'], it['star_bonus'],
                  it['final_score'], '达标' if it['qualified'] else '未达标']
        for col, v in enumerate(values, 1):
            ws3.cell(row=row, column=col, value=v).alignment = cell_align
            ws3.cell(row=row, column=col).border = thin_border
        row += 1

    for i, w in enumerate([12, 14, 10, 8, 12, 10, 10, 10, 10, 10], 1):
        ws3.column_dimensions[chr(64 + i)].width = w
    ws3.freeze_panes = 'A2'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f'成绩汇总_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)


@app.route('/admin/delete_session/<int:session_id>', methods=['DELETE'])
@admin_required
def delete_session(session_id):
    with get_db() as conn:
        conn.execute('DELETE FROM answers WHERE session_id = ?', (session_id,))
        conn.execute('DELETE FROM quiz_sessions WHERE id = ?', (session_id,))
        conn.commit()
    return jsonify({'success': True})


# ==================== 学情分析 ====================

@app.route('/admin/analytics')
@admin_required
def admin_analytics():
    """分类正确率 + 高频错题榜。mode: exam（默认）/ practice / all。"""
    mode = request.args.get('mode', 'exam')
    if mode not in ('exam', 'practice', 'all'):
        mode = 'exam'

    def mode_filter(col):
        if mode == 'all':
            return ''
        if mode == 'exam':
            return f" AND ({col} IS NULL OR {col} = 'exam')"
        return f" AND {col} = 'practice'"

    with get_db() as conn:
        cat_rows = conn.execute(
            f'''
            SELECT q.category,
                   COUNT(*) AS attempts,
                   SUM(a.is_correct) AS correct
            FROM answers a
            JOIN quiz_sessions qs ON qs.id = a.session_id
            JOIN questions q ON q.id = a.question_id
            WHERE qs.status IN ('completed', 'timeout'){mode_filter('qs.mode')}
            GROUP BY q.category
            '''
        ).fetchall()

        wrong_rows = conn.execute(
            f'''
            SELECT a.question_id, q.category, q.q_type, q.question,
                   COUNT(*) AS wrong_count,
                   SUM(CASE WHEN a.student_answer = '' THEN 1 ELSE 0 END) AS blank_count,
                   COUNT(DISTINCT qs.student_id) AS wrong_students
            FROM answers a
            JOIN quiz_sessions qs ON qs.id = a.session_id
            JOIN questions q ON q.id = a.question_id
            WHERE qs.status IN ('completed', 'timeout') AND a.is_correct = 0{mode_filter('qs.mode')}
            GROUP BY a.question_id
            ORDER BY wrong_count DESC, wrong_students DESC
            LIMIT 20
            '''
        ).fetchall()

    categories = []
    for r in cat_rows:
        pct = round(r['correct'] / r['attempts'] * 100, 1) if r['attempts'] else 0
        categories.append({'category': r['category'], 'attempts': r['attempts'],
                           'correct': r['correct'], 'accuracy': pct})
    categories.sort(key=lambda x: x['accuracy'])

    top_wrong = [dict(r) for r in wrong_rows]
    return jsonify({'success': True, 'mode': mode,
                    'category_accuracy': categories, 'top_wrong': top_wrong})


@app.route('/admin/student_trend/<int:student_id>')
@admin_required
def admin_student_trend(student_id):
    """单个学生的成长曲线：历次考试正确率 + 按日累计经验。"""
    with get_db() as conn:
        student = conn.execute('SELECT id, name, class_name FROM students WHERE id = ?',
                               (student_id,)).fetchone()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})

        sessions = conn.execute(
            '''
            SELECT qs.score, qs.total, qs.submitted_at, qs.mode, qs.label
            FROM quiz_sessions qs
            WHERE qs.student_id = ? AND qs.status IN ('completed', 'timeout')
              AND (qs.mode IS NULL OR qs.mode = 'exam')
            ORDER BY qs.submitted_at
            ''',
            (student_id,)).fetchall()

        xp_rows = conn.execute(
            '''
            SELECT gain_date, SUM(xp) AS xp
            FROM xp_log WHERE student_id = ?
            GROUP BY gain_date ORDER BY gain_date
            ''',
            (student_id,)).fetchall()

    exams = []
    for s in sessions:
        if not s['submitted_at']:
            continue
        exams.append({
            'date': to_beijing(s['submitted_at'])[:16],
            'pct': round(s['score'] / s['total'] * 100, 1) if s['total'] else 0,
            'label': s['label'] or '随机抽题',
        })

    xp_daily, cumulative = [], 0
    for r in xp_rows:
        cumulative += r['xp'] or 0
        xp_daily.append({'date': r['gain_date'], 'xp': r['xp'] or 0, 'cumulative': cumulative})

    return jsonify({
        'success': True,
        'student': {'id': student['id'], 'name': student['name'],
                    'class_name': student['class_name']},
        'exams': exams,
        'xp_daily': xp_daily,
        'total_xp': cumulative,
    })


@app.route('/admin/live')
@admin_required
def admin_live():
    """实时监考：正在进行的答题会话与考试管控设置。"""
    with get_db() as conn:
        state, hint = exam_window_state(conn)
        start, end = get_exam_window(conn)
        max_attempts = get_exam_max_attempts(conn)
        battle_enabled = get_battle_enabled(conn)
        rows = conn.execute(
            '''
            SELECT qs.id, qs.started_at, qs.deadline, qs.total, qs.mode, qs.label,
                   qs.switch_count, s.name, s.class_name,
                   (SELECT COUNT(*) FROM answers a WHERE a.session_id = qs.id) AS answered
            FROM quiz_sessions qs JOIN students s ON qs.student_id = s.id
            WHERE qs.status = 'in_progress'
            ORDER BY qs.started_at DESC
            '''
        ).fetchall()

    live = []
    for r in rows:
        item = dict(r)
        item['started_at'] = to_beijing(item['started_at'])
        try:
            # deadline 存 UTC，与 UTC 当前时间相减得到剩余分钟
            remain_min = max(0, round((datetime.strptime(item['deadline'], '%Y-%m-%d %H:%M:%S')
                                       - utcnow()).total_seconds() / 60))
        except (ValueError, TypeError):
            remain_min = None
        item['remain_min'] = remain_min
        live.append(item)

    return jsonify({
        'success': True,
        'sessions': live,
        'window': {'start': start, 'end': end, 'state': state, 'hint': hint},
        'max_attempts': max_attempts,
        'battle_enabled': battle_enabled,
        'server_time': beijing_now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    """
    兜底异常处理：把完整堆栈写到**原始** stderr 并给出可读响应。

    为什么需要：Flask 默认在生产模式下遇到未捕获异常只返回一个空白 500 页，
    教师端看到的就是"白屏"，完全无从排查。这里把堆栈打印出来（sys.__stderr__
    绕开模块顶部对 stdout/stderr 的 UTF-8 包装，避免编码问题导致日志丢失），
    API 请求额外返回 JSON 形式的错误原因。
    """
    from werkzeug.exceptions import HTTPException

    # 404/403 这类"正常"的 HTTP 错误不该被当成 500 报出去，原样返回
    if isinstance(exc, HTTPException):
        return exc

    import traceback
    try:
        sys.__stderr__.write('\n[500] %s: %s\n%s\n' %
                            (request.path, exc, traceback.format_exc()))
        sys.__stderr__.flush()
    except Exception:
        pass

    if request.path.startswith('/api/'):
        return jsonify({'success': False,
                        'message': '服务器内部错误：%s' % exc}), 500
    return '服务器内部错误，详细堆栈已输出到控制台。', 500


# ==================== 模块级初始化 ====================
# 关键：init_db() 必须放在模块级而不是 __main__ 里。
# 一旦改用 waitress / gunicorn 等 WSGI 方式部署，__main__ 不会执行，
# 表就不会被创建 —— 考试当天才发现就晚了。init_db 是幂等的，重复调用无害。
init_db()

# ---- 挂载模拟器考试模块（BIOS 设置模拟 + WinPE 装机维护模拟）----
# 采用依赖注入而非 from app import ...，避免 app.py 与 sim 包循环导入。
from sim import init_app as _sim_init_app

_sim_init_app(app, {
    'get_db': get_db,
    'utcnow': utcnow,
    'beijing_now': beijing_now,
    'to_beijing': to_beijing,
    'add_column': _add_column,
    'regular_rows': _regular_score_rows,
})


if __name__ == '__main__':
    init_db()
    load_questions()
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('QUIZ_DEBUG', '0') == '1'
    print("🚀 服务器启动中...")
    print(f"📍 统一入口: http://localhost:{port}/portal")
    print(f"📍 学生端: http://localhost:{port}")
    print(f"📍 管理后台: http://localhost:{port}/admin")
    print("🔑 首次使用默认管理密码 admin123，登录后请立即在后台修改")
    app.run(host='0.0.0.0', port=port, debug=debug)
