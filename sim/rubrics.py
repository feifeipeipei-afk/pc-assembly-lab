# -*- coding: utf-8 -*-
"""
模拟器考试 —— 评分细则（rubric）。

设计原则：
1. **版本化**：每套细则有版本号，随成绩一起写入 sim_sessions.rubric_version。
   考后若要调整细则，新增 bios-v2 而不是改 bios-v1，旧成绩不会被追溯篡改。
2. **可解释**：每一项都有 name（给学生看的评分项名）和 tip（没拿到分时的提示），
   教师端"单人明细"直接渲染 steps[]，学生能看懂自己哪一步错了。
3. **支持步骤前置依赖**：require 声明前驱项，前驱没做到给 partial 分而不是 0 分。
   例如"把 U 盘设为第一启动项"必须先进入 Boot Device Priority 子菜单——
   直接用全局快捷键改状态的，说明没走对流程，只给一半分。

难度定位：温州技师学院「计算机组装、维护与维修」课程，任务描述具体、
步骤可评分、结果可复现，不考偏题怪题。
"""

# ==================== BIOS 默认状态（与前端 DEFAULT_STATE 严格保持一致） ====================
# 前端在 static/sim/bios.html。改动此处必须同步改前端，否则服务端重放出的
# 状态与前端不一致，会误判。
BIOS_DEV = {
    'hdd': 'ATA HDD0: WDC WD5000LPCX-24C6HT0',
    'cd': 'ATAPI CD0: HL-DT-ST DVDRAM GT80N',
    'usb': 'USB HDD: SanDisk Cruzer Blade',
    'net': 'Network Boot: Realtek PXE B02 D00',
}

BIOS_DEFAULTS = {
    'sysTime': '12:00:00',
    'sysDate': '01/01/2026',
    'usbBiosSupport': 'Enabled',
    'pxeBoot': 'Disabled',
    'sataMode': 'AHCI',
    'virtualization': 'Enabled',
    'wakeOnLan': 'Disabled',
    'secureBoot': 'Enabled',        # 阶段5 新增：UEFI 安全启动
    'fastBoot': 'Enabled',          # 阶段5 新增：快速启动
    'csm': 'Disabled',              # 阶段5 新增：兼容性支持模块
    'tpm': 'Enabled',               # 阶段5 新增：可信平台模块
    'supervisorPassword': None,
    'userPassword': None,
    'passwordOnBoot': 'Disabled',
    'bootMode': 'UEFI',
    'bootOrder': [BIOS_DEV['hdd'], BIOS_DEV['cd'], BIOS_DEV['usb'], BIOS_DEV['net']],
    'usbBoot': 'Enabled',
    'networkBoot': 'Enabled',
    'fddBoot': 'Disabled',
    'loadedDefaults': False,
}

# ==================== WinPE 默认状态 ====================
PE_DEFAULTS = {
    'lastQuick': None,
    'lastDelete': None,
    'lastInstall': None,
    'lastCdi': None,
    'lastCdm': None,
    'lastScreenTest': None,
    'lastBurn': None,
    'lastAida': None,        # AIDA64 硬件信息检测报告
    'lastMemtest': None,     # MemTest 内存完整性检测报告
    'lastKbd': None,         # 键盘按键响应检测报告
    'lastMouse': None,       # 鼠标按键/滚轮检测报告
    'bootPicked': None,      # 阶段5 新增：U盘引导选择
    'peReady': False,        # 阶段5 新增：PE 桌面就绪
}


# ==================== 辅助判定函数 ====================
def _flag_in(fl, key, values):
    """flags 中某个集合类标记是否命中。"""
    v = fl.get(key)
    if not v:
        return False
    if isinstance(v, (list, tuple, set)):
        return any(x in values for x in v)
    return v in values


def _time_diff_sec(t1, t2):
    """两个 'HH:MM:SS' 之间的秒差，处理跨 24 点环绕。"""
    def to_sec(t):
        try:
            h, m, s = (int(x) for x in str(t).split(':'))
            return h * 3600 + m * 60 + s
        except (ValueError, AttributeError):
            return None

    a, b = to_sec(t1), to_sec(t2)
    if a is None or b is None:
        return None
    d = abs(a - b)
    return min(d, 86400 - d)     # 跨零点：23:59 与 00:01 相差 120 秒而非 86340 秒


def _is_usb_first(state):
    order = state.get('bootOrder') or []
    return bool(order) and str(order[0]).startswith('USB HDD')


# ==================== BIOS 评分细则（bios-v1 · 20 分钟 · 100 分） ====================
# 综合任务制：一次进入 BIOS，完成"用 U 盘装 Win10"前的全套配置，
# 最后 F10 保存退出即交卷。比逐题制更贴近真实装机，也能考察多步骤连贯操作。
BIOS_V1_ITEMS = [
    {
        'id': 'b1', 'name': '切换到 Boot 标签页', 'pts': 4,
        'tip': '用 ← → 方向键切换到 Boot 页签。',
        'check': lambda st, fl, ctx: 'Boot' in (fl.get('tabs') or []),
    },
    {
        'id': 'b2', 'name': '进入 Boot Device Priority 子菜单', 'pts': 4,
        'tip': '在 Boot 页选中 Boot Device Priority，按 Enter 进入。',
        'check': lambda st, fl, ctx: '__bootPriority' in (fl.get('submenus') or []),
    },
    {
        'id': 'b3', 'name': '把 U 盘（USB HDD）设为第一启动项', 'pts': 10,
        'require': 'b2', 'partial': 5,
        'tip': '在子菜单中选中 USB HDD，用 + 或 ↑ 把它移到第一位。',
        'check': lambda st, fl, ctx: _is_usb_first(st),
    },
    {
        'id': 'b4', 'name': '关闭 Secure Boot（安全启动）', 'pts': 6,
        'tip': 'Advanced 页：Secure Boot 改为 Disabled。不关会认不到 U 盘引导。',
        'check': lambda st, fl, ctx: st.get('secureBoot') == 'Disabled',
    },
    {
        'id': 'b5', 'name': '开启 CSM 或改为 Legacy 启动模式', 'pts': 6,
        'tip': 'Advanced/Boot 页：CSM 设为 Enabled，或 Boot Mode 改为 Legacy。',
        'check': lambda st, fl, ctx: (
            st.get('csm') == 'Enabled' or st.get('bootMode') == 'Legacy'
        ),
    },
    {
        # watch：这一项的默认状态本来就是 Enabled，光看最终状态无法区分
        # "学生检查并确认过"和"学生压根没动过"。要求必须发生过修改事件才给分，
        # 否则什么都不做的学生白拿 4 分。
        'id': 'b6', 'name': '检查并开启 USB Boot', 'pts': 4,
        'watch': 'usbBoot',
        'tip': 'Boot 页：确认 USB Boot 为 Enabled（若已开启，请改动一次再改回以表明已检查）。',
        'check': lambda st, fl, ctx: st.get('usbBoot') == 'Enabled',
    },
    {
        'id': 'b7', 'name': '检查并开启 USB BIOS Support', 'pts': 4,
        'watch': 'usbBiosSupport',
        'tip': 'Advanced 页：确认 USB BIOS Support 为 Enabled。',
        'check': lambda st, fl, ctx: st.get('usbBiosSupport') == 'Enabled',
    },
    {
        'id': 'b8', 'name': '把系统日期校正为今天', 'pts': 6,
        'tip': 'Main 页：System Date 改为考试当天的日期（MM/DD/YYYY）。',
        'check': lambda st, fl, ctx: (
            ctx.get('exam_date') and st.get('sysDate') == ctx['exam_date']
        ),
    },
    {
        'id': 'b9', 'name': '把系统时间校正（误差 ≤5 分钟）', 'pts': 6,
        'partial': 3,
        'tip': 'Main 页：System Time 改为当前时间（HH:MM:SS），误差不超过 5 分钟。',
        'check': lambda st, fl, ctx: (
            ctx.get('exam_time') is not None
            and (_time_diff_sec(st.get('sysTime'), ctx['exam_time']) or 10 ** 9) <= 300
        ),
        # 误差在 30 分钟内：知道要改时间，但没改准，给一半分
        'partial_check': lambda st, fl, ctx: (
            ctx.get('exam_time') is not None
            and (_time_diff_sec(st.get('sysTime'), ctx['exam_time']) or 10 ** 9) <= 1800
        ),
    },
    {
        'id': 'b10', 'name': '设置 Supervisor Password 并完成二次确认', 'pts': 8,
        'partial': 4, 'require': '_pwd_confirm',
        'tip': 'Security 页：Supervisor Password 按 Enter 设置，并在 Confirm 框中再输一次相同密码。',
        'check': lambda st, fl, ctx: bool(st.get('supervisorPassword')),
    },
    {
        'id': 'b11', 'name': '确认 Password on Boot 为 Disabled', 'pts': 4,
        'watch': 'passwordOnBoot',
        'tip': 'Security 页：确认 Password on Boot 为 Disabled，避免开机卡在密码输入。',
        'check': lambda st, fl, ctx: st.get('passwordOnBoot') == 'Disabled',
    },
    {
        'id': 'b12', 'name': 'F10 保存并退出（Exit Saving Changes）', 'pts': 10,
        'partial': 4,
        'tip': '在 Exit 页选 Exit Saving Changes，或直接按 F10 确认保存退出。',
        'check': lambda st, fl, ctx: _flag_in(fl, 'actions', ('saveExit',)),
        # 只点了 Save Changes 没退出：知道要保存，给少量分
        'partial_check': lambda st, fl, ctx: _flag_in(fl, 'actions', ('saveOnly',)),
    },
    {
        'id': 'b13', 'name': '用 F12 启动菜单临时从 U 盘启动', 'pts': 8,
        'partial': 3,
        'tip': '按 F12 打开一次性启动菜单，选择 USB HDD（不改 BIOS 里的启动顺序）。',
        'check': lambda st, fl, ctx: str(fl.get('bootmenu_pick') or '').startswith('USB'),
        # 进了启动菜单但选错设备
        'partial_check': lambda st, fl, ctx: bool(fl.get('bootmenu_pick')),
    },
    {
        'id': 'b14', 'name': 'POST 自检：识别内存异常并正确处置', 'pts': 10,
        'partial': 4,
        'tip': '开机自检提示内存异常时，应先重新插拔内存条排查；无效再更换。',
        'check': lambda st, fl, ctx: _flag_in(fl, 'post_handle', ('reseat', 'replace')),
        # 只是看到了报错，没有做出处置
        'partial_check': lambda st, fl, ctx: bool(fl.get('post_detected')),
    },
    {
        'id': 'b15', 'name': '故障判断：拔掉硬盘开机报什么错', 'pts': 10,
        'tip': '拔掉硬盘后开机，自检会报 "No boot device" / 找不到启动设备。',
        'check': lambda st, fl, ctx: bool(fl.get('fault_answer_ok')),
    },
]

# ==================== 任务清单的显示顺序 ====================
# 上面的 items 按"写作顺序"排列，这里换成**学生实际操作的先后顺序**。
# 关键：F10「保存并退出」在正式考试里等于交卷，必须排在最后 ——
# 否则学生做到清单中间就会把整场考试提前交掉，后面几步全都没做。
# 顺序与判分无关（每项只看重放后的状态），只影响前端任务清单与教师端明细的排列。
BIOS_TASK_ORDER = [
    'b14',   # 开机自检（进 BIOS 前就会遇到）
    'b1', 'b2', 'b3',              # 进 Boot 页 → 启动项子菜单 → U 盘第一启动
    'b4', 'b5', 'b6', 'b7',        # 关安全启动 / 开 CSM / USB Boot / USB BIOS Support
    'b8', 'b9',                    # 校正日期、时间
    'b10', 'b11',                  # 管理员密码、Password on Boot
    'b13',                         # F12 一次性启动菜单
    'b15',                         # 故障判断小测
    'b12',                         # ★ 最后一步：F10 保存并退出（＝交卷）
]
BIOS_V1_ITEMS = sorted(BIOS_V1_ITEMS,
                       key=lambda it: BIOS_TASK_ORDER.index(it['id']))

BIOS_V1 = {
    'version': 'bios-v1',
    'sim_type': 'bios',
    'title': 'BIOS 设置模拟考试（综合任务）',
    'max_score': 100,
    'minutes': 20,
    'items': BIOS_V1_ITEMS,
}

# ==================== WinPE 评分细则（winpe-v1 · 30 分钟 · 100 分） ====================
# 过程步骤分 + 结果分双轨。判据从前端 check() 整体搬来（逻辑不变），
# 但执行位置从浏览器移到服务端，学生无法再 F12 改分。
WINPE_V1_ITEMS = [
    {
        'id': 'w1', 'name': 'U 盘引导进入 WinPE', 'pts': 8,
        'tip': '开机按启动菜单键选 U 盘 → 等待 PE 加载 → 进入桌面。',
        'check': lambda st, fl, ctx: (
            _flag_in(fl, 'steps', ('boot.pick_usb',))
            and _flag_in(fl, 'steps', ('pe.loading_done',))
            and bool(st.get('peReady'))
        ),
    },
    {
        'id': 'w2', 'name': '快速分区 · 基础（MBR / 3 区 / C 盘 100GB / 4K 对齐 4096）', 'pts': 20,
        'tip': 'DiskGenius 快速分区：分区表类型 MBR，3 个分区，第一分区 100GB，勾选 4K 对齐并选 4096 扇区。',
        'check': lambda st, fl, ctx: _w2_check(st, 20),
        'detail': True,     # 需要返回逐项明细
    },
    {
        'id': 'w3', 'name': '快速分区 · 进阶（GUID / 4 区 / ESP+MSR / 80+200GB）', 'pts': 18,
        'tip': '分区表类型 GUID，4 个分区，勾选 ESP 与 MSR，前两区分别 80GB 和 200GB，4K 对齐。',
        'check': lambda st, fl, ctx: _w3_check(st, 18),
        'detail': True,
    },
    {
        'id': 'w4', 'name': '删除 E 盘并确认', 'pts': 8,
        'tip': '在 DiskGenius 中选中 E 盘，删除分区并在确认框中点"是"。',
        'check': lambda st, fl, ctx: (
            (st.get('lastDelete') or {}).get('label') == 'E盘'
            and (st.get('lastDelete') or {}).get('confirmed') is True
        ),
    },
    {
        'id': 'w5', 'name': '安装系统：引导分区与安装分区均选 C 盘', 'pts': 14,
        'tip': 'Windows 安装器中选择 install.wim，引导分区与安装分区都选 C 盘，等待进度完成。',
        'check': lambda st, fl, ctx: (
            (st.get('lastInstall') or {}).get('boot') == 'C'
            and (st.get('lastInstall') or {}).get('target') == 'C'
            and (st.get('lastInstall') or {}).get('finished') is True
        ),
    },
    {
        'id': 'w6', 'name': 'CrystalDiskInfo：健康结论"良好"且 C5 原始值为 0', 'pts': 8,
        'tip': '查看 SMART 信息，健康状态选"良好"，C5（当前待映射扇区）原始值填 0。',
        'check': lambda st, fl, ctx: (
            (st.get('lastCdi') or {}).get('verdict') == '良好'
            and str((st.get('lastCdi') or {}).get('c5')).strip() == '0'
        ),
    },
    {
        'id': 'w7', 'name': 'CrystalDiskMark：C 盘 / 5 次 / 1GiB / All 完整测速', 'pts': 10,
        'tip': '选择 C: 分区，测试次数 5，测试大小 1GiB，点 All 跑完再提交。',
        'check': lambda st, fl, ctx: (
            (st.get('lastCdm') or {}).get('drive') == 'C:'
            and str((st.get('lastCdm') or {}).get('count')) == '5'
            and str((st.get('lastCdm') or {}).get('size')) == '1GiB'
            and (st.get('lastCdm') or {}).get('mode') == 'All'
            and (st.get('lastCdm') or {}).get('done') is True
        ),
    },
    {
        'id': 'w8', 'name': '显示器坏点检测：五色全看 + 正确报告', 'pts': 8,
        'tip': '依次查看红绿蓝白黑五种纯色画面，找出亮/暗点位置后提交结论。',
        'check': lambda st, fl, ctx: (
            len((st.get('lastScreenTest') or {}).get('colors') or []) >= 5
            and (st.get('lastScreenTest') or {}).get('verdict_correct') is True
        ),
    },
    {
        'id': 'w9', 'name': 'CPU 烤机：Extreme / 全线程 / ≥60 秒', 'pts': 6,
        'tip': '选择 Extreme 模式与全部线程，点击开始后真实烤机满 60 秒再停止并提交。',
        'check': lambda st, fl, ctx: (
            (st.get('lastBurn') or {}).get('mode') == 'Extreme'
            and str((st.get('lastBurn') or {}).get('threads')) == '全部'
            and ((st.get('lastBurn') or {}).get('durationSec') or 0) >= 60
            and (st.get('lastBurn') or {}).get('stopped') is True
        ),
    },
]


# ==================== 分项按比例给分的实现 ====================
def _w2_check(st, pts):
    """
    快速分区基础题（MBR）：5 个要点，错一项扣 pts/5。

    必须遍历 quicks 历史而不是只看 lastQuick：
    学生可能先做基础题、再做进阶题，lastQuick 会被后面那次 GPT 分区覆盖，
    只看最后一次会误判基础题没做。
    """
    pool = list(st.get('quicks') or [])
    q = st.get('lastQuick')
    if q and q not in pool:
        pool.append(q)
    if not pool:
        return 0.0

    best = 0.0
    for item in pool:
        if not item:
            continue
        checks = [
            item.get('table') == 'MBR',
            int(item.get('count') or 0) == 3,
            abs(float(item.get('firstGB') or 0) - 100) <= 1,
            item.get('align4k') is True,
            str(item.get('alignSectors')) == '4096',
        ]
        ok = sum(1 for c in checks if c)
        best = max(best, pts * ok / float(len(checks)))
    return best


def _w3_check(st, pts):
    """快速分区进阶题（GUID）：7 个要点。同样遍历历史取最好一次。"""
    pool = list(st.get('quicks') or [])
    q = st.get('lastQuick')
    if q and q not in pool:
        pool.append(q)
    if not pool:
        return 0.0

    best = 0.0
    for item in pool:
        if not item:
            continue
        checks = [
            item.get('table') == 'GUID',
            int(item.get('count') or 0) == 4,
            item.get('esp') is True,
            item.get('msr') is True,
            abs(float(item.get('firstGB') or 0) - 80) <= 1,
            abs(float(item.get('secondGB') or 0) - 200) <= 1,
            item.get('align4k') is True,
        ]
        ok = sum(1 for c in checks if c)
        best = max(best, pts * ok / float(len(checks)))
    return best


WINPE_V1 = {
    'version': 'winpe-v1',
    'sim_type': 'winpe',
    'title': 'WinPE 装机维护模拟考试',
    'max_score': 100,
    'minutes': 30,
    'items': WINPE_V1_ITEMS,
}

# ==================== WinPE 评分细则（winpe-v2 · 30 分钟 · 100 分） ====================
# v2 把图吧工具箱里原先"只有图标、点开只弹提示"的四个工具补成真实可操作的
# 检测项（AIDA64 / MemTest 内存检测 / 键盘测试 / 鼠标测试），并同步加进考试。
# 为保持满分 100，把原有各步分值等比压缩，新增 4 项各 6 分（共 24 分）。
# v1 保持冻结不动，考过的成绩不受影响（版本号随成绩入库）。

_V2_PTS = {'w1': 6, 'w2': 15, 'w3': 14, 'w4': 6, 'w5': 11, 'w6': 6, 'w7': 8, 'w8': 6, 'w9': 4}


def _aida_ok(st):
    """AIDA64：主板型号正确、内存容量正确、CPU 温度在合理区间。"""
    a = st.get('lastAida') or {}
    if str(a.get('board') or '') != 'B660M-PLUS':
        return False
    if str(a.get('memGB') or '') != '16':
        return False
    try:
        t = float(a.get('cpuTemp'))
    except (TypeError, ValueError):
        return False
    return 30 <= t <= 85


def _memtest_ok(st):
    """MemTest：完整跑完至少 1 轮且 0 错误。"""
    m = st.get('lastMemtest') or {}
    try:
        passes = int(m.get('passes') or 0)
        errors = int(m.get('errors') or 0)
    except (TypeError, ValueError):
        return False
    return bool(m.get('done')) and passes >= 1 and errors == 0


def _kbd_ok(st):
    """键盘测试：A/S/D/F 与空格必须都被真实按下过一次。"""
    k = st.get('lastKbd') or {}
    keys = [str(x).lower() for x in (k.get('keys') or [])]
    return all(r in keys for r in ('a', 's', 'd', 'f', 'space'))


def _mouse_ok(st):
    """鼠标测试：左键/右键/滚轮/双击全部测到。"""
    m = st.get('lastMouse') or {}
    return all(bool(m.get(x)) for x in ('left', 'right', 'wheel', 'dbl'))


WINPE_V2_NEW_ITEMS = [
    {
        'id': 'w10', 'name': 'AIDA64：硬件信息检测与报告', 'pts': 6, 'partial': 3,
        'tip': '图吧工具箱 → 硬件检测 → AIDA64：在"计算机→汇总"记录主板型号与内存容量，'
               '在"传感器"页读取 CPU 温度，然后提交检测报告（本机主板 B660M-PLUS / 内存 16 GB）。',
        'check': lambda st, fl, ctx: _aida_ok(st),
        'partial_check': lambda st, fl, ctx: str((st.get('lastAida') or {}).get('board') or '') == 'B660M-PLUS',
    },
    {
        'id': 'w11', 'name': 'MemTest：内存完整性检测', 'pts': 6, 'partial': 3,
        'tip': '图吧工具箱 → 烤机测试 → 内存检测(MemTest)：选择测试容量后开始检测，'
               '完整跑满至少 1 轮且报告 0 错误，再提交报告。',
        'check': lambda st, fl, ctx: _memtest_ok(st),
        'partial_check': lambda st, fl, ctx: bool((st.get('lastMemtest') or {}).get('done')),
    },
    {
        'id': 'w12', 'name': '键盘测试：按键响应检测', 'pts': 6, 'partial': 3,
        'tip': '图吧工具箱 → 外设检测 → 键盘测试：依次真实按下 A、S、D、F 与空格键，'
               '确认界面均有响应后提交报告。',
        'check': lambda st, fl, ctx: _kbd_ok(st),
        'partial_check': lambda st, fl, ctx: bool(((st.get('lastKbd') or {}).get('keys') or [])),
    },
    {
        'id': 'w13', 'name': '鼠标测试：按键与滚轮检测', 'pts': 6, 'partial': 3,
        'tip': '图吧工具箱 → 外设检测 → 鼠标测试：依次点击左键、右键、上下滚动滚轮并双击，'
               '确认界面均有响应后提交报告。',
        'check': lambda st, fl, ctx: _mouse_ok(st),
        'partial_check': lambda st, fl, ctx: bool((st.get('lastMouse') or {}).get('left')
                                                  or (st.get('lastMouse') or {}).get('right')),
    },
]


def _build_winpe_v2_items():
    """在 v1 基础上等比压缩分值，并追加 4 个新增工具评分项。"""
    items = []
    for it in WINPE_V1_ITEMS:
        ni = dict(it)
        ni['pts'] = _V2_PTS[it['id']]
        if it['id'] == 'w2':
            ni['check'] = lambda st, fl, ctx: _w2_check(st, 15)
        elif it['id'] == 'w3':
            ni['check'] = lambda st, fl, ctx: _w3_check(st, 14)
        items.append(ni)
    items.extend(WINPE_V2_NEW_ITEMS)
    return items


WINPE_V2 = {
    'version': 'winpe-v2',
    'sim_type': 'winpe',
    'title': 'WinPE 装机维护模拟考试（含图吧工具箱硬件检测）',
    'max_score': 100,
    'minutes': 30,
    'items': _build_winpe_v2_items(),
}

# ==================== 版本注册表 ====================
RUBRICS = {
    'bios-v1': BIOS_V1,
    'winpe-v1': WINPE_V1,
    'winpe-v2': WINPE_V2,
}

CURRENT_VERSION = {
    'bios': 'bios-v1',
    'winpe': 'winpe-v2',
}


def get_rubric(sim_type, version=None):
    """取指定模拟器的评分细则；未指定版本则用当前版本。"""
    ver = version or CURRENT_VERSION.get(sim_type)
    return RUBRICS.get(ver)
