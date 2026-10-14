# -*- coding: utf-8 -*-
"""把「分题型」6 个 CSV 转换成题库可直接合并的「选择题」JSON。

转换规则（全部落成 app 支持的 mc / multi 题型）：
  02_单项选择题.csv      -> mc    选项去 "A、" 前缀，保留原答案字母
  03_多项选择题.csv      -> multi 选项去前缀，答案取字母集合（排序去重）；跳过残缺题
  04_判断题.csv          -> mc    用 _authored_exam.json 中改写的「下列说法正确/错误的是」四选项题
  01_填空题.csv          -> mc    正确答案=填空内容 + 3 个干扰项（_authored_exam.json）
  05_名词解释.csv        -> mc    正确释义 + 3 个干扰释义（_authored_exam.json）
  06_问答题.csv          -> 不导入（答案全是“略”）

内容来源：
  - 机械转换（单选/多选）：直接读 CSV。
  - 需要改写的题（填空/判断/名词）与全部解析：读 scripts/import_src/_authored_exam.json。
    该文件按「题号」索引：改写的题提供 correct + distractors + explanation（+ 可选 question 改写）；
    单选/多选只提供 explanation。

用法：
    py scripts/import_exam_csv.py [CSV目录]
输出：
    scripts/new_questions/exam_2026_assembly.json
"""
import csv
import json
import os
import re
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\y\Desktop\分题型'
AUTHORED_PATH = os.path.join(BASE, 'scripts', 'import_src', '_authored_exam.json')
OUT_PATH = os.path.join(BASE, 'scripts', 'new_questions', 'exam_2026_assembly.json')

CATEGORY = '计算机组装与维护'
PREFIX_RE = re.compile(r'^[A-F]\s*[.、．]\s*')   # 去掉 "A、" "B." 之类的选项前缀
NORM_RE = re.compile(r'\s+')

FILES = {
    'fill': '01_填空题.csv',
    'single': '02_单项选择题.csv',
    'multi': '03_多项选择题.csv',
    'judge': '04_判断题.csv',
    'term': '05_名词解释.csv',
}


def load_rows(fname):
    """读取一个 CSV，返回数据行列表（每行 11 列，异常行列数会 != 11）。"""
    path = os.path.join(CSV_DIR, fname)
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    return rows[1:]  # 去掉表头


def strip_prefix(s):
    return PREFIX_RE.sub('', (s or '').strip()).strip()


def place_options(correct, distractors, idx):
    """把正确项放到 idx 位置，其余位置按顺序填入干扰项，返回 (options, answer_letter)。"""
    opts = [None, None, None, None]
    opts[idx] = correct
    di = 0
    for i in range(4):
        if i != idx:
            opts[i] = distractors[di]
            di += 1
    return opts, 'ABCD'[idx]


def main():
    warnings, skipped = [], []
    out = []

    with open(AUTHORED_PATH, encoding='utf-8') as f:
        auth = json.load(f)

    # ---- 02 单项选择题 -> mc ----
    for r in load_rows(FILES['single']):
        if len(r) != 11:
            skipped.append(('row-count', r[:3])); continue
        tno, stem = r[1].strip(), r[3].strip()
        opts = [strip_prefix(x) for x in r[4:8]]
        ans = r[8].strip().upper()
        if ans not in 'ABCD' or len(opts) != 4 or len(set(opts)) != 4:
            skipped.append(('single-bad', tno)); continue
        expl = (auth.get(tno) or {}).get('explanation', '').strip()
        if not expl:
            warnings.append(f'{tno} 缺少解析')
        out.append((tno, {'category': CATEGORY, 'q_type': 'mc', 'question': stem,
                          'options': opts, 'answer': ans, 'explanation': expl}))

    # ---- 03 多项选择题 -> multi ----
    for r in load_rows(FILES['multi']):
        if len(r) != 11:
            skipped.append(('row-count', r[:3])); continue
        tno, stem = r[1].strip(), r[3].strip()
        opts = [strip_prefix(x) for x in r[4:8]]
        ans = ''.join(sorted(set(r[8].strip().upper())))
        if (not (2 <= len(ans) <= 4) or set(ans) - set('ABCD')
                or len(opts) != 4 or len(set(opts)) != 4):
            skipped.append(('multi-bad', tno)); continue
        expl = (auth.get(tno) or {}).get('explanation', '').strip()
        if not expl:
            warnings.append(f'{tno} 缺少解析')
        out.append((tno, {'category': CATEGORY, 'q_type': 'multi', 'question': stem,
                          'options': opts, 'answer': ans, 'explanation': expl}))

    # ---- 01 / 04 / 05 -> mc（内容取自 authored，correct+distractors 重新排位）----
    for key, fname in (('fill', FILES['fill']), ('judge', FILES['judge']), ('term', FILES['term'])):
        for r in load_rows(fname):
            if len(r) < 4:
                continue
            tno, stem = r[1].strip(), r[3].strip()
            a = auth.get(tno)
            if not a or 'correct' not in a:
                skipped.append(('no-authored', tno)); continue
            question = (a.get('question') or stem).strip()
            dist = [d.strip() for d in a['distractors']]
            if len(dist) != 3 or len(set([a['correct']] + dist)) != 4:
                skipped.append(('auth-bad', tno)); continue
            idx = int(tno) % 4
            opts, ans = place_options(a['correct'].strip(), dist, idx)
            out.append((tno, {'category': CATEGORY, 'q_type': 'mc', 'question': question,
                              'options': opts, 'answer': ans,
                              'explanation': a.get('explanation', '').strip()}))

    # ---- 自检：按题号稳定排序 + 批内题干去重 + 字段校验 ----
    out.sort(key=lambda x: x[0])
    seen, dedup = {}, []
    for tno, q in out:
        norm = NORM_RE.sub('', q['question'])
        if norm in seen:
            warnings.append(f'题干重复: {q["question"][:20]}')
            continue
        seen[norm] = True
        if not (q['question'].strip() and q['explanation'].strip() and len(q['options']) == 4):
            warnings.append(f'字段不完整: {q["question"][:20]}')
            continue
        dedup.append(q)

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(dedup, f, ensure_ascii=False, indent=2)

    tdist = Counter(q['q_type'] for q in dedup)
    print(f'输出: {os.path.relpath(OUT_PATH, BASE)}  共 {len(dedup)} 题  '
          f'(mc={tdist.get("mc", 0)}, multi={tdist.get("multi", 0)})')
    if skipped:
        print(f'跳过 {len(skipped)} 条:')
        for kind, info in skipped:
            print(f'  [{kind}] {info}')
    if warnings:
        print(f'警告 {len(warnings)} 条:')
        for w in warnings[:20]:
            print(f'  {w}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
