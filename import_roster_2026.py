# -*- coding: utf-8 -*-
"""一次性脚本：把 2026 下半年三个班级名单导入 quiz_app.db。

来源（C:\\Users\\LEGION\\Desktop\\2026年下半年班级名单）：
  26云计算-名单.xlsx        -> 2026级云计算技术应用
  26网安-名单.pdf           -> 2026级网络与信息安全班
  26计网-班级学生名单导出.pdf -> 2026级计算机网络应用

幂等：班级与同名学生已存在时跳过，可安全重跑。
用法：py import_roster_2026.py
"""
import re
import sqlite3
import sys
import os

import fitz  # PyMuPDF
import openpyxl

SRC_DIR = r'C:\Users\LEGION\Desktop\2026年下半年班级名单'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quiz_app.db')

# PDF 文本里混入的状态标注，不是姓名
STATUS_MARKS = {'计划休学', '暂未报到'}
NAME_RE = re.compile(r'^[\u4e00-\u9fa5·]{2,5}$')


def load_cloud():
    """云计算 Excel：第 4 行表头（序号/姓名），B 列为姓名直到空行。"""
    wb = openpyxl.load_workbook(os.path.join(SRC_DIR, '26云计算-名单.xlsx'))
    ws = wb.worksheets[0]
    names = []
    for row in ws.iter_rows(min_row=4):
        n = row[1].value
        if n is None:
            continue
        n = str(n).strip()
        if n and n != '姓名':
            names.append(n)
    return names


def load_pdf_names(path, expect_triples):
    """通用 PDF 名单解析。

    两个 PDF 的文本流都是「序号 换行 姓名 换行 (性别)」交替出现，
    性别列有无由 expect_triples 指定。状态标注（计划休学等）单独成行，
    归属于前一个学生，只记录不计入名单。
    """
    doc = fitz.open(path)
    text = '\n'.join(p.get_text() for p in doc)
    doc.close()

    names, statuses = [], {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        # 找一个数字行，其后紧跟姓名（可选性别）
        if lines[i].isdigit() and i + 1 < len(lines) and NAME_RE.match(lines[i + 1]):
            seq, name = int(lines[i]), lines[i + 1]
            i += 2
            if expect_triples and i < len(lines) and lines[i] in ('男', '女'):
                i += 1
            # 吃掉紧随其后的状态标注行（可能多行）
            while i < len(lines) and lines[i] in STATUS_MARKS:
                statuses[name] = lines[i]
                i += 1
            names.append(name)
        else:
            i += 1
    return names, statuses


def load_security():
    names, _ = load_pdf_names(os.path.join(SRC_DIR, '26网安-名单.pdf'), expect_triples=False)
    return names


def load_network():
    names, _ = load_pdf_names(os.path.join(SRC_DIR, '26计网-班级学生名单导出.pdf'), expect_triples=True)
    return names


def main():
    classes = [
        ('2026级云计算技术应用', load_cloud),
        ('2026级网络与信息安全班', load_security),
        ('2026级计算机网络应用', load_network),
    ]

    db = sqlite3.connect(DB_PATH)
    try:
        for class_name, loader in classes:
            names = loader()
            dup = len(names) - len(set(names))
            print(f'{class_name}: 解析到 {len(names)} 人' + (f'（重名 {dup} 个：已提示，将只导一份）' if dup else ''))

            cur = db.execute('INSERT OR IGNORE INTO classes (class_name) VALUES (?)', (class_name,))
            if cur.rowcount == 0:
                print(f'  班级已存在，跳过建班')

            existing = {r[0] for r in db.execute(
                'SELECT name FROM students WHERE class_name = ?', (class_name,))}
            added = 0
            for n in names:
                if n in existing:
                    continue
                db.execute('INSERT INTO students (name, class_name) VALUES (?, ?)', (n, class_name))
                existing.add(n)
                added += 1
            db.commit()
            print(f'  本次新增 {added} 人，跳过已存在 {len(names) - added} 人')

        print()
        for r in db.execute("""SELECT class_name, COUNT(*) FROM students
                               GROUP BY class_name ORDER BY class_name"""):
            print(f'库内现状：{r[0]} -> {r[1]} 人')

        # 特殊状态提示（计网班的休学/未报到）
        _, statuses = load_pdf_names(
            os.path.join(SRC_DIR, '26计网-班级学生名单导出.pdf'), expect_triples=True)
        if statuses:
            print()
            for name, st in statuses.items():
                print(f'注意：计算机网络应用班「{name}」名单标注为【{st}】，已一并导入；'
                      f'如不需参加可到管理后台删除')
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
