# -*- coding: utf-8 -*-
"""
模拟器考试模块 —— 建表与迁移。

设计要点（务必理解，否则会踩坑）：
    模拟器成绩 **绝不写入 quiz_sessions**。原因不是"想保持整洁"，而是实测发现
    app.py 里有两处 SQL 完全没有 mode 过滤：
        - /admin/data      (app.py:1988) 直接查全部 session
        - /admin/export    Sheet2 (app.py:2482) 遍历全部 session，未知 mode 会显示成"练习"
    只要往 quiz_sessions 插一行 mode='sim'，教师端数据页和导出表立刻被污染。
    因此这里独立建 4 张表，与既有业务零交集，既有统计代码一行都不用改。
"""

from . import config as C
from .ctx import get

# ==================== 建表 DDL ====================
DDL = '''
/* ① 模拟器考试会话 */
CREATE TABLE IF NOT EXISTS sim_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL,
    sim_type      TEXT NOT NULL,                       -- 'bios' | 'winpe'
    mode          TEXT NOT NULL DEFAULT 'exam',        -- exam | practice | voided
    paper_id      TEXT NOT NULL DEFAULT 'v1',          -- 卷别
    status        TEXT NOT NULL DEFAULT 'in_progress', -- in_progress | completed | timeout
    started_at    TIMESTAMP NOT NULL,
    deadline      TIMESTAMP NOT NULL,
    submitted_at  TIMESTAMP,
    duration_sec  INTEGER DEFAULT 0,
    switch_count  INTEGER DEFAULT 0,
    raw_score     REAL DEFAULT 0,                      -- rubric 卷面原始分
    max_score     REAL DEFAULT 0,                      -- 本卷满分
    normalized    REAL DEFAULT 0,                      -- 归一化到百分制
    rubric_version TEXT DEFAULT '',                    -- 判分细则版本，改细则不影响旧成绩
    events_hash   TEXT DEFAULT '',                     -- 事件序列哈希，事后可复核
    client_ip     TEXT DEFAULT '',
    user_agent    TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE INDEX IF NOT EXISTS idx_sim_sessions_student ON sim_sessions(student_id);
CREATE INDEX IF NOT EXISTS idx_sim_sessions_live    ON sim_sessions(sim_type, status);
CREATE INDEX IF NOT EXISTS idx_sim_sessions_mode    ON sim_sessions(mode);

/* ② 操作事件流 —— 服务端判分的唯一输入 */
CREATE TABLE IF NOT EXISTS sim_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    seq        INTEGER NOT NULL,          -- 前端单调自增，服务端按 (session_id, seq) 去重
    t_ms       INTEGER NOT NULL DEFAULT 0, -- 相对开考毫秒
    kind       TEXT NOT NULL,
    target     TEXT DEFAULT '',
    value      TEXT DEFAULT '',            -- JSON 字符串
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sim_sessions(id)
);

-- 必须唯一：交卷时事件会随交卷请求再发一次做兜底，
-- 靠 (session_id, seq) 唯一 + INSERT OR IGNORE 保证不重复入库。
CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_events_session ON sim_events(session_id, seq);

/* ③ 单人成绩汇总（一人一行） */
CREATE TABLE IF NOT EXISTS sim_scores (
    student_id       INTEGER PRIMARY KEY,
    bios_score       REAL,                 -- 百分制
    winpe_score      REAL,
    bios_session_id  INTEGER,
    winpe_session_id INTEGER,
    bios_switch      INTEGER DEFAULT 0,
    winpe_switch     INTEGER DEFAULT 0,
    manual_score     REAL,                 -- 实操装机手录分；NULL = 未录入
    manual_note      TEXT DEFAULT '',
    manual_at        TIMESTAMP,
    regular_score    REAL,                 -- 平时分快照（冻结时写入）
    regular_snapshot_at TIMESTAMP,
    exam_score       REAL,                 -- = .25*manual + .125*bios + .125*winpe
    final_score      REAL,                 -- = .5*regular + .5*exam
    updated_at       TIMESTAMP
);

/* ④ 改分审计 */
CREATE TABLE IF NOT EXISTS sim_score_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    field      TEXT NOT NULL,   -- manual_score | bios_score | winpe_score | void
    old_value  TEXT,
    new_value  TEXT,
    operator   TEXT DEFAULT 'admin',
    reason     TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sim_scorelog_student ON sim_score_log(student_id);
'''


def init_schema():
    """建表 + 建索引 + 增量迁移。幂等，可重复调用。"""
    add_column = get('add_column')

    with get('get_db')() as conn:
        conn.executescript(DDL)

        # 模拟器不需要学号也能跑，但成绩单对接教务系统时有用。
        # 注意：可空、非唯一，绝不改动现有身份键 (name, class_name)。
        add_column(conn, 'students', 'student_no', 'TEXT')

        _create_once_index(conn)
        _ensure_unique_events_index(conn)
        conn.commit()


def _create_once_index(conn):
    """
    「限考 1 次」的唯一可靠保障。

    用部分索引（partial unique index）：只有 mode='exam' 的行受约束。
    - 练习模式可无限次；
    - 教师作废时把 mode 改成 'voided'，约束自动解除，学生可重考，且记录保留可审计。

    为什么不用应用层 SELECT-then-INSERT：
        并发下两个请求可能同时查到"没考过"，随后都插入成功 —— 只有数据库约束能兜底。
    """
    try:
        # 注意：SQLite 禁止在部分索引的 WHERE 子句里使用绑定参数
        # （parameters prohibited in partial index WHERE clauses），
        # 所以这里拼接常量。C.MODE_EXAM 是代码里的常量而非用户输入，无注入风险。
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_once "
            "ON sim_sessions(student_id, sim_type) WHERE mode = '%s'" % C.MODE_EXAM
        )
    except Exception as exc:  # SQLite < 3.8.0 不支持部分索引
        print('[sim] 警告：部分唯一索引创建失败（%s），'
              '「限考 1 次」将退化为应用层检查，并发下存在理论风险。' % exc)


def _ensure_unique_events_index(conn):
    """
    老库迁移：早期版本建的是**普通**索引，(session_id, seq) 并不去重，
    INSERT OR IGNORE 也就挡不住重复事件。这里先删重、再重建为唯一索引。
    """
    try:
        rows = conn.execute("PRAGMA index_list('sim_events')").fetchall()
    except Exception:
        return
    # PRAGMA 返回 (seq, name, unique, origin, partial)，unique 为 1 表示唯一
    for r in rows:
        name = r[1] if len(r) > 1 else ''
        if name != 'idx_sim_events_session':
            continue
        if r[2]:          # 已经是唯一索引，无需处理
            return
        conn.execute(
            'DELETE FROM sim_events WHERE id NOT IN ('
            '  SELECT MIN(id) FROM sim_events GROUP BY session_id, seq)')
        conn.execute('DROP INDEX idx_sim_events_session')
        break
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_events_session '
        'ON sim_events(session_id, seq)')


def get_setting(conn, key, default=''):
    """读 settings 表；不存在时返回默认值。"""
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row and row['value'] not in (None, '') else default


def get_minutes(conn, sim_type):
    """取该模拟器的考试时长（分钟），未配置则用默认值。"""
    try:
        return int(get_setting(conn, C.MINUTES_KEY[sim_type], C.DEFAULT_MINUTES[sim_type]))
    except (ValueError, TypeError, KeyError):
        return C.DEFAULT_MINUTES[sim_type]


def get_switch_limit(conn):
    try:
        return int(get_setting(conn, C.K_SWITCH_LIMIT, 0))
    except (ValueError, TypeError):
        return 0
