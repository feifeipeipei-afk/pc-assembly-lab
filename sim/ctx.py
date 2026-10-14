# -*- coding: utf-8 -*-
"""
sim 模块的依赖注入容器。

为什么需要它：
    app.py 是一个 2700+ 行的脚本式单文件（不是包）。
    若 sim/routes.py 直接 `from app import get_db`，而 app.py 又要 `from sim import init_app`，
    就会形成循环导入（circular import）。

解决办法：
    app.py 在文件末尾（所有函数定义完成之后）调用 sim.init_app(app, {...})，
    把它自己的工具函数作为参数传进来。sim 内部只从本模块取用，永不 import app。
    这样 sim/grading.py 这类纯逻辑还能脱离 Flask 单独跑 pytest。
"""

_CTX = {}


def setup(ctx):
    """由 sim.init_app() 调用，注入宿主应用的依赖。"""
    _CTX.update(ctx)


def get(key):
    """取一个依赖；未注入时抛出明确错误，便于排查注册遗漏。"""
    try:
        return _CTX[key]
    except KeyError:
        raise RuntimeError(
            'sim 模块尚未初始化：缺少依赖 "%s"。请确认 app.py 末尾调用了 '
            'init_app(app, {...})。' % key
        )


def has(key):
    return key in _CTX
