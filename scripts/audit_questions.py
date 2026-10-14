# -*- coding: utf-8 -*-
"""
题库审计脚本：校验 schema、答案合法性、重复、前缀残留，统计答案分布。
用法: python scripts/audit_questions.py
报告写入 audit_report.txt，存在错误时退出码为 1。
"""
import json
import os
import re
import io
import sys
from collections import Counter, OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS_PATH = os.path.join(BASE, 'questions.json')
REPORT_PATH = os.path.join(BASE, 'audit_report.txt')

PREFIX_RE = re.compile(r'^[A-F]\s*[.、．]\s*')
NORM_RE = re.compile(r'\s+')

errors = []
warnings = []
report = io.StringIO()


def main():
    with open(QUESTIONS_PATH, encoding='utf-8') as f:
        qs = json.load(f)

    report.write(f'题库总量: {len(qs)} 道\n')

    required = {'category', 'q_type', 'question', 'options', 'answer', 'explanation'}
    seen_q = {}
    seen_text = {}
    cat_stats = OrderedDict()
    prev_cat = None
    seen_cats = set()

    for i, q in enumerate(qs, 1):
        tag = f'#{i}'

        # 字段完整性
        missing = required - set(q.keys())
        if missing:
            errors.append(f'{tag} 缺少字段: {missing}')
            continue
        if not q['question'].strip():
            errors.append(f'{tag} 题干为空')
        if not q['explanation'].strip():
            errors.append(f'{tag} 解析为空')
        if q['q_type'] not in ('mc', 'multi', 'tf'):
            errors.append(f'{tag} q_type 非法: {q["q_type"]}')

        # 选项
        opts = q['options']
        if q['q_type'] in ('mc', 'multi'):
            if len(opts) != 4:
                errors.append(f'{tag} {q["q_type"]} 选项数 {len(opts)}')
            if len(set(o.strip() for o in opts)) != len(opts):
                errors.append(f'{tag} 选项重复: {q["question"][:20]}')
        elif q['q_type'] == 'tf':
            if [o.strip() for o in opts] != ['正确', '错误']:
                errors.append(f'{tag} tf 选项非 [正确, 错误]: {opts}')

        # 答案
        if q['q_type'] == 'multi':
            ans = q['answer']
            if not (2 <= len(ans) <= 4 and ans == ''.join(sorted(set(ans)))
                    and set(ans) <= set('ABCD')):
                errors.append(f'{tag} multi 答案非法: {ans}')
                continue
        else:
            idx = ord(q['answer']) - 65 if len(q['answer']) == 1 else -1
            if not (0 <= idx < len(opts)):
                errors.append(f'{tag} 答案越界/非法: {q["answer"]}')
                continue

        # 前缀残留
        for o in opts:
            if PREFIX_RE.match(o):
                errors.append(f'{tag} 选项前缀残留: {o[:20]}')
                break

        # 题干重复
        norm = NORM_RE.sub('', q['question'])
        if norm in seen_q:
            errors.append(f'{tag} 与 #{seen_q[norm]} 题干重复: {q["question"][:24]}')
        seen_q[norm] = i

        # 分类连续性 + 分布统计
        cat = q['category']
        if prev_cat is not None and cat != prev_cat and cat in seen_cats:
            warnings.append(f'{tag} 分类 [{cat}] 重复出现（与上次出现之间隔了其他分类）')
        if cat not in cat_stats:
            cat_stats[cat] = Counter()
            seen_cats.add(cat)
        prev_cat = cat
        if q['q_type'] == 'mc':
            cat_stats[cat][q['answer']] += 1
        cat_stats[cat]['total'] += 1
        cat_stats[cat][{'mc': 'mc', 'multi': 'multi_n', 'tf': 'tf_n'}.get(q['q_type'], 'tf_n')] += 1

    # 分布统计
    overall = Counter(q['answer'] for q in qs if q['q_type'] == 'mc')
    report.write('\n== 总体答案分布（仅单选题） ==\n')
    total = sum(v for k, v in overall.items())
    for letter in 'ABCD':
        n = overall.get(letter, 0)
        bar = '#' * round(n / total * 50)
        report.write(f'  {letter}: {n:5d} ({n/total*100:5.1f}%) {bar}\n')

    report.write('\n== 分类统计 ==\n')
    for cat, c in cat_stats.items():
        tf_count = c.get('tf_n', 0)
        multi_count = c.get('multi_n', 0)
        letters = ', '.join(f'{l}={c.get(l, 0)}' for l in 'ABCD')
        report.write(f'  {cat}: 共{c["total"]}题 (multi {multi_count}, tf {tf_count}) | 单选 {letters}\n')

    report.write('\n== 错误 ==\n')
    report.write('\n'.join(errors) if errors else '  无')
    report.write('\n\n== 警告 ==\n')
    report.write('\n'.join(warnings) if warnings else '  无')
    report.write('\n')

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report.getvalue())

    print(f'errors={len(errors)} warnings={len(warnings)} -> {os.path.basename(REPORT_PATH)}')
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
