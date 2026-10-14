
/* ================= 题库 ================= */
const QUESTIONS = [
  {
    id:1, title:"快速分区 · 基础题", points:60,
    desc:"使用 DiskGenius 的【快速分区】功能，将硬盘重新分区：",
    req:["分成 <b>3 个分区</b>（1个主分区 + 2个逻辑分区均可，快速分区默认即可）",
         "C 盘（第一个分区）大小设为 <b>100 GB</b>",
         "勾选 <b>4K 对齐</b>，对齐分区到 4096 扇区",
         "分区表类型保持 <b>MBR（GUID 也可，若题目另有要求以此为准）</b>",
         "点击【确定】并在确认对话框中点击【是】完成操作"],
    check(state){
      const errs=[];
      const q=state.lastQuick;
      if(!q) return {score:0,errors:["尚未执行快速分区操作"]};
      if(q.count!==3) errs.push("分区数量应为3，实际为"+q.count);
      if(Math.abs(q.firstGB-100)>1) errs.push("第一分区(C盘)大小应为100GB，实际为"+q.firstGB+"GB");
      if(!q.align4k) errs.push("未勾选 4K 对齐");
      if(q.alignSectors!==4096) errs.push("4K对齐扇区数应为4096，实际为"+q.alignSectors);
      if(!q.confirmed) errs.push("未在确认对话框中点击【是】");
      const ratio=Math.max(0,1-errs.length/5);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:2, title:"快速分区 · 进阶题", points:60,
    desc:"按要求完成快速分区（GUID/UEFI 装机规范）：",
    req:["分区表类型选择 <b>GUID（GPT）</b>",
         "分区数量 <b>4 个</b>",
         "勾选【创建新ESP分区】和【创建MSR分区】",
         "第一分区 80GB，第二分区 200GB，其余默认",
         "勾选 4K 对齐（默认20480扇区即可），确认执行"],
    check(state){
      const errs=[]; const q=state.lastQuick;
      if(!q) return {score:0,errors:["尚未执行快速分区操作"]};
      if(q.table!=="GUID") errs.push("分区表类型应选择 GUID");
      if(q.count!==4) errs.push("分区数量应为4，实际为"+q.count);
      if(!q.esp) errs.push("未勾选【创建新ESP分区】");
      if(!q.msr) errs.push("未勾选【创建MSR分区】");
      if(Math.abs(q.firstGB-80)>1) errs.push("第一分区应为80GB，实际"+q.firstGB+"GB");
      if(Math.abs(q.secondGB-200)>1) errs.push("第二分区应为200GB，实际"+q.secondGB+"GB");
      if(!q.align4k) errs.push("未勾选 4K 对齐");
      if(!q.confirmed) errs.push("未确认执行");
      const ratio=Math.max(0,1-errs.length/7);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:3, title:"删除分区操作", points:40,
    desc:"对现有分区进行删除练习：",
    req:["在分区列表中选中 <b>E盘</b>",
         "右键或点击【删除分区】按钮",
         "在确认对话框中点击【是】"],
    check(state){
      const errs=[]; const d=state.lastDelete;
      if(!d) return {score:0,errors:["尚未执行删除分区操作"]};
      if(d.label!=="E盘") errs.push("删除的应是E盘，实际删除了"+d.label);
      if(!d.confirmed) errs.push("未在确认对话框中点击【是】");
      const ratio=Math.max(0,1-errs.length/2);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:4, title:"模拟安装系统", points:40,
    desc:"使用【Windows 安装器】模拟安装系统流程：",
    req:["打开桌面的【Windows 安装器】",
         "选择包含Windows的安装映像",
         "引导分区选择 <b>C</b>，安装分区选择 <b>C</b>",
         "点击【安装系统】并等待进度完成"],
    check(state){
      const errs=[]; const s=state.lastInstall;
      if(!s) return {score:0,errors:["尚未执行安装系统操作"]};
      if(s.boot!=="C") errs.push("引导分区应选择C");
      if(s.target!=="C") errs.push("安装分区应选择C");
      if(!s.finished) errs.push("安装进度未完成");
      const ratio=Math.max(0,1-errs.length/3);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:5, title:"硬盘健康检查（CrystalDiskInfo）", points:30,
    desc:"使用图吧工具箱中的 CrystalDiskInfo 检查硬盘健康状况：",
    req:["打开图吧工具箱 → 硬盘检测 → <b>CrystalDiskInfo</b>",
         "等待 SMART 信息加载完成（自动）",
         "判断当前硬盘健康状态并点击下方【提交健康结论】，选择 <b>良好</b>（模拟盘健康状态为良好）",
         "记录 C5 (待映射扇区数) 的原始值"],
    check(state){
      const errs=[]; const c=state.lastCdi;
      if(!c) return {score:0,errors:["尚未在 CrystalDiskInfo 中提交健康结论"]};
      if(c.verdict!=="良好") errs.push("健康结论判断错误，模拟盘状态为良好，你选择了"+c.verdict);
      if(c.c5!=="0") errs.push("C5 原始值应记录为 0，你填写的是"+c.c5);
      const ratio=Math.max(0,1-errs.length/2);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:6, title:"磁盘测速（CrystalDiskMark）", points:30,
    desc:"使用 CrystalDiskMark 对 C 盘进行基准测速：",
    req:["打开图吧工具箱 → 硬盘检测 → <b>CrystalDiskMark</b>",
         "测试分区选择 <b>C:</b>",
         "测试次数选 <b>5</b>，测试大小选 <b>1GiB</b>",
         "点击 <b>All</b> 按钮运行完整测试并等待完成",
         "完成后点击【提交成绩】"],
    check(state){
      const errs=[]; const m=state.lastCdm;
      if(!m) return {score:0,errors:["尚未提交 CrystalDiskMark 测速成绩"]};
      if(m.drive!=="C:") errs.push("测速分区应选择 C:，实际为 "+m.drive);
      if(m.count!==5) errs.push("测试次数应为5，实际为"+m.count);
      if(m.size!=="1GiB") errs.push("测试大小应为1GiB，实际为"+m.size);
      if(!m.allRun) errs.push("未点击 All 运行完整测试");
      if(!m.finished) errs.push("测试未完成就提交了成绩");
      const ratio=Math.max(0,1-errs.length/5);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:7, title:"显示器坏点检测", points:30,
    desc:"使用图吧工具箱的屏幕检测工具检测显示器：",
    req:["打开图吧工具箱 → 屏幕检测 → <b>屏幕检测(坏点/纯色)</b>",
         "依次切换 <b>红、绿、蓝、白、黑</b> 五种纯色（至少各查看一次）",
         "退出纯色模式，得出结论：模拟显示器为 <b>无坏点</b>",
         "点击【提交检测结论】"],
    check(state){
      const errs=[]; const s=state.lastScreenTest;
      if(!s) return {score:0,errors:["尚未提交屏幕检测结论"]};
      const need=["red","green","blue","white","black"];
      const miss=need.filter(c=>!s.colors.includes(c));
      if(miss.length) errs.push("还有纯色未查看: "+miss.map(c=>({red:"红",green:"绿",blue:"蓝",white:"白",black:"黑"}[c])).join("、"));
      if(s.verdict!=="无坏点") errs.push("检测结论应为【无坏点】，你选择了【"+s.verdict+"】");
      const ratio=Math.max(0,1-errs.length/(need.length+1));
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  },
  {
    id:8, title:"CPU 烤机测试", points:30,
    desc:"使用烤机工具对 CPU 进行压力测试：",
    req:["打开图吧工具箱 → 烤机测试 → <b>CPU烤机(压力测试)</b>",
         "选择测试模式 <b>极端模式(Extreme)</b>",
         "线程数保持 <b>全部线程</b>",
         "点击【开始烤机】并持续运行 <b>至少60秒</b>（模拟时间）",
         "点击【停止烤机】后提交烤机报告"],
    check(state){
      const errs=[]; const b=state.lastBurn;
      if(!b) return {score:0,errors:["尚未提交烤机报告"]};
      if(b.mode!=="Extreme") errs.push("测试模式应选择 Extreme，实际为 "+b.mode);
      if(b.threads!=="all") errs.push("线程应选择全部线程");
      if(b.durationSec<60) errs.push("烤机时长应至少60秒，实际"+(b.durationSec||0)+"秒");
      if(!b.stopped) errs.push("未正常停止烤机并提交报告");
      const ratio=Math.max(0,1-errs.length/4);
      return {score:Math.round(this.points*ratio),errors:errs};
    }
  }
];

/* ================= 全局状态 ================= */
function defaultDisks(){ return [{id:0,name:"HD0: NVMe SSD 512GB",sizeGB:476.94,parts:[
    {label:"C盘",type:"主分区",fs:"NTFS",startGB:0,sizeGB:150,used:68},
    {label:"D盘",type:"逻辑分区",fs:"NTFS",startGB:150,sizeGB:180,used:45},
    {label:"E盘",type:"逻辑分区",fs:"NTFS",startGB:330,sizeGB:146.94,used:30},
  ]}]; }

/* 用 let 而非 const：考试模式下会被换成 Proxy 包装的可观测对象。
   注意 cdmDoneAll / scrColors / burnSimSec 必须放进 state，
   否则 resetAll 清不掉（原实现里 cdmDoneAll 是模块级全局变量，
   跑过一次测速后永不重置 → 后面免做即得满分）。 */
let state = {
  disks: defaultDisks(),
  lastQuick:null, lastDelete:null, lastInstall:null,
  lastCdi:null, lastCdm:null, lastMemTest:null, lastScreenTest:null, lastBurn:null,
  examOpen:null, results:{},
  cdmDoneAll:false,     // 是否完整跑过一次 All 测速
  scrColors:[],         // 坏点检测已查看过的颜色
  burnSimSec:0,         // 烤机累计秒数
  bootPicked:null,      // 引导时选择的设备
  peReady:false         // PE 桌面是否就绪
};
const TOTAL_POINTS = QUESTIONS.reduce((s,q)=>s+q.points,0);

/**
 * 考试模式**禁用** localStorage。
 * 原实现把成绩存在浏览器本地，且 key 是全局常量 "pe_exam_state"：
 *   · 同一台机器考多个学生会互相覆盖串号
 *   · 学生 F12 改一下 localStorage 就能拿满分
 *   · 换台机器/清缓存成绩就蒸发
 * 正式考试一律走"服务端事件流"，本地只保留内存态。
 * 练习模式仍用 localStorage，方便课堂演示。
 */
function isExamMode(){ return !!(window.SimExam && SimExam.isExam()); }

function saveState(){
  if(isExamMode()) return;
  try{ localStorage.setItem("pe_exam_state", JSON.stringify({
    disks:state.disks, lastQuick:state.lastQuick, lastDelete:state.lastDelete,
    lastInstall:state.lastInstall, lastCdi:state.lastCdi, lastCdm:state.lastCdm,
    lastScreenTest:state.lastScreenTest, lastBurn:state.lastBurn, results:state.results,
    cdmDoneAll:state.cdmDoneAll, scrColors:state.scrColors, burnSimSec:state.burnSimSec
  })); }catch(e){}
}
function loadState(){
  if(isExamMode()) return;
  try{ const s=JSON.parse(localStorage.getItem("pe_exam_state")||"null"); if(s){ Object.assign(state,s); if(!s.disks) state.disks=defaultDisks(); } }catch(e){}
}
function resetAll(){
  state.lastQuick=null; state.lastDelete=null; state.lastInstall=null;
  state.lastCdi=null; state.lastCdm=null; state.lastScreenTest=null; state.lastBurn=null;
  state.results={};
  state.cdmDoneAll=false;      // ← 原实现漏了这一行，导致"免做即满分"
  state.scrColors=[];
  state.burnSimSec=0;
  state.disks=defaultDisks();
  if(isExamMode() && window.SimExam) SimExam.emit('step','env.reset',{});
  saveState();
}

/* ================= 工具函数 ================= */
const $=s=>document.querySelector(s);
function toast(msg,cls=""){ const d=document.createElement("div"); d.className="toastmsg "+cls; d.textContent=msg;
  $("#toast").appendChild(d); setTimeout(()=>d.remove(),2600); }
function fmt(n){ return n.toFixed(1); }

/* ================= 桌面图标 ================= */
const ICONS=[
 {id:"dg",name:"DiskGenius",ico:"💽",x:24,y:24,open:openDG},
 {id:"setup",name:"Windows 安装器",ico:"💿",x:24,y:130,open:openSetup},
 {id:"exam",name:"考试系统",ico:"📝",x:24,y:236,open:openExam},
 {id:"tuba",name:"图吧工具箱",ico:"🧰",x:24,y:342,open:openTuba},
 {id:"thispc",name:"此电脑",ico:"🖥️",x:24,y:448,open:()=>toast("此电脑：仅用于展示","ok")},
];
function buildDesktop(){
  const d=$("#desktop"); d.innerHTML="";
  ICONS.forEach(ic=>{
    const el=document.createElement("div"); el.className="dicon"; el.style.left=ic.x+"px"; el.style.top=ic.y+"px";
    el.innerHTML=`<div class="ico">${ic.ico}</div><div class="lbl">${ic.name}</div>`;
    el.ondblclick=ic.open; el.onclick=e=>{e.stopPropagation();};
    d.appendChild(el);
  });
}
$("#desktop").addEventListener("click",()=>{$("#startmenu").classList.remove("open");});

/* ================= 开始菜单 ================= */
function buildStartMenu(){
  const m=$("#startmenu");
  m.innerHTML=`<div class="smhead">WinPE 模拟考试系统</div>
   <div class="smitem" data-a="dg"><span class="si">💽</span>DiskGenius 分区工具</div>
   <div class="smitem" data-a="setup"><span class="si">💿</span>Windows 安装器</div>
   <div class="smitem" data-a="exam"><span class="si">📝</span>考试系统</div>
   <div class="smsep"></div>
   <div class="smitem" data-a="reset"><span class="si">🔄</span>重置考试环境</div>
   <div class="smitem" data-a="about"><span class="si">ℹ️</span>关于本系统</div>`;
  m.querySelectorAll(".smitem").forEach(it=>it.onclick=()=>{
    m.classList.remove("open");
    const a=it.dataset.a;
    if(a==="dg")openDG(); else if(a==="setup")openSetup(); else if(a==="exam")openExam();
    else if(a==="reset"){ if(confirm("确定要重置考试环境和所有答题记录吗？")){resetAll();toast("已重置考试环境","ok");refreshAll();} }
    else toast("WinPE 模拟考试系统 v1.0 — 技师培训专用");
  });
}
$("#startbtn").onclick=e=>{e.stopPropagation(); $("#startmenu").classList.toggle("open");};
document.addEventListener("click",e=>{ if(!e.target.closest("#startmenu")&&!e.target.closest("#startbtn")) $("#startmenu").classList.remove("open"); });

/* ================= 时钟 ================= */
setInterval(()=>{ const n=new Date();
  $("#clock").innerHTML=n.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"})+"<br>"+n.toLocaleDateString("zh-CN");
},1000);

/* ================= 窗口管理 ================= */
let zTop=100, winSeq=0, wins={};
function createWin(id,title,w,h,bodyHTML){
  if(wins[id]){ focusWin(id); return wins[id]; }
  const el=document.createElement("div"); el.className="win";
  el.style.width=w+"px"; el.style.height=h+"px";
  el.style.left=Math.max(10,(innerWidth-w)/2+ (winSeq*24%120))+"px";
  el.style.top=Math.max(10,(innerHeight-h)/2-30 + (winSeq*20%80))+"px";
  winSeq++;
  el.innerHTML=`<div class="titlebar"><span class="t">${title}</span>
    <span class="wbtn min">—</span><span class="wbtn max">▢</span><span class="wbtn close">✕</span></div>
    <div class="wbody">${bodyHTML}</div>`;
  $("#desktop").appendChild(el);
  const rec={el,id}; wins[id]=rec; zTop++; el.style.zIndex=zTop;
  // drag
  const tb=el.querySelector(".titlebar");
  tb.addEventListener("mousedown",ev=>{
    if(ev.target.classList.contains("wbtn"))return;
    const sx=ev.clientX-el.offsetLeft, sy=ev.clientY-el.offsetTop;
    const mv=e2=>{ el.style.left=(e2.clientX-sx)+"px"; el.style.top=Math.max(0,e2.clientY-sy)+"px"; };
    const up=()=>{ document.removeEventListener("mousemove",mv); document.removeEventListener("mouseup",up); };
    document.addEventListener("mousemove",mv); document.addEventListener("mouseup",up);
  });
  el.querySelector(".close").onclick=()=>{ el.remove(); delete wins[id]; refreshTaskbar(); };
  el.querySelector(".max").onclick=()=>{ el.classList.toggle("max"); };
  el.querySelector(".min").onclick=()=>{ el.style.display="none"; rec.min=true; refreshTaskbar(); };
  el.addEventListener("mousedown",()=>focusWin(id));
  // taskbar button
  const tb2=document.createElement("div"); tb2.className="tbtn"; tb2.textContent=title; tb2.dataset.win=id;
  tb2.onclick=()=>{ if(rec.min||el.style.display==="none"){el.style.display="flex";rec.min=false;focusWin(id);} else if(wins[id]&&el.style.zIndex==zTop){el.style.display="none";rec.min=true;} else focusWin(id); refreshTaskbar(); };
  $("#tasks").appendChild(tb2);
  refreshTaskbar();
  return rec;
}
function focusWin(id){ const r=wins[id]; if(!r)return; zTop++; r.el.style.zIndex=zTop; refreshTaskbar(); }
function refreshTaskbar(){ document.querySelectorAll(".tbtn").forEach(b=>{ const r=wins[b.dataset.win]; b.classList.toggle("active", r && !r.min); }); }
function refreshAll(){ if(wins["dg"]) renderDG(); if(wins["exam"]) renderExam(); }

/* ================= DiskGenius ================= */
let dgSel=-1;
function openDG(){
  const r=createWin("dg","DiskGenius 专业版 5.5.1 (模拟)",960,620,`
   <div class="dg">
    <div class="dg-menu"><span>硬盘</span><span>分区</span><span>工具</span><span>帮助</span></div>
    <div class="dg-toolbar">
      <button class="dg-btn" onclick="dgQuick()">快速分区</button>
      <button class="dg-btn" onclick="dgDelete()">删除分区</button>
      <button class="dg-btn" onclick="toast('模拟环境：格式化功能仅作展示')">格式化</button>
      <button class="dg-btn" onclick="toast('模拟环境：调整分区大小仅作展示')">调整分区大小</button>
      <button class="dg-btn" onclick="openExam()">考试系统</button>
    </div>
    <div class="dg-main">
      <div class="dg-left"><div class="dg-tree" id="dgTree"></div></div>
      <div class="dg-right">
        <div class="dg-diskbar"><h4 id="dgDiskTitle"></h4><div class="partbar" id="dgBar"></div></div>
        <table class="dg-table" id="dgTable"></table>
      </div>
    </div>
    <div class="dg-status"><span id="dgStatL"></span><span style="margin-left:auto" id="dgStatR"></span></div>
   </div>`);
  renderDG();
}
function renderDG(){
  const d=state.disks[0];
  $("#dgTree").innerHTML=`<div class="disknode">💾 ${d.name}</div>`+
    d.parts.map((p,i)=>`<div style="padding-left:22px;cursor:pointer" onclick="dgSel=${i};renderDG()">${p.label} (${p.fs})</div>`).join("");
  $("#dgDiskTitle").textContent=d.name+"  总容量 "+fmt(d.sizeGB)+" GB";
  const colors=["#3a7bd5","#43a047","#f4a22b","#8e5bd5","#d55b8e"];
  $("#dgBar").innerHTML=d.parts.map((p,i)=>{
    const pct=p.sizeGB/d.sizeGB*100;
    return `<div class="pseg ${dgSel===i?"psel":""}" style="width:${pct}%;background:${colors[i%5]}" onclick="dgSel=${i};renderDG()">
      <span class="pl">${p.label}</span><span class="pc">${fmt(p.sizeGB)}GB ${p.type}</span></div>`;
  }).join("");
  $("#dgTable").innerHTML=`<tr><th>分区</th><th>类型</th><th>文件系统</th><th>起始位置(GB)</th><th>大小(GB)</th><th>已用(GB)</th></tr>`+
    d.parts.map((p,i)=>`<tr class="${dgSel===i?"sel":""}" onclick="dgSel=${i};renderDG()">
      <td>${p.label}</td><td>${p.type}</td><td>${p.fs}</td><td>${fmt(p.startGB)}</td><td>${fmt(p.sizeGB)}</td><td>${p.used}</td></tr>`).join("");
  $("#dgStatL").textContent=`选中: ${dgSel>=0?d.parts[dgSel].label+" "+fmt(d.parts[dgSel].sizeGB)+"GB":"未选择"}`;
  $("#dgStatR").textContent=d.parts.length+" 个分区 | 已用 "+fmt(d.parts.reduce((s,p)=>s+p.used,0))+" GB";
}
function dlgBox(title,bodyHTML,onOk,okText="确定"){
  const mask=document.createElement("div"); mask.className="dlg-mask";
  mask.innerHTML=`<div class="dlg"><div class="dt">${title}</div><div class="db">${bodyHTML}</div>
   <div class="df"><button class="btn" data-a="cancel">取消</button><button class="btn primary" data-a="ok">${okText}</button></div></div>`;
  wins["dg"]&&wins["dg"].el.appendChild(mask);
  mask.querySelector('[data-a="cancel"]').onclick=()=>mask.remove();
  mask.querySelector('[data-a="ok"]').onclick=()=>{ if(onOk(mask)!==false) mask.remove(); };
  return mask;
}
function dgQuick(){
  const q = state.lastQuick||{};
  const m=dlgBox("快速分区 - DiskGenius",`
    <div class="quickrow"><label>分区表类型:</label>
      <select id="qTable"><option value="MBR"${q.table!=="GUID"?" selected":""}>MBR</option><option value="GUID"${q.table==="GUID"?" selected":""}>GUID(适用于UEFI)</option></select>
      <span style="font-size:11px;color:#777">修改后请点击【重置分区数量】</span></div>
    <div class="quickrow"><label>分区数量:</label>
      <select id="qCount">${[1,2,3,4,5,6].map(n=>`<option${(q.count||3)===n?" selected":""}>${n}</option>`).join("")}</select>
      <button class="btn" id="qReset" style="margin-left:12px">重置分区数量</button></div>
    <div class="chk"><input type="checkbox" id="qEsp"${q.esp?" checked":""}><label for="qEsp">创建新ESP分区</label>
      <input type="checkbox" id="qMsr"${q.msr?" checked":""}><label for="qMsr" style="margin-left:14px">创建MSR分区</label></div>
    <div id="qParts" style="margin:10px 0;border:1px solid #c0c8d4;background:#fff;padding:8px 10px"></div>
    <div class="chk"><input type="checkbox" id="qAlign"${q.align4k!==false?" checked":""}><label for="qAlign">对齐分区到此扇区数的整数倍 (4K对齐)</label>
      <select id="qAlignN" style="margin-left:8px"><option>1024</option><option>2048</option><option selected>4096</option><option>8192</option><option>20480</option></select></div>
    <div class="chk"><input type="checkbox" id="qRebuild" checked><label for="qRebuild">重建主引导记录(MBR)</label></div>
    <div class="warn">⚠ 警告: 快速分区将删除当前硬盘上的所有分区和数据！(模拟环境不破坏任何真实数据)</div>`,
  mask=>{
    const count=+mask.querySelector("#qCount").value;
    const table=mask.querySelector("#qTable").value;
    const sizes=[...mask.querySelectorAll(".qsz")].map(i=>+i.value||0);
    const align=mask.querySelector("#qAlign").checked;
    const alignN=+mask.querySelector("#qAlignN").value;
    const esp=mask.querySelector("#qEsp").checked, msr=mask.querySelector("#qMsr").checked;
    if(sizes[0]<=0){ toast("第一分区大小无效","err"); return false; }
    confirmDlg(`确认要立即执行快速分区吗？<br><br>硬盘 <b>${state.disks[0].name}</b> 将被重新划分为 <b>${count}</b> 个分区，原有数据将全部丢失。`,
    ()=>{
      // rebuild parts
      const total=state.disks[0].sizeGB;
      let rest=total - (esp?0.3:0) - (msr?0.016:0);
      let parts=[];
      let cur=0;
      if(esp){ parts.push({label:"ESP",type:"EFI系统分区",fs:"FAT32",startGB:0,sizeGB:0.3,used:0.05}); cur=0.3; }
      if(msr){ parts.push({label:"MSR",type:"Microsoft保留",fs:"-",startGB:cur,sizeGB:0.016,used:0}); cur+=0.016; }
      for(let i=0;i<count;i++){
        let sz = sizes[i];
        if(!sz||sz<=0) sz = (rest-cur)/(count-i);
        if(i===count-1) sz = rest-cur;
        // 容量溢出保护：原实现直接 Math.min(sz, rest-cur)，
        // 当 rest-cur 为负时会生成负容量分区，界面显示 "-120GB"
        if(rest-cur <= 0) sz = 0;
        else sz = Math.min(sz, rest-cur);
        parts.push({label:String.fromCharCode(67+i)+"盘",type:i===0?"主分区":"逻辑分区",fs:"NTFS",startGB:cur,sizeGB:Math.max(0,sz),used:0});
        cur+=sz;
      }
      state.disks[0].parts=parts; dgSel=-1;

      // 关键修复：判分依据必须来自**实际分出来的分区**，
      // 而不是用户在输入框里填的数字。
      // 原实现 firstGB:sizes[0] —— 学生把输入框改成 100 但实际只分出 20GB 也算对。
      const realMain = parts.filter(p=>p.type!=="EFI系统分区" && p.type!=="Microsoft保留");
      state.lastQuick={
        count: realMain.length,
        table: table,
        firstGB:  realMain[0] ? +realMain[0].sizeGB.toFixed(2) : 0,
        secondGB: realMain[1] ? +realMain[1].sizeGB.toFixed(2) : 0,
        align4k: align, alignSectors: alignN, esp, msr, confirmed: true
      };
      state.quicks = (state.quicks || []).concat([state.lastQuick]);   // 保留历史，供多题判定
      if(window.SimExam) SimExam.emit('step','dg.quick',state.lastQuick);
      saveState(); renderDG(); refreshAll();
      toast("快速分区完成：共 " + realMain.length + " 个分区，C 盘 "
            + (realMain[0] ? realMain[0].sizeGB.toFixed(1) : 0) + " GB","ok");
    });
  });
  // wire dynamic parts
  const buildParts=()=>{
    const table=m.querySelector("#qTable").value;
    const count=+m.querySelector("#qCount").value;
    const esp=m.querySelector("#qEsp").checked;
    const total=476.94;
    const box=m.querySelector("#qParts");
    let html="";
    let pre=0;
    if(table==="GUID"){ html+=`<div style="font-size:11px;color:#888;margin:2px 0">${esp?"ESP 300MB(自动)":""}${esp&&m.querySelector("#qMsr").checked?" + ":""}${m.querySelector("#qMsr").checked&&esp?"MSR 16MB(自动)":""}</div>`; }
    for(let i=0;i<count;i++){
      const lbl=String.fromCharCode(67+i);
      const def = q.firstGB&&i===0?q.firstGB:(q.secondGB&&i===1?q.secondGB:(i===count-1?"剩余":80+i*60));
      html+=`<div class="ptsize"><span style="width:110px;font-size:12px">${i===0?"主分区":(table==="GUID"&&esp?"主分区":"逻辑分区")} ${i+1} (${lbl}盘):</span>
        <input class="qsz" data-i="${i}" value="${def}"> <span class="u">GB</span>
        <div class="bar"><div class="fill"></div></div>
        ${i===0?'<span style="font-size:11px;color:#777">用于安装系统和存储数据</span>':""}</div>`;
    }
    box.innerHTML=html;
    box.querySelectorAll(".qsz").forEach(inp=>inp.oninput=drawBars);
    drawBars();
  };
  const drawBars=()=>{
    const total=476.94; let used=0;
    m.querySelectorAll(".ptsize").forEach(row=>{
      const inp=row.querySelector(".qsz");
      let v=parseFloat(inp.value);
      if(isNaN(v)||v<=0||inp.value==="剩余"){ row.querySelector(".fill").style.width="100%"; row.querySelector(".fill").style.background="#8aa6c8"; return; }
      used+=v;
      row.querySelector(".fill").style.width=Math.min(100,v/total*100)+"%";
      row.querySelector(".fill").style.background="#3266b0";
    });
  };
  const qmask=wins["dg"]?wins["dg"].el.querySelector(".dlg-mask:last-child"):null;
  if(qmask){
    qmask.querySelector("#qReset").onclick=buildParts;
    qmask.querySelector("#qCount").onchange=buildParts;
    qmask.querySelector("#qTable").onchange=buildParts;
    qmask.querySelector("#qEsp").onchange=buildParts;
    buildParts();
  }
}
function confirmDlg(msg,onYes){
  dlgBox("DiskGenius 确认",`<div style="font-size:13px;line-height:1.8">${msg}</div>`,()=>{ onYes(); });
}
function dgDelete(){
  if(dgSel<0){ toast("请先在分区列表中选中一个分区","err"); return; }
  const p=state.disks[0].parts[dgSel];
  confirmDlg(`确认要删除分区 <b>${p.label} (${fmt(p.sizeGB)}GB)</b> 吗？<br><br>分区上的所有数据将会丢失。`,
  ()=>{
    state.disks[0].parts.splice(dgSel,1); dgSel=-1;
    state.lastDelete={label:p.label,confirmed:true};
    if(window.SimExam) SimExam.emit('step','dg.delete',state.lastDelete);
    saveState(); renderDG(); refreshAll();
    toast(`已删除 ${p.label}`,"ok");
  });
}

/* ================= Windows 安装器 ================= */
function openSetup(){
  createWin("setup","Windows 安装器 (模拟)",680,480,`
   <div class="setup">
    <h2>Windows 安装器 — 模拟环境</h2>
    <p style="font-size:12px;color:#666">本界面模拟系统安装流程，用于考核装机步骤是否正确。</p>
    <div class="langsel">
      <select><option>简体中文</option><option>English</option></select>
      <select><option>zh-CN</option><option>en-US</option></select>
      <select><option>中文(简体)</option></select>
    </div>
    <div style="margin:10px 0;font-size:13px;font-weight:bold">选择包含 Windows 安装映像的文件:</div>
    <select id="iImage" style="padding:5px 8px;border:1px solid #999;border-radius:3px;width:320px">
      <option value="win11">install.wim — Windows 11 专业版 24H2</option>
      <option value="win10">install.wim — Windows 10 专业版 22H2</option>
    </select>
    <div style="margin:14px 0 6px;font-size:13px;font-weight:bold">选择引导分区 / 安装分区:</div>
    <table class="ptlist" id="iTable"></table>
    <div style="margin-top:16px;display:flex;gap:10px;align-items:center">
      <button class="bigbtn" id="iGo">安装系统</button>
      <span id="iMsg" style="font-size:12px;color:#555"></span>
    </div>
    <div class="progress" id="iProg" style="display:none"><div class="pf" id="iPF"></div></div>
    <div id="iDone" style="display:none;color:#2c7a3f;font-weight:bold"></div>
   </div>`);
  renderInstallTable();
  $("#iGo").onclick=startInstall;
}
function renderInstallTable(){
  const t=$("#iTable"); if(!t)return;
  const parts=state.disks[0].parts;
  t.innerHTML=`<tr><th>分区</th><th>大小</th><th>引导分区</th><th>安装分区</th></tr>`+
    parts.map((p,i)=>`<tr><td>${p.label} (${p.fs})</td><td>${fmt(p.sizeGB)}GB</td>
     <td><input type="radio" name="boot" value="${p.label[0]}"></td>
     <td><input type="radio" name="target" value="${p.label[0]}"></td></tr>`).join("");
}
function startInstall(){
  const boot=(document.querySelector('input[name="boot"]:checked')||{}).value;
  const target=(document.querySelector('input[name="target"]:checked')||{}).value;
  if(!boot||!target){ $("#iMsg").textContent="请先选择引导分区和安装分区"; return; }
  const img=$("#iImage").value;
  $("#iProg").style.display="block"; $("#iDone").style.display="none"; $("#iGo").disabled=true;
  let p=0;
  const timer=setInterval(()=>{
    p+=Math.random()*9+3; if(p>100)p=100;
    $("#iPF").style.width=p+"%";
    $("#iMsg").textContent=`正在应用映像 (${Math.floor(p)}%) ...`;
    if(p>=100){
      clearInterval(timer);
      $("#iMsg").textContent="";
      $("#iDone").textContent="✔ 安装完成！系统将在重启后进入 OOBE 阶段（模拟）。";
      $("#iGo").disabled=false;
      state.lastInstall={img,boot,target,finished:true};
      if(window.SimExam) SimExam.emit('step','setup.install',state.lastInstall);
      saveState(); refreshAll();
      toast("Windows 安装完成（模拟）","ok");
    }
  },200);
}

/* ================= 考试系统 ================= */
function openExam(){
  const exam = isExamMode();
  createWin("exam", exam ? "考试系统 — 正式考试" : "考试系统 — 技师学员考核", 880, 560, `
   <div class="exam">
    <div class="exam-side">
      <h3>📋 考试题目 (${QUESTIONS.length}题)</h3>
      <div id="examList"></div>
      ${exam
        /* 考试模式：不能本地判分。
           本地判分 = 把答案和判分逻辑都交给学生，可以无限重试直到满分。
           改为"交卷"，由服务端按操作事件重放判定。 */
        ? `<button class="btn primary" style="width:100%;margin-top:6px" onclick="submitWinpeExam()">交 卷</button>
           <div style="margin-top:8px;padding:8px 10px;background:#e8f4ff;border-radius:6px;font-size:11px;color:#0a4d80;line-height:1.6">
             正式考试期间不显示单题对错。<br>完成后点【交卷】，成绩由服务器判定，<b>限考 1 次</b>。</div>`
        : `<button class="btn primary" style="width:100%;margin-top:6px" onclick="gradeAll()">判分并汇总</button>
           <button class="btn" style="width:100%;margin-top:8px" onclick="resetAll();refreshAll();toast('考试环境已重置','ok')">重置考试环境</button>`
      }
    </div>
    <div class="exam-main">
      <div class="exam-head" id="examHead">请选择左侧题目</div>
      <div class="exam-body" id="examBody"><p style="color:#888">${exam
        ? "按左侧各题要求，在 DiskGenius / Windows 安装器 / 图吧工具箱中完成操作，完成后点【交卷】。"
        : "从左侧选择一道题目，按要求在 DiskGenius / Windows 安装器中完成操作，然后回到这里查看判分。"}</p></div>
      <div class="exam-score" id="examScore"></div>
    </div>
   </div>`);
  renderExam();
}

/* 正式考试交卷：先把剩余事件补发，再交给服务端判分 */
function submitWinpeExam(){
  if(!window.SimExam || !SimExam.isExam()){ toast("当前不是考试模式","err"); return; }
  if(!confirm("确定要交卷吗？交卷后不能再修改，且本科目限考 1 次。")) return;
  SimExam.flush(false);
  SimExam.submit('user');
}
function renderExam(){
  const list=$("#examList"); if(!list)return;
  list.innerHTML=QUESTIONS.map((q,i)=>{
    const r=state.results[q.id];
    const tag=r? (r.score>=q.points*0.99?`<span class="tag done">通过 ${r.score}分</span>`:`<span class="tag fail">未通过 ${r.score}分</span>`)
              :`<span class="tag todo">待完成</span>`;
    return `<div class="exam-q ${state.examOpen===q.id?"active":""}" onclick="openQ(${q.id})"><b>第${i+1}题</b> ${q.title} <span style="color:#9fc">(${q.points}分)</span>${tag}</div>`;
  }).join("");
  if(state.examOpen){ showQ(state.examOpen); } else { $("#examScore").innerHTML=""; }
}
function openQ(id){ state.examOpen=id; renderExam(); focusWin("exam"); }
function showQ(id){
  const q=QUESTIONS.find(x=>x.id===id); if(!q)return;
  $("#examHead").textContent=`第${QUESTIONS.indexOf(q)+1}题 · ${q.title}（${q.points}分）`;
  $("#examBody").innerHTML=`<p>${q.desc}</p><div class="req"><ol style="padding-left:18px">${q.req.map(r=>`<li>${r}</li>`).join("")}</ol></div>
    <p style="color:#888;font-size:12px">💡 提示：打开桌面的 DiskGenius 或 Windows 安装器完成操作后，点击下方【立即判分】。</p>
    <button class="btn primary" style="margin-top:10px" onclick="gradeOne(${q.id})">立即判分</button>`;
  const r=state.results[q.id];
  renderScoreLine(q,r);
}
function renderScoreLine(q,r){
  const s=$("#examScore"); if(!s)return;
  if(!r){ s.innerHTML=`<span>本题尚未判分 · 满分 ${q.points} 分</span>`; return; }
  const ok=r.score>=q.points*0.99;
  s.innerHTML=`<span class="score-big ${ok?"":"bad"}">${r.score} / ${q.points} 分</span>
   <span>${ok?"✔ 操作完全正确！":"✘ 存在以下问题："}</span>
   <span style="font-size:12px;color:${ok?"#cde":"#ffc9c9"}">${ok?"":r.errors.join("；")}</span>`;
}
function gradeOne(id){
  const q=QUESTIONS.find(x=>x.id===id);
  const res=q.check(state);
  state.results[id]=res; saveState(); renderExam(); renderScoreLine(q,res);
  if(res.score>=q.points*0.99) toast(`第${QUESTIONS.indexOf(q)+1}题通过！得分 ${res.score}`,"ok");
  else toast(`本题得分 ${res.score}/${q.points}，详见错误提示`,"err");
}
function gradeAll(){
  QUESTIONS.forEach(q=>{ state.results[q.id]=q.check(state); });
  saveState(); renderExam();
  const total=QUESTIONS.reduce((s,q)=>s+(state.results[q.id]?.score||0),0);
  const pct=Math.round(total/TOTAL_POINTS*100);
  const pass=pct>=60;
  $("#examScore").innerHTML=`<span class="score-big ${pass?"":"bad"}">${total} / ${TOTAL_POINTS} 分（${pct}分）</span>
   <span style="font-size:15px">${pass?"🎉 考试通过！":"未达到60分及格线，请查看各题错误提示后重试。"}</span>`;
  toast(pass?"考试通过！":"考试未通过，请继续练习",pass?"ok":"err");
}

/* ================= 图吧工具箱 ================= */
const TUBA_CATS = [
  {name:"硬件检测",tools:[
    {name:"CPU-Z",ico:"🔷",open:openCpuZ},
    {name:"GPU-Z",ico:"🔶",open:openGpuZ},
    {name:"AIDA64",ico:"🔷",open:()=>toast("AIDA64 模拟版：此处仅作展示","ok")},
  ]},
  {name:"硬盘检测",tools:[
    {name:"CrystalDiskInfo",ico:"📟",open:openCdi},
    {name:"CrystalDiskMark",ico:"📊",open:openCdm},
  ]},
  {name:"屏幕检测",tools:[
    {name:"屏幕检测(坏点/纯色)",ico:"🖼️",open:openScreenTest},
  ]},
  {name:"烤机测试",tools:[
    {name:"CPU烤机(压力测试)",ico:"🔥",open:openBurn},
    {name:"内存检测(MemTest)",ico:"🧪",open:()=>toast("MemTest 模拟版：8K条目检测中…(仅展示)","ok")},
  ]},
  {name:"外设检测",tools:[
    {name:"键盘测试",ico:"⌨️",open:()=>toast("键盘测试：按下任意按键显示键值(模拟)","ok")},
    {name:"鼠标测试",ico:"🖱️",open:()=>toast("鼠标测试：左键/右键/滚轮(模拟)","ok")},
  ]},
];
function openTuba(){
  createWin("tuba","图吧工具箱 v5.10.9.1 (模拟)",900,600,`
   <div style="display:flex;height:100%;background:#f2f5f9">
    <div style="width:190px;background:#233449;color:#dce6f2;padding:10px 0;overflow:auto;flex-shrink:0">
      <div style="text-align:center;padding:8px 0 14px;color:#7ec8ff;font-weight:bold;font-size:14px">🧰 图吧工具箱</div>
      ${TUBA_CATS.map((c,i)=>`<div style="padding:7px 16px;font-size:12.5px;${i===0?"background:#2f4a6e":""}" class="tubacat" data-i="${i}">▸ ${c.name}</div>`).join("")}
      <div style="padding:16px;font-size:10.5px;color:#7a8ba0;line-height:1.6">图吧工具箱模拟版<br>仅供技师教学考核</div>
    </div>
    <div style="flex:1;padding:14px;overflow:auto">
      <div style="font-size:14px;font-weight:bold;margin-bottom:10px" id="tubaCatTitle">硬件检测</div>
      <div style="display:flex;flex-wrap:wrap;gap:12px" id="tubaGrid"></div>
    </div>
   </div>`);
  renderTubaCat(0);
  const win=wins["tuba"].el;
  win.querySelectorAll(".tubacat").forEach(el=>el.onclick=()=>{
    win.querySelectorAll(".tubacat").forEach(x=>x.style.background="");
    el.style.background="#2f4a6e";
    renderTubaCat(+el.dataset.i);
  });
}
function renderTubaCat(i){
  const c=TUBA_CATS[i]; if(!c)return;
  const t=wins["tuba"].el.querySelector("#tubaCatTitle");
  const g=wins["tuba"].el.querySelector("#tubaGrid");
  if(t)t.textContent=c.name;
  // 修复：原实现用 `${t.open.name}()` 拼 onclick。
  // 匿名箭头函数（AIDA64/MemTest/键盘/鼠标）的 .name 是空串，
  // 生成出来的 HTML 是 onclick="()"，点击直接 JS 报错 —— 这 4 个工具实际不可用。
  // 改为 data-tool 索引 + 事件委托，与函数命名彻底解耦。
  g.innerHTML=c.tools.map((t,ti)=>`<div class="tubatool" data-ti="${ti}" style="width:96px;text-align:center;cursor:pointer;padding:10px 4px;background:#fff;border:1px solid #dfe5ec;border-radius:6px">
    <div style="font-size:30px">${t.ico}</div><div style="font-size:11.5px;margin-top:5px;color:#333">${t.name}</div></div>`).join("");

  g.onclick = (e)=>{
    const el = e.target.closest(".tubatool");
    if(!el) return;
    const tool = c.tools[+el.dataset.ti];
    if(tool && typeof tool.open === "function"){
      tool.open();
      if(window.SimExam) SimExam.emit('step','tuba.open',{tool:tool.name});
    }
  };
}
/* ---- CrystalDiskInfo ---- */
function openCdi(){
  createWin("cdi","CrystalDiskInfo 9.1.1 (模拟)",720,520,`
   <div style="background:#eef1f5;height:100%;display:flex;flex-direction:column;font-size:12px;color:#222">
    <div style="background:#dde3ea;border-bottom:1px solid #b8c0cc;padding:4px 8px;display:flex;gap:6px">
      <span style="padding:3px 10px;background:#c3d4ec;border-radius:3px">文件</span><span>编辑</span><span>功能</span><span>主题</span><span>帮助</span></div>
    <div style="display:flex;gap:10px;padding:10px 14px;align-items:center">
      <div style="border:1px solid #aab;padding:8px 14px;background:#fff;text-align:center">
        <div style="font-size:30px;font-weight:bold;color:#2c7a3f" id="cdiHealth">良好</div><div style="font-size:10px;color:#777">健康状态</div></div>
      <div style="flex:1">
        <div style="display:flex;gap:8px;margin-bottom:4px">
          <select style="padding:3px 6px"><option>HD0: NVMe SSD 512GB (模拟)</option></select>
          <span style="color:#2c7a3f;font-weight:bold">✔ 正常</span></div>
        <div style="font-size:11.5px;color:#444;line-height:1.7">
          固件: SIM1.0 &nbsp;| 通电次数: 1,024 &nbsp;| 通电时间: 3,860 小时<br>
          主机总计读取: 2.4 TB &nbsp;| 主机总计写入: 1.8 TB &nbsp;| 温度: 38 ℃</div></div></div>
    <div style="flex:1;overflow:auto;padding:0 14px 10px">
      <table style="width:100%;border-collapse:collapse;background:#fff;font-size:11px" id="cdiTable">
        <tr style="background:#3266b0;color:#fff"><th>ID</th><th>属性名</th><th>当前值</th><th>最差值</th><th>阈值</th><th>原始值</th><th>状态</th></tr>
      </table>
    </div>
    <div style="padding:8px 14px;border-top:1px solid #ccc;display:flex;gap:8px;align-items:center;background:#f7f8fa">
      <span style="font-size:12px">健康结论:</span>
      <select id="cdiVerdict" style="padding:3px 6px"><option>请选择</option><option>良好</option><option>警告</option><option>异常</option></select>
      <span style="font-size:12px;margin-left:10px">C5 (05,C6) 原始值:</span>
      <input id="cdiC5" style="width:70px;padding:3px 6px" placeholder="记录原始值">
      <button class="btn primary" onclick="cdiSubmit()">提交健康结论</button>
    </div></div>`);
  const attrs=[["01","读取错误率","100","100","0","0","正常"],["05","重新映射扇区数","100","100","10","0","正常"],
   ["09","通电时间","96","96","0","3860","正常"],["0C","通电次数","100","100","0","1024","正常"],
   ["B1","磨损平衡","100","100","0","0","正常"],["C5","待映射扇区数","100","100","1","0","正常"],
   ["C6","无法校正扇区数","100","100","0","0","正常"],["C7","CRC错误计数","100","100","0","0","正常"],
   ["E7","剩余寿命","100","100","10","100 %","正常"],["E9","磨损量","100","100","0","3 %","正常"]];
  const tb=document.querySelector("#cdiTable");
  attrs.forEach(a=>{ const tr=document.createElement("tr");
    tr.innerHTML=a.map(x=>`<td style="border:1px solid #ccd;padding:4px 8px;text-align:center">${x}</td>`).join("");
    tb.appendChild(tr); });
}
function cdiSubmit(){
  const v=document.querySelector("#cdiVerdict").value;
  const c5=document.querySelector("#cdiC5").value.trim();
  if(v==="请选择"){ toast("请先选择健康结论","err"); return; }
  state.lastCdi={verdict:v,c5:c5};
  if(window.SimExam) SimExam.emit('step','cdi.submit',state.lastCdi);
  saveState(); refreshAll();
  toast("健康结论已提交","ok");
}
/* ---- CrystalDiskMark ---- */
function openCdm(){
  createWin("cdm","CrystalDiskMark 8.0.6 (模拟)",760,560,`
   <div style="background:#f4f6f9;height:100%;display:flex;flex-direction:column;font-size:12px;color:#222">
    <div style="display:flex;gap:8px;align-items:center;padding:10px 14px;border-bottom:1px solid #ccd;flex-wrap:wrap">
      <span>测试分区:</span><select id="cdmDrive" style="padding:3px 6px"><option>C:</option><option>D:</option><option>E:</option></select>
      <span>次数:</span><select id="cdmCount" style="padding:3px 6px"><option>1</option><option>3</option><option>5</option><option>9</option></select>
      <span>大小:</span><select id="cdmSize" style="padding:3px 6px"><option>64MiB</option><option>256MiB</option><option>512MiB</option><option>1GiB</option><option>4GiB</option></select>
      <button class="btn primary" onclick="cdmRun('all')">All</button>
      <button class="btn" onclick="cdmRun('seq1m')">SEQ1M Q8T1</button>
      <button class="btn" onclick="cdmRun('rnd4k')">RND4K Q32T1</button>
    </div>
    <div style="padding:10px 14px;flex:1">
      <table style="width:100%;border-collapse:collapse;background:#fff;font-size:11.5px;text-align:center" id="cdmTable">
        <tr style="background:#3266b0;color:#fff"><th style="border:1px solid #27538f;padding:5px"></th><th style="border:1px solid #27538f">Read [MB/s]</th><th style="border:1px solid #27538f">Write [MB/s]</th></tr>
        <tr><td style="border:1px solid #ccd;padding:6px">SEQ1M Q8T1</td><td id="cdmS1R" style="border:1px solid #ccd">-</td><td id="cdmS1W" style="border:1px solid #ccd">-</td></tr>
        <tr><td style="border:1px solid #ccd;padding:6px">SEQ1M Q1T1</td><td id="cdmS2R" style="border:1px solid #ccd">-</td><td id="cdmS2W" style="border:1px solid #ccd">-</td></tr>
        <tr><td style="border:1px solid #ccd;padding:6px">RND4K Q32T1</td><td id="cdmR1R" style="border:1px solid #ccd">-</td><td id="cdmR1W" style="border:1px solid #ccd">-</td></tr>
        <tr><td style="border:1px solid #ccd;padding:6px">RND4K Q1T1</td><td id="cdmR2R" style="border:1px solid #ccd">-</td><td id="cdmR2W" style="border:1px solid #ccd">-</td></tr>
      </table>
      <div id="cdmStatus" style="margin-top:10px;font-size:11.5px;color:#555">就绪</div>
      <div class="progress" id="cdmProg" style="display:none"><div class="pf" id="cdmPF"></div></div>
    </div>
    <div style="padding:8px 14px;border-top:1px solid #ccd;background:#f7f8fa">
      <button class="btn primary" onclick="cdmSubmit()">提交成绩</button>
    </div></div>`);
}
let cdmRunning=false;
/* cdmDoneAll 原来是模块级全局变量：只要跑过一次 All，重开窗口也不会重置，
   学生点一下"提交成绩"就能拿满分。已改为 state.cdmDoneAll，随 resetAll 清零。 */
function cdmRun(mode){
  if(cdmRunning){ toast("测试进行中，请等待","err"); return; }
  cdmRunning=true;
  const drive=document.querySelector("#cdmDrive").value;
  const count=+document.querySelector("#cdmCount").value;
  const size=document.querySelector("#cdmSize").value;
  document.querySelector("#cdmProg").style.display="block";
  let p=0;
  const total=mode==="all"?8:2;
  const cells=mode==="all"?[["cdmS1R",3400,"cdmS1W",2900],["cdmS2R",3100,"cdmS2W",2700],["cdmR1R",480,"cdmR1W",520],["cdmR2R",65,"cdmR2W",180]]
                          :(mode==="seq1m"?[["cdmS1R",3400,"cdmS1W",2900]]:[["cdmR1R",480,"cdmR1W",520]]);
  let ci=0;
  const timer=setInterval(()=>{
    p+=100/(total*10);
    document.querySelector("#cdmPF").style.width=Math.min(100,p)+"%";
    document.querySelector("#cdmStatus").textContent=`[${drive}] 正在测试 (${ci+1}/${total}) ...`;
    if(p>=(ci+1)*100/total && ci<cells.length){
      const c=cells[ci];
      document.querySelector("#"+c[0]).textContent=(c[1]*(0.95+Math.random()*0.1)).toFixed(2);
      document.querySelector("#"+c[2]).textContent=(c[3]*(0.95+Math.random()*0.1)).toFixed(2);
      ci++;
    }
    if(p>=100){
      clearInterval(timer);
      document.querySelector("#cdmStatus").textContent="✔ 测试完成 ["+drive+"] count="+count+" size="+size;
      document.querySelector("#cdmProg").style.display="none";
      cdmRunning=false;
      if(mode==="all") state.cdmDoneAll=true;
      if(window.SimExam) SimExam.emit('step','cdm.rundone',{mode:mode,drive:drive,count:count,size:size});
    }
  },120);
}
function cdmSubmit(){
  const drive=document.querySelector("#cdmDrive").value;
  const count=+document.querySelector("#cdmCount").value;
  const size=document.querySelector("#cdmSize").value;
  // 关键：必须真的跑完过 All，否则点提交不给分（原来只靠一个全局标记，可绕过）
  const reallyDone = state.cdmDoneAll && !cdmRunning;
  if(!reallyDone && window.SimExam && SimExam.isExam()){
    toast("请先选择 All 并完整跑完一次测速，再提交","err");
  }
  state.lastCdm={drive,count,size,mode:"All",done:reallyDone,allRun:state.cdmDoneAll};
  if(window.SimExam) SimExam.emit('step','cdm.submit',state.lastCdm);
  saveState(); refreshAll();
  toast(reallyDone ? "测速成绩已提交" : "已提交（未完整跑完测速，该项不计分）",
        reallyDone ? "ok" : "err");
}
/* ---- 屏幕检测(坏点/纯色) ---- */
let scrOverlay=null;
function openScreenTest(){
  createWin("scr","屏幕检测 (坏点/纯色) - 模拟",640,420,`
   <div style="padding:14px;font-size:12.5px;color:#222">
    <div style="font-weight:bold;margin-bottom:6px">纯色测试</div>
    <p style="color:#666;line-height:1.7;font-size:12px">点击色块进入全屏纯色模式，仔细观察屏幕是否有坏点/亮点/暗点。按 <b>ESC</b> 或点击右上角 ✕ 退出。</p>
    <div style="display:flex;gap:10px;margin:12px 0" id="scrColors">
      <div data-c="red" style="width:70px;height:48px;background:#e53935;border:1px solid #999;cursor:pointer;border-radius:4px"></div>
      <div data-c="green" style="width:70px;height:48px;background:#43a047;border:1px solid #999;cursor:pointer;border-radius:4px"></div>
      <div data-c="blue" style="width:70px;height:48px;background:#1e88e5;border:1px solid #999;cursor:pointer;border-radius:4px"></div>
      <div data-c="white" style="width:70px;height:48px;background:#ffffff;border:1px solid #999;cursor:pointer;border-radius:4px"></div>
      <div data-c="black" style="width:70px;height:48px;background:#111;border:1px solid #999;cursor:pointer;border-radius:4px"></div>
    </div>
    <div style="font-weight:bold;margin:12px 0 6px">检测结论</div>
    <div style="display:flex;gap:8px;align-items:center">
      <select id="scrVerdict" style="padding:4px 6px"><option>请选择</option><option>无坏点</option><option>有坏点</option><option>有亮线</option></select>
      <button class="btn primary" onclick="scrSubmit()">提交检测结论</button>
    </div>
    <div id="scrLog" style="margin-top:10px;font-size:11px;color:#888"></div>
   </div>`);
  state.scrColors=state.scrColors||[];
  const win=wins["scr"].el;
  win.querySelectorAll("#scrColors > div").forEach(el=>el.onclick=()=>{
    const c=el.dataset.c;
    showPureColor(c);
    if(!state.scrColors.includes(c)) state.scrColors.push(c);
    if(window.SimExam) SimExam.emit('step','scr.view',{color:c});
    win.querySelector("#scrLog").textContent="已查看颜色: "+state.scrColors.map(x=>({red:"红",green:"绿",blue:"蓝",white:"白",black:"黑"}[x])).join("、");
  });
}

/**
 * 纯色画面。这一台"显示器"是**有问题**的：
 *   白色画面上有一个黑色暗点、黑色画面上有一个红色亮点。
 * 原实现只是铺一层纯色，屏幕上什么都没有，学生只能凭猜测选"无坏点"，
 * 题目本身不可验证。现在坏点真实可见，必须观察完白/黑两色才能发现。
 */
const SCREEN_DEFECTS = {
  white: [ {x:'42%', y:'36%', w:7, h:7, bg:'#000', kind:'暗点'} ],
  black: [ {x:'63%', y:'58%', w:7, h:7, bg:'#ff2222', kind:'亮点'} ]
};

function showPureColor(c){
  const map={red:"#e53935",green:"#43a047",blue:"#1e88e5",white:"#ffffff",black:"#111111"};
  if(scrOverlay) scrOverlay.remove();
  scrOverlay=document.createElement("div");
  scrOverlay.style.cssText=`position:fixed;inset:0;background:${map[c]};z-index:99999;`;
  let dots = "";
  (SCREEN_DEFECTS[c] || []).forEach(d=>{
    dots += `<div style="position:absolute;left:${d.x};top:${d.y};width:${d.w}px;height:${d.h}px;background:${d.bg}"></div>`;
  });
  scrOverlay.innerHTML=`<div style="position:absolute;top:12px;right:16px;background:rgba(0,0,0,.5);color:#fff;padding:6px 14px;border-radius:16px;cursor:pointer;font-size:13px" onclick="scrExit()">✕ 退出 (ESC)</div>
   ${dots}
   <div style="position:absolute;bottom:16px;left:16px;color:${c==="white"?"#888":"rgba(255,255,255,.55)"};font-size:12px">纯色测试: ${({red:"红色",green:"绿色",blue:"蓝色",white:"白色",black:"黑色"})[c]} — 仔细观察是否有亮点 / 暗点</div>`;
  document.body.appendChild(scrOverlay);
}
function scrExit(){ if(scrOverlay){scrOverlay.remove();scrOverlay=null;} }
document.addEventListener("keydown",e=>{ if(e.key==="Escape") scrExit(); });
function scrSubmit(){
  if(!state.scrColors||!state.scrColors.length){ toast("请至少查看一种纯色","err"); return; }
  const v=document.querySelector("#scrVerdict").value;
  if(v==="请选择"){ toast("请先选择检测结论","err"); return; }
  // 这台显示器确实有坏点（白屏暗点 + 黑屏亮点），结论与实际一致才算对
  const hasDefect = true;
  state.lastScreenTest={colors:[...state.scrColors], verdict:v,
                        verdict_correct: hasDefect ? (v==="有坏点") : (v==="无坏点")};
  if(window.SimExam) SimExam.emit('step','scr.submit',state.lastScreenTest);
  saveState(); refreshAll();
  scrExit();
  toast("屏幕检测结论已提交","ok");
}
/* ---- CPU 烤机 ---- */
let burnTimer=null, burnStart=0;
function openBurn(){
  createWin("burn","CPU 烤机压力测试 (模拟)",680,480,`
   <div style="padding:14px;font-size:12.5px;color:#222">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span>测试模式:</span>
      <select id="burnMode" style="padding:4px 6px"><option>标准模式(Standard)</option><option>极端模式(Extreme)</option><option>轻载模式(Light)</option></select>
      <span>线程:</span>
      <select id="burnThreads" style="padding:4px 6px"><option value="all">全部线程 (16)</option><option value="half">一半线程 (8)</option><option value="one">单线程</option></select>
      <button class="bigbtn" id="burnGo" onclick="burnStartFn()">开始烤机</button>
      <button class="btn" id="burnStop" onclick="burnStopFn()" disabled>停止烤机</button>
    </div>
    <div style="display:flex;gap:14px;margin-top:16px">
      <div style="flex:1;background:#26323f;color:#9ef2a5;border-radius:6px;padding:14px;font-family:monospace">
        <div style="color:#889;font-size:11px">CPU 温度</div><div style="font-size:28px" id="burnTemp">32 ℃</div></div>
      <div style="flex:1;background:#26323f;color:#ffd28f;border-radius:6px;padding:14px;font-family:monospace">
        <div style="color:#889;font-size:11px">CPU 功耗</div><div style="font-size:28px" id="burnPower">8 W</div></div>
      <div style="flex:1;background:#26323f;color:#8fc1ff;border-radius:6px;padding:14px;font-family:monospace">
        <div style="color:#889;font-size:11px">运行时间</div><div style="font-size:28px" id="burnTime">0:00</div></div>
      <div style="flex:1;background:#26323f;color:#ff9f9f;border-radius:6px;padding:14px;font-family:monospace">
        <div style="color:#889;font-size:11px">CPU 占用</div><div style="font-size:28px" id="burnUsage">3 %</div></div>
    </div>
    <div class="progress" id="burnNote" style="border:none;background:transparent"></div>
    <div style="margin-top:14px;font-size:12px;color:#555" id="burnStatus">就绪 — 1:1 真实秒计时，需烤满 60 秒（请确认散热良好，模拟环境无风险）</div>
    <div style="margin-top:14px">
      <button class="btn primary" onclick="burnReport()">提交烤机报告</button>
    </div>
   </div>`);
}
/**
 * 烤机计时改为 **1:1 真实秒**。
 * 原实现是 1 真实秒 = 30 模拟秒，学生点"开始"等 2 秒就直接满足"≥60 秒"，
 * 题目要求形同虚设。现在要真等满 60 秒，同时也更符合真机烤机的认知。
 *（考试 30 分钟里占 1 分钟，可接受；练习模式想快进可改用标准模式说明。）
 */
function burnStartFn(){
  if(burnTimer) return;
  burnStart=Date.now();
  state.burnSimSec=0;
  document.querySelector("#burnGo").disabled=true;
  document.querySelector("#burnStop").disabled=false;
  document.querySelector("#burnStatus").textContent="烤机运行中… 1:1 真实秒计时，请烤满 60 秒";
  burnTimer=setInterval(()=>{
    const el=Math.round((Date.now()-burnStart)/1000);
    state.burnSimSec=el;
    document.querySelector("#burnTemp").textContent=(88+Math.round(Math.sin(el/3)*3))+" ℃";
    document.querySelector("#burnPower").textContent=(240+Math.round(Math.cos(el/4)*8))+" W";
    document.querySelector("#burnUsage").textContent="100 %";
    document.querySelector("#burnTime").textContent=Math.floor(el/60)+":"+String(el%60).padStart(2,"0");
  },1000);
  if(window.SimExam) SimExam.emit('step','burn.start',{at:Date.now()});
  toast("烤机已开始（真实秒计时）","ok");
}
function burnStopFn(){
  if(!burnTimer) return;
  clearInterval(burnTimer); burnTimer=null;
  const realSec=Math.round((Date.now()-burnStart)/1000);
  state.burnSimSec=realSec;                       // ← 原来是 realSec*30
  document.querySelector("#burnGo").disabled=false;
  document.querySelector("#burnStop").disabled=true;
  document.querySelector("#burnUsage").textContent="4 %";
  document.querySelector("#burnTemp").textContent="42 ℃";
  document.querySelector("#burnStatus").textContent="烤机已停止，实际烤机 "+state.burnSimSec+" 秒。"
    + (state.burnSimSec>=60 ? "可提交烤机报告。" : "不足 60 秒，提交后该项不计分。");
  if(window.SimExam) SimExam.emit('step','burn.stop',{durationSec:state.burnSimSec});
  toast("烤机已停止","ok");
}
function burnReport(){
  const sim=state.burnSimSec||0;
  const mode=document.querySelector("#burnMode").value;
  const m=mode.match(/Extreme/)?'Extreme':(mode.match(/Standard/)?"Standard":"Light");
  const th=document.querySelector("#burnThreads").value;
  const threads=th==="all"?"全部":(th==="half"?"一半":"单线程");
  // 必须真的烤满且已停止；否则提交也不给分（原来 stopped 只看 sim>0，等于白送）
  state.lastBurn={mode:m,threads,durationSec:sim,stopped:!burnTimer&&sim>=60};
  if(window.SimExam) SimExam.emit('step','burn.report',state.lastBurn);
  saveState(); refreshAll();
  toast(state.lastBurn.stopped ? "烤机报告已提交" : "已提交（未烤满 60 秒，该项不计分）",
        state.lastBurn.stopped ? "ok" : "err");
}
/* ---- CPU-Z ---- */
function openCpuZ(){
  createWin("cpuz","CPU-Z 2.10 (模拟)",640,500,`
   <div style="background:#f4f6f9;height:100%;font-size:12.5px;color:#222">
    <div style="background:#dde3ea;border-bottom:1px solid #b8c0cc;padding:5px 10px;display:flex;gap:2px;font-size:12px">
      ${["CPU","缓存","主板","内存","SPD","显卡","测试分数","关于"].map((t,i)=>`<span style="padding:4px 12px;${i===0?"background:#fff;border:1px solid #b8c0cc;border-bottom-color:#fff":"color:#555"}">${t}</span>`).join("")}</div>
    <div style="padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;line-height:2">
      <div><b>处理器名称:</b> AMD Ryzen 7 5800X (模拟)</div><div><b>核心代号:</b> Vermeer</div>
      <div><b>插槽:</b> AM4</div><div><b>工艺:</b> 7 nm</div>
      <div><b>核心/线程:</b> 8 / 16</div><div><b>频率:</b> 3800 - 4850 MHz</div>
      <div><b>倍频:</b> x38.0</div><div><b>总线速度:</b> 100 MHz</div>
      <div><b>L1 缓存:</b> 512 KB</div><div><b>L2 缓存:</b> 4 MB</div>
      <div><b>L3 缓存:</b> 32 MB</div><div><b>电压:</b> 1.18 V</div>
    </div>
    <div style="text-align:center;color:#888;font-size:11px;margin-top:10px">— 仅供教学模拟 —</div>
   </div>`);
}
/* ---- GPU-Z ---- */
function openGpuZ(){
  createWin("gpuz","GPU-Z 2.58 (模拟)",640,500,`
   <div style="background:#f4f6f9;height:100%;font-size:12.5px;color:#222">
    <div style="background:#dde3ea;border-bottom:1px solid #b8c0cc;padding:5px 10px;font-size:12px;display:flex;gap:2px">
      ${["显卡","传感器","高级"].map((t,i)=>`<span style="padding:4px 12px;${i===0?"background:#fff;border:1px solid #b8c0cc":"color:#555"}">${t}</span>`).join("")}</div>
    <div style="padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;line-height:2">
      <div><b>显卡名称:</b> NVIDIA RTX 4060 (模拟)</div><div><b>核心代号:</b> AD107</div>
      <div><b>工艺:</b> 5 nm</div><div><b>显存:</b> 8 GB GDDR6</div>
      <div><b>位宽:</b> 128 bit</div><div><b>核心频率:</b> 1830 - 2460 MHz</div>
      <div><b>显存频率:</b> 17 Gbps</div><div><b>流处理器:</b> 3072</div>
      <div><b>DirectX:</b> 12 Ultimate</div><div><b>PCIe:</b> 4.0 x8</div>
    </div>
    <div style="text-align:center;color:#888;font-size:11px;margin-top:10px">— 仅供教学模拟 —</div>
   </div>`);
}

/* ================= 启动 ================= */
/* ---- 考试流程接入：身份校验 + 埋点 + 交卷 ---- */
let SIM_PAPER = {};

function startExamMode(){
  const boot = window.SIM_BOOT || {};
  if(window.SimExam) SimExam.setWho((boot.student_name||"") + "　" + (boot.class_name||""));

  // 考试模式下屏蔽"重置考试环境"：否则学生做完不满意可以抹掉重来
  const hideReset = ()=>{
    document.querySelectorAll("#startmenu .smitem").forEach(it=>{
      if(it.dataset.a === "reset") it.style.display = "none";
    });
  };
  hideReset();
  const mo = new MutationObserver(hideReset);
  const sm = document.getElementById("startmenu");
  if(sm) mo.observe(sm, {childList:true, subtree:true});

  // 先走 U 盘引导动画，再进 PE 桌面
  runBootChain();
}

/* --- U 盘引导 → PE 加载 → 桌面就绪 --- */
function runBootChain(){
  const lines = [
    "Booting from USB HDD: SanDisk Cruzer Blade ...",
    "Loading WinPE image (boot.wim) ...",
    "Initializing hardware abstraction layer ...",
    "Starting Windows PE 10.0.19041 ..."
  ];
  const el = document.createElement("div");
  el.id = "peBoot";
  el.style.cssText = "position:fixed;inset:0;z-index:9600;background:#000;color:#cfd8e3;"
    + "font:14px/1.9 Consolas,monospace;padding:40px 48px;white-space:pre-wrap";
  document.body.appendChild(el);

  let i = 0;
  const t = setInterval(()=>{
    if(i < lines.length){ el.textContent += lines[i++] + "\n"; return; }
    clearInterval(t);
    el.textContent += "\n正在进入 PE 桌面 ...\n";
    if(window.SimExam) SimExam.emit('step','pe.loading_done',{});
    setTimeout(()=>{
      el.remove();
      state.peReady = true;
      if(window.SimExam) SimExam.emit('step','pe.desktop_ready',{});
      toast("WinPE 维护环境已就绪，双击桌面图标开始操作","ok");
    }, 1200);
  }, 620);

  // 引导设备选择：装机时最关键的一步，单独埋点
  if(window.SimExam) SimExam.emit('step','boot.pick_usb',{ device:'USB HDD: SanDisk Cruzer Blade' });
}

(function initWinpe(){
  loadState(); buildDesktop(); buildStartMenu();

  if(!window.SimExam) return;   // 离线双击：保持原练习流程

  fetch('/api/sim/paper?type=winpe')
    .then(r => r.ok ? r.json() : null)
    .then(d => { SIM_PAPER = (d && d.paper) ? d.paper : {}; })
    .catch(()=>{ SIM_PAPER = {}; })
    .then(()=>{
      SimExam.boot({
        simType: "winpe",
        onReady: function(S){ if(S.mode === "exam") startExamMode(); },
        onBlocked: function(){ setTimeout(function(){ location.href = "/portal"; }, 4000); }
      });
    });
})();
