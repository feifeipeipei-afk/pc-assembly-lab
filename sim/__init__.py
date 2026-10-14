# -*- coding: utf-8 -*-
"""
模拟器考试模块（BIOS 设置模拟 + WinPE 装机维护模拟）。

把两个原本纯前端、成绩存在浏览器里的 HTML 模拟器，
改造成"操作事件上送服务端 → 服务端按 rubric 重放判分 → 成绩入库"的正式考试模块，
并接入刷题系统的学员名单与平时分体系。

挂载方式（由 app.py 在末尾调用，避免循环导入）：
    from sim import init_app
    init_app(app, {
        'get_db': get_db,
        'utcnow': utcnow,
        'beijing_now': beijing_now,
        'to_beijing': to_beijing,
        'add_column': _add_column,
        'regular_rows': _regular_score_rows,
    })
"""

__all__ = ['init_app']


def init_app(app, ctx):
    """在宿主 Flask 应用上挂载模拟器考试模块。"""
    from .ctx import setup
    setup(ctx)

    from . import schema
    schema.init_schema()

    from . import routes
    app.register_blueprint(routes.bp)

    print('[sim] 模拟器考试模块已挂载：/portal  /sim/bios  /sim/winpe  /admin/sim/*')
    return app
