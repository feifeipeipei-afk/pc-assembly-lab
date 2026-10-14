# -*- coding: utf-8 -*-
"""对全库 mc 选项做确定性重排，使每分类答案字母分布尽量均匀。"""
import json
import os
import re
from collections import Counter, OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS_PATH = os.path.join(BASE, 'questions.json')

LOCK_RE = re.compile(r'以上|以下|都不|都是|全部|完全相同|均不|均可|都正确|都错误')
NUM_RE = re.compile(r'\d+(?:\.\d+)?')


def is_monotonic_numeric(options):
    nums = []
    for opt in options:
        found = NUM_RE.findall(opt)
        if len(found) != 1:
            return False
        try:
            nums.append(float(found[0]))
        except ValueError:
            return False
    return all(a < b for a, b in zip(nums, nums[1:]))


def main():
    qs = json.load(open(QUESTIONS_PATH, encoding='utf-8'))
    categories = OrderedDict()
    for q in qs:
        categories.setdefault(q['category'], []).append(q)

    moved = 0
    for cat, cat_qs in categories.items():
        counter = Counter()
        movable = []
        for q in cat_qs:
            if q['q_type'] != 'mc':
                continue
            opts = q['options']
            if (len(opts) != 4
                    or any(LOCK_RE.search(o) for o in opts)
                    or is_monotonic_numeric(opts)):
                counter[q['answer']] += 1
            else:
                movable.append(q)
        for q in movable:
            avail = ['A', 'B', 'C', 'D']
            target = min(avail, key=lambda L: (counter.get(L, 0), L))
            old_idx = ord(q['answer']) - 65
            new_idx = ord(target) - 65
            if old_idx != new_idx:
                correct = q['options'][old_idx]
                others = [o for i, o in enumerate(q['options']) if i != old_idx]
                q['options'] = others[:new_idx] + [correct] + others[new_idx:]
                q['answer'] = target
                moved += 1
            counter[target] += 1

    dist = Counter(q['answer'] for q in qs if q['q_type'] == 'mc')
    print('moved:', moved, '| dist:', ', '.join(f'{k}={v}' for k, v in sorted(dist.items())))
    with open(QUESTIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(qs, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
