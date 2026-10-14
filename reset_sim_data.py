# -*- coding: utf-8 -*-
"""
清空模拟考试数据（重来一次）。

只清 sim_sessions / sim_events / sim_scores / sim_score_log 四张表，
不动 students、quiz_sessions 等刷题系统原有数据。

用法：
    python reset_sim_data.py          演练：只列将要删除的内容
    python reset_sim_data.py --yes    真正执行
"""
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quiz_app.db')
TABLES = ['sim_score_log', 'sim_events', 'sim_sessions', 'sim_scores']


def main():
    really = '--yes' in sys.argv
    if not os.path.exists(DB):
        print('找不到数据库：%s' % DB)
        return 1

    conn = sqlite3.connect(DB, timeout=15)
    total = 0
    print('数据库：%s' % DB)
    print('-' * 52)
    for t in TABLES:
        try:
            n = conn.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        total += n
        print('  %-16s %6d 行' % (t, n))
    print('-' * 52)
    print('  合计 %d 行' % total)

    if not really:
        print('\n[演练模式] 未做任何改动。确认无误后加 --yes 执行。')
        conn.close()
        return 0

    if total == 0:
        print('\n没有可清理的数据。')
        conn.close()
        return 0

    conn.executescript('\n'.join('DELETE FROM %s;' % t for t in TABLES))
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('sim_sessions','sim_events')")
    conn.commit()
    conn.execute('VACUUM')
    conn.close()
    print('\n已清空模拟考试数据。学生名单与刷题记录不受影响。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
