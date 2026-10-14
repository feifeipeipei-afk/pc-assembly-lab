# -*- coding: utf-8 -*-
"""导出新题审阅文件：每题显示标注答案对应的选项文本，供人工核对。"""
import json
import glob
import io

out = io.StringIO()
for path in sorted(glob.glob('scripts/new_questions/*.json')):
    batch = json.load(open(path, encoding='utf-8'))
    out.write(f'===== {path} ({len(batch)}) =====\n')
    for i, q in enumerate(batch, 1):
        if q['q_type'] == 'mc':
            ans_text = q['options'][ord(q['answer']) - 65]
        elif q['q_type'] == 'multi':
            ans_text = '、'.join(q['options'][ord(l) - 65] for l in q['answer'])
        else:
            ans_text = '正确' if q['answer'] == 'A' else '错误'
        out.write(f'{i}. [{q["q_type"]}] {q["question"]}\n   => {q["answer"]}: {ans_text}\n')
    out.write('\n')
open('new_review.txt', 'w', encoding='utf-8').write(out.getvalue())
print('written new_review.txt')
