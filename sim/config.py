# -*- coding: utf-8 -*-
"""
模拟器考试模块 —— 常量与权重配置。

总评构成（教师已确认）：
    总评 100% = 平时分 50% + 考试分 50%
    考试分 50% = 实操装机 25%（教师现场评分后手动录入）
                 + BIOS 模拟 12.5%
                 + WinPE 模拟 12.5%
"""

# ==================== 模拟器类型 ====================
SIM_TYPES = ('bios', 'winpe')

SIM_LABELS = {
    'bios': 'BIOS 设置模拟',
    'winpe': 'WinPE 装机维护模拟',
}

# 默认考试时长（分钟），可通过 settings 表覆盖，无需改代码
DEFAULT_MINUTES = {
    'bios': 20,
    'winpe': 30,
}

# ==================== 总评权重 ====================
W_REGULAR = 0.5    # 平时分（沿用刷题系统的等级折算 + 竞技场星级加成）
W_MANUAL = 0.25    # 实操装机（教师手录）
W_BIOS = 0.125     # BIOS 模拟操作分
W_WINPE = 0.125    # WinPE 模拟操作分

WEIGHTS = {
    'regular': W_REGULAR,
    'manual': W_MANUAL,
    'bios': W_BIOS,
    'winpe': W_WINPE,
}

# ==================== settings 表的键 ====================
# 教师可在管理后台修改，避免为了调个时长改代码重启服务
K_BIOS_MINUTES = 'sim_bios_minutes'
K_WINPE_MINUTES = 'sim_winpe_minutes'
K_SWITCH_LIMIT = 'sim_switch_limit'          # 切屏告警阈值，0 = 只记录不告警
K_REGULAR_FROZEN = 'sim_regular_frozen'      # 平时分是否已冻结快照
K_BIOS_WINDOW_START = 'sim_bios_window_start'
K_BIOS_WINDOW_END = 'sim_bios_window_end'
K_WINPE_WINDOW_START = 'sim_winpe_window_start'
K_WINPE_WINDOW_END = 'sim_winpe_window_end'

MINUTES_KEY = {
    'bios': K_BIOS_MINUTES,
    'winpe': K_WINPE_MINUTES,
}

WINDOW_KEY = {
    'bios': (K_BIOS_WINDOW_START, K_BIOS_WINDOW_END),
    'winpe': (K_WINPE_WINDOW_START, K_WINPE_WINDOW_END),
}

# ==================== 事件上报限制 ====================
EVENT_BATCH_MAX = 50        # 单次批量上报事件上限
EVENT_MAX_T_MS = 24 * 3600 * 1000   # 单条事件相对时间的合理上限（防伪造超大 t_ms）

# ==================== 会话状态 ====================
STATUS_IN_PROGRESS = 'in_progress'
STATUS_COMPLETED = 'completed'
STATUS_TIMEOUT = 'timeout'

# ==================== 会话模式 ====================
MODE_EXAM = 'exam'        # 正式考试（受唯一索引约束，限考 1 次）
MODE_PRACTICE = 'practice'  # 练习（不计分，可无限次）
MODE_VOIDED = 'voided'    # 教师作废（解除唯一索引约束，保留审计）

# ==================== 事件类型 ====================
KIND_SET = 'set'              # 状态字段变更（Proxy 自动埋点）
KIND_ACTION = 'action'        # 动作：loadDefaults / saveExit / discardExit / saveOnly
KIND_NAV = 'nav'              # 导航：切换页签、进入/退出子菜单
KIND_KEY = 'key'              # 功能键：F9 / F10 / F12
KIND_STEP = 'step'            # 关键操作结果：dg.quick / setup.install / cdi.submit ...
KIND_SNAPSHOT = 'snapshot'    # 兜底全量快照（对账用，不作为判分依据）
KIND_SWITCH = 'switch'        # 切屏
KIND_SUSPECT = 'suspect'      # 可疑行为（DevTools 等）
KIND_SUBMIT = 'submit'        # 交卷
