
/* ============================================================
   ① 配置数据区
   ============================================================ */
const CONFIG = { ptsPerQuestion: 10, practiceCount: 10, passLine: 60 };

/* ==== 学生名单 ====
   统一考试系统下，考生身份由服务端（/portal 登录后）注入到 window.SIM_BOOT.student，
   不再使用本地硬编码名单——否则学生可 F12 冒名顶替，且无法与成绩库对齐。
   离线双击打开本文件时 STUDENTS 为空，自动降级为「练习模式（不计分）」。
   若教师需离线课堂演练，可临时填入 { id: "学号", name: "姓名" }，正式考试前务必清空。 */
const STUDENTS = [];   // 由服务端注入身份，禁止硬编码真实名单

/* 启动设备（可自定义型号字符串，判定只看前缀） */
const DEV = {
  hdd: "ATA HDD0: WDC WD5000LPCX-24C6HT0",
  cd:  "ATAPI CD0: HL-DT-ST DVDRAM GT80N",
  usb: "USB HDD: SanDisk Cruzer Blade",
  net: "Network Boot: Realtek PXE B02 D00"
};

/* ============================================================
   ② BIOS 状态模型
   ============================================================ */
const DEFAULT_STATE = {
  sysTime: "12:00:00",
  sysDate: "01/01/2026",
  usbBiosSupport: "Enabled",
  pxeBoot: "Disabled",
  sataMode: "AHCI",
  virtualization: "Enabled",
  wakeOnLan: "Disabled",
  /* --- 以下 4 项为统一考试系统新增：UEFI 时代装机必考项 --- */
  secureBoot: "Enabled",     // 安全启动：不关会认不到多数 PE 启动盘
  fastBoot: "Enabled",       // 快速启动：开着会跳过 USB 设备检测
  csm: "Disabled",           // 兼容性支持模块（CSM）：装老系统/legacy PE 需要开
  tpm: "Enabled",            // 可信平台模块
  supervisorPassword: null,
  userPassword: null,
  passwordOnBoot: "Disabled",
  bootMode: "UEFI",
  bootOrder: [DEV.hdd, DEV.cd, DEV.usb, DEV.net],
  usbBoot: "Enabled",
  networkBoot: "Enabled",
  fddBoot: "Disabled",
  loadedDefaults: false
};

function clone(o){ return JSON.parse(JSON.stringify(o)); }

/* 恢复出厂默认：修改可改字段，并置 loadedDefaults=true
   注意：用 muteOn/muteOff 包住，否则一次 F9 会刷出十几条 set 事件 */
function applySetupDefaults(s){
  if (window.SimExam) SimExam.muteOn();
  s.sysTime = "12:00:00";
  s.sysDate = "01/01/2026";
  s.usbBiosSupport = "Enabled";
  s.pxeBoot = "Disabled";
  s.sataMode = "AHCI";
  s.virtualization = "Enabled";
  s.wakeOnLan = "Disabled";
  s.secureBoot = "Enabled";
  s.fastBoot = "Enabled";
  s.csm = "Disabled";
  s.tpm = "Enabled";
  s.supervisorPassword = null;
  s.userPassword = null;
  s.passwordOnBoot = "Disabled";
  s.bootMode = "UEFI";
  s.bootOrder = [DEV.hdd, DEV.cd, DEV.usb, DEV.net];
  s.usbBoot = "Enabled";
  s.networkBoot = "Enabled";
  s.fddBoot = "Disabled";
  s.loadedDefaults = true;
  if (window.SimExam) SimExam.muteOff('action', 'defaults', {});
}

/* ============================================================
   ③ 标签页定义（界面渲染 + 选项）
   ============================================================ */
const TABS = [
  {
    name: "Main",
    items: [
      { type:"section", title:"System Information" },
      { key:"sysTime", label:"System Time", type:"time",
        help:"设置系统时间。格式 HH:MM:SS。选中后按 Enter 进入编辑，用 ↑↓ / + - 调整，← → 切换时/分/秒。" },
      { key:"sysDate", label:"System Date", type:"date",
        help:"设置系统日期。格式 MM/DD/YYYY。选中后按 Enter 进入编辑，用 ↑↓ / + - 调整，← → 切换月/日/年。" },
      { type:"info", label:"BIOS Version", value:"2.05", help:"主板固件版本，只读。" },
      { type:"info", label:"Product Name", value:"Lenovo G480", help:"整机型号，只读。" },
      { type:"info", label:"Manufacturer", value:"LENOVO", help:"整机制造商，只读。" },
      { type:"info", label:"CPU Type", value:"Intel(R) Core(TM) i3-3110M 2.40GHz", help:"处理器型号，只读。" },
      { type:"info", label:"Total Memory", value:"4096 MB", help:"内存容量，只读。" }
    ]
  },
  {
    name: "Advanced",
    items: [
      { type:"section", title:"USB / Storage Configuration" },
      { key:"usbBiosSupport", label:"USB BIOS Support", type:"enum", options:["Enabled","Disabled"],
        help:"是否在 BIOS 阶段支持 USB 设备。若需从 U 盘启动，应设为 Enabled。" },
      { key:"pxeBoot", label:"PXE Boot ROM", type:"enum", options:["Enabled","Disabled"],
        help:"是否启用网卡 PXE 引导固件。" },
      { key:"sataMode", label:"SATA Mode", type:"enum", options:["AHCI","IDE"],
        help:"硬盘控制器模式。AHCI 为现代模式，IDE 为兼容模式。" },
      { key:"virtualization", label:"Intel Virtualization Technology", type:"enum", options:["Enabled","Disabled"],
        help:"Intel 虚拟化技术，用于虚拟机加速。" },
      { key:"wakeOnLan", label:"Wake on LAN", type:"enum", options:["Enabled","Disabled"],
        help:"是否允许网络唤醒开机。" },
      { type:"section", title:"UEFI / Windows 8 相关" },
      { key:"secureBoot", label:"Secure Boot", type:"enum", options:["Enabled","Disabled"],
        help:"安全启动。UEFI 模式下只信任已签名引导程序。用 U 盘装系统或进 PE 前通常需要先关闭它，否则会提示「选定的引导设备未通过安全校验」。" },
      { key:"fastBoot", label:"Fast Boot", type:"enum", options:["Enabled","Disabled"],
        help:"快速启动。跳过部分硬件自检以加快开机，但会导致开机时不检测 U 盘，装机时应关闭。" },
      { key:"csm", label:"CSM (Compatibility Support Module)", type:"enum", options:["Enabled","Disabled"],
        help:"兼容性支持模块。开启后支持传统 Legacy 引导；安装老版本系统或使用老 PE 时需要开启，纯 UEFI 装机则应关闭。" },
      { key:"tpm", label:"TPM 2.0 (PTT)", type:"enum", options:["Enabled","Disabled"],
        help:"可信平台模块。Windows 11 安装要求开启 TPM 2.0；关闭时安装 Win11 会提示「这台电脑无法运行 Windows 11」。" }
    ]
  },
  {
    name: "Security",
    items: [
      { type:"section", title:"Security Settings" },
      { key:"supervisorPassword", label:"Supervisor Password", type:"password",
        help:"管理员密码。按 Enter 输入新密码；若已设置，输入留空再回车即可清除。" },
      { key:"userPassword", label:"User Password", type:"password",
        help:"用户密码。按 Enter 输入新密码；输入留空再回车即可清除。" },
      { key:"passwordOnBoot", label:"Password on Boot", type:"enum", options:["Enabled","Disabled"],
        help:"开机时是否要求输入密码。" },
      { type:"info", label:"HDD Password Status", value:"Not Set", help:"硬盘密码状态，只读。" }
    ]
  },
  {
    name: "Boot",
    items: [
      { type:"section", title:"Boot Configuration" },
      { key:"bootMode", label:"Boot Mode", type:"enum", options:["UEFI","Legacy"],
        help:"启动模式。UEFI 为新式固件启动，Legacy 为传统 BIOS 启动。" },
      { key:"__bootPriority", label:"Boot Device Priority", type:"submenu",
        help:"设置开机时尝试启动设备的先后顺序。按 Enter 进入。" },
      { key:"usbBoot", label:"USB Boot", type:"enum", options:["Enabled","Disabled"],
        help:"是否允许从 USB 设备启动。" },
      { key:"networkBoot", label:"Network Boot", type:"enum", options:["Enabled","Disabled"],
        help:"是否允许从网络（PXE）启动。" },
      { key:"fddBoot", label:"Floppy (FDD) Boot", type:"enum", options:["Enabled","Disabled"],
        help:"是否允许从软驱启动。" }
    ]
  },
  {
    /* Hardware Monitor：真实 BIOS 的硬件监控页，装机后烤机、排查高温死机要看这里 */
    name: "H/W Monitor",
    items: [
      { type:"section", title:"PC Health Status" },
      { type:"info", label:"CPU Temperature", value:"46°C / 115°F",
        help:"CPU 温度。待机正常约 35~55°C；满载超过 90°C 需检查散热器是否装好、硅脂是否涂抹均匀。" },
      { type:"info", label:"System Temperature", value:"38°C / 100°F",
        help:"主板温度（机箱内环境温度），反映整机散热风道是否正常。" },
      { type:"info", label:"CPU Fan Speed", value:"1850 RPM",
        help:"CPU 风扇转速。转速为 0 说明风扇没插好或损坏，会触发开机报警。" },
      { type:"info", label:"Chassis Fan Speed", value:"N/A",
        help:"机箱风扇转速。显示 N/A 表示未接机箱风扇或该接口不支持测速。" },
      { type:"info", label:"Vcore", value:"1.184 V",
        help:"CPU 核心电压。异常偏高可能导致 CPU 发热剧增，偏低则可能蓝屏死机。" },
      { type:"info", label:"+12V", value:"12.096 V",
        help:"电源 12V 输出。偏离 ±5% 以上说明电源老化或功率不足。" },
      { type:"info", label:"+5V", value:"5.040 V", help:"电源 5V 输出，供硬盘、USB 等设备使用。" },
      { type:"info", label:"+3.3V", value:"3.312 V", help:"电源 3.3V 输出，供主板部分芯片与内存使用。" }
    ]
  },
  {
    name: "Exit",
    items: [
      { type:"section", title:"Exit Options" },
      { type:"action", action:"saveExit", label:"Exit Saving Changes", help:"保存所有修改并退出（等同于按 F10），提交本题。" },
      { type:"action", action:"defaults", label:"Load Setup Defaults", help:"载入出厂默认设置（等同于按 F9）。" },
      { type:"action", action:"discardExit", label:"Exit Discarding Changes", help:"不保存修改并退出，本题按未完成处理。" },
      { type:"action", action:"saveOnly", label:"Save Changes", help:"保存修改，但停留在 BIOS 设置界面。" },
      { type:"section", title:"Diagnostics" },
      { type:"action", action:"faultQuiz", label:"Fault Diagnosis Quiz",
        help:"故障判断小测：根据现象判断开机报错的原因。答对后才算完成本题。" }
    ]
  }
];

/* ============================================================
   ④ 题库：练习 / A 卷 / B 卷
   ============================================================ */
const P = CONFIG.ptsPerQuestion;

/* —— 练习题库（随机抽取 CONFIG.practiceCount 题）—— */
const QUESTION_BANK = [
  { id:"P01", type:"task", pts:P, stem:"把系统日期修改为 2026 年 10 月 13 日。",
    hint:"Main 标签 → System Date，按 Enter 进入编辑，用 ↑↓ / + - 或直接输入数字修改月/日/年。",
    answerText:"System Date = 10/13/2026", check:s=>s.sysDate==="10/13/2026" },
  { id:"P02", type:"task", pts:P, stem:"把系统时间修改为 08:30:00。",
    hint:"Main 标签 → System Time，按 Enter 进入编辑后调整时/分/秒。",
    answerText:"System Time = 08:30:00", check:s=>s.sysTime==="08:30:00" },
  { id:"P03", type:"task", pts:P, stem:"把第一启动项设置为 U 盘（USB HDD）。",
    hint:"Boot 标签 → 进入 Boot Device Priority → 选中 USB HDD → 用 + / - 把它移到最上面。",
    answerText:"Boot Device Priority 第一位 = USB HDD", check:s=>s.bootOrder[0].startsWith("USB HDD") },
  { id:"P04", type:"task", pts:P, stem:"把第一启动项设置为光驱（ATAPI CD0）。",
    hint:"Boot 标签 → Boot Device Priority → 用 + / - 把 ATAPI CD0 移到最上面。",
    answerText:"Boot Device Priority 第一位 = ATAPI CD0", check:s=>s.bootOrder[0].startsWith("ATAPI CD0") },
  { id:"P05", type:"task", pts:P, stem:"把第一启动项设置为硬盘（ATA HDD0）。",
    hint:"Boot 标签 → Boot Device Priority → 用 + / - 把 ATA HDD0 移到最上面。",
    answerText:"Boot Device Priority 第一位 = ATA HDD0",
    initial:{ bootOrder:[DEV.cd, DEV.hdd, DEV.usb, DEV.net] },
    check:s=>s.bootOrder[0].startsWith("ATA HDD0") },
  { id:"P06", type:"task", pts:P, stem:"把启动模式（Boot Mode）由 UEFI 改为 Legacy。",
    hint:"Boot 标签 → Boot Mode，用 + / - 或按 Enter 切换为 Legacy。",
    answerText:"Boot Mode = Legacy", check:s=>s.bootMode==="Legacy" },
  { id:"P07", type:"task", pts:P, stem:"把启动模式（Boot Mode）由 Legacy 改为 UEFI。",
    hint:"Boot 标签 → Boot Mode，切换为 UEFI。",
    answerText:"Boot Mode = UEFI", initial:{ bootMode:"Legacy" }, check:s=>s.bootMode==="UEFI" },
  { id:"P08", type:"task", pts:P, stem:"关闭 USB 启动（USB Boot = Disabled）。",
    hint:"Boot 标签 → USB Boot，切换为 Disabled。",
    answerText:"USB Boot = Disabled", check:s=>s.usbBoot==="Disabled" },
  { id:"P09", type:"task", pts:P, stem:"开启 USB 启动（USB Boot = Enabled）。",
    hint:"Boot 标签 → USB Boot，切换为 Enabled。",
    answerText:"USB Boot = Enabled", initial:{ usbBoot:"Disabled" }, check:s=>s.usbBoot==="Enabled" },
  { id:"P10", type:"task", pts:P, stem:"关闭网络启动（Network Boot = Disabled）。",
    hint:"Boot 标签 → Network Boot，切换为 Disabled。",
    answerText:"Network Boot = Disabled", check:s=>s.networkBoot==="Disabled" },
  { id:"P11", type:"task", pts:P, stem:"开启网络启动（Network Boot = Enabled）。",
    hint:"Boot 标签 → Network Boot，切换为 Enabled。",
    answerText:"Network Boot = Enabled", initial:{ networkBoot:"Disabled" }, check:s=>s.networkBoot==="Enabled" },
  { id:"P12", type:"task", pts:P, stem:"开启软驱启动（Floppy/FDD Boot = Enabled）。",
    hint:"Boot 标签 → Floppy (FDD) Boot，切换为 Enabled。",
    answerText:"FDD Boot = Enabled", check:s=>s.fddBoot==="Enabled" },
  { id:"P13", type:"task", pts:P, stem:"关闭软驱启动（Floppy/FDD Boot = Disabled）。",
    hint:"Boot 标签 → Floppy (FDD) Boot，切换为 Disabled。",
    answerText:"FDD Boot = Disabled", initial:{ fddBoot:"Enabled" }, check:s=>s.fddBoot==="Disabled" },
  { id:"P14", type:"task", pts:P, stem:"开启 USB BIOS Support。",
    hint:"Advanced 标签 → USB BIOS Support，切换为 Enabled。",
    answerText:"USB BIOS Support = Enabled", initial:{ usbBiosSupport:"Disabled" }, check:s=>s.usbBiosSupport==="Enabled" },
  { id:"P15", type:"task", pts:P, stem:"关闭 USB BIOS Support。",
    hint:"Advanced 标签 → USB BIOS Support，切换为 Disabled。",
    answerText:"USB BIOS Support = Disabled", check:s=>s.usbBiosSupport==="Disabled" },
  { id:"P16", type:"task", pts:P, stem:"设置管理员密码（Supervisor Password）为 123456。",
    hint:"Security 标签 → Supervisor Password → 按 Enter → 输入 123456 → 回车。",
    answerText:"Supervisor Password = 123456", check:s=>s.supervisorPassword==="123456" },
  { id:"P17", type:"task", pts:P, stem:"清除管理员密码（Supervisor Password）。",
    hint:"Security 标签 → Supervisor Password → 按 Enter → 直接回车（不输入内容）即可清除。",
    answerText:"Supervisor Password = 未设置", initial:{ supervisorPassword:"123456" },
    check:s=>s.supervisorPassword===null },
  { id:"P18", type:"task", pts:P, stem:"设置用户密码（User Password）为 abc123。",
    hint:"Security 标签 → User Password → 按 Enter → 输入 abc123 → 回车。",
    answerText:"User Password = abc123", check:s=>s.userPassword==="abc123" },
  { id:"P19", type:"task", pts:P, stem:"开启开机密码提示（Password on Boot = Enabled）。",
    hint:"Security 标签 → Password on Boot，切换为 Enabled。",
    answerText:"Password on Boot = Enabled", check:s=>s.passwordOnBoot==="Enabled" },
  { id:"P20", type:"task", pts:P, stem:"关闭开机密码提示（Password on Boot = Disabled）。",
    hint:"Security 标签 → Password on Boot，切换为 Disabled。",
    answerText:"Password on Boot = Disabled", initial:{ passwordOnBoot:"Enabled" }, check:s=>s.passwordOnBoot==="Disabled" },
  { id:"P21", type:"task", pts:P, stem:"把 SATA 模式改为 IDE。",
    hint:"Advanced 标签 → SATA Mode，切换为 IDE。",
    answerText:"SATA Mode = IDE", check:s=>s.sataMode==="IDE" },
  { id:"P22", type:"task", pts:P, stem:"开启 Intel 虚拟化技术（Intel Virtualization Technology = Enabled）。",
    hint:"Advanced 标签 → Intel Virtualization Technology，切换为 Enabled。",
    answerText:"Intel Virtualization Technology = Enabled", initial:{ virtualization:"Disabled" },
    check:s=>s.virtualization==="Enabled" },
  { id:"P23", type:"task", pts:P, stem:"恢复 BIOS 出厂默认设置（Load Setup Defaults）。",
    hint:"按 F9，或进入 Exit 标签选择 Load Setup Defaults，确认后即可。",
    answerText:"已载入出厂默认设置", check:s=>s.loadedDefaults===true },
  { id:"P24", type:"quiz", pts:P, stem:"在 Phoenix BIOS 中，保存设置并退出的快捷键是哪个？",
    options:["F2","F9","F10","Esc"], answer:2,
    hint:"看界面底部提示栏，写着 Save and Exit。", explain:"F10 = Save and Exit（保存并退出）；F9 = 恢复默认设置。" },
  { id:"P25", type:"quiz", pts:P, stem:"恢复到 BIOS 出厂默认设置的快捷键是哪个？",
    options:["F1","F5","F9","F10"], answer:2,
    hint:"界面底部提示栏写着 Setup Defaults。", explain:"F9 = Setup Defaults（恢复默认设置）。" },
  { id:"P26", type:"quiz", pts:P, stem:"在 BIOS 设置界面中，切换顶部选项卡（标签）应使用哪个键？",
    options:["↑ ↓ 方向键","← → 方向键","Enter 键","Esc 键"], answer:1,
    hint:"底部提示栏写着「←→ Select Screen」。", explain:"← → 切换顶部选项卡；↑ ↓ 用于在当前列表中选择项目。" },
  { id:"P27", type:"quiz", pts:P, stem:"进入某个选项的子菜单（如 Boot Device Priority）应使用哪个键？",
    options:["Enter 键","空格键","Tab 键","Esc 键"], answer:0,
    hint:"选项后面带 ▶ 表示按 Enter 进入。", explain:"Enter = 进入子菜单 / 执行该选项。" },
  { id:"P28", type:"quiz", pts:P, stem:"「启动顺序」中的第一位代表什么含义？",
    options:["开机时最先尝试启动的设备","开机时最后尝试启动的设备","硬盘的分区顺序","操作系统的版本"], answer:0,
    hint:"第一项 = 首选启动设备。", explain:"开机时 BIOS 会按照启动顺序从上到下依次尝试，第一位最先尝试。" },
  { id:"P29", type:"quiz", pts:P, stem:"关于 UEFI 与 Legacy 启动模式，下列说法正确的是？",
    options:["UEFI 是新式固件启动方式，Legacy 是传统 BIOS 启动方式","两者完全相同","UEFI 只能用于启动 U 盘","Legacy 只能在服务器上使用"], answer:0,
    hint:"新式 = UEFI，传统 = Legacy。", explain:"UEFI 是较新的固件启动标准，Legacy 是传统 BIOS 启动方式。" }
];

/* —— 考试 A 卷（固定 10 题）—— */
const EXAM_A = [
  { id:"A01", type:"task", pts:P, stem:"把系统日期修改为 2026 年 10 月 13 日。",
    hint:"Main 标签 → System Date。", answerText:"System Date = 10/13/2026", check:s=>s.sysDate==="10/13/2026" },
  { id:"A02", type:"task", pts:P, stem:"把系统时间修改为 08:30:00。",
    hint:"Main 标签 → System Time。", answerText:"System Time = 08:30:00", check:s=>s.sysTime==="08:30:00" },
  { id:"A03", type:"task", pts:P, stem:"把第一启动项设置为 U 盘（USB HDD）。",
    hint:"Boot 标签 → Boot Device Priority。", answerText:"第一位 = USB HDD",
    check:s=>s.bootOrder[0].startsWith("USB HDD") },
  { id:"A04", type:"task", pts:P, stem:"把启动模式（Boot Mode）由 UEFI 改为 Legacy。",
    hint:"Boot 标签 → Boot Mode。", answerText:"Boot Mode = Legacy", check:s=>s.bootMode==="Legacy" },
  { id:"A05", type:"task", pts:P, stem:"关闭 USB 启动（USB Boot = Disabled）。",
    hint:"Boot 标签 → USB Boot。", answerText:"USB Boot = Disabled", check:s=>s.usbBoot==="Disabled" },
  { id:"A06", type:"task", pts:P, stem:"开启网络启动（Network Boot = Enabled）。",
    hint:"Boot 标签 → Network Boot。", answerText:"Network Boot = Enabled",
    initial:{ networkBoot:"Disabled" }, check:s=>s.networkBoot==="Enabled" },
  { id:"A07", type:"task", pts:P, stem:"设置管理员密码（Supervisor Password）为 123456。",
    hint:"Security 标签 → Supervisor Password。", answerText:"Supervisor Password = 123456",
    check:s=>s.supervisorPassword==="123456" },
  { id:"A08", type:"task", pts:P, stem:"开启开机密码提示（Password on Boot = Enabled）。",
    hint:"Security 标签 → Password on Boot。", answerText:"Password on Boot = Enabled",
    check:s=>s.passwordOnBoot==="Enabled" },
  { id:"A09", type:"task", pts:P, stem:"把硬盘（ATA HDD0）设置为第一启动项。",
    hint:"Boot 标签 → Boot Device Priority。", answerText:"第一位 = ATA HDD0",
    initial:{ bootOrder:[DEV.cd, DEV.hdd, DEV.usb, DEV.net] }, check:s=>s.bootOrder[0].startsWith("ATA HDD0") },
  { id:"A10", type:"task", pts:P, stem:"恢复 BIOS 出厂默认设置（Load Setup Defaults）。",
    hint:"按 F9，或 Exit 标签 → Load Setup Defaults。", answerText:"已载入出厂默认设置",
    check:s=>s.loadedDefaults===true }
];

/* —— 考试 B 卷（固定 10 题）—— */
const EXAM_B = [
  { id:"B01", type:"task", pts:P, stem:"把系统日期修改为 2025 年 09 月 01 日。",
    hint:"Main 标签 → System Date。", answerText:"System Date = 09/01/2025", check:s=>s.sysDate==="09/01/2025" },
  { id:"B02", type:"task", pts:P, stem:"把系统时间修改为 15:45:00。",
    hint:"Main 标签 → System Time。", answerText:"System Time = 15:45:00", check:s=>s.sysTime==="15:45:00" },
  { id:"B03", type:"task", pts:P, stem:"把第一启动项设置为光驱（ATAPI CD0）。",
    hint:"Boot 标签 → Boot Device Priority。", answerText:"第一位 = ATAPI CD0",
    check:s=>s.bootOrder[0].startsWith("ATAPI CD0") },
  { id:"B04", type:"task", pts:P, stem:"把启动模式（Boot Mode）由 Legacy 改为 UEFI。",
    hint:"Boot 标签 → Boot Mode。", answerText:"Boot Mode = UEFI",
    initial:{ bootMode:"Legacy" }, check:s=>s.bootMode==="UEFI" },
  { id:"B05", type:"task", pts:P, stem:"开启 USB 启动（USB Boot = Enabled）。",
    hint:"Boot 标签 → USB Boot。", answerText:"USB Boot = Enabled",
    initial:{ usbBoot:"Disabled" }, check:s=>s.usbBoot==="Enabled" },
  { id:"B06", type:"task", pts:P, stem:"关闭网络启动（Network Boot = Disabled）。",
    hint:"Boot 标签 → Network Boot。", answerText:"Network Boot = Disabled",
    check:s=>s.networkBoot==="Disabled" },
  { id:"B07", type:"task", pts:P, stem:"设置用户密码（User Password）为 abc123。",
    hint:"Security 标签 → User Password。", answerText:"User Password = abc123",
    check:s=>s.userPassword==="abc123" },
  { id:"B08", type:"task", pts:P, stem:"关闭开机密码提示（Password on Boot = Disabled）。",
    hint:"Security 标签 → Password on Boot。", answerText:"Password on Boot = Disabled",
    initial:{ passwordOnBoot:"Enabled" }, check:s=>s.passwordOnBoot==="Disabled" },
  { id:"B09", type:"task", pts:P, stem:"把启动顺序调整为：光驱（ATAPI CD0）第一、硬盘（ATA HDD0）第二。",
    hint:"Boot 标签 → Boot Device Priority → 用 + / - 调整。", answerText:"第一位 = ATAPI CD0，第二位 = ATA HDD0",
    check:s=>s.bootOrder[0].startsWith("ATAPI CD0") && s.bootOrder[1].startsWith("ATA HDD0") },
  { id:"B10", type:"task", pts:P, stem:"恢复 BIOS 出厂默认设置（Load Setup Defaults）。",
    hint:"按 F9，或 Exit 标签 → Load Setup Defaults。", answerText:"已载入出厂默认设置",
    check:s=>s.loadedDefaults===true }
];

/* ============================================================
   ⑤ 运行时状态
   ============================================================ */
let currentScreen = "login";
let session = null;      // { mode, student, paperName, questions, idx, results, startAt, endAt }
let state = null;        // 当前 BIOS 状态
let baseline = null;     // 本题初始快照（用于 Discard Changes）
let timerId = null;
const bios = {
  tabIndex: 0, itemIndex: 0,
  sub: null, subIndex: 0,      // sub === "bootPriority" 时进入启动顺序子菜单
  edit: false, editField: 0, digitBuf: "",
  modal: null
};

/* ============================================================
   工具函数
   ============================================================ */
const $ = id => document.getElementById(id);
function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
const pad = (n,len)=> String(n).padStart(len,"0");

function showScreen(name){
  currentScreen = name;
  ["login","bios","feedback","result"].forEach(n=>{
    $("screen-"+n).classList.toggle("hidden", n!==name);
  });
  if(document.activeElement && document.activeElement.blur) document.activeElement.blur();
}

function setStatus(msg){ $("biosStatus").textContent = msg || "\u00a0"; }

/* 时间 / 日期 字段解析 */
function timeParts(v){ return v.split(":").map(Number); }
function dateParts(v){ return v.split("/").map(Number); }
function fmtTime(a){ return [pad(a[0],2),pad(a[1],2),pad(a[2],2)].join(":"); }
function fmtDate(a){ return [pad(a[0],2),pad(a[1],2),pad(a[2],4)].join("/"); }
function fieldMax(type, idx){
  if(type==="time") return idx===0?23:59;
  return idx===0?12: idx===1?31 : 9999;
}
function fieldMin(type, idx){
  if(type==="time") return 0;
  return idx===0?1: idx===1?1 : 0;
}
function fieldLen(type, idx){
  if(type==="time") return 2;
  return idx===2?4:2;
}

/* ============================================================
   ⑥ 登录页逻辑
   ============================================================ */
let selectedMode = "practice";

function initLogin(){
  const sel = $("loginStudent");
  sel.innerHTML = "";
  STUDENTS.forEach((s,i)=>{
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = `${s.name}（${s.id}）`;
    sel.appendChild(o);
  });
  const other = document.createElement("option");
  other.value = "manual";
  other.textContent = STUDENTS.length ? "其他（手动输入）…" : "手动输入姓名…";
  sel.appendChild(other);
  if(!STUDENTS.length) sel.value = "manual";
  sel.onchange = ()=>{
    $("manualWrap").classList.toggle("hidden", sel.value!=="manual");
  };
  $("manualWrap").classList.toggle("hidden", sel.value!=="manual");

  document.querySelectorAll(".mode-opt").forEach(el=>{
    el.onclick = ()=>{
      document.querySelectorAll(".mode-opt").forEach(x=>x.classList.remove("active"));
      el.classList.add("active");
      selectedMode = el.dataset.mode;
    };
  });
  $("startBtn").onclick = startSession;
}

function resolveStudent(){
  const sel = $("loginStudent");
  if(sel.value !== "manual"){
    const s = STUDENTS[Number(sel.value)];
    if(s) return { id:s.id, name:s.name };
  }
  const name = ($("manualName").value||"").trim() || "未命名考生";
  const id = ($("manualId").value||"").trim() || "-";
  return { id, name };
}

/* ============================================================
   ⑦ 流程控制
   ============================================================ */
function pickRandom(arr, n){
  const a = arr.slice();
  for(let i=a.length-1;i>0;i--){ const j=Math.floor(Math.random()*(i+1)); [a[i],a[j]]=[a[j],a[i]]; }
  return a.slice(0, Math.min(n, a.length));
}

function startSession(){
  const student = resolveStudent();
  let questions, paperName, modeLabel;
  if(selectedMode==="examA"){ questions = EXAM_A.slice(); paperName="A卷"; modeLabel="考试 A 卷"; }
  else if(selectedMode==="examB"){ questions = EXAM_B.slice(); paperName="B卷"; modeLabel="考试 B 卷"; }
  else { questions = pickRandom(QUESTION_BANK, CONFIG.practiceCount); paperName="练习"; modeLabel="练习模式"; }

  session = {
    mode: selectedMode, student, paperName, modeLabel,
    questions, idx: 0, results: [], startAt: Date.now(), endAt: null
  };
  $("hudMode").textContent = modeLabel;
  $("hudQTotal").textContent = questions.length;
  $("hudScoreWrap").classList.toggle("hidden", selectedMode!=="practice");
  const tp = $("examTaskPanel"); if(tp) tp.style.display = "none";
  showScreen("bios");
  startTimer();
  loadQuestion();
}

/**
 * 正式考试：综合任务制。
 * 一次进入 BIOS，按任务清单完成整套"用 U 盘装系统前"的配置，
 * 最后 F10 保存退出即交卷。分数由服务端按操作事件重放判定。
 */
function startExamSession(){
  const boot = window.SIM_BOOT || {};
  const taskMeta = (window.__SIM_PAPER__ && window.__SIM_PAPER__.items) || [];
  const paper = window.__SIM_PAPER__ || {};

  session = {
    mode: "exam",
    student: { name: boot.student_name || "", id: boot.student_id || "" },
    paperName: "综合任务卷",
    modeLabel: "正式考试",
    questions: [{}], idx: 0, results: [],
    startAt: Date.now(), endAt: null,
    tasks: taskMeta,
    paperTitle: paper.title || "综合任务：完成 BIOS 配置后按 F10 保存退出",
    examDate: paper.exam_date || "",
    examTime: paper.exam_time || ""
  };

  $("hudMode").textContent = "正式考试";
  $("hudQTotal").textContent = "1";
  $("hudScoreWrap").classList.add("hidden");
  if(window.SimExam) SimExam.setWho((boot.student_name||"") + "　" + (boot.class_name||""));
  showScreen("bios");
  startTimer();
  // 先走一遍开机自检（含内存报错处置），再进入 BIOS 设置界面——还原真实装机流程
  runPOST(function(){ loadQuestion(); });
}

function startTimer(){
  stopTimer();
  timerId = setInterval(()=>{
    if(!session) return;
    $("hudTime").textContent = fmtClock(Date.now() - session.startAt);
  }, 1000);
  $("hudTime").textContent = "00:00";
}
function stopTimer(){ if(timerId){ clearInterval(timerId); timerId = null; } }
function fmtClock(ms){
  const t = Math.max(0, Math.floor(ms/1000));
  return pad(Math.floor(t/60),2) + ":" + pad(t%60,2);
}

function curQuestion(){ return session.questions[session.idx]; }

/**
 * 生成受监控的 BIOS 状态对象。
 * 用 Proxy 包一层后，任何 state.xxx = yyy 都会自动产生一条操作事件，
 * 无需在十几处赋值点手工埋点（手工埋点改一次漏一次）。
 */
function mkState(raw){
  return (window.SimExam) ? SimExam.makeObservable(raw) : raw;
}

function loadQuestion(){
  // ============ 考试模式：综合任务制，一次进入 BIOS 完成全部配置 ============
  if(session && session.mode === "exam"){
    state = mkState(clone(DEFAULT_STATE));
    if(session.initial) Object.assign(state, clone(session.initial));
    baseline = clone(state);

    bios.tabIndex = 0; bios.itemIndex = 0;
    bios.sub = null; bios.subIndex = 0;
    bios.edit = false; bios.editField = 0; bios.digitBuf = "";
    bios.modal = null; bios.quizSel = 0;

    $("hudQNo").textContent = "1";
    $("hudQTotal").textContent = "1";
    $("hudStem").textContent = session.paperTitle || "综合任务：按要求完成 BIOS 配置后按 F10 保存退出";
    $("quizPanel").classList.add("hidden");
    renderExamTasks();
    setStatus("完成全部任务后，按 F10 保存并退出即交卷。操作过程已实时记录。");
    ensureSelectable();
    renderBIOS();
    return;
  }

  const q = curQuestion();
  // 全新 BIOS 会话：默认状态 + 本题初始覆盖
  state = mkState(clone(DEFAULT_STATE));
  if(q.initial) Object.assign(state, clone(q.initial));
  baseline = clone(state);

  bios.tabIndex = 0;
  bios.itemIndex = 0;
  bios.sub = null; bios.subIndex = 0;
  bios.edit = false; bios.editField = 0; bios.digitBuf = "";
  bios.modal = null;
  bios.quizSel = 0;

  // HUD
  $("hudQNo").textContent = session.idx + 1;
  $("hudStem").textContent = q.stem;
  updateHudScore();

  // 知识题面板
  const isQuiz = q.type === "quiz";
  $("quizPanel").classList.toggle("hidden", !isQuiz);
  if(isQuiz) renderQuiz();

  setStatus("按 F10 保存并退出以提交本题（练习模式可先自由尝试）");
  ensureSelectable();
  renderBIOS();
  focusBios();
}

/* 考试模式的任务清单面板：告诉学生要做哪几件事，但不透露判分细则 */
function renderExamTasks(){
  let box = $("examTaskPanel");
  if(!box){
    box = document.createElement("div");
    box.id = "examTaskPanel";
    box.className = "exam-tasks";
    const hud = document.querySelector("#screen-bios .hud");
    if(hud) hud.appendChild(box); else document.body.appendChild(box);
  }
  const items = (session && session.tasks) || [];
  box.innerHTML =
    '<div class="et-h">📋 考试任务清单（完成后按 F10 保存退出）</div>' +
    '<ol class="et-list">' + items.map(function(t){
      return '<li data-id="' + esc(t.id) + '"><span class="et-n">' + esc(t.name) +
             '</span><span class="et-p">' + t.pts + '分</span></li>';
    }).join("") + '</ol>';
  box.style.display = items.length ? "" : "none";
}

function focusBios(){ try{ $("biosRoot").focus(); }catch(e){} }

function updateHudScore(){
  if(!session || session.mode!=="practice") return;
  const got = session.results.reduce((a,r)=>a+r.got, 0);
  const done = session.results.length;
  $("hudScore").textContent = `${got} 分 / 已答 ${done} 题`;
}

/* ============================================================
   ⑧ BIOS 渲染
   ============================================================ */
function curTab(){ return TABS[bios.tabIndex]; }
function isSelectable(it){ return it.type !== "section"; }
function ensureSelectable(){
  const items = curTab().items;
  if(!isSelectable(items[bios.itemIndex])){
    for(let i=0;i<items.length;i++){ if(isSelectable(items[i])){ bios.itemIndex=i; return; } }
  }
}
function curItem(){ return curTab().items[bios.itemIndex]; }

function renderTabs(){
  const el = $("biosTabs");
  el.innerHTML = TABS.map((t,i)=>
    `<span class="bios-tab ${i===bios.tabIndex?"active":""}">${t.name}</span>`
  ).join("");
}

function renderValueHtml(it){
  if(it.type==="info") return `<span class="valwrap ro-v">${esc(it.value)}</span>`;
  if(it.type==="enum") return `<span class="valwrap">${esc(state[it.key])}</span>`;
  if(it.type==="password") return `<span class="valwrap ${state[it.key]?"":"ro-v"}">${state[it.key]?"Set":"Not Set"}</span>`;
  if(it.type==="submenu" || it.type==="action") return `<span class="valwrap">▶</span>`;
  if(it.type==="time" || it.type==="date"){
    const parts = it.type==="time" ? timeParts(state[it.key]) : dateParts(state[it.key]);
    const active = bios.edit && curItem()===it && !bios.sub;
    const seps = it.type==="time" ? [":",":"] : ["/","/"];
    let html = "";
    parts.forEach((v,i)=>{
      if(i>0) html += `<span class="sep">${seps[i-1]}</span>`;
      const isAct = active && i===bios.editField;
      html += `<span class="field ${isAct?"active":""}">${pad(v, fieldLen(it.type,i))}</span>`;
    });
    return `<span class="valwrap">${html}</span>`;
  }
  return "";
}

function renderBIOS(){
  renderTabs();
  const list = $("biosList");
  const help = $("biosHelp");

  if(bios.sub === "bootPriority"){
    // 启动顺序子菜单
    list.innerHTML = `<div class="section">Boot Device Priority</div>` +
      state.bootOrder.map((d,i)=>
        `<div class="row ${i===bios.subIndex?"sel":""}">
           <span class="lbl">${i+1}. ${esc(d)}</span>
         </div>`
      ).join("");
    help.innerHTML =
      `<div class="h-title">Item Specific Help</div>
       <div class="h-body">用 <b>↑ ↓</b> 选择设备，用 <b>+ / -</b> 或 F5/F6 上移 / 下移调整启动顺序。</div>
       <div class="h-extra">排在最上面的设备会被最先尝试启动。按 <b>Esc</b> 返回上一级。</div>`;
    renderModal();
    return;
  }

  const items = curTab().items;
  list.innerHTML = items.map((it,i)=>{
    if(it.type==="section") return `<div class="section">${esc(it.title)}</div>`;
    const sel = i===bios.itemIndex;
    const ro = it.type==="info";
    return `<div class="row ${sel?"sel":""} ${ro?"ro":""}">
              <span class="lbl">${esc(it.label)}</span>${renderValueHtml(it)}
            </div>`;
  }).join("");

  const it = curItem();
  help.innerHTML =
    `<div class="h-title">Item Specific Help</div>
     <div class="h-body">${it && it.help ? esc(it.help) : ""}</div>
     <div class="h-extra">F9 = 恢复默认设置　|　F10 = 保存并退出</div>`;

  renderModal();
}

function renderModal(){
  const root = $("biosRoot");
  const old = root.querySelector(".bios-modal");
  if(old) old.remove();
  if(!bios.modal) return;
  const m = bios.modal;
  const div = document.createElement("div");
  div.className = "bios-modal";
  if(m.kind==="yn"){
    div.innerHTML = `<div class="m-title">${esc(m.title)}</div>
      <div class="m-text">${esc(m.text)}</div>
      <div class="m-hint">按 Y 确认，按 N 或 Esc 取消</div>`;
  }else{
    div.innerHTML = `<div class="m-title">${esc(m.title)}</div>
      <div class="m-text">${esc(m.text)}</div>
      <input type="text" id="modalInput" value="${esc(m.value||"")}" autocomplete="off">
      <div class="m-hint">${esc(m.hint||"")}</div>`;
  }
  root.appendChild(div);
  if(m.kind==="input"){
    const inp = div.querySelector("#modalInput");
    inp.focus();
    inp.onkeydown = (e)=>{
      e.stopPropagation();
      if(e.key==="Enter"){ e.preventDefault(); const v=inp.value; closeModal(); m.onOk && m.onOk(v); renderBIOS(); }
      else if(e.key==="Escape"){ e.preventDefault(); closeModal(); renderBIOS(); }
    };
  }
}
function closeModal(){ bios.modal = null; }

/* 知识题面板 */
function renderQuiz(){
  const q = curQuestion();
  const box = $("quizOpts");
  const labels = ["A","B","C","D","E"];
  box.innerHTML = q.options.map((o,i)=>
    `<div class="qp-opt ${i===bios.quizSel?"active":""}">
       <span class="key">${labels[i]}</span><span>${esc(o)}</span>
     </div>`
  ).join("");
}

/* ============================================================
   ⑨ 键盘控制
   ============================================================ */
window.addEventListener("keydown", (e)=>{
  if(currentScreen==="bios"){ handleBiosKey(e); }
  else if(currentScreen==="feedback"){
    if(e.key==="Enter"){ e.preventDefault(); gotoNextQuestion(); }
  }
}, true);

function handleBiosKey(e){
  const q = curQuestion();
  if(!q) return;

  // 弹窗优先
  if(bios.modal){
    if(bios.modal.kind==="yn"){
      if(e.key==="y"||e.key==="Y"){ e.preventDefault(); const cb=bios.modal.onYes; closeModal(); renderBIOS(); cb && cb(); return; }
      if(e.key==="n"||e.key==="N"||e.key==="Escape"){ e.preventDefault(); closeModal(); renderBIOS(); return; }
      return;
    }
    return; // input 弹窗由输入框自身处理
  }

  // 知识题：只用 ↑↓ + Enter
  if(q.type==="quiz"){
    if(e.key==="ArrowUp"){ e.preventDefault(); bios.quizSel=(bios.quizSel-1+q.options.length)%q.options.length; renderQuiz(); }
    else if(e.key==="ArrowDown"){ e.preventDefault(); bios.quizSel=(bios.quizSel+1)%q.options.length; renderQuiz(); }
    else if(e.key==="Enter"){ e.preventDefault(); submitQuiz(); }
    return;
  }

  // 启动顺序子菜单（优先处理，含 F5/F6）
  if(bios.sub==="bootPriority"){
    if(e.key==="ArrowUp"){ e.preventDefault(); bios.subIndex=(bios.subIndex-1+state.bootOrder.length)%state.bootOrder.length; renderBIOS(); return; }
    if(e.key==="ArrowDown"){ e.preventDefault(); bios.subIndex=(bios.subIndex+1)%state.bootOrder.length; renderBIOS(); return; }
    if(e.key==="+"||e.key==="="||e.key==="F5"){ e.preventDefault(); moveBoot(-1); return; }
    if(e.key==="-"||e.key==="_"||e.key==="F6"){ e.preventDefault(); moveBoot(1); return; }
  }

  // 功能键
  if(e.key==="F9"){ e.preventDefault(); if(window.SimExam) SimExam.emit('key','F9',{}); askDefaults(); return; }
  if(e.key==="F10"){ e.preventDefault(); if(window.SimExam) SimExam.emit('key','F10',{}); askSaveExit(); return; }
  if(e.key==="F12"){ e.preventDefault(); if(window.SimExam) SimExam.emit('key','F12',{}); openBootMenu(); return; }
  if(e.key==="F5"||e.key==="F6"){ e.preventDefault(); changeValue(e.key==="F5"?-1:1); return; }
  if(e.key==="Escape"){ e.preventDefault(); onEscape(); return; }

  // 子菜单内的其它按键不处理
  if(bios.sub==="bootPriority") return;

  // 时间/日期 编辑模式
  if(bios.edit){
    if(e.key==="ArrowUp"||e.key==="+"||e.key==="="){ e.preventDefault(); bumpField(1); return; }
    if(e.key==="ArrowDown"||e.key==="-"){ e.preventDefault(); bumpField(-1); return; }
    if(e.key==="ArrowLeft"){ e.preventDefault(); bios.editField=(bios.editField-1+3)%3; bios.digitBuf=""; renderBIOS(); return; }
    if(e.key==="ArrowRight"){ e.preventDefault(); bios.editField=(bios.editField+1)%3; bios.digitBuf=""; renderBIOS(); return; }
    if(/^[0-9]$/.test(e.key)){ e.preventDefault(); typeDigit(e.key); return; }
    if(e.key==="Enter"||e.key==="Escape"){ e.preventDefault(); bios.edit=false; bios.digitBuf=""; setStatus(""); renderBIOS(); return; }
    return;
  }

  // 普通导航
  if(e.key==="ArrowLeft"){ e.preventDefault(); switchTab(-1); }
  else if(e.key==="ArrowRight"){ e.preventDefault(); switchTab(1); }
  else if(e.key==="ArrowUp"){ e.preventDefault(); moveItem(-1); }
  else if(e.key==="ArrowDown"){ e.preventDefault(); moveItem(1); }
  else if(e.key==="Enter"){ e.preventDefault(); activateItem(); }
  else if(e.key==="+"||e.key==="="){ e.preventDefault(); changeValue(1); }
  else if(e.key==="-"||e.key==="_"){ e.preventDefault(); changeValue(-1); }
}

function switchTab(d){
  bios.tabIndex = (bios.tabIndex + d + TABS.length) % TABS.length;
  bios.itemIndex = 0;
  bios.edit=false; bios.digitBuf="";
  ensureSelectable();
  // 埋点：是否找对了页签，是"流程分"的依据
  if(window.SimExam) SimExam.emit('nav', 'tab:' + TABS[bios.tabIndex].name, {});
  setStatus("");
  renderBIOS();
}
function moveItem(d){
  const items = curTab().items;
  let i = bios.itemIndex;
  for(let step=0; step<items.length; step++){
    i = (i + d + items.length) % items.length;
    if(isSelectable(items[i])){ bios.itemIndex=i; break; }
  }
  bios.edit=false; bios.digitBuf="";
  setStatus("");
  renderBIOS();
}
function moveBoot(d){
  const i = bios.subIndex;
  const j = i + d;
  if(j<0 || j>=state.bootOrder.length) return;
  // 先构造新数组再整体赋值：
  // 若直接对 state.bootOrder 做解构交换，会触发两次 set 且中间态是错的，
  // 服务端重放时就无法还原"把谁移到了第几位"。
  const next = state.bootOrder.slice();
  const tmp = next[i]; next[i] = next[j]; next[j] = tmp;
  state.bootOrder = next;
  bios.subIndex = j;
  renderBIOS();
}

function changeValue(d){ changeValueOn(curItem(), d); }
function changeValueOn(it, d){
  if(!it) return;
  if(it.type==="enum"){
    const idx = it.options.indexOf(state[it.key]);
    const nidx = (idx + d + it.options.length) % it.options.length;
    state[it.key] = it.options[nidx];
    renderBIOS();
  } else if(it.type==="time" || it.type==="date"){
    // 直接改当前字段（无需进入编辑）
    bios.edit = true;
    bumpField(d, it);
  }
}

function bumpField(d, itArg){
  const it = itArg || curItem();
  if(!it || (it.type!=="time" && it.type!=="date")) return;
  const parts = it.type==="time" ? timeParts(state[it.key]) : dateParts(state[it.key]);
  const idx = bios.editField;
  let v = parts[idx] + d;
  if(v > fieldMax(it.type, idx)) v = fieldMin(it.type, idx);
  if(v < fieldMin(it.type, idx)) v = fieldMax(it.type, idx);
  parts[idx] = v;
  state[it.key] = it.type==="time" ? fmtTime(parts) : fmtDate(parts);
  bios.digitBuf = "";
  setStatus("编辑中：← → 切换字段，↑ ↓ / + - 调整，直接输入数字，Enter / Esc 完成");
  renderBIOS();
}

function typeDigit(digit){
  const it = curItem();
  if(!it || (it.type!=="time" && it.type!=="date")) return;
  bios.digitBuf += digit;
  const idx = bios.editField;
  let val = parseInt(bios.digitBuf, 10);
  const max = fieldMax(it.type, idx);
  if(val > max) val = max;
  const parts = it.type==="time" ? timeParts(state[it.key]) : dateParts(state[it.key]);
  parts[idx] = val;
  state[it.key] = it.type==="time" ? fmtTime(parts) : fmtDate(parts);
  if(bios.digitBuf.length >= fieldLen(it.type, idx)){
    bios.digitBuf = "";
    bios.editField = (idx + 1) % 3;
  }
  setStatus("编辑中：← → 切换字段，↑ ↓ / + - 调整，直接输入数字，Enter / Esc 完成");
  renderBIOS();
}

function activateItem(){
  const it = curItem();
  if(!it) return;
  if(it.type==="submenu" && it.key==="__bootPriority"){
    bios.sub = "bootPriority"; bios.subIndex = 0;
    if(window.SimExam) SimExam.emit('nav', 'submenu:__bootPriority', {});
    renderBIOS(); return;
  }
  if(it.type==="action"){ runAction(it.action); return; }
  if(it.type==="enum"){ changeValue(1); return; }
  if(it.type==="time" || it.type==="date"){ bios.edit = true; bios.editField = 0; bios.digitBuf=""; setStatus("编辑中：← → 切换字段，↑ ↓ / + - 调整，直接输入数字，Enter / Esc 完成"); renderBIOS(); return; }
  if(it.type==="password"){ openPasswordModal(it); return; }
}

/**
 * 密码设置：真实 BIOS 必须"输入 → 再确认一次"，两次不一致会提示
 * Password Installed Failed。原实现只输一次就生效，不符合真机行为，
 * 也让学生可以随手一按就拿分，这里补上二次确认。
 * 注意：事件里只记"确认是否通过"，绝不记录密码明文。
 */
function openPasswordModal(it){
  const cur = state[it.key];
  bios.modal = {
    kind:"input",
    title: it.label,
    text: cur ? `当前已设置：${cur}\n输入新密码后回车；留空回车表示清除密码。` : "请输入新密码（留空回车表示不设置）。",
    value:"",
    hint:"按 Enter 确认，Esc 取消",
    onOk:(v)=>{
      v = (v||"").trim();
      if(!v.length){
        state[it.key] = null;
        if(window.SimExam) SimExam.emit('step', 'pwd.clear', { field: it.key });
        setStatus(`已清除 ${it.label}`);
        renderBIOS();
        return;
      }
      // 第二步：确认新密码
      bios.modal = {
        kind:"input",
        title: "Confirm New Password",
        text: "请再次输入相同的密码以确认：",
        value:"",
        hint:"两次输入必须一致；Enter 确认，Esc 取消",
        onOk:(v2)=>{
          v2 = (v2||"").trim();
          if(v2 !== v){
            setStatus("两次输入的密码不一致，密码设置失败（真机提示：Password Installed Failed）。");
            if(window.SimExam) SimExam.emit('step', 'pwd.confirm', { ok:false, field: it.key });
            renderBIOS();
            return;
          }
          state[it.key] = v;
          setStatus(`已设置 ${it.label}（二次确认通过）`);
          if(window.SimExam) SimExam.emit('step', 'pwd.confirm', { ok:true, field: it.key });
          renderBIOS();
        }
      };
      renderBIOS();
    }
  };
  renderBIOS();
}

function runAction(action){
  if(window.SimExam) SimExam.emit('action', action, {});
  if(action==="saveExit") askSaveExit();
  else if(action==="defaults") askDefaults();
  else if(action==="discardExit") askDiscardExit();
  else if(action==="saveOnly"){ setStatus("修改已保存（按 F10 可保存并退出、提交本题）。"); }
  else if(action==="faultQuiz"){ openFaultQuiz(); }
}

function onEscape(){
  if(bios.sub){ bios.sub=null; renderBIOS(); return; }
  if(bios.edit){ bios.edit=false; bios.digitBuf=""; setStatus(""); renderBIOS(); return; }
  askDiscardExit();
}

/* ============================================================
   ⑪-a 开机自检（POST）/ F12 启动菜单 / 故障判断
   真实装机流程里，BIOS 设置之前的自检、以及独立的一次性启动菜单，
   都是技师班学生必须会的。原系统缺这三块，这里补齐。
   ============================================================ */

function showOverlay(html, onMount){
  let el = $("simOverlay");
  if(!el){
    el = document.createElement("div");
    el.id = "simOverlay"; el.className = "sim-overlay";
    document.body.appendChild(el);
  }
  el.innerHTML = html;
  el.style.display = "";
  if(onMount) onMount(el);
  return el;
}
function hideOverlay(){ const el = $("simOverlay"); if(el) el.style.display = "none"; }

/**
 * 开机自检。逐行滚动出真机开机画面，中途报一个内存错误，
 * 让学生判断怎么处置（先重新插拔排查，无效再更换）。
 */
function runPOST(onDone){
  const lines = [
    "Phoenix SecureCore(tm) BIOS Version 2.05",
    "Copyright (C) 1985-2012 Phoenix Technologies Ltd. All Rights Reserved",
    "",
    "CPU : Intel(R) Core(TM) i3-3110M CPU @ 2.40GHz",
    "Speed : 2.40 GHz      Count : 2",
    "",
    "Testing Memory ........................."
  ];

  showOverlay('<div class="post-screen" id="postText"></div>');
  const box = $("postText");
  let i = 0;

  const timer = setInterval(()=>{
    if(i < lines.length){
      box.textContent += lines[i++] + "\n";
      return;
    }
    clearInterval(timer);

    // 内存自检报错：真机此时会停在这里并给出提示
    box.innerHTML += '<span class="err">ERROR : Memory module in DIMM1 failed the POST test</span>\n'
                   + '<span class="err">        Memory Size decreased from 4096 MB to 2048 MB</span>\n'
                   + '<span class="hint">        Press F1 to continue, DEL to enter SETUP</span>\n';
    if(window.SimExam) SimExam.emit('step', 'post.detected', { code: 'DIMM1' });

    setTimeout(()=> askPostHandle(onDone), 900);
  }, 240);
}

function askPostHandle(onDone){
  const opts = [
    { k:"A", t:"先关机，把内存条拔下来用橡皮擦金手指后重新插紧，再开机观察", v:"reseat", good:true },
    { k:"B", t:"直接判定内存条损坏，更换一根新内存条", v:"replace", good:false },
    { k:"C", t:"忽略报错，按 F1 继续开机进系统", v:"ignore", good:false }
  ];
  showOverlay(
    '<div class="sim-choice">' +
    '<h3>开机自检报错：内存未通过 POST 测试</h3>' +
    '<div class="sub">你是机房维护人员，正确的排查顺序是？<br>' +
    '（提示：先排除接触不良这类低成本原因，再考虑更换硬件）</div>' +
    '<ul>' + opts.map(o =>
      `<li data-v="${o.v}"><span class="k">${o.k}</span>${esc(o.t)}</li>`).join("") + '</ul>' +
    '<div class="foot">用鼠标点选，或按 A / B / C 键</div></div>',
    (el)=>{
      const pick = (v)=>{
        if(window.SimExam) SimExam.emit('step', 'post.handle', { action: v });
        el.querySelectorAll("li").forEach(li=>{
          li.classList.toggle("sel", li.dataset.v === v);
        });
        const chosen = opts.find(o=>o.v===v);
        setTimeout(()=>{
          box_done(chosen, onDone);
        }, 500);
      };
      el.querySelectorAll("li").forEach(li=>{ li.onclick = ()=>pick(li.dataset.v); });
      el._onKey = (e)=>{
        const k = (e.key||"").toUpperCase();
        const o = opts.find(x=>x.k===k);
        if(o){ e.preventDefault(); document.removeEventListener("keydown", el._onKey, true); pick(o.v); }
      };
      document.addEventListener("keydown", el._onKey, true);
    }
  );

  function box_done(chosen, onDone){
    showOverlay(
      '<div class="sim-choice">' +
      '<h3>' + (chosen.good ? '✔ 处置合理' : '⚠ 处置不够规范') + '</h3>' +
      '<div class="sub">' +
      (chosen.good
        ? '内存报错绝大多数是金手指氧化或没插紧导致的。先断电重新插拔是最省成本、也最应该先做的排查；仍无效再考虑更换内存。'
        : '直接换内存跳过了最基础的排查。规范顺序应是：先重新插拔（排除接触不良）→ 仍报错再更换 → 更换无效则检查内存插槽或主板。') +
      '</div><div class="foot">按任意键继续开机…</div></div>',
      (el2)=>{
        const go = ()=>{ document.removeEventListener("keydown", go, true); afterPost(onDone); };
        document.addEventListener("keydown", go, true);
        el2.onclick = go;
      }
    );
  }
}

function afterPost(onDone){
  showOverlay(
    '<div class="post-screen" id="postText2">Initializing USB Controllers .. Done.\n'
    + 'Detecting IDE Drives ...\n'
    + '  ' + DEV.hdd + '\n'
    + '  ' + DEV.cd + '\n\n'
    + '<span class="hint">Press F2 to enter SETUP, F12 to select boot device</span>\n</div>'
  );
  setTimeout(()=>{ hideOverlay(); if(onDone) onDone(); }, 1600);
}

/**
 * F12 一次性启动菜单：临时换个设备启动，不改动 BIOS 里的启动顺序。
 * 装机时最常用的就是这个——不用进 BIOS 改设置就能从 U 盘启动。
 */
function openBootMenu(){
  const devices = [
    { name: DEV.hdd, tag:"SATA HDD" },
    { name: DEV.cd,  tag:"CD/DVD" },
    { name: DEV.usb, tag:"USB HDD（U 盘）" },
    { name: DEV.net, tag:"Network / PXE" }
  ];
  showOverlay(
    '<div class="sim-choice">' +
    '<h3>Boot Menu（一次性启动菜单）</h3>' +
    '<div class="sub">本次开机临时选择启动设备，<b>不会</b>修改 BIOS 中的启动顺序。<br>' +
    '装机进 PE 时通常选哪一项？</div>' +
    '<ul>' + devices.map((d,i)=>
      `<li data-v="${esc(d.name)}"><span class="k">${i+1}</span>${esc(d.tag)}　<span style="color:#7fa3bd">${esc(d.name)}</span></li>`
    ).join("") + '</ul>' +
    '<div class="foot">点选或按数字键 1~4，Esc 取消</div></div>',
    (el)=>{
      const pick = (name)=>{
        if(window.SimExam) SimExam.emit('step', 'bootmenu.pick', { device: name });
        const isUsb = String(name).indexOf('USB') === 0;
        setTimeout(()=>{
          showOverlay(
            '<div class="sim-choice"><h3>' + (isUsb ? '✔ 正在从 U 盘启动' : '已选择：' + esc(name)) + '</h3>' +
            '<div class="sub">' + (isUsb
              ? 'U 盘启动成功。实际装机时此时会进入 PE 维护环境或系统安装界面。'
              : '提示：装机进 PE 一般应选 USB HDD（U 盘）。这只是临时启动，不影响 BIOS 里的启动顺序。') +
            '</div><div class="foot">按任意键返回</div></div>',
            (el2)=>{ const go=()=>{ document.removeEventListener("keydown",go,true); hideOverlay(); };
                     document.addEventListener("keydown",go,true); el2.onclick=go; }
          );
        }, 300);
      };
      el.querySelectorAll("li").forEach(li=>{ li.onclick = ()=>pick(li.dataset.v); });
      const onKey = (e)=>{
        if(e.key === "Escape"){ document.removeEventListener("keydown", onKey, true); hideOverlay(); return; }
        const n = parseInt(e.key, 10);
        if(n >= 1 && n <= devices.length){
          e.preventDefault();
          document.removeEventListener("keydown", onKey, true);
          pick(devices[n-1].name);
        }
      };
      document.addEventListener("keydown", onKey, true);
    }
  );
}

/** 故障判断小测：拔掉硬盘后开机报什么错 */
function openFaultQuiz(){
  const opts = [
    { k:"A", t:"No boot device / 找不到可启动设备", good:true },
    { k:"B", t:"Windows 蓝屏（BSOD）", good:false },
    { k:"C", t:"自动进入 BIOS 设置界面", good:false },
    { k:"D", t:"屏幕完全不亮、无任何显示", good:false }
  ];
  showOverlay(
    '<div class="sim-choice">' +
    '<h3>故障判断</h3>' +
    '<div class="sub">一台正常使用的电脑，把硬盘的数据线和电源线都拔掉后开机，' +
    '屏幕最可能出现什么提示？</div>' +
    '<ul>' + opts.map(o=>`<li data-v="${o.k}"><span class="k">${o.k}</span>${esc(o.t)}</li>`).join("") + '</ul>' +
    '<div class="foot">点选或按 A~D</div></div>',
    (el)=>{
      const pick = (k)=>{
        const chosen = opts.find(o=>o.k===k);
        if(window.SimExam) SimExam.emit('step', 'fault.answer', { ok: !!chosen.good, choice: k });
        setTimeout(()=>{
          showOverlay(
            '<div class="sim-choice"><h3>' + (chosen.good ? '✔ 回答正确' : '✘ 回答错误') + '</h3>' +
            '<div class="sub">硬盘自检通过后，BIOS 会按顺序找启动设备；一块硬盘都没有时，' +
            '会停在 <b>No boot device / No bootable device</b> 并提示按任意键重启。<br>' +
            '蓝屏是系统已加载后才可能出现的故障；屏幕不亮多是内存、显卡或电源问题。</div>' +
            '<div class="foot">按任意键返回</div></div>',
            (el2)=>{ const go=()=>{ document.removeEventListener("keydown",go,true); hideOverlay(); };
                     document.addEventListener("keydown",go,true); el2.onclick=go; }
          );
        }, 300);
      };
      el.querySelectorAll("li").forEach(li=>{ li.onclick = ()=>pick(li.dataset.v); });
      const onKey = (e)=>{
        const k = (e.key||"").toUpperCase();
        if(opts.some(o=>o.k===k)){ e.preventDefault(); document.removeEventListener("keydown",onKey,true); pick(k); }
      };
      document.addEventListener("keydown", onKey, true);
    }
  );
}

/* ---- 弹窗动作 ---- */
function askDefaults(){
  bios.modal = {
    kind:"yn", title:"Load Setup Defaults",
    text:"是否载入出厂默认设置？\n（按 Y 将恢复所有选项的默认值）",
    onYes:()=>{ applySetupDefaults(state); setStatus("已载入出厂默认设置。按 F10 保存并退出以提交本题。"); }
  };
  renderBIOS();
}
function askSaveExit(){
  // 考试模式：F10 = 交卷，交卷后不能修改
  if(window.SimExam && SimExam.isExam()){
    bios.modal = {
      kind:"yn", title:"Save and Exit",
      text:"是否保存所有修改并退出？\n这将立即【交卷】，交卷后不能再修改。",
      onYes:()=>{
        SimExam.emit('action', 'saveExit', {});
        SimExam.flush(false);           // 先把剩余事件同步发出，再交卷
        SimExam.submit('user');
      }
    };
    renderBIOS();
    return;
  }
  bios.modal = {
    kind:"yn", title:"Save and Exit",
    text:"是否保存所有修改并退出？\n这将会提交本题并进入下一题。",
    onYes:()=>{ submitTask(); }
  };
  renderBIOS();
}
function askDiscardExit(){
  bios.modal = {
    kind:"yn", title:"Exit Discarding Changes",
    text:"是否放弃本题（不保存并退出）？\n本题将按未完成计 0 分。",
    onYes:()=>{ submitTask(true); }
  };
  renderBIOS();
}

/* ============================================================
   ⑩ 判分与流程
   ============================================================ */
function submitTask(forceFail){
  const q = curQuestion();
  let ok = false, detail = "";
  if(forceFail){ ok = false; detail = "未完成 / 已放弃"; }
  else { ok = !!q.check(state); detail = ok ? "操作正确" : "操作与要求不符"; }
  recordResult(q, ok, detail);
  advance();
}

function submitQuiz(){
  const q = curQuestion();
  const ok = bios.quizSel === q.answer;
  recordResult(q, ok, ok ? "选择正确" : "选择错误");
  advance();
}

function recordResult(q, ok, detail){
  session.results.push({
    id:q.id, type:q.type, stem:q.stem, pts:q.pts,
    got: ok ? q.pts : 0, ok,
    answerText: q.type==="quiz" ? q.options[q.answer] : q.answerText,
    hint: q.hint, explain: q.explain || ""
  });
}

function advance(){
  if(session.mode==="practice"){
    showFeedback();
  }else{
    // 考试模式：不显示对错，直接静默进入下一题
    if(session.idx < session.questions.length - 1){
      session.idx++;
      loadQuestion();
    }else{
      finishSession();
    }
  }
}

function showFeedback(){
  const r = session.results[session.results.length - 1];
  const isLast = session.idx >= session.questions.length - 1;
  const v = $("fbVerdict");
  v.classList.toggle("ok", r.ok);
  v.classList.toggle("bad", !r.ok);
  $("fbIcon").textContent = r.ok ? "✓" : "✕";
  $("fbTitle").textContent = r.ok ? "操作正确" : "操作错误";
  const got = session.results.reduce((a,x)=>a+x.got,0);
  $("fbSub").textContent = r.ok ? `本题 +${r.pts} 分　当前累计 ${got} 分`
                                : `本题 0 分　当前累计 ${got} 分`;
  $("fbStem").textContent = r.stem;
  $("fbAnswer").textContent = r.answerText;
  $("fbHint").textContent = r.hint || "—";
  $("fbNext").textContent = isLast ? "查看成绩 (Enter)" : "下一题 (Enter)";
  $("fbNext").onclick = gotoNextQuestion;
  $("fbQuit").onclick = ()=>{ session.endAt=Date.now(); finishSession(); };
  showScreen("feedback");
}

function gotoNextQuestion(){
  if(currentScreen!=="feedback") return;
  if(session.idx >= session.questions.length - 1){ finishSession(); return; }
  session.idx++;
  showScreen("bios");
  loadQuestion();
}

/* ============================================================
   ⑪ 成绩页
   ============================================================ */
function finishSession(){
  stopTimer();
  session.endAt = session.endAt || Date.now();
  const used = Math.max(0, Math.round((session.endAt - session.startAt)/1000));
  const total = session.results.reduce((a,r)=>a+r.got,0);
  const full = session.questions.length * CONFIG.ptsPerQuestion;
  const isExam = session.mode !== "practice";
  const pass = total >= CONFIG.passLine;

  let grade;
  const pct = full ? total/full*100 : 0;
  if(pct>=90) grade="优秀"; else if(pct>=80) grade="良好";
  else if(pct>=70) grade="中等"; else if(pct>=60) grade="及格"; else grade="不及格";

  $("rsScore").textContent = `${total} 分`;
  $("rsScore").classList.toggle("fail", isExam && !pass);
  $("rsGrade").textContent = isExam ? (pass ? `评定：${grade}（及格线 ${CONFIG.passLine} 分）` : `评定：${grade}（未达及格线 ${CONFIG.passLine} 分）`)
                                    : `练习完成（正确率 ${pct.toFixed(0)}%）`;
  $("rsMeta").innerHTML =
    `考生：${esc(session.student.name)}（${esc(session.student.id)}）　|　` +
    `模式：${esc(session.modeLabel)}　|　用时：${fmtClock(used*1000)}<br>` +
    `答对：${session.results.filter(r=>r.ok).length} / ${session.questions.length} 题　|　满分：${full} 分`;

  const t = $("rsTable");
  let html = `<tr><th>题号</th><th>题目</th><th>结果</th><th>得分</th><th>正确答案</th></tr>`;
  session.results.forEach((r,i)=>{
    html += `<tr>
      <td>${i+1}</td>
      <td>${esc(shorten(r.stem,34))}</td>
      <td class="${r.ok?"ok":"no"}">${r.ok?"✔ 正确":"✘ 错误"}</td>
      <td class="${r.ok?"ok":"no"}">${r.got}</td>
      <td>${esc(shorten(r.answerText,34))}</td>
    </tr>`;
  });
  t.innerHTML = html;

  $("rsWarn").textContent = isExam
    ? "提示：本成绩为浏览器本地统计，请点击下方「下载成绩单」保存后交给老师。"
    : "提示：本次为练习模式，不计入考试成绩。可返回首页重新练习。";

  $("rsDownloadCsv").onclick = ()=>downloadReport("csv");
  $("rsDownloadTxt").onclick = ()=>downloadReport("txt");
  $("rsHome").onclick = backHome;

  showScreen("result");
}
function shorten(s,n){ s=String(s); return s.length>n ? s.slice(0,n)+"…" : s; }

function backHome(){
  stopTimer();
  session = null;
  $("manualWrap").classList.add("hidden");
  showScreen("login");
}

/* ============================================================
   ⑫ 成绩单下载
   ============================================================ */
function reportHeader(){
  const used = Math.max(0, Math.round(((session.endAt||Date.now()) - session.startAt)/1000));
  const total = session.results.reduce((a,r)=>a+r.got,0);
  const full = session.questions.length * CONFIG.ptsPerQuestion;
  const pass = total >= CONFIG.passLine;
  return { used, total, full, pass };
}
function csvCell(v){ return `"${String(v).replace(/"/g,'""')}"`; }

function downloadReport(kind){
  if(!session) return;
  const {used,total,full,pass} = reportHeader();
  const base = `成绩单_${session.student.id}_${session.student.name}_${session.paperName}`;
  let content, mime, ext;

  if(kind==="csv"){
    const cols = ["学号","姓名","卷别","用时","总分","满分","是否及格"];
    session.questions.forEach((q,i)=>cols.push(`第${i+1}题得分`));
    const row1 = [session.student.id, session.student.name, session.paperName, fmtClock(used*1000), total, full,
                  session.mode==="practice" ? "练习" : (pass?"及格":"不及格")];
    session.results.forEach(r=>row1.push(r.got));

    let lines = [];
    lines.push(cols.map(csvCell).join(","));
    lines.push(row1.map(csvCell).join(","));
    lines.push("");
    lines.push(["题号","题目","结果","得分","正确答案"].map(csvCell).join(","));
    session.results.forEach((r,i)=>{
      lines.push([i+1, r.stem, r.ok?"正确":"错误", r.got, r.answerText].map(csvCell).join(","));
    });
    content = "\uFEFF" + lines.join("\r\n");
    mime = "text/csv;charset=utf-8";
    ext = "csv";
  }else{
    let L = [];
    L.push("=========== BIOS 设置模拟实训 成绩单 ===========");
    L.push("考生姓名：" + session.student.name);
    L.push("学号：" + session.student.id);
    L.push("考试模式：" + session.modeLabel + "（" + session.paperName + "）");
    L.push("用时：" + fmtClock(used*1000));
    L.push("总分：" + total + " / " + full + (session.mode==="practice" ? "（练习）" : ("　" + (pass?"及格":"不及格"))));
    L.push("");
    L.push("----------- 逐题明细 -----------");
    session.results.forEach((r,i)=>{
      L.push(`${i+1}. [${r.ok?"✔":"✘"}] ${r.got}分  ${r.stem}`);
      L.push(`     正确答案：${r.answerText}`);
    });
    L.push("");
    L.push("生成时间：" + new Date().toLocaleString("zh-CN"));
    content = L.join("\r\n");
    mime = "text/plain;charset=utf-8";
    ext = "txt";
  }

  const blob = new Blob([content], {type:mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = base + "." + ext;
  document.body.appendChild(a);
  a.click();
  setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);
}

/* ============================================================
   ⑬ 其它绑定 & 初始化
   ============================================================ */
$("hudQuit").onclick = ()=>{
  if(window.SimExam && SimExam.isExam()){
    if(confirm("考试尚未交卷，确定要离开吗？未提交的操作将不被记录。")){
      SimExam.flush(false); location.href = "/portal";
    }
    return;
  }
  if(confirm("确定要返回首页吗？当前答题进度将丢失。")){ backHome(); }
};

/* ---- 启动：判断是否处于统一考试系统（已登录）----
   必须等 DOMContentLoaded：服务端会把 window.SIM_BOOT 注入到 </body> 之前，
   同步执行时它还没定义。 */
function initSim(){
  initLogin();
  showScreen("login");

  if(!window.SimExam) return;                 // 纯离线双击打开：保持原有练习流程

  // 取服务端下发的任务清单（只含要做什么，不含判分逻辑）
  fetch('/api/sim/paper?type=bios')
    .then(r => r.ok ? r.json() : null)
    .then(d => { window.__SIM_PAPER__ = (d && d.paper) ? d.paper : {}; })
    .catch(()=>{ window.__SIM_PAPER__ = {}; })
    .then(()=>{
      SimExam.boot({
        simType: "bios",
        onReady: function(S){
          if(S.mode === "exam"){
            startExamSession();               // 已登录：直接进入正式考试
          }
          // 练习模式：留在登录页，由学生选模式后进练习
        },
        onBlocked: function(){
          // 已考过 / 未开放：给个返回入口，不要让学生卡在空页面
          setTimeout(function(){ location.href = "/portal"; }, 4000);
        }
      });
    });
}

if(document.readyState === "loading"){
  document.addEventListener("DOMContentLoaded", initSim);
}else{
  initSim();
}
