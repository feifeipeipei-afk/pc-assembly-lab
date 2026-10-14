# -*- coding: utf-8 -*-
"""
刷题系统自动化测试：登录、考试判分、练习即时反馈、错题本、
增量题库同步、经验与等级系统、排行榜、管理端鉴权与改密。
运行: python -m pytest tests/ -v
"""
import json
import os
import random
import shutil
import sqlite3
import tempfile
import uuid
import sys

# 必须在导入 app 前设置临时数据库
TMP_DIR = tempfile.mkdtemp(prefix='quiz_test_')
os.environ['QUIZ_DB_PATH'] = os.path.join(TMP_DIR, 'test_quiz.db')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope='session')
def client():
    app_module.init_db()
    app_module.load_questions()
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        # 历史测试沿用"自由注册"语义：默认关闭花名册模式（生产默认开启）
        with app_module.get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('roster_mode', '0')")
            conn.commit()
        yield c


@pytest.fixture(scope='session')
def db():
    conn = sqlite3.connect(os.environ['QUIZ_DB_PATH'])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def uniq(prefix):
    return f'{prefix}{uuid.uuid4().hex[:8]}'


def login_student(client, name=None, class_name='测试1班'):
    name = name or uniq('学生')
    res = client.post('/login', json={'name': name, 'class_name': class_name})
    assert res.get_json()['success']
    return name


# ==================== 登录与基础 ====================

def test_student_login_and_registration(client):
    name = uniq('张三')
    res = client.post('/login', json={'name': name, 'class_name': '登录测试班'})
    data = res.get_json()
    assert data['success']
    # 再次登录同一人不应新建
    res2 = client.post('/login', json={'name': name, 'class_name': '登录测试班'})
    assert res2.get_json()['success']
    rows = client.get('/my_scores').get_json()
    assert rows['success']


def test_login_validation(client):
    res = client.post('/login', json={'name': '', 'class_name': ''})
    assert not res.get_json()['success']


def test_categories_api(client):
    data = client.get('/api/categories').get_json()
    assert data['categories']
    total = sum(c['count'] for c in data['categories'])
    assert total >= 1700


# ==================== 考试全流程与判分 ====================

def test_exam_full_flow_and_grading(client, db):
    login_student(client)
    res = client.post('/start_quiz').get_json()
    assert res['success']
    session_id = res['session_id']

    data = client.get('/get_questions').get_json()
    assert data['success']
    assert data['mode'] == 'exam'
    assert len(data['questions']) == app_module.QUIZ_QUESTION_COUNT
    # 考试模式不应泄露答案
    assert 'answer' not in data['questions'][0]
    assert data.get('feedback') is None

    qids = [q['id'] for q in data['questions']]

    # 全部按正确答案作答，但第1题故意答错
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}
    wrong_answer = 'B' if correct_map[qids[0]] != 'B' else 'A'
    for i, qid in enumerate(qids):
        ans = wrong_answer if i == 0 else correct_map[qid]
        r = client.post('/save_answer', json={'question_id': qid, 'answer': ans}).get_json()
        assert r['success'], f'保存第{i}题失败'
        # 考试模式即时反馈不应包含答案
        assert 'practice_feedback' not in r

    sub = client.post('/submit_quiz').get_json()
    assert sub['success']
    assert sub['total'] == app_module.QUIZ_QUESTION_COUNT
    assert sub['score'] == app_module.QUIZ_QUESTION_COUNT - 1

    # 回看详情
    detail = client.get(f'/quiz_result/{session_id}').get_json()
    assert detail['success']
    assert detail['score'] == sub['score']
    assert detail['mode'] == 'exam'
    assert len(detail['details']) == app_module.QUIZ_QUESTION_COUNT

    # 历史记录带模式
    scores = client.get('/my_scores').get_json()['scores']
    assert any(s['id'] == session_id and s['mode'] == 'exam' for s in scores)


def test_invalid_answer_rejected(client):
    login_student(client)
    client.post('/start_quiz')
    data = client.get('/get_questions').get_json()
    qid = data['questions'][0]['id']
    res = client.post('/save_answer', json={'question_id': qid, 'answer': 'Z'}).get_json()
    assert not res['success']


# ==================== 练习模式 ====================

def test_practice_immediate_feedback(client, db):
    login_student(client)
    res = client.post('/start_practice', json={'source': 'category',
                                               'category': '计算机硬件基础', 'count': 5}).get_json()
    assert res['success']
    assert res['mode'] == 'practice'
    assert res['label'] == '计算机硬件基础'

    data = client.get('/get_questions').get_json()
    assert data['mode'] == 'practice'
    # 练习模式恢复信息包含正确答案（用于还原即时反馈）
    assert data['feedback'] is not None

    qid = data['questions'][0]['id']
    correct = db.execute('SELECT answer FROM questions WHERE id=?', (qid,)).fetchone()['answer']
    wrong_answer = 'B' if correct != 'B' else 'A'

    r1 = client.post('/save_answer', json={'question_id': qid, 'answer': correct}).get_json()
    assert r1['practice_feedback']['correct'] is True
    assert r1['practice_feedback']['answer'] == correct
    assert r1['practice_feedback']['explanation']

    qid2 = data['questions'][1]['id']
    correct2 = db.execute('SELECT answer FROM questions WHERE id=?', (qid2,)).fetchone()['answer']
    wrong2 = 'B' if correct2 != 'B' else 'A'
    r2 = client.post('/save_answer', json={'question_id': qid2, 'answer': wrong2}).get_json()
    assert r2['practice_feedback']['correct'] is False

    sub = client.post('/submit_quiz').get_json()
    assert sub['success']
    assert sub['mode'] == 'practice'
    assert sub['score'] == 1

    # 练习的错题也应进入错题本
    stats = client.get('/api/wrong_stats').get_json()
    assert stats['total'] >= 1


def test_practice_invalid_category(client):
    login_student(client)
    res = client.post('/start_practice', json={'source': 'category',
                                               'category': '不存在的分类', 'count': 5}).get_json()
    assert not res['success']


# ==================== 错题本 ====================

def test_wrong_stats_and_repractice(client, db):
    login_student(client)
    # 没有历史时
    stats = client.get('/api/wrong_stats').get_json()
    assert stats['success'] and stats['total'] == 0
    res = client.post('/start_practice', json={'source': 'wrong', 'count': 10}).get_json()
    assert not res['success']  # 无错题不能开练

    # 制造一场全错的考试
    client.post('/start_quiz')
    data = client.get('/get_questions').get_json()
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}
    for q in data['questions']:
        ans = 'B' if correct_map[q['id']] != 'B' else 'A'
        client.post('/save_answer', json={'question_id': q['id'], 'answer': ans})
    client.post('/submit_quiz')

    stats = client.get('/api/wrong_stats').get_json()
    assert stats['total'] == app_module.QUIZ_QUESTION_COUNT
    assert len(stats['categories']) > 0
    assert all('answer' in wq and 'explanation' in wq for wq in stats['questions'])

    # 错题重练
    res = client.post('/start_practice', json={'source': 'wrong', 'count': 30}).get_json()
    assert res['success']
    assert res['label'] == '错题重练'
    data = client.get('/get_questions').get_json()
    assert 0 < len(data['questions']) <= 30
    client.post('/submit_quiz')


# ==================== 排行榜过滤练习 ====================

def test_leaderboard_excludes_practice(client, db):
    name = uniq('排行')
    login_student(client, name=name, class_name='排行测试班')
    # 做一场满分考试
    client.post('/start_quiz')
    data = client.get('/get_questions').get_json()
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}
    for q in data['questions']:
        client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})
    client.post('/submit_quiz')

    # 再做一场零分练习
    client.post('/start_practice', json={'source': 'category', 'category': '网络基础', 'count': 5})
    pdata = client.get('/get_questions').get_json()
    for q in pdata['questions']:
        correct = correct_map[q['id']]
        wrong = 'B' if correct != 'B' else 'A'
        client.post('/save_answer', json={'question_id': q['id'], 'answer': wrong})
    client.post('/submit_quiz')

    lb = client.get('/api/leaderboard').get_json()
    assert lb['success']
    me = next(item for item in lb['leaderboard'] if item['name'] == name)
    # 考试统计字段仍只算考试：练习不拉低平均分、不计入考试次数
    assert me['avg_score'] == 100.0, '练习不应拉低排行榜平均分'
    assert me['attempts'] == 1, '练习不应计入考试次数'


# ==================== 经验与等级系统 ====================

def test_level_and_score_mapping():
    """等级折算平时成绩：1 级 0 分，合格级 60 分，满级 100 分。"""
    assert app_module.score_from_level(1, 20) == 0
    assert app_module.score_from_level(10, 20) == 28
    assert app_module.score_from_level(20, 20) == 60
    assert app_module.score_from_level(25, 20) == 80
    assert app_module.score_from_level(30, 20) == 100

    lv = app_module.level_from_xp(app_module.total_xp_for_level(20), 20)
    assert lv['level'] == 20 and lv['qualified'] and lv['regular_score'] == 60
    lv19 = app_module.level_from_xp(app_module.total_xp_for_level(20) - 1, 20)
    assert lv19['level'] == 19 and not lv19['qualified']


def test_xp_granted_on_exam_submit(client, db):
    """正常交卷应发放经验并返回升级信息（此前仅超时交卷发经验）。"""
    login_student(client)
    client.post('/start_quiz')
    data = client.get('/get_questions').get_json()
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}
    for q in data['questions']:
        client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})

    sub = client.post('/submit_quiz').get_json()
    # 50 题首次全对：前 15 题×10 + 中 15 题×5 + 后 20 题×1 = 245
    assert sub['xp']['gained'] == 245
    assert sub['xp']['level_up'] is True
    assert sub['xp']['level'] > sub['xp']['level_before'] >= 1

    profile = client.get('/api/profile').get_json()
    assert profile['success']
    assert profile['total_xp'] == 245
    assert profile['rank'] >= 1 and profile['class_total'] >= 1
    assert 'regular_score' in profile and 'xp_to_qualify' in profile


def test_xp_repeat_decay(client, db):
    """同一题反复做经验衰减：首次 100%，第二次 30%，第三次起 0。"""
    login_student(client)
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}

    def practice_round():
        random.seed(2026)  # 固定种子 → 每轮抽到同样的 5 题
        res = client.post('/start_practice', json={'source': 'category',
                                                   'category': '计算机硬件基础', 'count': 5}).get_json()
        assert res['success']
        data = client.get('/get_questions').get_json()
        for q in data['questions']:
            client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})
        return client.post('/submit_quiz').get_json()

    assert practice_round()['xp']['gained'] == 50   # 5 × 10
    assert practice_round()['xp']['gained'] == 15   # 5 × 3
    assert practice_round()['xp']['gained'] == 0    # 5 × 0


def test_xp_no_reward_for_wrong_first_then_correct(client, db):
    """先乱答再重刷不能拿满经验：做错过的题再答对只有 30%。"""
    login_student(client)
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}

    # 第一轮全部故意答错（练习模式顺便看答案）
    random.seed(88)
    client.post('/start_practice', json={'source': 'category', 'category': '计算机硬件基础', 'count': 5})
    data = client.get('/get_questions').get_json()
    for q in data['questions']:
        correct = correct_map[q['id']]
        wrong = 'B' if correct != 'B' else 'A'
        client.post('/save_answer', json={'question_id': q['id'], 'answer': wrong})
    assert client.post('/submit_quiz').get_json()['xp']['gained'] == 0

    # 第二轮同样 5 题（同种子）全答对：每题只剩 30% = 3 经验
    random.seed(88)
    client.post('/start_practice', json={'source': 'category', 'category': '计算机硬件基础', 'count': 5})
    data = client.get('/get_questions').get_json()
    for q in data['questions']:
        client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})
    sub = client.post('/submit_quiz').get_json()
    assert sub['xp']['gained'] == 15, '做错过的题重刷不应拿满经验'


def test_leaderboard_ranks_by_xp(client, db):
    """排行榜按总经验排序（考试与练习都计入经验）。"""
    cname = uniq('等级榜')
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}

    name_a = login_student(client, name=uniq('高经验'), class_name=cname)
    client.post('/start_quiz')
    data = client.get('/get_questions').get_json()
    for q in data['questions']:
        client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})
    client.post('/submit_quiz')

    name_b = login_student(client, name=uniq('低经验'), class_name=cname)
    client.post('/start_practice', json={'source': 'category', 'category': '网络基础', 'count': 5})
    pdata = client.get('/get_questions').get_json()
    for q in pdata['questions']:
        client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})
    client.post('/submit_quiz')

    lb = client.get('/api/leaderboard').get_json()  # 以 B 的身份查看
    assert lb['metric'] == 'total_xp'
    assert lb['current_rank'] == 2
    top = lb['leaderboard'][0]
    assert top['name'] == name_a and top['total_xp'] == 245
    me = next(i for i in lb['leaderboard'] if i['name'] == name_b)
    assert me['total_xp'] == 50 and me['rank'] == 2
    assert 'level_name' in top and 'qualified' in top


# ==================== 管理端设置与平时成绩 ====================

def test_admin_settings_and_levels(client):
    name = login_student(client)
    client.post('/start_practice', json={'source': 'category', 'category': '网络基础', 'count': 5})
    client.get('/get_questions')
    client.post('/submit_quiz')  # 不作答，0 经验

    admin_login(client)
    s = client.get('/admin/settings').get_json()
    assert s['success'] and 2 <= s['qualify_level'] <= s['max_level']

    # 非法合格等级被拒
    assert not client.post('/admin/settings', json={'qualify_level': 1}).get_json()['success']
    assert not client.post('/admin/settings', json={'qualify_level': 99}).get_json()['success']

    # 调整合格线对所有接口生效
    assert client.post('/admin/settings', json={'qualify_level': 5}).get_json()['success']
    prof = client.get('/api/profile').get_json()
    assert prof['qualify_level'] == 5
    lv = client.get('/admin/levels').get_json()
    assert lv['success'] and 'students' in lv and 'qualified_count' in lv
    me_row = next(x for x in lv['students'] if x['name'] == name)
    assert me_row['level'] == 1 and me_row['regular_score'] == 0

    # 还原默认并退出管理登录，避免影响其他测试
    client.post('/admin/settings', json={'qualify_level': app_module.QUALIFY_LEVEL})
    client.get('/admin/logout')


# ==================== 增量同步不丢成绩 ====================

def test_incremental_sync_preserves_sessions(client, db, monkeypatch):
    # 造一场已完成考试
    login_student(client, name=uniq('同步'), class_name='同步测试班')
    client.post('/start_quiz')
    data = client.get('/get_questions').get_json()
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}
    for q in data['questions']:
        client.post('/save_answer', json={'question_id': q['id'], 'answer': correct_map[q['id']]})
    client.post('/submit_quiz')

    before_sessions = db.execute('SELECT COUNT(*) FROM quiz_sessions').fetchone()[0]
    before_answers = db.execute('SELECT COUNT(*) FROM answers').fetchone()[0]
    before_qcount = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    sample_answer = db.execute('SELECT a.question_id FROM answers a LIMIT 1').fetchone()['question_id']

    # 复制题库并修改：加一题、改一题
    tmp_json = os.path.join(TMP_DIR, 'questions_test.json')
    shutil.copyfile(app_module.QUESTIONS_PATH, tmp_json)
    questions = json.load(open(tmp_json, encoding='utf-8'))
    questions.append({'category': '测试分类', 'q_type': 'tf', 'question': uniq('增量测试题'),
                      'options': ['正确', '错误'], 'answer': 'A', 'explanation': '测试'})
    # 修改第一题的解析（内容变化 → 哈希变化）
    old_q = dict(questions[0])
    questions[0] = {**old_q, 'explanation': old_q['explanation'] + '（修订）'}
    json.dump(questions, open(tmp_json, 'w', encoding='utf-8'), ensure_ascii=False)

    monkeypatch.setattr(app_module, 'QUESTIONS_PATH', tmp_json)
    app_module.load_questions()

    after_sessions = db.execute('SELECT COUNT(*) FROM quiz_sessions').fetchone()[0]
    after_answers = db.execute('SELECT COUNT(*) FROM answers').fetchone()[0]
    after_qcount = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]

    assert after_sessions == before_sessions, '同步不应清空答题会话'
    assert after_answers == before_answers, '同步不应清空答题记录'
    assert after_qcount >= before_qcount  # 新增1题；被修改的旧题因被引用而保留
    # 新题已入库
    added = db.execute("SELECT COUNT(*) FROM questions WHERE category='测试分类'").fetchone()[0]
    assert added == 1
    # 历史答题记录仍能关联到题目（成绩详情完整）
    linked = db.execute(
        'SELECT COUNT(*) FROM answers a JOIN questions q ON a.question_id = q.id').fetchone()[0]
    assert linked == after_answers


# ==================== 管理端 ====================

def admin_login(client, password='admin123'):
    return client.post('/admin/login', json={'password': password}).get_json()


def test_admin_auth_and_password_change(client):
    # 未登录访问被拦截
    res = client.get('/admin')
    assert res.status_code == 302

    res = client.get('/admin/data')
    assert res.status_code == 302

    # 错误密码
    assert admin_login(client, 'wrong')['success'] is False
    # 正确密码
    assert admin_login(client)['success'] is True

    # 修改密码：原密码错误
    res = client.post('/admin/change_password', json={'old_password': 'bad', 'new_password': 'newpass6'}).get_json()
    assert not res['success']
    # 修改成功
    res = client.post('/admin/change_password', json={'old_password': 'admin123', 'new_password': 'newpass6'}).get_json()
    assert res['success']
    # 新密码登录
    client.get('/admin/logout')
    assert admin_login(client, 'admin123')['success'] is False
    assert admin_login(client, 'newpass6')['success'] is True
    # 改回默认，避免影响其他测试
    client.post('/admin/change_password', json={'old_password': 'newpass6', 'new_password': 'admin123'})


def test_admin_data_and_statistics(client):
    admin_login(client)
    data = client.get('/admin/data').get_json()
    assert 'sessions' in data and 'stats' in data
    assert data['stats']['question_count'] >= 1700

    stats = client.get('/admin/statistics').get_json()
    assert 'score_distribution' in stats and 'class_stats' in stats

    export = client.get('/admin/export')
    assert export.status_code == 200
    assert export.data[:2] == b'PK'  # xlsx 是 zip 包


def test_admin_sync_questions(client):
    admin_login(client)
    # 未登录不可访问
    client.get('/admin/logout')
    assert client.post('/admin/sync_questions').status_code == 302
    admin_login(client)

    # 前面的增量同步测试会污染数据库（指向临时题库文件），先把数据库归位到真实文件
    app_module.load_questions()

    # 题库文件与数据库一致时应返回 skipped
    res = client.post('/admin/sync_questions').get_json()
    assert res['success']
    assert res['skipped'] is True
    assert res['total'] >= 1700

    # 修改题库文件（追加一题）后应能检测到变化并同步
    import json as _json
    with open('questions.json', encoding='utf-8') as f:
        original_text = f.read()
    backup = _json.loads(original_text)
    try:
        new_q = {'category': '硬件资讯与新品动态', 'q_type': 'tf',
                 'question': '【测试】同步接口专用临时题目。',
                 'options': ['正确', '错误'], 'answer': 'A',
                 'explanation': '测试后会被还原。'}
        backup.append(new_q)
        with open('questions.json', 'w', encoding='utf-8') as f:
            _json.dump(backup, f, ensure_ascii=False, indent=2)
        res = client.post('/admin/sync_questions').get_json()
        assert res['success'] and res['skipped'] is False
        assert res['added'] == 1
        # 再同步一次回到无变化状态
        res2 = client.post('/admin/sync_questions').get_json()
        assert res2['skipped'] is True
    finally:
        # 逐字还原题库文件并再次同步，让数据库也回到原状态
        with open('questions.json', 'w', encoding='utf-8') as f:
            f.write(original_text)
        client.post('/admin/sync_questions')


def test_admin_class_crud(client):
    admin_login(client)
    cname = uniq('测试班级')
    res = client.post('/admin/classes', json={'class_name': cname}).get_json()
    assert res['success']
    # 重名拒绝
    assert not client.post('/admin/classes', json={'class_name': cname}).get_json()['success']

    classes = client.get('/admin/classes').get_json()['classes']
    target = next(c for c in classes if c['class_name'] == cname)
    # 改名
    new_name = cname + '改'
    assert client.put(f"/admin/classes/{target['id']}", json={'class_name': new_name}).get_json()['success']
    # 无学生可删
    assert client.delete(f"/admin/classes/{target['id']}").get_json()['success']
    assert not client.delete(f"/admin/classes/{target['id']}").get_json()['success']


def test_admin_login_throttle(client):
    # 连续5次失败后应被限流
    for _ in range(5):
        client.post('/admin/login', json={'password': 'bad'})
    res = client.post('/admin/login', json={'password': 'admin123'})
    assert res.status_code == 429
    # 清理限流状态，避免影响其他测试
    app_module.LOGIN_ATTEMPTS.clear()


def test_xss_name_survives_roundtrip(client):
    """含HTML的姓名应能正常注册并原样返回（由前端负责转义渲染）"""
    evil_name = '<b>x</b>' + uniq('')
    login_student(client, name=evil_name, class_name='XSS测试班')
    client.post('/start_quiz')
    client.get('/get_questions')
    client.post('/submit_quiz')
    admin_login(client)
    data = client.get('/admin/data').get_json()
    assert any(s['name'] == evil_name for s in data['sessions'])


# ==================== 北京时间显示 ====================

def test_to_beijing_conversion():
    """UTC 时间字符串应正确转换为东八区时间"""
    assert app_module.to_beijing('2026-08-27 04:30:00') == '2026-08-27 12:30:00'
    assert app_module.to_beijing('2026-01-01 16:00:00') == '2026-01-02 00:00:00'  # 跨日
    assert app_module.to_beijing('') == ''
    assert app_module.to_beijing(None) is None
    assert app_module.to_beijing('garbage') == 'garbage'  # 异常格式原样返回


def test_my_scores_returns_beijing_time(client):
    """历史成绩接口返回的时间应为北京时间（与库内 UTC 相差 8 小时）"""
    name = login_student(client, class_name='时区测试班')
    client.post('/start_quiz')
    client.get('/get_questions')
    client.post('/submit_quiz')
    data = client.get('/my_scores').get_json()
    assert data['success']
    with sqlite3.connect(os.environ['QUIZ_DB_PATH']) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT submitted_at FROM quiz_sessions WHERE status = ? '
            'ORDER BY id DESC LIMIT 1', ('completed',)).fetchone()
        utc_time = row['submitted_at']
    api_time = next(s['submitted_at'] for s in data['scores'])
    from datetime import datetime, timedelta
    delta = (datetime.strptime(api_time, '%Y-%m-%d %H:%M:%S')
             - datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S'))
    assert delta == timedelta(hours=8)


# ==================== 花名册模式与学生管理 ====================

def _set_roster_mode(enabled):
    with app_module.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('roster_mode', ?)",
                     ('1' if enabled else '0',))
        conn.commit()


def test_roster_mode_blocks_unlisted_login(client):
    """花名册模式下，名单外姓名应被拒绝登录"""
    _set_roster_mode(True)
    try:
        res = client.post('/login', json={'name': '捣蛋鬼' + uniq(''), 'class_name': '花名册测试班'})
        data = res.get_json()
        assert not data['success']
        assert '名单' in data['message']
    finally:
        _set_roster_mode(False)


def test_admin_student_crud_and_merge(client):
    admin_login(client)
    cls = uniq('管理班')

    # 单个添加 + 重复拒绝
    assert client.post('/admin/students', json={'name': '张小明', 'class_name': cls}).get_json()['success']
    assert not client.post('/admin/students', json={'name': '张小明', 'class_name': cls}).get_json()['success']

    # 批量导入：去空行、去重、跳过已有
    res = client.post('/admin/students/bulk',
                      json={'class_name': cls, 'names': '李大聪\n王二妞\n  \n张小明'}).get_json()
    assert res['success'] and res['added'] == 2 and res['skipped'] == ['张小明']

    # 花名册模式下名单内学生可登录
    _set_roster_mode(True)
    try:
        res = client.post('/login', json={'name': '张小明', 'class_name': cls})
        assert res.get_json()['success']
        client.get('/logout')
    finally:
        _set_roster_mode(False)

    students = client.get('/admin/students').get_json()['students']
    ids = {s['name']: s['id'] for s in students if s['class_name'] == cls}
    assert set(ids) == {'张小明', '李大聪', '王二妞'}

    # 编辑改名
    res = client.put(f"/admin/students/{ids['王二妞']}", json={'name': '王二妞2', 'class_name': cls})
    assert res.get_json()['success']

    # 合并账号：李大聪 并入 张小明
    res = client.post('/admin/students/merge',
                      json={'source_id': ids['李大聪'], 'target_id': ids['张小明']})
    assert res.get_json()['success']
    students = client.get('/admin/students').get_json()['students']
    names = {s['name'] for s in students if s['class_name'] == cls}
    assert '李大聪' not in names and '张小明' in names

    # 重置经验
    res = client.post(f"/admin/students/{ids['张小明']}/reset_xp")
    assert res.get_json()['success']

    # 删除账号级联清理（删除改名后的王二妞2 和 张小明）
    for sid in (ids['王二妞'], ids['张小明']):
        res = client.delete(f"/admin/students/{sid}")
        assert res.get_json()['success']
    students = client.get('/admin/students').get_json()['students']
    assert not any(s['class_name'] == cls for s in students)
    with sqlite3.connect(os.environ['QUIZ_DB_PATH']) as conn:
        left = conn.execute(
            'SELECT COUNT(*) FROM quiz_sessions qs JOIN students s ON qs.student_id = s.id '
            'WHERE s.class_name = ?', (cls,)).fetchone()[0]
    assert left == 0


def test_roster_mode_toggle_via_settings(client):
    """管理端可切换花名册模式开关"""
    admin_login(client)
    res = client.post('/admin/settings', json={'roster_mode': True}).get_json()
    assert res['success']
    data = client.get('/admin/settings').get_json()
    assert data['roster_mode'] is True
    res = client.post('/admin/settings', json={'roster_mode': False}).get_json()
    assert res['success']
    data = client.get('/admin/settings').get_json()
    assert data['roster_mode'] is False


# ==================== 考试管控 ====================

def _set_exam_controls(start='', end='', attempts='0'):
    with app_module.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('exam_window_start', ?)", (start,))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('exam_window_end', ?)", (end,))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('exam_max_attempts', ?)", (attempts,))
        conn.commit()


def _fmt(dt):
    return dt.strftime('%Y-%m-%d %H:%M')


def test_exam_window_blocks_outside_hours(client):
    """考试开放时段外拒绝开考，时段内允许，练习不受影响"""
    from datetime import timedelta
    login_student(client, class_name='窗口测试班')
    try:
        # 未到开始时间
        _set_exam_controls(start=_fmt(app_module.beijing_now() + timedelta(minutes=10)))
        data = client.post('/start_quiz').get_json()
        assert not data['success'] and '还未开始' in data['message']
        # 练习不受窗口限制
        cats = client.get('/api/categories').get_json()['categories']
        data = client.post('/start_practice', json={'source': 'category', 'category': cats[0]['category'], 'count': 5}).get_json()
        assert data['success']
        client.post('/submit_quiz')
        # 已过结束时间
        _set_exam_controls(end=_fmt(app_module.beijing_now() - timedelta(minutes=10)))
        data = client.post('/start_quiz').get_json()
        assert not data['success'] and '结束' in data['message']
        # 窗口内正常开考
        _set_exam_controls(start=_fmt(app_module.beijing_now() - timedelta(minutes=10)),
                           end=_fmt(app_module.beijing_now() + timedelta(minutes=90)))
        data = client.post('/start_quiz').get_json()
        assert data['success']
        client.post('/submit_quiz')
    finally:
        _set_exam_controls()


def test_exam_max_attempts(client):
    """考试次数达到上限后拒绝再次开考"""
    login_student(client, class_name='次数测试班')
    try:
        _set_exam_controls(attempts='1')
        assert client.post('/start_quiz').get_json()['success']
        client.post('/submit_quiz')
        data = client.post('/start_quiz').get_json()
        assert not data['success'] and '上限' in data['message']
        # 练习不受次数限制
        cats = client.get('/api/categories').get_json()['categories']
        assert client.post('/start_practice', json={'source': 'category', 'category': cats[0]['category'], 'count': 5}).get_json()['success']
        client.post('/submit_quiz')
    finally:
        _set_exam_controls()


def test_switch_reporting_exam_only(client):
    """切屏上报：考试模式累加计数，练习模式忽略"""
    login_student(client, class_name='切屏测试班')
    client.post('/start_quiz')
    client.post('/report_switch')
    client.post('/report_switch')
    with sqlite3.connect(os.environ['QUIZ_DB_PATH']) as conn:
        sid = conn.execute('SELECT id FROM quiz_sessions ORDER BY id DESC LIMIT 1').fetchone()[0]
        cnt = conn.execute('SELECT switch_count FROM quiz_sessions WHERE id = ?', (sid,)).fetchone()[0]
    assert cnt == 2
    client.post('/submit_quiz')

    # 练习模式上报应被忽略
    cats = client.get('/api/categories').get_json()['categories']
    client.post('/start_practice', json={'source': 'category', 'category': cats[0]['category'], 'count': 5})
    client.post('/report_switch')
    with sqlite3.connect(os.environ['QUIZ_DB_PATH']) as conn:
        sid = conn.execute('SELECT id FROM quiz_sessions ORDER BY id DESC LIMIT 1').fetchone()[0]
        cnt = conn.execute('SELECT switch_count FROM quiz_sessions WHERE id = ?', (sid,)).fetchone()[0]
    assert cnt == 0
    client.post('/submit_quiz')


def test_admin_live_monitor(client):
    """实时监考接口：能看到进行中的考试会话与管控设置"""
    admin_login(client)
    name = login_student(client, class_name='监考测试班')
    client.post('/start_quiz')
    data = client.get('/admin/live').get_json()
    assert data['success']
    assert any(s['name'] == name and (s['mode'] or 'exam') == 'exam' for s in data['sessions'])
    assert 'window' in data and 'max_attempts' in data
    client.post('/submit_quiz')
    data = client.get('/admin/live').get_json()
    assert not any(s['name'] == name for s in data['sessions'])


# ==================== 学情分析 ====================

def test_admin_analytics_category_and_wrong(client):
    """分类正确率与高频错题榜：考试与练习口径可切换"""
    admin_login(client)
    data = client.get('/admin/analytics?mode=exam').get_json()
    assert data['success'] and data['mode'] == 'exam'
    # 前面测试产生过考试数据，应有分类统计
    assert len(data['category_accuracy']) > 0
    for c in data['category_accuracy']:
        assert 0 <= c['accuracy'] <= 100
        assert c['attempts'] >= c['correct'] >= 0
    assert isinstance(data['top_wrong'], list)

    data = client.get('/admin/analytics?mode=practice').get_json()
    assert data['success'] and data['mode'] == 'practice'

    # 非法 mode 归一化为 exam
    data = client.get('/admin/analytics?mode=xxx').get_json()
    assert data['mode'] == 'exam'


def test_admin_student_trend(client):
    """学生成长曲线：考试序列与按日累计经验"""
    admin_login(client)
    name = login_student(client, class_name='成长曲线班')
    with sqlite3.connect(os.environ['QUIZ_DB_PATH']) as conn:
        conn.row_factory = sqlite3.Row
        sid = conn.execute('SELECT id FROM students WHERE name = ?', (name,)).fetchone()['id']

    data = client.get(f'/admin/student_trend/{sid}').get_json()
    assert data['success']
    assert data['student']['name'] == name
    assert 'exams' in data and 'xp_daily' in data and 'total_xp' in data

    # 不存在的学生
    data = client.get('/admin/student_trend/999999').get_json()
    assert not data['success']


# ==================== 战斗竞技场（PVE 闯关 / PVP 影子对战） ====================

BATTLE_CLASS = uniq('竞技场班')


def answer_battle_session(client, db, wrong_count=0):
    """当前战斗会话按正确答案作答（前 wrong_count 题故意答错），返回交卷结果。"""
    data = client.get('/get_questions').get_json()
    assert data['success']
    qids = [q['id'] for q in data['questions']]
    correct_map = {row['id']: row['answer'] for row in
                   db.execute('SELECT id, answer FROM questions').fetchall()}
    for i, qid in enumerate(qids):
        ans = ('B' if correct_map[qid] != 'B' else 'A') if i < wrong_count else correct_map[qid]
        r = client.post('/save_answer', json={'question_id': qid, 'answer': ans}).get_json()
        assert r['success']
        # PVP 模式只回对错不回答案；battle 模式回完整反馈
        if data['mode'] == 'pvp':
            assert 'battle_feedback' in r and 'answer' not in r['battle_feedback']
            if r['battle_feedback']['correct']:
                assert 'practice_feedback' not in r
        else:
            assert 'practice_feedback' in r
    return client.post('/submit_quiz').get_json()


def test_arena_stage_flow_and_star_bonus(client, db):
    """PVE 闯关：顺序解锁、星级结算、三星计入平时成绩加成。"""
    login_student(client, class_name=BATTLE_CLASS)
    arena = client.get('/api/arena').get_json()
    assert arena['success']
    assert arena['stages'] and arena['star_bonus']['stages'] >= 1
    # 关卡顺序解锁：第一关默认开放
    assert arena['stages'][0]['unlocked'] is True
    assert arena['stages'][1]['unlocked'] is False

    stage = next(s for s in arena['stages'] if s['count'] >= app_module.BATTLE_QUESTIONS_PER_STAGE)
    # 未通关上一关时后续关被拒
    later = next(s for s in arena['stages'] if s['no'] > stage['no'])
    res = client.post('/start_battle', json={'type': 'stage', 'category': later['category']}).get_json()
    assert not res['success']

    res = client.post('/start_battle', json={'type': 'stage', 'category': stage['category']}).get_json()
    assert res['success']
    data = client.get('/get_questions').get_json()
    assert data['mode'] == 'battle'
    assert data['battle_meta'] == {'type': 'battle'}
    assert len(data['questions']) == app_module.BATTLE_QUESTIONS_PER_STAGE

    # 全对 → 三星
    sub = answer_battle_session(client, db, wrong_count=0)
    assert sub['success']
    assert sub['battle']['type'] == 'battle'
    assert sub['battle']['stars'] == 3
    assert sub['battle']['new_best'] is True
    # 战斗模式照常发经验
    assert sub['xp']['gained'] > 0

    arena = client.get('/api/arena').get_json()
    done = next(s for s in arena['stages'] if s['category'] == stage['category'])
    assert done['stars'] == 3
    assert arena['star_bonus']['star3'] == 1
    assert arena['star_bonus']['bonus'] > 0

    # 第二关现在解锁
    assert next(s for s in arena['stages'] if s['no'] == stage['no'] + 1)['unlocked'] is True


def test_arena_stage_defeat_and_two_stars(client, db):
    """PVE 闯关：答对 7/10 得两星，答对 5/10 战败 0 星（不足 60% 不通关）。"""
    login_student(client, class_name=BATTLE_CLASS)
    arena = client.get('/api/arena').get_json()
    stage = next(s for s in arena['stages'] if s['unlocked'] and s['count'] >= app_module.BATTLE_QUESTIONS_PER_STAGE)
    assert client.post('/start_battle', json={'type': 'stage', 'category': stage['category']}).get_json()['success']
    sub = answer_battle_session(client, db, wrong_count=3)
    assert sub['battle']['stars'] == 2

    stage = next(s for s in client.get('/api/arena').get_json()['stages']
                 if s['unlocked'] and s['count'] >= app_module.BATTLE_QUESTIONS_PER_STAGE and s['stars'] == 0)
    assert client.post('/start_battle', json={'type': 'stage', 'category': stage['category']}).get_json()['success']
    sub = answer_battle_session(client, db, wrong_count=5)
    assert sub['battle']['stars'] == 0
    # 战败不推进解锁进度
    fresh = client.get('/api/arena').get_json()
    assert next(s for s in fresh['stages'] if s['category'] == stage['category'])['stars'] == 0


def test_arena_record_and_shadow_challenge(client, db):
    """PVP：排位赛录制影子 → 同班同学挑战影子，天梯双方计分。"""
    defender = login_student(client, class_name=BATTLE_CLASS)
    res = client.post('/start_battle', json={'type': 'record'}).get_json()
    assert res['success']
    data = client.get('/get_questions').get_json()
    assert data['mode'] == 'pvp'
    assert data['battle_meta']['type'] == 'record'
    # PVP 不泄露答案
    assert data.get('feedback') == {}
    sub = answer_battle_session(client, db, wrong_count=2)
    assert sub['battle']['type'] == 'record'
    assert sub['battle']['correct'] == app_module.BATTLE_QUESTIONS_PER_STAGE - 2

    # 影子已可被同班同学看到
    challenger = login_student(client, class_name=BATTLE_CLASS)
    arena = client.get('/api/arena').get_json()
    foes = [o for o in arena['opponents'] if o['name'] == defender]
    assert foes and foes[0]['correct_count'] == sub['battle']['correct']

    res = client.post('/start_battle', json={'type': 'challenge', 'defender_id': foes[0]['student_id']}).get_json()
    assert res['success']
    data = client.get('/get_questions').get_json()
    assert data['battle_meta']['type'] == 'challenge'
    assert data['battle_meta']['defender_name'] == defender
    assert data['battle_meta']['ghost']['events']

    # 挑战者全对 → 判胜，双方天梯落库
    sub = answer_battle_session(client, db, wrong_count=0)
    assert sub['battle']['type'] == 'challenge'
    assert sub['battle']['result'] == 'win'
    assert sub['battle']['points_delta'] == app_module.LADDER_POINTS['win']

    with sqlite3.connect(os.environ['QUIZ_DB_PATH']) as conn:
        conn.row_factory = sqlite3.Row
        did = conn.execute('SELECT id FROM students WHERE name = ?', (defender,)).fetchone()['id']
        cid = conn.execute('SELECT id FROM students WHERE name = ?', (challenger,)).fetchone()['id']
        d = conn.execute('SELECT * FROM pvp_ladder WHERE student_id = ?', (did,)).fetchone()
        c = conn.execute('SELECT * FROM pvp_ladder WHERE student_id = ?', (cid,)).fetchone()
        assert d['losses'] == 1 and d['points'] == app_module.LADDER_POINTS['loss']
        assert c['wins'] == 1 and c['points'] == app_module.LADDER_POINTS['win']

    ladder = client.get('/api/arena').get_json()
    assert ladder['my_ladder']['wins'] == 1
    assert any(r['name'] == challenger and r['is_me'] for r in ladder['ladder']) or ladder['my_ladder']['rank']


def test_arena_dummy_battle_no_ladder(client, db):
    """训练假人：可挑战、判胜负，但假人不计天梯分。"""
    login_student(client, class_name=BATTLE_CLASS)
    res = client.post('/start_battle', json={'type': 'dummy', 'tier': 1}).get_json()
    assert res['success']
    data = client.get('/get_questions').get_json()
    assert data['battle_meta']['type'] == 'challenge'
    assert data['battle_meta']['is_dummy'] is True
    assert data['battle_meta']['defender_name'].startswith('训练假人')

    # 青铜假人答对 4 题，挑战者全对必胜
    sub = answer_battle_session(client, db, wrong_count=0)
    assert sub['battle']['result'] == 'win'
    assert sub['battle']['points_delta'] == 0
    assert sub['battle']['is_dummy'] is True
    assert client.get('/api/arena').get_json()['my_ladder']['points'] == 0


def test_battle_toggle_by_admin(client):
    """老师开关：关闭后竞技场入口与开局均被拒，开启后恢复。"""
    login_student(client, class_name=BATTLE_CLASS)
    admin_login(client)
    res = client.post('/admin/settings', json={'battle_enabled': False}).get_json()
    assert res['success']
    # 管理端监控接口回传开关状态
    assert client.get('/admin/live').get_json()['battle_enabled'] is False

    arena = client.get('/api/arena').get_json()
    assert not arena['success'] and arena.get('disabled')
    res = client.post('/start_battle', json={'type': 'record'}).get_json()
    assert not res['success']

    client.post('/admin/settings', json={'battle_enabled': True})
    assert client.get('/api/arena').get_json()['success'] is True


def test_battle_idempotent_submit(client, db):
    """战斗交卷幂等：重复交卷不再叠加星级/进度。"""
    login_student(client, class_name=BATTLE_CLASS)
    arena = client.get('/api/arena').get_json()
    stage = next(s for s in arena['stages'] if s['unlocked'] and s['count'] >= app_module.BATTLE_QUESTIONS_PER_STAGE)
    assert client.post('/start_battle', json={'type': 'stage', 'category': stage['category']}).get_json()['success']
    sub = answer_battle_session(client, db, wrong_count=0)
    assert sub['battle'] is not None
    # 已完成的会话再交卷：不产生新的战斗结算
    again = client.post('/submit_quiz').get_json()
    assert not again['success'] or again.get('battle') is None
    fresh = client.get('/api/arena').get_json()
    row = next(s for s in fresh['stages'] if s['category'] == stage['category'])
    assert row['times'] == 1
