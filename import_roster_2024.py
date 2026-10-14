# -*- coding: utf-8 -*-
"""一次性脚本：把「2024级数字康养技术应用」班级名单导入 quiz_app.db。

数据来源（默认路径，可用命令行参数覆盖）：
    C:/Users/y/Desktop/2024级数字康养技术应用   .xlsx

实现说明：
    - 仅使用 Python 标准库（zipfile + xml.etree + sqlite3），零第三方依赖。
    - xlsx 本质是 zip 包，姓名存储在 sharedStrings.xml（字符串表）与各 worksheet xml 中，
      本脚本直接解析这两类 XML，避免依赖 openpyxl。
    - 优先读取 Excel 的 Sheet2（单列 A = 姓名），若该表缺失则从 Sheet1 的
      左右两张子表（B 列 / F 列）兜底解析；两处内容均为同一 23 人。
    - 写入前自动备份 quiz_app.db，导入逻辑幂等（班级/学生已存在则跳过），可安全重跑。

用法：
    py import_roster_2024.py
    py import_roster_2024.py "D:\其它路径\名单.xlsx"
"""
import os
import re
import shutil
import sqlite3
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

# ----------------------------------------------------------------------------
# 配置区（可按需修改）
# ----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, 'quiz_app.db')
CLASS_NAME = '2024级数字康养技术应用'
DEFAULT_EXCEL = r'C:\Users\y\Desktop\2024级数字康养技术应用   .xlsx'

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


# ----------------------------------------------------------------------------
# Excel 解析（标准库实现）
# ----------------------------------------------------------------------------
def _col_letter(ref):
    """从单元格引用（如 'B12'）中提取列字母。"""
    return re.match(r'[A-Z]+', ref).group()


def _row_number(ref):
    """从单元格引用（如 'B12'）中提取行号。"""
    return int(re.sub(r'[A-Z]', '', ref))


def _load_shared_strings(z):
    """读取 sharedStrings.xml，返回共享字符串列表。"""
    if 'xl/sharedStrings.xml' not in z.namelist():
        return []
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    strings = []
    for si in root.findall(NS + 'si'):
        # 一个 <si> 可能包含多个 <t>（富文本分段），拼接得到完整文本
        text = ''.join(t.text or '' for t in si.iter(NS + 't'))
        strings.append(text)
    return strings


def _read_sheet_cells(z, target, shared):
    """读取某个 worksheet，返回 {列字母: {行号: 单元格文本}}。"""
    root = ET.fromstring(z.read(target))
    cells = {}
    for c in root.iter(NS + 'c'):
        ref = c.get('r')
        t = c.get('t')            # 单元格类型：'s'=共享字符串, 'inlineStr'=内联字符串
        v = c.find(NS + 'v')
        isn = c.find(NS + 'is')
        value = None
        if t == 's' and v is not None:
            value = shared[int(v.text)]
        elif v is not None:
            value = v.text
        elif isn is not None:
            value = ''.join(x.text or '' for x in isn.iter(NS + 't'))
        col = _col_letter(ref)
        cells.setdefault(col, {})[_row_number(ref)] = (value or '').strip()
    return cells


def _sheet_file_map(z):
    """返回 {sheet显示名: 内部文件路径}，依据 workbook.xml + rels 映射。"""
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    rid_to_target = {r.get('Id'): r.get('Target') for r in rels}
    mapping = {}
    for s in wb.iter(NS + 'sheet'):
        name = s.get('name')
        rid = s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        target = rid_to_target.get(rid, '')
        if not target.startswith('xl/'):
            target = 'xl/' + target.lstrip('/')
        mapping[name] = target
    return mapping


def extract_names(path):
    """从 Excel 提取去重后的姓名列表。

    优先 Sheet2 单列 A；兜底 Sheet1 的 B 列与 F 列两张子表。
    """
    with zipfile.ZipFile(path) as z:
        shared = _load_shared_strings(z)
        sheets = _sheet_file_map(z)

        # 1) 优先：Sheet2 单列 A
        if 'Sheet2' in sheets:
            cells = _read_sheet_cells(z, sheets['Sheet2'], shared)
            col_a = cells.get('A', {})
            names = [col_a[r] for r in sorted(col_a)
                     if col_a[r] and col_a[r] != '姓名']
            if names:
                return _dedup(names)

        # 2) 兜底：Sheet1 的 B 列与 F 列两张子表
        if 'Sheet1' in sheets:
            cells = _read_sheet_cells(z, sheets['Sheet1'], shared)
            names = []
            for col in ('B', 'F'):
                col_cells = cells.get(col, {})
                for r in sorted(col_cells):
                    v = col_cells[r]
                    if v and v != '姓名':
                        names.append(v)
            if names:
                return _dedup(names)

    raise ValueError('未能从 Excel 中解析出任何姓名，请检查文件结构。')


def _dedup(names):
    """去空白、去空值、保序去重。"""
    seen, out = set(), []
    for n in names:
        n = (n or '').strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ----------------------------------------------------------------------------
# 数据库操作
# ----------------------------------------------------------------------------
def backup_db(db_path):
    """导入前完整备份数据库，返回备份文件路径。"""
    stamp = datetime.now().strftime('%Y%m%d')
    bak = f'{db_path}.bak-{stamp}'
    # 同日多次运行不覆盖旧备份，追加序号
    i = 1
    while os.path.exists(bak):
        bak = f'{db_path}.bak-{stamp}-{i}'
        i += 1
    shutil.copy2(db_path, bak)
    return bak


def main():
    excel_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXCEL
    if not os.path.exists(excel_path):
        print(f'[错误] Excel 文件不存在：{excel_path}')
        return 2
    if not os.path.exists(DB_PATH):
        print(f'[错误] 数据库文件不存在：{DB_PATH}')
        return 2

    # 1) 解析姓名
    names = extract_names(excel_path)
    print(f'已从 Excel 解析到 {len(names)} 名学生（班级：{CLASS_NAME}）')

    # 2) 备份
    bak = backup_db(DB_PATH)
    print(f'已备份数据库 -> {bak}')

    # 3) 写入（幂等）
    db = sqlite3.connect(DB_PATH)
    try:
        cur = db.execute(
            'INSERT OR IGNORE INTO classes (class_name) VALUES (?)', (CLASS_NAME,))
        class_new = cur.rowcount > 0
        print(f'班级处理：{"新建" if class_new else "已存在，跳过建班"}')

        existing = {r[0] for r in db.execute(
            'SELECT name FROM students WHERE class_name = ?', (CLASS_NAME,))}

        added, skipped = 0, 0
        for n in names:
            if n in existing:
                skipped += 1
                continue
            db.execute(
                'INSERT INTO students (name, class_name) VALUES (?, ?)',
                (n, CLASS_NAME))
            existing.add(n)
            added += 1
        db.commit()

        total = db.execute(
            'SELECT COUNT(*) FROM students WHERE class_name = ?',
            (CLASS_NAME,)).fetchone()[0]
        print(f'本次新增 {added} 人，跳过已存在 {skipped} 人')
        print(f'库内「{CLASS_NAME}」现共 {total} 人')
    finally:
        db.close()

    # 4) 完整性校验
    if total != len(names):
        print('[警告] 库内人数与解析人数不一致，请检查是否有重名被跳过。')
        return 1
    print('导入完成 ✅')
    return 0


if __name__ == '__main__':
    sys.exit(main())
