# -*- coding: utf-8 -*-
"""
校验题库一致性：新题以 scripts/new_questions/*.json 为基准，
检查题库中对应题目的"答案字母所指选项文本"与基准的正确选项文本是否一致。
输出所有错位条目。
"""
import json
import glob
import re

NORM = re.compile(r'\s+')


def norm(s):
    return NORM.sub('', s)


bank = json.load(open('questions.json', encoding='utf-8'))
bank_by_q = {}
for q in bank:
    bank_by_q[norm(q['question'])] = q

bad = []
checked = 0
for path in sorted(glob.glob('scripts/new_questions/*.json')):
    for src in json.load(open(path, encoding='utf-8')):
        key = norm(src['question'])
        b = bank_by_q.get(key)
        if not b:
            bad.append(('缺失', src['question'][:30], ''))
            continue
        checked += 1
        if src['q_type'] == 'multi' or b['q_type'] == 'multi':
            src_set = frozenset(norm(src['options'][ord(l) - 65]) for l in src['answer'])
            bank_set = frozenset(norm(b['options'][ord(l) - 65]) for l in b['answer'])
            if src_set != bank_set:
                bad.append(('错位', src['question'][:36],
                            f'库answer={b["answer"]} | 源answer={src["answer"]}'))
        else:
            src_correct = norm(src['options'][ord(src['answer']) - 65])
            bank_correct = norm(b['options'][ord(b['answer']) - 65])
            if src_correct != bank_correct:
                bad.append(('错位', src['question'][:36],
                            f'库answer={b["answer"]}:{bank_correct[:22]} | 源answer={src["answer"]}:{src_correct[:22]}'))

print(f'checked={checked} bad={len(bad)}')
for kind, q, detail in bad:
    print(f'[{kind}] {q} | {detail}')
