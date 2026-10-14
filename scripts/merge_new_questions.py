# -*- coding: utf-8 -*-
"""
合并新题：将 scripts/new_questions/*.json 校验后插入 questions.json 对应分类末尾。
校验：schema、选项数、答案范围、选项前缀、解析非空、与现有题库不重复。
"""
import json
import os
import re
import io
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS_PATH = os.path.join(BASE, 'questions.json')
NEW_DIR = os.path.join(BASE, 'scripts', 'new_questions')
REPORT_PATH = os.path.join(BASE, 'merge_report.txt')

PREFIX_RE = re.compile(r'^[A-F]\s*[.、．]\s*')
NORM_RE = re.compile(r'\s+')

report = io.StringIO()
errors = []


def log(msg=''):
    report.write(msg + '\n')


def validate(q, i, fname, seen_norm):
    tag = f'{fname}#{i}'
    if set(q.keys()) != {'category', 'q_type', 'question', 'options', 'answer', 'explanation'}:
        errors.append(f'{tag} 字段不完整: {sorted(q.keys())}')
        return
    if q['q_type'] not in ('mc', 'multi', 'tf'):
        errors.append(f'{tag} q_type 非法: {q["q_type"]}')
        return
    if not q['question'].strip() or not q['explanation'].strip():
        errors.append(f'{tag} 题干或解析为空')
    opts = q['options']
    if q['q_type'] == 'tf':
        if [o.strip() for o in opts] != ['正确', '错误']:
            errors.append(f'{tag} tf 选项非 [正确, 错误]')
    else:  # mc / multi
        if len(opts) != 4:
            errors.append(f'{tag} {q["q_type"]} 选项数 {len(opts)}')
        elif len(set(o.strip() for o in opts)) != 4:
            errors.append(f'{tag} 选项重复: {q["question"][:20]}')
    if q['q_type'] == 'multi':
        # 多选：答案为 2-4 个已排序去重的 A-D 字母
        ans = q['answer']
        if not (2 <= len(ans) <= 4 and ans == ''.join(sorted(set(ans)))
                and set(ans) <= set('ABCD')):
            errors.append(f'{tag} multi 答案非法: {ans}')
            return
    else:
        idx = ord(q['answer']) - 65 if len(q['answer']) == 1 else -1
        if not (0 <= idx < len(opts)):
            errors.append(f'{tag} 答案越界: {q["answer"]}')
            return
    for o in opts:
        if PREFIX_RE.match(o):
            errors.append(f'{tag} 选项含字母前缀: {o[:20]}')
            break
    norm = NORM_RE.sub('', q['question'])
    if norm in seen_norm:
        errors.append(f'{tag} 题干重复(新题之间): {q["question"][:24]}')
    seen_norm.add(norm)


def main():
    with open(QUESTIONS_PATH, encoding='utf-8') as f:
        qs = json.load(f)
    log(f'现有题库: {len(qs)} 道')

    seen_norm = {NORM_RE.sub('', q['question']) for q in qs}
    originals = set(seen_norm)

    files = sorted(f for f in os.listdir(NEW_DIR) if f.endswith('.json'))
    new_all = []
    for fname in files:
        with open(os.path.join(NEW_DIR, fname), encoding='utf-8') as f:
            batch = json.load(f)
        log(f'{fname}: {len(batch)} 题')
        for i, q in enumerate(batch, 1):
            validate(q, i, fname, seen_norm)
        new_all.extend(batch)

    if errors:
        log('\n校验失败:\n' + '\n'.join(errors))
        with open(REPORT_PATH, 'w', encoding='utf-8') as f:
            f.write(report.getvalue())
        print(f'FAILED errors={len(errors)}')
        sys.exit(1)

    # 与旧库重复检查（validate 已通过 seen_norm 覆盖新题之间与新旧之间）
    dup_with_old = sum(
        1 for q in new_all if NORM_RE.sub('', q['question']) in originals)
    log(f'与旧库重复的题干数: {dup_with_old}（应为 0）')

    # 插入到各分类最后一题之后；全新分类追加到题库末尾
    cat_last = {}
    for i, q in enumerate(qs):
        cat_last[q['category']] = i
    new_cats = sorted({q['category'] for q in new_all if q['category'] not in cat_last})
    inserted_cats = Counter()
    for q in sorted(new_all, key=lambda x: cat_last.get(x['category'], -1)):
        cat = q['category']
        if cat not in cat_last:
            # 新分类：直接追加到末尾（同批新分类的题保持稳定顺序）
            qs.append(q)
        else:
            pos = cat_last[cat] + 1
            qs.insert(pos, q)
        inserted_cats[cat] += 1
        cat_last = {}
        for i, item in enumerate(qs):
            cat_last[item['category']] = i

    log(f'\n合并后总量: {len(qs)}')
    for cat, n in inserted_cats.items():
        log(f'  {cat}: +{n}')
    if new_cats:
        log(f'新增分类（追加到题库末尾）: {", ".join(new_cats)}')

    type_dist = Counter(q['q_type'] for q in qs)
    log('合并后题型分布: ' + ', '.join(f'{k}={v}' for k, v in sorted(type_dist.items())))
    dist = Counter(q['answer'] for q in qs if q['q_type'] == 'mc')
    log('合并后 mc 答案分布: ' + ', '.join(f'{k}={v}' for k, v in sorted(dist.items())))

    with open(QUESTIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(qs, f, ensure_ascii=False, indent=2)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report.getvalue())
    print('MERGED OK')


if __name__ == '__main__':
    main()
