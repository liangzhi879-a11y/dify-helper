// ==UserScript==
// @name         Dify Claude Floating Window
// @namespace    https://github.com/dify-helper
// @version      0.3.13
// @description  本机 Dify 调试专用版：与本地 bridge 配合，悬浮 Claude CLI
// @author       dify-helper
// @homepageURL  https://github.com/liangzhi879-a11y/dify-helper
// @updateURL    https://raw.githubusercontent.com/liangzhi879-a11y/dify-helper/main/tampermonkey/dify-claude-floating-window.user.js
// @downloadURL  https://raw.githubusercontent.com/liangzhi879-a11y/dify-helper/main/tampermonkey/dify-claude-floating-window.user.js
// @supportURL   https://github.com/liangzhi879-a11y/dify-helper/issues
// ★ 0.3.7 标题栏拆两行 + FAB 用 Claude Code 官方 banner：
//   1) 标题栏（第一行）只剩"标题 + 👤 + ✕"三项；其余 6 个徽章下移到第二行
//   2) 第二行 = .dcfw-statusbar，三 cell：权限(mode) / Agent(status+bridge) / URL(page)
//      整 cell 可点：mode→下拉 / Agent→重探测 / URL→复制+显示
//   3) FAB 像素画采用 Claude Code 官方 banner（claude CLI 启动时显示的机器人）：
//        行1（头）: " ▐▛███▜▌"
//        行2（身）: "▝▜█████▛▘"
//        行3（腿）: "  ▘▘ ▝▝"
//      —— 字符使用 ▐▛▜▌▝▘ 等 box-drawing 半角 block，原版就这样
//      —— 行1/2/3 宽度不同（8/9/7 chars）是 Claude Code 原版设计，不是 bug
//      —— CSS 加 font-variant-emoji:text 防 emoji 字体接管导致宽度漂移
// ★ 0.3.8 用户反馈修复：
//   1) tab(对话/会话/资源/快捷) 移除 ▎ 前缀 — 用户反馈"看起来像 icon，不是文字"
//   2) @match 宽化为 http://*/* — 用户在 LAN 部署 Dify 时 127.0.0.1 不够
//   3) BRIDGE_CANDIDATES 占位符 __REMOTE_BRIDGE_HOST__ — 公网 IP 不入仓
//      用户在 Tampermonkey 脚本值里 GM_setValue("__bridge_remote_host__", "<IP>")
//      即可启动时自动注入；未配置只走 loopback fallback
//   4) gmFetch.onerror 包 Error — 之前直接 reject(err)，上游 e.message||e 走到 e 分支
//      → String(err) === "[object Object]"，错误消息不可读
// ★ 0.3.11 自动从 window.location 推导 remote bridge host：
//   之前要求用户在 Tampermonkey 脚本值（Values 标签）里设 __bridge_remote_host__。
//   油猴面板只有"编辑器/设置"两个标签，Values 是用户值（脚本 set/get 用），
//   多数用户找不到。现在改为自动从当前页面 URL 推导：用户在
//   http://<公网 IP>:9980/ 访问时，自动派生 http://<公网 IP>:8002。
//   本机/loopback 访问仍只探测 loopback fallback，公网 IP 不入仓。
//   GM_getValue("__bridge_remote_host__") 仍作为用户硬覆盖保留。
// ★ 0.3.12 发送按钮复用为停止按钮（打断 agent）：
//   - agent 运行时（state.isSending=true）：按钮变红色 + ⏹ 矩形图标 + 呼吸动画，
//     title="停止 agent（中断当前流）"，点一下 / 按 Enter 即中断
//   - idle 时：保持原 ➤ + Claude 橙，可正常发消息
//   - 中断行为：abort SSE/poll → finalize thinking → 清 rAF 队列 → setSending(false)
//   - 与 0.2.16 注释不同：stop 场景显式清 sseRequest，因为用户主动打断 → listener
//     重建由下一次 sendMessage 触发，比 idle-but-ready 状态更准确
//   - 同样的逻辑也在 keydown Enter 触发（流式中按 Enter = 打断）
// ★ 0.3.10 initSession 错误消息带上 BRIDGE 探测结果 + 远程配置提示：
//   之前只显示最后一次 initSession catch 的 e.message，远程用户看不到 BRIDGE_CANDIDATES
//   探测状态（每个 URL 是 ok/fail/pending、错误原因），只能盲猜。现在把探测结果列表
//   + "配 GM __bridge_remote_host__ + 路由器 8002 转发" 提示一并塞进错误消息。
// ★ 0.3.6 FAB 机器人像素画重设计 + 跳动动画修复（用户报 0.3.5 翻车）：
//   1) 像素画：原 "▐▛███▜▌\n▝▜█████▛▘\n  ▘▘ ▝▝" 改用纯半角 block
//     "▄▀▀▀▀▄\n█▀  ▀█\n▀▀▀▀▀▀" —— 3 行各 6 字符，全用 ▄▀█
//     (跨 monospace 字体稳定半角)，消除腿视觉偏右问题
//   2) 跳动动画：translateY(-4px) 1.2s 循环（之前 translateX(-0.5px) 加上
//     translateY 混用，逻辑混乱）；现在仅 translateY，纯垂直跳动
//   3) 关键修复：togglePanel 不再切 fab.innerHTML = "✕" —— 面板打开时
//     FAB 保持机器人形态（跳动），关闭按钮已在 titlebar 右上角，不需 ❌
// ★ 0.3.5 面板 titlebar 单行化 + FAB 机器人居中修复 + 跳动动画：
//   1) titlebar: 加 flex-wrap: nowrap + 标题 flex:1 + min-width:0 (ellipsis)，
//      右侧 6 个徽章 flex:0 0 auto，强制单行避免两行换行
//   2) FAB 像素画: 改 text-align:left + display:inline-block + translateX(-0.5px)
//      微调，让腿"▘▘ ▝▝"视觉上跟头"▐▛███▜▌"对齐（之前用 text-align:center
//      但 unicode box-drawing 字符在不同 monospace 字体里半角/全角混排导致腿偏右）
//   3) FAB 跳动动画: hostEl 加 .dcfw-panel-open class → @keyframes dcfw-robot-jump
//      1.2s 上下 3px 循环；面板关闭时移除 class → 回到静态
// ★ 0.3.4 加 GitHub auto-update URL：
//   @homepageURL  → https://github.com/liangzhi879-a11y/dify-helper
//   @updateURL    → https://raw.githubusercontent.com/.../main/...user.js
//   @downloadURL  → 同上
//   @supportURL   → .../issues
//   Tampermonkey 默认每天检查一次 @version，bump 后用户自动收到更新提示。
//   零额外发布步骤：git push main → 用户 24h 内弹更新。
//   验证：浏览器安装本脚本后，看 Tampermonkey 面板 "Updates" 标签
//         应能看到 "Last checked: ..." + "Latest version: 0.3.4"
// ★ 0.3.2 修复 Firefox 上展开按钮闪退：
//   用户报"火狐浏览器闪退，展开按钮显示一下就闪退"，但看不到 console 报错。
//   修复：
//   1) window 全局 error + unhandledrejection 监听，把异常记录到 FAB title + 屏幕
//      顶部 overlay（点 overlay 关闭），用户不开 F12 也能看到根因
//   2) togglePanel 全函数 try/catch — 防御 shadow DOM adoption / getElementById
//      返回 null 时 throw 把整个 FAB click handler 吞掉
//   3) 防御性 panel/fab 元素存在检查，缺失时显示明确错误而不是 silently fail
// ★ 0.3.1 修复 v0.3.0 启动 race condition 导致 badge 永远 👤?：
// ★ 0.3.0 多用户隔离（对应 bridge v0.3.0）：
//   升级为内部团队多用户共存，单一指纹 = (ip+UA+lang) HMAC-SHA256 → uuid5。
//   三大改造：
//     1) bootstrap /auth/whoami — 启动时拿 fingerprint + user_id + display_name
//        + collisions（撞库候选），写 state。撞库 > 0 自动弹 👤 选择器。
//     2) GM key 命名空间化 — 所有 session/MRU/draft 改 dcfw_<fp>_* 形式。
//        旧 key (dify_claude_session_id / dify_claude_session_mru / dcfw_draft_*)
//        由 migrateLegacyKeys() 一次性迁到新 key + 删旧。
//     3) gmFetch/gmFetchJSON 加 X-Bridge-Fingerprint + X-Bridge-Display-Name header。
//        bridge 端以服务端重算 user_id 为准（防伪造），client 仅作二次细分。
//   兼容性：未带 header 的老油猴实例仍走 LEGACY 兜底 user_id，行为不变。
//   显示：标题栏新增 👤 badge，点击弹 display_name popover（列 candidates + 新建）。
// ★ 0.2.22 SSE 切换为 HTTP 轮询（修复 remote 端事件丢失）：
//   之前用 GM_xmlhttpRequest 订阅 /sessions/{id}/events （SSE 流）。在 remote
//   场景（REDACTED_HOST:8002 经过路由器端口转发）下，SSE chunk 在中途被
//   路由器/防火墙 buffer、合并、或截断，导致 onprogress 只触发一两次、
//   整段响应堆到最后才到 ——"Dify Claude助手" 面板里看不到实时思考和文字气泡。
//   Bridge 后端**已经内置了 polling 备选**（GET /sessions/{id}/events/poll
//   ?since=N&max_wait=1.0），注释明写"替代 SSE 给 Tampermonkey 等 SSE
//   不稳的客户端用"。本版改用 polling：
//     1) connectPolling 替代 connectSSE，复用 state.sseRequest abort 兼容
//     2) state.sseLastEventId 跟踪服务端单调 event_id，每次 poll 用 since
//     3) 事件处理仍走 handleSSEEvent —— UI / 渲染 / 队列逻辑零改动
//     4) 50ms 间隔短轮询：事件密集时接近 SSE 体验，最大延迟 <100ms
//     5) SSE 函数保留作 fallback（代码还在，万一 polling 也不行还有退路）
// ★ 0.2.21 修复输入框（textarea）字色继承丢失：
//   <textarea> 是 form 元素，UA 样式表显式设了 `color`，部分浏览器 + 暗色页面
//   （用 color-scheme: dark）的组合下，:host 继承的 #1F1E1B 会被拦截，输入框
//   仍按页面暗黑主题显示白字。
//   修复：在 #dcfw-chat-input 直接写 color: #1F1E1B，覆盖 UA + 任何继承源。
//   （caret-color 0.2.19 已加，同步保留）
// ★ 0.2.20 修复 0.2.19 的回归：
//   0.2.19 把 color 写在 `:host, * { color: ... }`。* 是直接规则（特异性 0,0,0,0），
//   会**破坏继承**：所有未显式声明 color 的子元素（包括「Dify Claude 助手」/ 状态
//   图标 / 调试面板内的子项）被强制改成黑字，导致橙底白字设计意图失效（白→黑），
//   调试面板深灰底更是完全看不见。
//   修正：color 只写在 `:host`，descendants 通过继承拿默认（#1F1E1B），而子元素
//   自己的显式 color（`.dcfw-titlebar { color: #fff }` 等）仍按 class 特异性胜出。
//   font-family 仍保留在 `:host, *`（无害，inherit 兼容）。

// ★ 0.2.19 修复目标网站暗色主题导致悬浮窗文字不可见：
//   根因：Shadow DOM v1 中 `color` 是继承属性，从 host 元素继承到 shadow tree。
//   目标网站若设了 `color: white`（暗色模式），本面板所有未显式声明 color 的元素
//   （tab / popover / input / cmd-palette / resource-item / session-info 等）会
//   全继承白字，米色/白底上看不见。
//   修复：
//     1) :host 加 color: #1F1E1B（Claude 主题深棕）作通用默认（0.2.20 修正见上）
//     2) #dcfw-chat-input 加 caret-color: #1F1E1B（暗色主题下系统插入符也变白，
//        米色背景上看不见）
// ★ 0.2.18 用户反馈后的二次修复（0.2.16 之后两个残留 bug）：
//   1) thinking 累积后仍不会折叠 — 之前只在 appendThinking 首次创建时按初始 len
//      决定 open，delta 累积 >200 字符后从不动态关闭；改为 else 分支每收到 delta
//      都检查 _textLength > 200 → 立即 open=false。finalizeThinkingBlock 也改为
//      open = (n <= 200) 强制收敛终态，不再"无条件短才展开"
//   2) 长不可断字符串（URL / 长 hash / 大段 dump）撑爆气泡宽度 → 出现横向滚动条
//      即使后续 bubble 收回宽度也不会消失。原因：.dcfw-msg 缺 min-width:0 + overflow-wrap:anywhere，
//      #dcfw-chat-messages 缺 overflow-x:hidden。补齐后长字符串在任何字符边界强制断行
//      (覆盖 word-wrap 在 unbreakable content 上的盲点)，水平滚动条消失
// ★ 0.2.17 FAB 悬浮按钮改 ClaudeCode 小机器人像素画（3 行 unicode）：
//   ▐▛███▜▌  /  ▝▜█████▛▘  /    ▘▘ ▝▝
// ★ 0.2.16 综合性修复（6 个 bug 一次过）：
//   1) setMode 信任 resp.mode 写 state.currentMode — bridge 不返回时徽章变 "undefined"
//      并丢 CSS class；改为只在 MODE_LABELS 命中时写入，且无条件 syncModeFromStatus() 兜底
//   2) thinking 太长无折叠 — 改 <details>/<summary>，>200 字默认折叠，
//      流结束后 summary 显示 "💭 思考 (N 字)"
//   3) 输出顺序错乱 — 两个独立 buffer (pendingText/ThinkingDelta) 改单一有序队列
//      state.pendingDeltaQueue，flushDeltas 严格按到达顺序
//   4) SSE 永远显示"未连接" — state.sseRequest 在 result/error 被清空导致 idle but ready
//      状态被判为未连接；改为只清 abort/关流场景，UI 拆 "● 已挂载 / ▍ 流式中" 两态
//   5) Dify Helper 当前页面无法传到 agent — state.activePageContext +
//      capturePageContext() 抓 URL/title/app_id，bridge SendMessageRequest 新增可选
//      page_context，前置为 [Page context ...] text block
//   6) 路由切换 / 切 tab 不更新上下文 — setupRouteWatcher 加 visibilitychange +
//      popstate/hashchange/pushState 各自收尾 capturePageContext()，
//      标题栏新增 dcfw-page-badge 显示当前页标题（截 30 字）
// ★ 0.2.14 深度修复 0.2.13 仍未根除的"点击闪退 + 无法再呼出"：
//   1) 删除 setupClickOutsideClose——document 级 mousedown 在 Dify + 扩展丰富的环境
//      下不可靠（retarget 失败 / 扩展劫持 / ShadowRoot polyfill）
//   2) 修 setupDrag 坐标语义：panel.position:absolute 在 fixed host 内，
//      panel.style.left 实际是 host-relative，不是 viewport。否则 host 一动 panel 错位
//   3) FAB click didMove 状态机从双 listener 合并为单一 listener，边缘 didMove 卡 true
//      不会卡死 toggle
//   4) injectUI 入口清理 _popoverDocClickHandler 旧引用，避免 SPA 路由切换累积
//   5) titlebar 加 ✕ 显式关闭按钮（替代被删的"点击外部关闭"行为）
//   6) resetPanelPosition 显式清理 panel.style.left/top 内联（老版本可能残留错误坐标）
// ★ 0.2.13 修复拖拽标题栏时面板闪退：
//   setupClickOutsideClose 用 composedPath 判定 insideUi 在某些场景会失败
//   （composedPath 依赖浏览器实现 + shadow DOM 事件 retarget + 外部扩展干扰）。
//   改用 hostEl.contains(e.target)：Shadow DOM v1 retarget 后 e.target === hostEl，
//   内部点击 hostEl.contains(hostEl) === true，外部点击 e.target 是其他元素
//   hostEl.contains(...) === false。语义更稳，不依赖 composedPath 数组。
// ★ 0.2.12 UI 调整：
//   1) 整体字体缩小（基线 14 → 13，msg 14 → 13/12，tabs/cmd/resource 13 → 12）
//   2) agent 回复气泡（.dcfw-msg-claude）字体 14 → 12，padding 收紧
//   3) 状态文字 → 图标：titlebar #dcfw-status 文字标签改 unicode 图标
//      （未连接 ○ / 已连接 ● / 思考中 💭 / 回复中 ▍ / 调用工具 🔧 / 完成 ✓ ...）
//      bridge 徽章隐藏 URL 文本，只保留 10px 彩色圆点（hover title 看详细）
//   4) 修输入框溢出 panel：#dcfw-chat-input 加 box-sizing:border-box + flex:1
//      发送按钮改 flex 布局（align-self:center），跟随 textarea 高度中点对齐
// ★ 0.2.11 修复 0.2.10 仍然 panel 闪退：
//   0.2.10 的"虚拟 host 边界"(440×748) 数学错了——
//   panel 实际占据 hostLeft-440 .. hostLeft × hostTop-692 .. hostTop-72，
//   但 clamp 用了 y ∈ [-(h-minVis), vh-minVis] = [-732, vh-16]，
//   允许 hostTop 最小为 -732，panel 实际飞到 y = -732 - 72 - 620 = -1424。
//   改用 host 位置直接 clamp：
//     hostLeft ∈ [440, vw-16]   (panel.left ≥ 0 + fab 右边留 16)
//     hostTop  ∈ [692, vh-16]   (panel.top  = hostTop-692 ≥ 0 + fab 底留 16)
// ★ 0.2.10 系统性修复 panel 跟随 host 离屏：
//   根因：#dcfw-panel 用 position:absolute; right:0; bottom:72px 锚定到 host（不是 viewport），
//   拖 FAB/host 时 panel 跟着 host 走，0.2.9 的 clampToViewport 用 fab 尺寸（56×56）只保护了
//   FAB 自身，panel（440×620 挂在 host 顶部）完全不受保护，能被拖出视口。
//   修复：
//   1) setupFabDrag 用"虚拟 host 边界" clamp（440×748 = panel + 偏移 + fab）
//   2) resetPanelPosition 同步重置 host 到默认 right:24px / bottom:24px
//   3) resize 监听器也 clamp host
//   4) toggleModePopover 用模块级 _popoverDocClickHandler 引用，setTimeout 内闭包改为
//      单一可移除的 handler，防止反复开/关导致 document mousedown 监听器泄漏
//   5) isPanelFullyOffscreen 同时检查 FAB getBoundingClientRect（FAB 是 host 内唯一可见子元素）
// ★ 0.2.9 拖拽视口限制 + 离屏恢复：
//   1) setupDrag / setupFabDrag 接入 clampToViewport（面板保留 40px 可见边、FAB 保留 16px）
//   2) togglePanel 加 isPanelFullyOffscreen 检测：完全离屏时自动重置到右下角默认位置
//   3) window resize 监听器：缩窗后重新 clamp，防止部分出屏
// ★ 0.2.8 标题栏重构 + 拖拽崩溃修复：
//   1) mode select 改为徽章内嵌下拉（点 badge 弹 popover），标题栏节省 ~170px
//   2) setupDrag pointerdown 加 closest() 过滤，排除 select/button/badge 等交互元素，
//      解决 0.2.7 点 select 触发 setPointerCapture 抑制原生下拉 + 改写 panel 位置的"闪退" bug
// ★ 0.2.7 Claude 模式支持：标题栏下拉切换 plan/bypass/default/acceptEdits，
//   调桥接 POST /sessions/{id}/mode（子进程重启，保留 session_id + 历史）。
//   徽章颜色区分：橙=auto / 蓝紫=plan / 绿=acceptEdits / 灰=default。
// ★ 0.2.6 三项体验优化：
//   1) 流式输出实时：SSE buffer 接住不完整事件 + rAF 合并 + textNode O(1) 拼接
//   2) 拖拽改用 Pointer Events + setPointerCapture，避免 mouseup 丢失导致错位
//   3) Claude 主题：#CC785C 橙 + #FAF9F5 米色，助手消息 serif + 左侧引用线
// ★ 0.2.5 同步 console 捕获调试功能（默认开，可手动关）：Dify 页面下捕获
//   console.error/warn/log/info/debug，存 200 条 ring buffer，调试面板展示
//   最近 20 条 + toggle/clear 按钮，复制诊断时附带。
// ★ 0.2.4 修复 bridge 探测卡在 PENDING：GM_xmlhttpRequest timeout 不可靠时用
//   Promise.race 强制 3s 硬超时；catch + 状态更新都包 try-catch，确保状态一定更新。
//   把注释里的 at-match / at-grant 字面量改为 match / grant，避开 no-invalid-metadata；
//   把 renderQuickActions 里的 shadowRoot 提到局部变量，避开 no-loop-func。
// @match        http://127.0.0.1/*
// @match        http://localhost/*
// @match        http://*/*
// @connect      127.0.0.1
// @connect      localhost
// @connect      *
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // ============================================================
  // 主机白名单：拒绝在公网域名激活（feathersound.cn 等无关页面）
  //   @match http://*/* 会让脚本在所有 http 页面注入，必须运行时再过滤一次
  //   允许：localhost / 127.0.0.1 / .local / RFC1918 / 公网 IP / 单标签 hostname
  //   拒绝：常见公网 TLD（com/cn/net/org/io/...）
  // ============================================================
  var _PUBLIC_TLDS = {
    com: 1, net: 1, org: 1, info: 1, biz: 1, xyz: 1, top: 1, vip: 1,
    club: 1, site: 1, tech: 1, app: 1, dev: 1, wiki: 1, store: 1, shop: 1,
    pro: 1, mobi: 1, name: 1, cc: 1, tv: 1, co: 1, io: 1, me: 1, ai: 1,
    cn: 1, "com.cn": 1, "net.cn": 1, "org.cn": 1, "edu.cn": 1, "gov.cn": 1,
    hk: 1, tw: 1, jp: 1, kr: 1, uk: 1, de: 1, fr: 1, ru: 1,
  };
  function _isPrivateHost(rawHost) {
    if (!rawHost) return false;
    var host = String(rawHost).toLowerCase();
    // 剥 IPv6 brackets + IPv4 端口（[::1]:9980 / <公网 IP>:9980）
    if (host.charAt(0) === "[") {
      var rb = host.indexOf("]");
      if (rb >= 0) host = host.slice(1, rb);
    } else if (/^[\d.]+:\d+$/.test(host)) {
      host = host.split(":")[0];
    }
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") return true;
    if (host.endsWith(".local") || host.endsWith(".lan") || host.endsWith(".internal")) return true;
    // IPv4（任意 IP 段都算：用户用公网 IP 远程访问 Dify 是合法用例）
    var m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (m && (+m[1] <= 255) && (+m[2] <= 255) && (+m[3] <= 255) && (+m[4] <= 255)) return true;
    // 单标签 host（myserver / dify 等 mDNS / 内网名）
    if (host.indexOf(".") < 0) return true;
    // 多标签：TLD 不在白名单 → 公网域名 → 拒绝
    var tld = host.split(".").pop();
    return !_PUBLIC_TLDS[tld];
  }
  if (!_isPrivateHost(location.hostname)) {
    // 公网域名（feathersound.cn 等），不是 Dify。静默退出 ——
    // 不注 FAB、不挂 unhandledrejection、不污染页面。
    return;
  }

  // ============================================================
  // 内部错误 sentinel：全局 error/unhandledrejection 只归因 plugin 自身，
  //   页面原生 JS 报错（feathersound.cn theme.js 的 null.dataset）忽略
  // ============================================================
  var _DCFW_SENTINEL = "__dcfw_internal_error__";
  function _markDcfwError(err) {
    if (err && typeof err === "object") {
      try { err[_DCFW_SENTINEL] = true; } catch (_) {}
    }
    return err;
  }

  // ============================================================
  // 远程访问版配置
  // ============================================================
  // 服务器：192.168.x.x（局域网）/ REDACTED_HOST（公网，需路由器转发）
  // Dify 实际监听 nginx 80 端口；外部 9980 是路由器转发后的端口
  // Bridge 监听 8002（避开 8000 vllm / 8001 bge-m3）
  //
  // 你需要在 OpenWrt 路由器（http://192.168.3.1）配置 2 条端口转发：
  //   外部 9980 → 192.168.x.x:80      （Dify Web）
  //   外部 8002 → 192.168.x.x:8002    （Bridge API）
  //
  // 【模型锁定】强制使用 MiniMax-M3（与本仓库开发者当前使用的一致）
  //   - 不要擅自切换模型；未授权的模型无法正常使用
  //   - 该锁定通过环境变量 ANTHROPIC_MODEL 在 bridge 端生效（见 config.yaml）
  // ============================================================

  // 候选 BRIDGE_URL 列表（按优先级探测）
  // 远程访问场景下首选公网地址，本地/同网段访问也能 fallback
  // ★ 0.3.11: 自动从 window.location 推导 remote bridge host
  //   - 用户在 http://<公网 IP>:9980/ 访问 Dify 时，自动派生出 http://<公网 IP>:8002
  //   - 公网 IP 仍不入仓（避免脱敏负担），用户在 Dify 页面访问就自动生效
  //   - 本机访问（127.0.0.1/localhost/192.168.x.x）仍走 loopback fallback
  // ★ 0.3.8: 用户也可在 Tampermonkey 脚本值里设
  //   GM_setValue("__bridge_remote_host__", "<公网 IP>") 覆盖推导值。
  const BRIDGE_CANDIDATES = [
    "http://__REMOTE_BRIDGE_HOST__:8002",   // 远程（自动从 window.location 推导，未推导出则跳过）
    "http://127.0.0.1:8002",        // 本机 loopback
    "http://localhost:8002",        // 本机 loopback 备选
  ];
  // ★ 0.3.11: 优先 GM 值；否则从 window.location 自动推导；都无则降级跳过占位符
  (function injectRemoteBridgeHost() {
    try {
      // 1) 用户硬覆盖（最高优先级）
      let h = GM_getValue("__bridge_remote_host__", "");
      if (!h || !h.trim()) {
        // 2) 自动从当前页面 URL 推导（同 host，端口 9980 → 8002）
        try {
          const pageUrl = new URL(window.location.href);
          const host = pageUrl.hostname;
          // 只在 "非 loopback / 非纯 LAN" 时才算 remote
          const isPrivate = host === "127.0.0.1" || host === "localhost"
            || host.startsWith("192.168.")
            || host.startsWith("10.")
            || /^172\.(1[6-9]|2\d|3[01])\./.test(host);
          if (!isPrivate && host) {
            h = host;
          }
        } catch (_) {}
      }
      if (h && h.trim()) {
        BRIDGE_CANDIDATES[0] = "http://" + h.trim() + ":8002";
      } else {
        // 3) 都无 → 降级跳过占位符（避免探测 __REMOTE_BRIDGE_HOST__）
        BRIDGE_CANDIDATES.shift();
      }
    } catch (_) {
      BRIDGE_CANDIDATES.shift();
    }
  })();

  const CONFIG = {
    BRIDGE_URL: BRIDGE_CANDIDATES[0],     // 启动先用远程地址
    DIFY_URL: window.location.origin,      // 跟当前页面（自动适配 9980 等）
    BRIDGE_CANDIDATES,                    // 暴露给自动探测
    // ★ 0.3.0: 旧 key 直接保留作 fallback（migrateLegacyKeys 后会被删）
    SESSION_ID_KEY: "dify_claude_session_id",
    SESSION_MRU_KEY: "dify_claude_session_mru",
    SESSION_DRAFT_KEY_PREFIX: "dcfw_draft_",
    // ★ 0.3.0: 多用户隔离 — fingerprint 缓存 + display_name 持久
    FINGERPRINT_KEY: "dcfw_fingerprint",       // 缓存服务端 /auth/whoami 返回的 fingerprint
    DISPLAY_NAME_KEY: "dcfw_display_name",     // 用户自命名（持久，重启后仍用）
    MIGRATION_DONE_KEY: "dcfw_migration_v030_done",  // 一次性迁移标记
    // ★ 0.2.15: MRU 持久化 + 每会话 draft 暂存
    SESSION_MRU_CAP: 10,
    SSE_TIMEOUT_MS: 600000,               // 10 分钟
    HEARTBEAT_IGNORE: true,
    IS_REMOTE_EDITION: true,
  };

  // ==================== ★ 0.3.0: 多用户隔离 helper ====================
  // 所有 GM key 通过 getStoragePrefix() 动态计算 → "dcfw_<fp>_" 形式。
  // 未拿到 fingerprint 时退化 "__legacy__"（bridge 会再走 LEGACY 兜底）。

  function getStoragePrefix() {
    const fp = state.fingerprint || "__legacy__";
    return "dcfw_" + fp + "_";
  }
  function getSessionIdKey()      { return getStoragePrefix() + "session_id"; }
  function getSessionMRUKey()     { return getStoragePrefix() + "session_mru"; }
  function getDraftKey(sid)       { return getStoragePrefix() + "draft_" + sid; }

  // 旧 key 一次性迁移到新 prefix key
  function migrateLegacyKeys() {
    if (GM_getValue(CONFIG.MIGRATION_DONE_KEY, false)) return;
    const prefix = getStoragePrefix();
    // 1) 单值 key
    const singles = [
      [CONFIG.SESSION_ID_KEY, "session_id"],
      [CONFIG.SESSION_MRU_KEY, "session_mru"],
    ];
    for (const [oldK, newSuffix] of singles) {
      const newK = prefix + newSuffix;
      const oldV = GM_getValue(oldK, null);
      if (oldV !== null && GM_getValue(newK, null) === null) {
        GM_setValue(newK, oldV);
      }
      if (oldV !== null) GM_deleteValue(oldK);
    }
    // 2) draft_<sid> 前缀
    const draftOldPrefix = CONFIG.SESSION_DRAFT_KEY_PREFIX;  // "dcfw_draft_"
    for (const k of GM_listValues()) {
      if (k.startsWith(draftOldPrefix)) {
        const sid = k.slice(draftOldPrefix.length);
        const newK = getDraftKey(sid);
        const v = GM_getValue(k);
        if (GM_getValue(newK, null) === null) GM_setValue(newK, v);
        GM_deleteValue(k);
      }
    }
    GM_setValue(CONFIG.MIGRATION_DONE_KEY, true);
    console.log("[bridge] v0.3.0 legacy GM keys migrated to prefix:", prefix);
  }

  // 调 /auth/whoami 拿 fingerprint + user_id + display_name + collisions
  async function bootstrap() {
    try {
      // 等 bridge 探测完成（state.bridgeProbes 有 ok 项）
      const ok = (state.bridgeProbes || []).find((p) => p.status === "ok");
      if (!ok) {
        // 探测未完成 / 全部失败：用默认第一个候选 + 兜底路径
        // 这样即使 bridge 挂了，UI 仍能渲染、用户能切 BRIDGE_URL 重试
        state.fingerprint = GM_getValue(CONFIG.FINGERPRINT_KEY, null) || null;
        state.displayName = GM_getValue(CONFIG.DISPLAY_NAME_KEY, null) || null;
        state.isLegacy = !state.fingerprint && !state.displayName;
        return;
      }
      CONFIG.BRIDGE_URL = ok.url;
      const who = await gmFetchJSON("GET", ok.url + "/auth/whoami");
      state.userId = who.user_id || null;
      state.fingerprint = who.fingerprint || null;
      state.displayName = who.display_name || null;
      state.isLegacy = !!who.is_legacy;
      // 缓存 fingerprint（client 不信任，但下次启动可立即用 → 省一次 whoami 之前的 storage lookup）
      if (state.fingerprint) GM_setValue(CONFIG.FINGERPRINT_KEY, state.fingerprint);
      if (state.displayName)  GM_setValue(CONFIG.DISPLAY_NAME_KEY, state.displayName);
      console.log(`[bridge] v0.3.0 bootstrap: user=${state.userId?.slice(0,8)}... fp=${state.fingerprint} legacy=${state.isLegacy} collisions=${who.collisions}`);
      // 撞库自动弹选择器
      if ((who.collisions || 0) > 0) {
        showDisplayNamePicker(who.candidates || [], who.display_name);
      }
    } catch (e) {
      console.warn("[bridge] bootstrap 失败（降级 legacy）", e);
      state.fingerprint = GM_getValue(CONFIG.FINGERPRINT_KEY, null) || null;
      state.displayName = GM_getValue(CONFIG.DISPLAY_NAME_KEY, null) || null;
      state.isLegacy = !state.fingerprint && !state.displayName;
    }
  }

  // ==================== 状态 ====================
  // 【重要】以下变量必须按顺序在 detectBridge()/start() 调用之前声明，否则
  //   函数体里访问它们会抛 ReferenceError（let/const 不 hoist，TDZ）。
  //   旧版本把 state 放在文件后面，导致新版 badge/复制诊断完全失效（v0.2.15 修过）。
  //   v0.2.18 再补 shadowRoot/hostEl 与 _DIFY_PATH_PREFIXES 两个遗漏项：
  //     - detectBridge() 同步调用 updateBridgeBadge/renderProbeResults → 需要 shadowRoot/hostEl
  //     - start() 调用 _isDifyPage() → 需要 _DIFY_PATH_PREFIXES
  const state = {
    // ★ 0.3.0: 多用户隔离 — 由 bootstrap() 注入
    userId: null,         // 服务端计算的 (ip+UA+lang) → uuid5
    fingerprint: null,    // 短哈希（client 缓存用，服务端权威）
    displayName: null,    // 👤 用户自命名（撞库细分）
    isLegacy: true,       // 无 fingerprint + 无 display_name → 走 LEGACY
    sessionId: null,
    sseRequest: null,
    sseLastIndex: 0,
    // ★ 0.2.6: SSE 不完整事件缓冲（处理 onprogress 切到一半的情况）
    sseBuffer: "",
    // ★ 0.2.6: rAF 合并渲染缓冲（避免每个 delta 都触发 reflow）
    pendingFlush: null,
    // ★ 0.2.16: 单有序 delta 队列，保留到达顺序（之前两个独立 buffer 丢顺序）
    pendingDeltaQueue: [],     // [{type: 'text'|'thinking', text: string}]
    // ★ 0.2.22: polling 状态（替代 SSE）
    sseLastEventId: 0,         // 服务端单调 event_id，本地游标，since= 此值
    pollingActive: false,      // polling 循环是否在跑
    isSending: false,
    currentAssistantBubble: null,
    panelOpen: false,
    activeTab: "chat",
    resourceLoaded: false,
    // ★ 0.2.7: Claude 当前模式（与桥接端 /sessions/{id}/status.mode 同步）
    currentMode: "bypass",
    // ★ 0.2.15: 会话管理
    sessionList: [],          // bridge 返回的实时列表 [{id, status, mode, name, first_message_preview, message_count, last_active_at}]
    sessionMRU: [],           // 最近使用过的会话 [{id, name, preview, last_active_at}]，持久化到 GM
    activeSessionDraft: "",   // 占位（实际从 GM per-session key 读）
    // ★ 0.2.16: 当前页面上下文（URL + title + app_id），自动捕获并随 sendMessage 发给 agent
    activePageContext: null,  // {url, title, app_id|null, capturedAt}
    // 【诊断】bridge 探测结果：[{url, status:'pending'|'ok'|'fail', latencyMs, error}]
    bridgeProbes: [],
    // ★ 0.2.5: console 捕获（Dify 页面下默认开，可手动关）
    consoleCapture: {
      enabled: true,
      buffer: [],          // [{t: ms, level: 'log'|'warn'|..., args: [...]}]
      maxSize: 200,
      originals: null,     // {log, warn, error, info, debug} 安装后的原始函数表
      filteredPrefixes: ["[bridge]", "[Dify Bridge]", "[Dify Claude"],
    },
  };

  // ★ 0.2.18 修复 TDZ：以下两个变量原声明在文件 626 行附近，但 detectBridge()
  //   在 ~313 行同步调用 updateBridgeBadge()/renderProbeResults()，访问 shadowRoot 时
  //   仍在 TDZ（let 不 hoist）→ ReferenceError。统一上移到 state 之后、detectBridge 之前。
  let shadowRoot = null;
  let hostEl = null;

  // ★ 0.2.18 修复 TDZ：原声明在文件 3390 行，但 start() 在 ~3377 行调用 _isDifyPage()，
  //   _isDifyPage 访问 _DIFY_PATH_PREFIXES 时仍在 TDZ → ReferenceError。
  const _DIFY_PATH_PREFIXES = [
    "/apps", "/datasets", "/chat", "/tools", "/workflow",
    "/explore", "/install", "/signin", "/signup", "/forgot-password",
    "/finish", "/education",
  ];

  // 异步探测哪个 BRIDGE_URL 可达
  async function detectBridge() {
    // 初始化所有候选为 pending，触发徽章更新
    state.bridgeProbes = BRIDGE_CANDIDATES.map((url) => ({
      url,
      status: "pending",
      latencyMs: 0,
      error: null,
    }));
    try { updateBridgeBadge(); } catch (e) { console.warn("[bridge] updateBridgeBadge 失败", e); }
    try { renderProbeResults(); } catch (e) { console.warn("[bridge] renderProbeResults 失败", e); }

    for (let i = 0; i < BRIDGE_CANDIDATES.length; i++) {
      const url = BRIDGE_CANDIDATES[i];
      const start = Date.now();
      let resultStatus = "fail";
      let resultError = null;
      let resultLatency = 0;
      try {
        // Promise.race 强制 3s 超时，即使 GM_xmlhttpRequest 的 ontimeout 不可靠
        const r = await Promise.race([
          new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
              method: "GET",
              url: url + "/health",
              timeout: 2500,
              onload: (resp) => resolve({ ok: true, resp }),
              onerror: (e) => reject(new Error("network error")),
              ontimeout: () => reject(new Error("gm timeout (2.5s)")),
            });
          }),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error("hard timeout (3s)")), 3000)
          ),
        ]);
        resultLatency = Date.now() - start;
        if (r && r.ok && r.resp && r.resp.status === 200) {
          resultStatus = "ok";
          console.log(`[bridge] ✅ ${url} 200 OK (${resultLatency}ms)`);
        } else if (r && r.ok && r.resp) {
          resultStatus = "fail";
          resultError = `HTTP ${r.resp.status}`;
          console.log(`[bridge] ❌ ${url} HTTP ${r.resp.status}`);
        }
      } catch (e) {
        resultLatency = Date.now() - start;
        resultStatus = "fail";
        resultError = (e && e.message) || String(e);
        console.log(`[bridge] ❌ ${url} ${resultError}`);
      }
      // ★ 不管成功/失败，状态一定更新（确保不会永远 pending）
      try {
        state.bridgeProbes[i] = {
          url,
          status: resultStatus,
          latencyMs: resultLatency,
          error: resultError,
        };
      } catch (e) {
        console.error("[bridge] state 更新失败", e);
      }
      // 第一个成功就选用 + 早返回
      if (resultStatus === "ok") {
        try {
          CONFIG.BRIDGE_URL = url;
          updateBridgeBadge();
          renderProbeResults();
          updateDebugInfo();
        } catch (e) {
          console.warn("[bridge] UI 刷新失败", e);
        }
        return url;
      }
      // 每个失败后也刷新 UI（让用户看到进度，避免永远"探测中"）
      try {
        updateBridgeBadge();
        renderProbeResults();
      } catch (e) {
        console.warn("[bridge] UI 刷新失败", e);
      }
    }

    console.warn(
      "[Dify Bridge] ❌ 所有候选地址都不可达，悬浮窗功能将不可用。\n" +
        "候选：" + BRIDGE_CANDIDATES.join(", ") + "\n" +
        "请检查：(1) 服务器 Bridge 是否运行 (2) 路由器端口转发 8002 是否配好\n" +
        "【诊断】展开调试面板查看每个地址的失败原因，或点击徽章复制诊断信息发给同事"
    );
    try { updateBridgeBadge(); } catch (e) {}
    try { renderProbeResults(); } catch (e) {}
    return null;
  }

  // 立即启动探测（不等完成，后台并发 — 仅供 UI 提前显示"探测中"）
  // ★ 0.3.1: 关键修复 — 移除此 fire-and-forget 调用。bootstrap() 现在在 start()
  //   内部 await detectBridge() 之后跑，避免 bootstrap 读到 state.bridgeProbes 全
  //   pending 而 early-return，导致 /auth/whoami 永远不调、fingerprint 永远为空、
  //   badge 一直显示 👤?。注释里"时序安全"的承诺原本就不成立。
  // detectBridge();

  // 斜杠指令数据驱动分组
  // type: claude-native（转发给 Claude）/ local（bridge 本地处理）/ disabled（TUI 专属，拦截提示）
  const SLASH_COMMANDS = [
    {
      group: "会话控制",
      items: [
        { cmd: "/clear", desc: "清空当前对话历史（bridge 等价 /reset）", type: "local" },
        { cmd: "/compact", desc: "压缩上下文（保留摘要）", type: "claude-native" },
        { cmd: "/resume", desc: "恢复之前的会话", type: "claude-native" },
        { cmd: "/continue", desc: "继续上次未完成的任务", type: "claude-native" },
      ],
    },
    {
      group: "项目记忆",
      items: [
        { cmd: "/memory", desc: "查看/编辑项目记忆（bridge 列出路径，claude 编辑）", type: "local" },
        { cmd: "/add-dir", desc: "添加工作目录", type: "claude-native" },
        { cmd: "/init", desc: "初始化项目记忆文件", type: "claude-native" },
      ],
    },
    {
      group: "开发辅助",
      items: [
        { cmd: "/help", desc: "查看帮助（bridge 列出所有支持指令）", type: "local" },
        { cmd: "/config", desc: "查看/修改配置", type: "claude-native" },
        { cmd: "/model", desc: "切换模型", type: "claude-native" },
        { cmd: "/permissions", desc: "管理工具权限", type: "claude-native" },
        { cmd: "/mcp", desc: "查看 MCP 服务器状态（bridge 列出 41 个工具）", type: "local" },
        { cmd: "/skills", desc: "查看可用 Skill", type: "claude-native" },
      ],
    },
    {
      group: "监控诊断",
      items: [
        { cmd: "/cost", desc: "查看本次会话 token 消耗", type: "claude-native" },
        { cmd: "/status", desc: "查看当前 session 状态（bridge 版）", type: "local" },
        { cmd: "/doctor", desc: "诊断 Claude Code 安装（bridge 跑 claude doctor）", type: "local" },
        { cmd: "/usage", desc: "查看使用量", type: "claude-native" },
      ],
    },
    {
      group: "高级集成",
      items: [
        { cmd: "/agents", desc: "查看/管理自定义 agents", type: "claude-native" },
        { cmd: "/hooks", desc: "管理 hooks", type: "claude-native" },
        { cmd: "/output-style", desc: "设置输出风格", type: "claude-native" },
        { cmd: "/release-notes", desc: "查看发布说明", type: "claude-native" },
        { cmd: "/upgrade", desc: "升级 Claude Code", type: "claude-native" },
        { cmd: "/migrate-installer", desc: "迁移安装方式", type: "claude-native" },
      ],
    },
    {
      group: "账户其他",
      items: [
        { cmd: "/login", desc: "登录账户", type: "claude-native" },
        { cmd: "/logout", desc: "登出账户", type: "claude-native" },
      ],
    },
    {
      group: "bridge 本地",
      items: [
        { cmd: "/reset", desc: "重置会话（销毁旧子进程，新建）", type: "local" },
        { cmd: "/history", desc: "查看当前会话消息历史", type: "local" },
        { cmd: "/list-sessions", desc: "列出所有活跃会话", type: "local" },
        { cmd: "/switch", desc: "切换活跃会话（用法: /switch <id>）", type: "local" },
        { cmd: "/export", desc: "导出会话为 Markdown", type: "local" },
        { cmd: "/dify-help", desc: "查看 Dify Helper 可用 Skill", type: "local" },
      ],
    },
    {
      group: "TUI 专属（不可用）",
      items: [
        { cmd: "/rewind", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/branch", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/btw", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/chrome", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/install-github-app", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/remote-control", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/exit", desc: "该指令仅在交互式终端可用", type: "disabled" },
        { cmd: "/quit", desc: "该指令仅在交互式终端可用", type: "disabled" },
      ],
    },
  ];

  // 快捷按钮预设
  const QUICK_ACTIONS = [
    {
      label: "创建工作流应用",
      prompt:
        "请用 dify_create_app 创建一个 workflow 模式的应用，名称为「新建工作流」，描述「自动生成的客服工作流」。然后用 dify_update_workflow 配置：start 节点（接收 query 变量）→ LLM 节点（用已配置模型回复用户）→ end 节点（输出结果）。最后用 dify_publish_workflow 发布。",
    },
    {
      label: "创建知识库",
      prompt:
        "请用 dify_create_dataset 创建一个知识库，名称为「新建知识库」，索引方式 high_quality。然后告诉我如何上传文档。",
    },
    {
      label: "导出当前应用 DSL",
      prompt:
        "请先用 dify_list_apps 列出所有应用，让我选择一个，然后用 dify_export_dsl 导出它的 DSL 配置。",
    },
    {
      label: "查看索引状态",
      prompt:
        "请先用 dify_list_datasets 列出所有知识库，让我选择一个，再用 dify_list_documents 列出文档，查询每个文档的 dify_get_indexing_status。",
    },
    {
      label: "审查我的代码",
      prompt: "请激活 code-review-strict Skill，我接下来会贴代码让你审查。",
    },
    {
      label: "调试这个 bug",
      prompt: "请激活 bug-diagnostician 和 systematic-thinking Skill，我接下来会描述 bug 现象。",
    },
  ];

  // ==================== 状态 ====================
  // 【重要】state 必须在 detectBridge() 调用之前声明，否则 detectBridge 内部
  // 访问 state.bridgeProbes 会抛 ReferenceError（const 不 hoist，TDZ）。
  // 旧版本把 state 放在文件后面，导致新版 badge/复制诊断完全失效。

  // ==================== 工具函数 ====================

  function gmFetch(method, url, options) {
    return new Promise((resolve, reject) => {
      // ★ 0.3.0: 注入多用户隔离 header（bridge 服务端权威重算 user_id，
      //   client 头仅作撞库细分 + 调试可见性）
      const headers = Object.assign({}, (options && options.headers) || {});
      if (state.fingerprint) headers["X-Bridge-Fingerprint"] = state.fingerprint;
      if (state.displayName)  headers["X-Bridge-Display-Name"] = state.displayName;
      const opts = Object.assign(
        {
          method: method,
          url: url,
          timeout: CONFIG.SSE_TIMEOUT_MS,
          headers: headers,
          onload: function (resp) {
            resolve(resp);
          },
          onerror: function (err) {
            // ★ 0.3.8: GM_xmlhttpRequest 传 raw err（{error, status} 对象），
            //   直接 reject 会让上游 e.message || e 走到 e 分支 → toString "[object Object]"
            //   包成 Error 让上游能拿到 .message
            // ★ 0.3.13: 加 sentinel — 让 unhandledrejection 监听器识别这是我们自己的错
            const msg = (err && (err.error || err.message)) || "network error";
            reject(_markDcfwError(new Error("GM network error: " + msg + " (" + url + ")")));
          },
          ontimeout: function () {
            reject(_markDcfwError(new Error("GM_xmlhttpRequest timeout: " + url)));
          },
        },
        options || {}
      );
      // 覆盖 headers（opts.headers 在 Object.assign 后已被 options.headers 覆盖，但
      //   我们要在 options 之后强制塞回 user identity —— 重新覆盖一次）
      opts.headers = headers;
      GM_xmlhttpRequest(opts);
    });
  }

  function gmFetchJSON(method, url, body) {
    const opts = {
      headers: { "Content-Type": "application/json" },
    };
    if (body) {
      opts.data = JSON.stringify(body);
    }
    return gmFetch(method, url, opts).then((resp) => {
      try {
        return JSON.parse(resp.responseText);
      } catch (e) {
        throw new Error("invalid JSON response: " + resp.responseText.slice(0, 200));
      }
    });
  }

  // ★ 0.2.5: console 捕获（默认开，可手动关）
  function _safeStringify(v) {
    try {
      if (typeof v === "string") return v.slice(0, 500);
      if (typeof v === "number" || typeof v === "boolean") return String(v);
      if (v === null) return "null";
      if (v === undefined) return "undefined";
      if (v instanceof Error) {
        return (v.name + ": " + v.message + "\n" + (v.stack || "")).slice(0, 1000);
      }
      return JSON.stringify(v).slice(0, 500);
    } catch (e) {
      return String(v).slice(0, 100);
    }
  }

  function _captureConsoleEntry(level, args) {
    const cap = state.consoleCapture;
    if (!cap || !cap.enabled) return;
    // 过滤掉自己产生的日志
    const filtered = args.filter((a) => {
      const s = String(a || "");
      for (const p of cap.filteredPrefixes) {
        if (s.includes(p)) return false;
      }
      return true;
    });
    if (filtered.length === 0) return;
    cap.buffer.push({
      t: Date.now(),
      level: level,
      args: filtered.slice(0, 5).map(_safeStringify),
      url: window.location.href,
    });
    if (cap.buffer.length > cap.maxSize) {
      cap.buffer.shift();
    }
  }

  function _installConsoleHooks() {
    if (state.consoleCapture.originals) return; // 已安装
    const levels = ["log", "warn", "error", "info", "debug"];
    const originals = {};
    for (const level of levels) {
      originals[level] = console[level].bind(console);
      // 用普通函数（非箭头）保留 arguments
      console[level] = function () {
        // 原始调用必须先做（确保页面 console 行为不变）
        originals[level].apply(console, arguments);
        _captureConsoleEntry(level, Array.prototype.slice.call(arguments));
      };
    }
    state.consoleCapture.originals = originals;
    console.log("[bridge] 📡 console 捕获已启用（最多 200 条，可在调试面板关闭）");
  }

  function _uninstallConsoleHooks() {
    const originals = state.consoleCapture.originals;
    if (!originals) return;
    for (const level of Object.keys(originals)) {
      console[level] = originals[level];
    }
    state.consoleCapture.originals = null;
    console.log("[bridge] 📡 console 捕获已关闭");
  }

  function toggleConsoleCapture() {
    const cap = state.consoleCapture;
    cap.enabled = !cap.enabled;
    if (cap.enabled) {
      _installConsoleHooks();
    } else {
      _uninstallConsoleHooks();
    }
    renderDebugPanel();
  }

  function clearConsoleCapture() {
    state.consoleCapture.buffer = [];
    renderDebugPanel();
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ★ 0.2.5: 调试面板渲染入口（聚合 probe + console 两块）
  function renderDebugPanel() {
    try { renderProbeResults(); } catch (e) { console.warn("[bridge] renderProbeResults 失败", e); }
    try { renderConsoleCapture(); } catch (e) { console.warn("[bridge] renderConsoleCapture 失败", e); }
  }

  // ★ 0.2.5: 渲染 console 捕获面板（最近 20 条 + toggle/clear）
  function renderConsoleCapture() {
    if (!shadowRoot) return;
    const panel = shadowRoot.getElementById("dcfw-console-panel");
    const listEl = shadowRoot.getElementById("dcfw-console-list");
    const countEl = shadowRoot.getElementById("dcfw-console-count");
    const toggleBtn = shadowRoot.getElementById("dcfw-console-toggle");
    if (!panel || !listEl || !countEl || !toggleBtn) return;

    const cap = state.consoleCapture;
    countEl.textContent = String(cap.buffer.length);
    toggleBtn.textContent = cap.enabled ? "📡 ON" : "⏸ OFF";
    toggleBtn.classList.toggle("on", cap.enabled);
    toggleBtn.classList.toggle("off", !cap.enabled);

    const recent = cap.buffer.slice(-20);
    if (recent.length === 0) {
      listEl.innerHTML =
        `<div style="color:#6b7280;padding:2px 0;">` +
        (cap.enabled ? "（暂无 console 输出）" : "（已关闭，未捕获）") +
        `</div>`;
      return;
    }
    listEl.innerHTML = recent
      .map((e) => {
        const t = new Date(e.t).toLocaleTimeString("zh-CN", { hour12: false });
        const lvl = (e.level || "log").toLowerCase();
        const msg = (e.args || []).map(_safeStringify).join(" ");
        return (
          `<div class="dcfw-console-entry">` +
          `<span class="dcfw-console-time">${t}</span>` +
          `<span class="dcfw-console-level ${lvl}">${lvl.toUpperCase()}</span>` +
          `<span class="dcfw-console-args">${escapeHtml(msg)}</span>` +
          `</div>`
        );
      })
      .join("");
  }

  // ==================== UI 渲染（Shadow DOM 隔离） ====================

  // ★ 0.2.18 修复 TDZ：shadowRoot/hostEl 声明已上移到 state 之后（避免 detectBridge()
  //   同步调用 updateBridgeBadge/renderProbeResults 时仍在 TDZ 抛 ReferenceError）。
  //   见顶部 `const state = {...}` 下方集中声明区。

  function injectUI() {
    if (hostEl && document.body.contains(hostEl)) {
      return; // 已注入（幂等性：避免 MutationObserver 触发的反复 inject）
    }

    // ★ 0.2.14: 清理可能残留的 document 级 listener（理论上有 SPA 路由变化导致
    //   host 被移除 → 重新 inject 的可能；旧版本没清理会让 listener 累积）
    if (_popoverDocClickHandler) {
      document.removeEventListener("mousedown", _popoverDocClickHandler, true);
      _popoverDocClickHandler = null;
    }
    if (_userPopoverDocClickHandler) {
      document.removeEventListener("mousedown", _userPopoverDocClickHandler, true);
      _userPopoverDocClickHandler = null;
    }

    hostEl = document.createElement("div");
    hostEl.id = "dify-claude-floating-window-host";
    hostEl.className = "dcfw-host";  /* ★ 0.3.5: 给 host 加 class 钩子，配合 FAB 跳动动画 */
    // 初始状态：面板关闭 → 不加 dcfw-panel-open
    // ⚠️ 不用 `all:initial`：它会覆盖前面的 `position:fixed`（CSS cascade 规则），
    // 导致悬浮按钮变成"追加在页面底部"的普通块级元素。
    // Shadow DOM 已经提供了样式隔离，这里不需要 `all:initial`。
    hostEl.style.cssText =
      "position:fixed; bottom:24px; right:24px; z-index:2147483647;" +
      "width:0; height:0; pointer-events:none;";
    document.body.appendChild(hostEl);

    shadowRoot = hostEl.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = STYLES;
    shadowRoot.appendChild(style);

    // 悬浮按钮（用 wrapper 撑出点击区，按钮本身保持 56×56）
    const fabWrap = document.createElement("div");
    fabWrap.id = "dcfw-fab-wrap";
    shadowRoot.appendChild(fabWrap);

    const btn = document.createElement("div");
    btn.id = "dcfw-fab";
    // ★ 0.2.17: ClaudeCode 小机器人像素画（3 行字符画）
    btn.innerHTML = '<pre class="dcfw-fab-robot" aria-hidden="true"> ▐▛███▜▌\n▝▜█████▛▘\n  ▘▘ ▝▝</pre>';
    btn.title = "Dify Claude 助手（拖拽移动位置）";
    // 不在这里注册 click，由 setupFabDrag() 统一管理（避免与拖拽吞 click 冲突）
    fabWrap.appendChild(btn);

    // 面板容器
    const panel = document.createElement("div");
    panel.id = "dcfw-panel";
    // ⚠️ 不要在这里设 panel.style.display = "none" —— inline style 优先级高于 CSS，
    // 会让 .open class 永远赢不了，togglePanel 加了 class 也不显示！
    // 初始隐藏由 CSS #dcfw-panel { display: none; } 负责
    panel.innerHTML = PANEL_HTML;
    shadowRoot.appendChild(panel);

    bindPanelEvents();
    setupFabDrag();
    // ★ 0.2.14: 删除 setupClickOutsideClose——document 级 mousedown 监听在 Dify 这种
    //   React + 浏览器扩展丰富的环境下不可靠（retarget 失败 / 扩展劫持 / ShadowRoot polyfill）。
    //   Panel 关闭改由 FAB 唯一控制 + titlebar 新增 ✕ 按钮（Fix 7）。
  }

  // ★ 0.3.2: 全局错误兜底 — 用户报"Firefox 展开按钮闪退"但看不到 console。
  //   在 FAB title + 一个小 overlay 双重显示最近未捕获错误，开不开 F12 都能看到根因。
  //   overlay 是 hostEl 的 sibling div，绝对定位覆盖在屏幕中央，z-index 比 Dify 高。
  let _fatalErrors = [];
  function _recordFatal(scope, err) {
    const msg = (err && (err.stack || err.message)) || String(err);
    _fatalErrors.push({ scope, msg, t: Date.now() });
    if (_fatalErrors.length > 5) _fatalErrors.shift();
    // 在 FAB title 显示
    try {
      const fab = shadowRoot && shadowRoot.getElementById("dcfw-fab");
      if (fab) fab.title = "⚠ 错误 (" + scope + "): " + msg.slice(0, 200) + "\n\n完整错误请开 F12 console";
    } catch (_) {}
    // 显示 overlay
    try { _showFatalOverlay(); } catch (_) {}
    console.error("[bridge] FATAL " + scope + ":", err);
  }
  function _showFatalOverlay() {
    if (!hostEl || !document.body.contains(hostEl)) return;
    let overlay = document.getElementById("dcfw-fatal-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "dcfw-fatal-overlay";
      overlay.style.cssText = [
        "position:fixed", "left:50%", "top:20px", "transform:translateX(-50%)",
        "max-width:80vw", "max-height:60vh", "overflow:auto",
        "background:#1F1E1B", "color:#FFE4E1", "border:2px solid #CC785C",
        "border-radius:8px", "padding:12px 16px",
        "font-family:Courier,monospace", "font-size:12px", "line-height:1.5",
        "z-index:2147483647", "box-shadow:0 8px 32px rgba(0,0,0,0.5)",
        "white-space:pre-wrap", "word-break:break-word",
      ].join(";");
      document.body.appendChild(overlay);
    }
    overlay.textContent = "⚠ Dify Bridge 错误\n" + _fatalErrors.map((e) =>
      "[" + new Date(e.t).toLocaleTimeString("zh-CN", { hour12: false }) + " " + e.scope + "]\n" + e.msg
    ).join("\n\n---\n\n") + "\n\n(点此关闭)";
    overlay.onclick = () => overlay.remove();
  }
  // 注册全局错误捕获（必须在 injectUI 之前就生效，所以放在模块顶层）
  // ★ 0.3.13: 仅归因 plugin 自身的 sentinel-标记错误 —— 页面原生 JS 报错
  //   （如 feathersound.cn theme.js 的 TypeError）不再被误标为 "Dify Bridge 错误"
  window.addEventListener("error", (e) => {
    const err = (e && e.error) || (e && e.message ? new Error(e.message) : null);
    if (!err) return;
    if (err[_DCFW_SENTINEL] !== true) return; // 页面原生错误，不归因到 bridge
    _recordFatal("window.error", err);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e && e.reason;
    if (!reason) return;
    if (reason[_DCFW_SENTINEL] !== true) return; // 页面原生 promise rejection
    _recordFatal("unhandledrejection", reason);
  });

  function togglePanel() {
    // ★ 0.3.2: 全函数 try/catch — Firefox 上点 FAB 直接闪退的根因之一（shadow DOM
    //   adoption / getElementById 在某些场景返回 null 时 throw）。
    try {
      state.panelOpen = !state.panelOpen;
      const panel = shadowRoot.getElementById("dcfw-panel");
      const fab = shadowRoot.getElementById("dcfw-fab");
      if (!panel || !fab) {
        _recordFatal("togglePanel", new Error("panel/fab 元素缺失 — shadowRoot 可能被破坏"));
        return;
      }
      if (state.panelOpen) {
        if (isPanelFullyOffscreen()) {
          console.warn("[bridge] panel 离屏，自动重置到默认位置");
          resetPanelPosition();
        }
        panel.classList.add("open");
        // ★ 0.3.5: host 加 dcfw-panel-open class → 触发 FAB 机器人跳动动画
        if (hostEl) hostEl.classList.add("dcfw-panel-open");
        // ★ 0.3.5: 不再切到 "✕" — 机器人保持显示，关闭按钮在 titlebar 已存在
        // fab.innerHTML 保持初始机器人像素画
        if (!state.sessionId) {
          initSession();
        }
        // ★ 0.2.15: 打开面板时同步刷一次会话列表（填充会话 tab）
        loadSessionList();
        if (state.activeTab === "resource" && !state.resourceLoaded) {
          loadResources();
        }
      } else {
        panel.classList.remove("open");
        // ★ 0.3.5: 移除 host class → FAB 机器人回到静态
        if (hostEl) hostEl.classList.remove("dcfw-panel-open");
        // fab.innerHTML 保持机器人像素画（不切回 ✕，因为我们让机器人承担全部视觉）
      }
    } catch (e) {
      _recordFatal("togglePanel", e);
    }
  }

  // ==================== 样式 ====================

  const STYLES = `
    /* ★ 0.2.6: Claude 主题调色板
       主色 #CC785C（Claude 橙）+ 背景 #FAF9F5（米色）+ 字体衬线
       调试面板保留深色（dev tool 风格解耦） */
    :host {
      /* ★ 0.2.20 修复：0.2.19 误用 * 给所有元素直写 color，破坏继承
         ——改为只在 :host 设 color，descendants 通过继承拿默认；
         已显式声明的子元素（标题栏 #fff / 调试面板 #f3f4f6 等）按 class 特异性胜出 */
      color: #1F1E1B;  /* Claude 主题深棕；dark 站点也不会被外部 color 覆盖 */
    }
    :host, * {
      /* ★ 0.2.11 字体升级：
         英文/数字/符号: Courier Prime（等宽，coding-friendly）
         中文: 明体（macOS PMingLiU / Windows SimSun / Linux Noto Serif CJK SC）
         跨平台 stack: Courier Prime → Courier/Courier New → PMingLiU → MingLiU
                       → STSongti SC / Songti SC → SimSun → Noto Serif CJK SC → serif */
      font-family:
        "Courier Prime",
        Courier,
        "Courier New",
        "Source Han Serif SC",
        "PMingLiU",
        "MingLiU",
        "STSongti SC",
        "Songti SC",
        SimSun,
        "Noto Serif CJK SC",
        serif;
    }

    #dcfw-fab-wrap {
      position: absolute; right: 0; bottom: 0;
      width: 56px; height: 56px;
      pointer-events: auto;
      touch-action: none;
    }
    #dcfw-fab {
      width: 56px; height: 56px; border-radius: 50%;
      background: #CC785C;
      color: #fff; font-size: 24px; text-align: center; line-height: 56px;
      cursor: grab; box-shadow: 0 4px 16px rgba(204, 120, 92, 0.35);
      transition: transform 0.2s, box-shadow 0.2s;
      user-select: none;
      touch-action: none;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    /* ★ 0.2.17: ClaudeCode 机器人像素画（3 行 unicode 字符画）
       ★ 0.3.5: 改用纯半角 block 元素 (▄▀█) —— 之前的字符画混了
         ▐▛▜▌▝▘ 等 box-drawing 字符，这些在不同 monospace 字体里
         半角/全角宽度混排导致腿视觉偏右。新设计全用 ▄▀█，所有 3 行
         都是 6 个字符，跨字体稳定对齐。
       ★ 0.3.7-rc2: 改回原版 ▐▛▜▌▝▘ —— 用户要求对照桌面 CLAUDECODE bot
         文档恢复原始设计。腿偏右问题在 0.3.5/0.3.6 之前是空格数错了
         （原文 5 空格 + 5 字 = 10 列，头只 6 列），现在已修正为 1 空格
         + 5 字 = 6 列，与头同宽居中。CSS 加 font-variant-emoji: text
         防止 emoji 字体接管导致宽度漂移。 */
    .dcfw-fab-robot {
      margin: 0;
      padding: 0;
      font-family: "SF Mono", "Monaco", "Menlo", "Consolas", "Courier New", monospace;
      font-size: 9px;
      line-height: 10px;
      letter-spacing: 0;
      color: #fff;
      text-align: left;
      white-space: pre;
      pointer-events: none;
      display: inline-block;
      font-variant-emoji: text;     /* 防止 emoji 字体接管 ▐▛▜▌▝▘ */
      font-feature-settings: "tnum" 1;  /* 启用等宽数字（部分字体需要） */
    }
    /* ★ 0.3.5: 跳动动画 —— host 加 dcfw-panel-open 时循环 */
    @keyframes dcfw-robot-jump {
      0%, 100% { transform: translateY(0); }
      50%      { transform: translateY(-4px); }
    }
    .dcfw-host.dcfw-panel-open #dcfw-fab .dcfw-fab-robot {
      animation: dcfw-robot-jump 1.2s ease-in-out infinite;
    }
    .dcfw-host:not(.dcfw-panel-open) #dcfw-fab .dcfw-fab-robot {
      animation: none;
    }
    #dcfw-fab:hover { transform: scale(1.08); box-shadow: 0 6px 20px rgba(204, 120, 92, 0.55); }
    #dcfw-fab.dragging { cursor: grabbing; transition: none; }

    #dcfw-panel {
      position: absolute; bottom: 72px; right: 0;
      width: 440px; height: 620px;
      background: #FFFFFF; border-radius: 14px;
      box-shadow: 0 4px 24px rgba(204, 120, 92, 0.10), 0 1px 2px rgba(0,0,0,0.06);
      display: none; flex-direction: column; overflow: hidden;
      border: 1px solid #EFE9DC;
      pointer-events: auto;
      font-size: 13px; /* ★ 0.2.12: 整体缩小基线（原 14px） */
    }
    #dcfw-panel.open { display: flex; }

    .dcfw-titlebar {
      padding: 6px 10px; background: #CC785C;
      color: #fff; display: flex; align-items: center; justify-content: space-between; gap: 8px;
      cursor: move; user-select: none; font-size: 13px; font-weight: 600;
      touch-action: none;
      position: relative;    /* ★ 0.2.8: 给 mode popover 绝对定位锚点 */
      flex-wrap: nowrap;
    }
    .dcfw-titlebar-title {
      flex: 1 1 auto; min-width: 0; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap;
      display: inline-flex; align-items: center; gap: 6px;
    }
    .dcfw-titlebar-title::before {
      content: "▌";                     /* 终端 block cursor */
      opacity: 0.55;
      font-weight: 300;
      font-family: "SF Mono", "Menlo", "Consolas", monospace;
    }
    .dcfw-titlebar-actions { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; }
    .dcfw-titlebar-status { font-size: 11px; opacity: 0.9; font-weight: 400; }
    /* ★ 0.3.7: 第二行状态栏 —— 拟终端 prompt 链
       设计意图：模拟 shell prompt  "▸ ⚡AUTO │ ● agent │ ~/dify-page"
       - 无 padding / 无 border / 无 hover 反馈（与 REPL 工具栏一致）
       - 用 ASCII 字符 (▸ │) 代替 pill 边框，让结构靠字符本身
       - 字号比 titlebar 小 2px，灰度更弱（"环境信息" 不是 "主标题"） */
    .dcfw-statusbar {
      display: flex; align-items: center; gap: 0;
      background: #B86A50;            /* 比 titlebar 略深 */
      color: #fff;
      padding: 3px 10px;
      font-family: "SF Mono", "Menlo", "Consolas", monospace;
      font-size: 11px;
      line-height: 14px;
      user-select: none;
    }
    .dcfw-statusbar-cell {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 0;
      cursor: pointer;
      min-width: 0;
    }
    .dcfw-statusbar-cell + .dcfw-statusbar-cell::before {
      content: "│";                     /* prompt 分隔符 */
      margin: 0 8px;
      opacity: 0.35;
      font-weight: 300;
      pointer-events: none;
    }
    .dcfw-statusbar-cell.dcfw-statusbar-cell-grow { flex: 1 1 auto; }
    .dcfw-statusbar-cell:hover .dcfw-statusbar-prompt { opacity: 1; }
    .dcfw-statusbar-cell:hover .dcfw-statusbar-value { opacity: 1; }

    /* 拟 prompt 前缀：▸ 仅第一个 cell 有 (主 prompt) */
    .dcfw-statusbar-prompt {
      opacity: 0.55;
      font-weight: 700;
      flex: 0 0 auto;
    }
    .dcfw-statusbar-label {
      opacity: 0.55;                    /* "权限" / "Agent" / "URL" 是 schema 提示 */
      font-weight: 400;
    }
    .dcfw-statusbar-value {
      opacity: 0.95;
      font-weight: 600;
      min-width: 0;
    }
    .dcfw-statusbar-cell .dcfw-mode-badge {
      font-size: 11px; padding: 0; border-radius: 0;
      background: transparent;         /* 去掉 pill 底，纯文字 */
      color: inherit;
      border: none;
      font-weight: 600;
    }
    .dcfw-statusbar-cell .dcfw-bridge-badge {
      display: inline-flex; align-items: center; gap: 3px;
      padding: 0; background: transparent;
      font-weight: 600;
      color: inherit;
      border: none;
      margin-left: 0;
      cursor: pointer;
    }
    .dcfw-statusbar-cell .dcfw-bridge-badge.probing,
    .dcfw-statusbar-cell .dcfw-bridge-badge.connected,
    .dcfw-statusbar-cell .dcfw-bridge-badge.failed {
      background: transparent;       /* 去掉 pill 底色 */
      color: inherit;
    }
    .dcfw-statusbar-cell .dcfw-bridge-dot {
      width: 7px; height: 7px;       /* prompt 链里 dot 小一点 */
    }
    .dcfw-statusbar-cell .dcfw-page-badge {
      flex: 1 1 auto; min-width: 0; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap;
      font-size: 11px; opacity: 0.95;
      background: transparent;
      padding: 0;
      border: none;
    }

    /* ★ 0.2.7/0.2.8: Claude 模式徽章（0.2.8 起兼任下拉触发器，删掉原生 select） */
    .dcfw-mode-badge {
      padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;
      background: #CC785C; color: #fff; border: 1px solid rgba(255,255,255,0.25);
      white-space: nowrap;
      cursor: pointer;        /* ★ 0.2.8: 提示可点 */
      transition: transform 0.1s ease;
    }
    .dcfw-mode-badge:hover  { transform: scale(1.05); }
    .dcfw-mode-badge:active { transform: scale(0.95); }
    .dcfw-mode-badge.mode-bypass       { background: #CC785C; }  /* 橙 */
    .dcfw-mode-badge.mode-plan         { background: #8B5CF6; }  /* 蓝紫 */
    .dcfw-mode-badge.mode-acceptEdits  { background: #10B981; }  /* 绿 */
    .dcfw-mode-badge.mode-default      { background: #6B7280; }  /* 灰 */
    .dcfw-mode-badge.switching         { opacity: 0.6; animation: dcfw-pulse 1s ease-in-out infinite; }

    /* ★ 0.2.8: 徽章点击弹出的模式选择 popover */
    .dcfw-mode-popover {
      position: absolute;
      top: 100%; right: 0;
      margin-top: 4px;
      background: #FFFFFF;
      border: 1px solid #EFE9DC;
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(204, 120, 92, 0.18);
      min-width: 200px;
      padding: 4px;
      z-index: 10000;
      font-size: 12px;
      font-weight: 400;
      color: #1f2937;
    }
    .dcfw-mode-popover-item {
      display: flex; align-items: center; gap: 8px;
      padding: 6px 10px; border-radius: 6px;
      cursor: pointer; user-select: none;
    }
    .dcfw-mode-popover-item:hover  { background: #FAF9F5; }
    .dcfw-mode-popover-item.current { background: rgba(204, 120, 92, 0.10); font-weight: 600; }
    .dcfw-mode-popover-item.current::after {
      content: "✓";
      margin-left: auto;
      color: #CC785C;
    }
    .dcfw-mode-popover-desc { color: #6B7280; font-size: 11px; }
    @keyframes dcfw-pulse { 0%,100% { opacity: 0.5; } 50% { opacity: 1; } }

    .dcfw-tabs {
      display: flex; border-bottom: 1px solid #EFE9DC; background: #FAF9F5;
    }
    .dcfw-tab {
      flex: 1; padding: 8px 0; text-align: center; cursor: pointer;
      font-size: 12px; color: #8B7355; border-bottom: 2px solid transparent;
      transition: color 0.15s, background-color 0.15s;
      letter-spacing: 0.5px;
    }
    /* ★ 0.3.8: tab 不再带 ▎ 前缀 — 用户反馈图标化误以为是 icon */
    .dcfw-tab:hover { color: #4A3F35; background: #F5F0E8; }
    .dcfw-tab.active { color: #CC785C; border-bottom-color: #CC785C; font-weight: 600; }

    .dcfw-tab-content { flex: 1; overflow: hidden; display: none; flex-direction: column; }
    .dcfw-tab-content.active { display: flex; }

    /* 对话 Tab */
    #dcfw-chat-messages {
      flex: 1; overflow-y: auto; overflow-x: hidden; padding: 12px; background: #FAF9F5;
      display: flex; flex-direction: column; gap: 8px;
      min-width: 0;
    }
    .dcfw-msg { max-width: 88%; min-width: 0; padding: 8px 12px; border-radius: 10px; font-size: 13px; line-height: 1.55; word-wrap: break-word; overflow-wrap: anywhere; white-space: pre-wrap; }
    .dcfw-msg-user {
      align-self: flex-end; background: #CC785C; color: #fff;
      font-family:
        "Courier Prime",
        Courier,
        "Courier New",
        "Source Han Serif SC",
        "PMingLiU",
        "MingLiU",
        "STSongti SC",
        "Songti SC",
        SimSun,
        "Noto Serif CJK SC",
        serif;
    }
    .dcfw-msg-claude {
      align-self: flex-start; background: transparent; color: #1F1E1B;
      border-left: 2px solid #CC785C; padding: 6px 10px; border-radius: 4px;
      font-family:
        "Courier Prime",
        Courier,
        "Courier New",
        "Source Han Serif SC",
        "PMingLiU",
        "MingLiU",
        "STSongti SC",
        "Songti SC",
        SimSun,
        "Noto Serif CJK SC",
        serif;
      font-size: 12px; line-height: 1.65;  /* ★ 0.2.12: agent 回复气泡缩小（14 → 12） */
    }
    .dcfw-msg-system { align-self: center; background: #FEF3E2; color: #92400e; font-size: 12px; }
    .dcfw-msg-error { align-self: center; background: #FEE2E2; color: #991B1B; font-size: 12px; }
    /* ★ 0.2.16: thinking 块改 <details>/<summary>；[open] 时才有 padding */
    .dcfw-thinking {
      align-self: flex-start; background: #F5F0E8; color: #8B7355; font-style: italic; font-size: 12px;
      border-radius: 8px; border-left: 3px solid #D4CCB8; margin-left: 4px;
      padding: 0;
    }
    .dcfw-thinking[open] { padding: 6px 10px; }
    .dcfw-thinking > summary.dcfw-thinking-summary {
      padding: 6px 10px; cursor: pointer; user-select: none;
      list-style: none; display: flex; align-items: center; gap: 6px;
    }
    .dcfw-thinking > summary.dcfw-thinking-summary::-webkit-details-marker { display: none; }
    .dcfw-thinking > summary.dcfw-thinking-summary::before {
      content: "▸"; font-size: 10px; color: #8B7355;
      display: inline-block; width: 10px; transition: transform 0.15s;
    }
    .dcfw-thinking[open] > summary.dcfw-thinking-summary::before { transform: rotate(90deg); }
    .dcfw-thinking-body {
      padding: 4px 10px 6px 22px; word-wrap: break-word; white-space: pre-wrap;
      border-top: 1px dashed rgba(139, 115, 85, 0.25);
    }

    /* ★ 0.2.16: 标题栏页面徽章 */
    .dcfw-page-badge {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 500;
      background: rgba(255, 255, 255, 0.18); color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.25);
      white-space: nowrap; max-width: 220px;
      overflow: hidden; text-overflow: ellipsis; cursor: help;
    }
    .dcfw-page-badge:hover { filter: brightness(0.95); }
    .dcfw-tool { align-self: flex-start; background: #ECFDF5; color: #065F46; font-size: 12px; padding: 6px 10px; border-radius: 8px; border-left: 3px solid #10B981; margin-left: 4px; font-family: "Courier Prime", Courier, "Courier New", "Source Han Serif SC", "PMingLiU", "MingLiU", "STSongti SC", "Songti SC", SimSun, "Noto Serif CJK SC", monospace; }
    .dcfw-tool-result { align-self: flex-start; background: #F0F9FF; color: #0C4A6E; font-size: 12px; padding: 6px 10px; border-radius: 8px; border-left: 3px solid #0284C7; margin-left: 4px; font-family: "Courier Prime", Courier, "Courier New", "Source Han Serif SC", "PMingLiU", "MingLiU", "STSongti SC", "Songti SC", SimSun, "Noto Serif CJK SC", monospace; max-height: 120px; overflow-y: auto; }

    .dcfw-input-area { border-top: 1px solid #EFE9DC; padding: 10px; background: #FFFFFF; position: relative; display: flex; align-items: center; gap: 8px; }
    #dcfw-chat-input {
      flex: 1; min-width: 0; min-height: 40px; max-height: 120px; padding: 10px 12px;
      box-sizing: border-box;
      border: 1px solid #D4CCB8; border-radius: 10px; font-size: 13px; resize: none; outline: none;
      font-family: inherit; background: #FAF9F5;
      /* ★ 0.2.21: 显式写 color —— <textarea> UA 默认 + 暗色页面 color-scheme
         会拦截从 :host 的继承，必须直接覆盖才能保证深色字 */
      color: #1F1E1B;
      /* ★ 0.2.19: 暗色网站系统插入符也是白的，米色背景看不见 */
      caret-color: #1F1E1B;
    }
    #dcfw-chat-input:focus { border-color: #CC785C; background: #FFFFFF; }
    #dcfw-chat-input::placeholder { color: #B8AB95; }
    .dcfw-send-btn {
      flex: 0 0 auto; width: 36px; height: 36px;
      border: none; border-radius: 8px; background: #CC785C; color: #fff; cursor: pointer;
      font-size: 16px; display: flex; align-items: center; justify-content: center;
      align-self: center;  /* ★ 0.2.12: input-area flex 居中，button 跟 textarea 高度中点对齐 */
    }
    .dcfw-send-btn:hover { background: #B8644A; }
    .dcfw-send-btn:disabled { background: #D4CCB8; cursor: not-allowed; }
    /* ★ 0.3.12: 发送按钮复用为停止按钮（agent 运行时）—— 红色显眼 + 矩形 stop 图标 */
    .dcfw-send-btn.dcfw-stop-btn {
      background: #DC2626;  /* 危险红，与 Claude 橙形成对比 */
      animation: dcfw-pulse-stop 1.5s ease-in-out infinite;
    }
    .dcfw-send-btn.dcfw-stop-btn:hover { background: #B91C1C; }
    @keyframes dcfw-pulse-stop {
      0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.4); }
      50%      { transform: scale(1.05); box-shadow: 0 0 0 6px rgba(220, 38, 38, 0); }
    }

    /* 斜杠指令面板 */
    .dcfw-cmd-palette {
      position: absolute; bottom: 60px; left: 8px; right: 8px; max-height: 280px;
      background: #FFFFFF; border: 1px solid #EFE9DC; border-radius: 10px;
      box-shadow: 0 4px 16px rgba(204, 120, 92, 0.12); overflow-y: auto; z-index: 10; display: none;
    }
    .dcfw-cmd-group { padding: 4px 0; }
    .dcfw-cmd-group-title { padding: 6px 12px; font-size: 11px; color: #8B7355; font-weight: 600; text-transform: uppercase; background: #FAF9F5; }
    .dcfw-cmd-item { padding: 6px 12px; cursor: pointer; font-size: 12px; display: flex; justify-content: space-between; align-items: center; }
    .dcfw-cmd-item:hover, .dcfw-cmd-item.selected { background: #F5F0E8; }
    .dcfw-cmd-item-cmd { font-family: "Courier Prime", Courier, "Courier New", "Source Han Serif SC", "PMingLiU", "MingLiU", "STSongti SC", "Songti SC", SimSun, "Noto Serif CJK SC", monospace; color: #CC785C; font-weight: 600; }
    .dcfw-cmd-item-desc { color: #8B7355; font-size: 12px; margin-left: 8px; }
    .dcfw-cmd-item.disabled .dcfw-cmd-item-cmd { color: #B8AB95; }

    /* 资源 Tab */
    #dcfw-resource-list { flex: 1; overflow-y: auto; padding: 14px; background: #FAF9F5; }
    .dcfw-resource-section { margin-bottom: 16px; }
    .dcfw-resource-section-title { font-size: 12px; font-weight: 600; color: #4A3F35; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid #EFE9DC; }
    .dcfw-resource-item { padding: 10px; border: 1px solid #EFE9DC; border-radius: 8px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; background: #FFFFFF; }
    .dcfw-resource-info { flex: 1; min-width: 0; }
    .dcfw-resource-name { font-size: 12px; color: #1F1E1B; font-weight: 500; }
    .dcfw-resource-meta { font-size: 11px; color: #8B7355; margin-top: 2px; }
    .dcfw-resource-action { padding: 4px 10px; font-size: 11px; background: #F5F0E8; color: #CC785C; border: none; border-radius: 6px; cursor: pointer; white-space: nowrap; }
    .dcfw-resource-action:hover { background: #EFE9DC; }
    .dcfw-loading { text-align: center; padding: 20px; color: #8B7355; font-size: 12px; }
    .dcfw-empty { text-align: center; padding: 40px 20px; color: #8B7355; font-size: 12px; }

    /* 快捷 Tab */
    #dcfw-quick-list { flex: 1; overflow-y: auto; padding: 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: #FAF9F5; }
    .dcfw-quick-btn {
      padding: 14px 10px; border: 1px solid #EFE9DC; border-radius: 10px; background: #FFFFFF;
      cursor: pointer; text-align: center; font-size: 13px; color: #4A3F35; transition: all 0.15s;
    }
    .dcfw-quick-btn:hover { border-color: #CC785C; color: #CC785C; background: #F5F0E8; transform: translateY(-1px); }

    .dcfw-scroll::-webkit-scrollbar { width: 6px; }
    .dcfw-scroll::-webkit-scrollbar-thumb { background: #D4CCB8; border-radius: 3px; }
    .dcfw-scroll::-webkit-scrollbar-track { background: transparent; }

    /* 调试面板 */
    #dcfw-debug-panel {
      border-top: 1px solid #e5e7eb; background: #1f2937; color: #f3f4f6;
      font-family: "Courier Prime", Courier, "Courier New", "Source Han Serif SC", "PMingLiU", "MingLiU", "STSongti SC", "Songti SC", SimSun, "Noto Serif CJK SC", monospace; font-size: 11px;
      max-height: 180px; overflow-y: auto;
    }
    .dcfw-debug-header {
      padding: 6px 12px; background: #111827; color: #fbbf24; cursor: pointer;
      display: flex; justify-content: space-between; align-items: center; user-select: none;
      font-weight: 600;
    }
    .dcfw-debug-header:hover { background: #0f172a; }
    .dcfw-debug-body { padding: 6px 10px; display: none; }
    .dcfw-debug-body.open { display: block; }
    .dcfw-debug-row { padding: 2px 0; border-bottom: 1px solid #374151; word-break: break-all; }
    .dcfw-debug-row:last-child { border-bottom: none; }
    .dcfw-debug-time { color: #9ca3af; margin-right: 6px; }
    .dcfw-debug-type { display: inline-block; min-width: 90px; padding: 1px 4px; border-radius: 3px; font-weight: 600; font-size: 10px; }
    .dcfw-debug-type.text_delta { background: #10b981; color: #fff; }
    .dcfw-debug-type.thinking_delta { background: #6b7280; color: #fff; }
    .dcfw-debug-type.result { background: #3b82f6; color: #fff; }
    .dcfw-debug-type.error { background: #ef4444; color: #fff; }
    .dcfw-debug-type.assistant_complete { background: #8b5cf6; color: #fff; }
    .dcfw-debug-type.tool_call, .dcfw-debug-type.tool_result { background: #f59e0b; color: #fff; }
    .dcfw-debug-type.heartbeat, .dcfw-debug-type.system { background: #4b5563; color: #fff; }
    .dcfw-debug-type.raw, .dcfw-debug-type.unknown, .dcfw-debug-type.stream_event { background: #4b5563; color: #d1d5db; }
    .dcfw-debug-text { color: #f3f4f6; margin-left: 4px; }
    .dcfw-debug-info { padding: 4px 10px; color: #9ca3af; border-bottom: 1px solid #374151; font-size: 10px; }
    .dcfw-debug-info strong { color: #fbbf24; }

    /* ★ 0.2.5: console 捕获面板 */
    .dcfw-console-panel {
      padding: 4px 10px; border-bottom: 1px solid #374151; font-size: 10px;
    }
    .dcfw-console-head {
      display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;
    }
    .dcfw-console-head strong { color: #fbbf24; }
    .dcfw-console-toggle {
      background: #374151; color: #f3f4f6; border: none; border-radius: 3px;
      padding: 2px 6px; cursor: pointer; font-size: 10px;
    }
    .dcfw-console-toggle:hover { background: #4b5563; }
    .dcfw-console-toggle.on { background: #10b981; }
    .dcfw-console-toggle.off { background: #6b7280; }
    .dcfw-console-clear {
      background: #4b5563; color: #f3f4f6; border: none; border-radius: 3px;
      padding: 2px 6px; cursor: pointer; font-size: 10px; margin-left: 4px;
    }
    .dcfw-console-clear:hover { background: #6b7280; }
    .dcfw-console-entry {
      padding: 2px 0; border-bottom: 1px dotted #374151; word-break: break-all;
      font-family: "Courier Prime", Courier, "Courier New", "Source Han Serif SC", "PMingLiU", "MingLiU", "STSongti SC", "Songti SC", SimSun, "Noto Serif CJK SC", monospace;
    }
    .dcfw-console-entry:last-child { border-bottom: none; }
    .dcfw-console-time { color: #6b7280; margin-right: 4px; }
    .dcfw-console-level {
      display: inline-block; min-width: 40px; padding: 0 3px; border-radius: 2px;
      font-size: 9px; font-weight: 600; margin-right: 4px; color: #fff; text-align: center;
    }
    .dcfw-console-level.error { background: #ef4444; }
    .dcfw-console-level.warn { background: #f59e0b; }
    .dcfw-console-level.log, .dcfw-console-level.info { background: #3b82f6; }
    .dcfw-console-level.debug { background: #6b7280; }
    .dcfw-console-args { color: #d1d5db; }

    /* 标题栏右侧：bridge 诊断徽章（始终可见，三态） */
    .dcfw-bridge-badge {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500;
      cursor: help; user-select: none; transition: background-color 0.3s, color 0.3s;
      margin-left: 6px;
    }
    .dcfw-bridge-badge.probing { background: rgba(254, 243, 199, 0.18); color: #FEF3C7; }
    .dcfw-bridge-badge.connected { background: rgba(209, 250, 229, 0.18); color: #D1FAE5; }
    .dcfw-bridge-badge.failed { background: rgba(254, 226, 226, 0.18); color: #FEE2E2; }
    .dcfw-bridge-badge:hover { filter: brightness(0.95); }
    .dcfw-bridge-dot {
      display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: currentColor;
    }
    .dcfw-bridge-dot.pulse { animation: dcfw-pulse 1s ease-in-out infinite; }

    /* ★ 0.2.14: titlebar 显式 ✕ 关闭按钮 */
    .dcfw-close-btn {
      background: transparent; border: none; color: #fff; font-size: 16px;
      padding: 0 6px; margin-left: 2px; cursor: pointer;
      opacity: 0.8; line-height: 1; font-weight: 400;
      transition: opacity 0.15s;
      border-radius: 4px;
    }
    .dcfw-close-btn:hover  { opacity: 1; background: rgba(255,255,255,0.15); }
    .dcfw-close-btn:active { transform: scale(0.92); }
    .dcfw-close-btn[hidden] { display: none !important; }

    /* ★ 0.3.0: 👤 用户身份徽章（撞库时高亮成橙红） */
    .dcfw-user-badge {
      background: transparent; border: none; color: #fff; font-size: 14px;
      padding: 0 4px; margin-left: 2px; cursor: pointer;
      opacity: 0.85; line-height: 1; transition: opacity 0.15s, background 0.15s;
      border-radius: 4px;
    }
    .dcfw-user-badge:hover { opacity: 1; background: rgba(255,255,255,0.15); }
    .dcfw-user-badge.has-name { opacity: 1; background: rgba(204,120,92,0.3); }
    .dcfw-user-badge.legacy { opacity: 0.6; }
    .dcfw-user-badge.collision { animation: dcfw-pulse-warn 1.5s infinite; }
    @keyframes dcfw-pulse-warn {
      0%, 100% { background: rgba(220,80,80,0.3); }
      50%      { background: rgba(220,80,80,0.7); }
    }

    /* ★ 0.3.0: 👤 user popover（display_name 选择器） */
    .dcfw-user-popover {
      position: absolute; top: 36px; right: 8px; width: 280px;
      background: #FFFFFF; border: 1px solid #EFE9DC; border-radius: 10px;
      box-shadow: 0 4px 16px rgba(204, 120, 92, 0.18); z-index: 11;
      padding: 12px; box-sizing: border-box;
    }
    .dcfw-user-popover-title { font-size: 12px; font-weight: 600; color: #4A3F35; margin-bottom: 6px; }
    .dcfw-user-popover-info { font-size: 11px; color: #8B7355; margin-bottom: 8px; word-break: break-all; }
    .dcfw-user-popover-candidates { max-height: 120px; overflow-y: auto; margin-bottom: 8px; }
    .dcfw-user-popover-candidate {
      padding: 6px 8px; font-size: 12px; cursor: pointer; border-radius: 6px;
      color: #4A3F35; margin-bottom: 2px;
    }
    .dcfw-user-popover-candidate:hover { background: #F5F0E8; color: #CC785C; }
    .dcfw-user-popover-candidate.current { background: #CC785C; color: #fff; }
    .dcfw-user-popover-input { display: flex; gap: 4px; margin-bottom: 6px; }
    .dcfw-user-popover-input input {
      flex: 1; padding: 5px 8px; font-size: 12px; border: 1px solid #EFE9DC; border-radius: 6px;
      background: #FAF9F5; color: #1F1E1B; outline: none;
    }
    .dcfw-user-popover-input input:focus { border-color: #CC785C; background: #fff; }
    .dcfw-user-popover-input button {
      padding: 5px 10px; font-size: 11px; background: #CC785C; color: #fff;
      border: none; border-radius: 6px; cursor: pointer; white-space: nowrap;
    }
    .dcfw-user-popover-input button:hover { background: #B8694E; }
    .dcfw-user-popover-hint { font-size: 11px; color: #8B7355; line-height: 1.4; margin-bottom: 6px; }
    .dcfw-user-popover-clear { border-top: 1px solid #EFE9DC; padding-top: 6px; }
    .dcfw-user-popover-clear button {
      width: 100%; padding: 4px; font-size: 11px; background: transparent;
      color: #8B7355; border: none; cursor: pointer; border-radius: 4px;
    }
    .dcfw-user-popover-clear button:hover { background: #F5F0E8; color: #CC785C; }
    /* ★ 0.2.12: 状态徽章只显示图标 dot，不再显示 URL 文本（hover title 看详细） */
    #dcfw-bridge-badge-text { display: none; }
    @keyframes dcfw-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.25; }
    }

    /* 调试面板：探测结果列表 */
    .dcfw-debug-probes { padding: 4px 10px; color: #9ca3af; border-bottom: 1px solid #374151; font-size: 10px; }
    .dcfw-debug-probes-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px; }
    .dcfw-debug-probes-head strong { color: #fbbf24; }
    .dcfw-debug-copy {
      background: #374151; color: #d1d5db; border: none; padding: 1px 6px;
      border-radius: 3px; cursor: pointer; font-size: 9px; font-family: inherit;
    }
    .dcfw-debug-copy:hover { background: #4b5563; color: #fff; }
    .dcfw-debug-copy.copied { background: #10b981; color: #fff; }
    .dcfw-debug-probe-row {
      padding: 1px 0; font-family: "Courier Prime", Courier, "Courier New", "Source Han Serif SC", "PMingLiU", "MingLiU", "STSongti SC", "Songti SC", SimSun, "Noto Serif CJK SC", monospace;
      display: flex; align-items: center; gap: 6px;
    }
    .dcfw-debug-probe-row.chosen { background: #374151; margin: 0 -10px; padding: 1px 10px; border-radius: 2px; }
    .dcfw-debug-probe-icon { display: inline-block; width: 14px; text-align: center; }
    .dcfw-debug-probe-row.ok .dcfw-debug-probe-icon { color: #10b981; }
    .dcfw-debug-probe-row.fail .dcfw-debug-probe-icon { color: #ef4444; }
    .dcfw-debug-probe-row.pending .dcfw-debug-probe-icon { color: #6b7280; }
    .dcfw-debug-probe-url { flex: 1; word-break: break-all; }
    .dcfw-debug-probe-meta { color: #6b7280; font-size: 9px; }
    .dcfw-debug-probe-current { color: #fbbf24; font-weight: 600; }

    /* ★ 0.2.15: 会话 tab 样式 */
    .dcfw-session-actions {
      padding: 12px;
      border-top: 1px solid #EFE9DC;
      background: #FAF9F5;
    }
    .dcfw-new-session-btn {
      width: 100%;
      padding: 10px;
      border: 1px dashed #CC785C;
      border-radius: 10px;
      background: transparent;
      color: #CC785C;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    .dcfw-new-session-btn:hover { background: #FEF3E2; border-style: solid; }
    #dcfw-session-list {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      background: #FAF9F5;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    #dcfw-session-list .dcfw-empty {
      text-align: center;
      color: #8B7355;
      padding: 40px 20px;
      font-size: 13px;
    }
    .dcfw-session-row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border: 1px solid #EFE9DC;
      border-radius: 10px;
      background: #FFFFFF;
      cursor: pointer;
      transition: all 0.15s;
    }
    .dcfw-session-row:hover {
      border-color: #CC785C;
      transform: translateY(-1px);
      box-shadow: 0 2px 6px rgba(204, 120, 92, 0.08);
    }
    .dcfw-session-row.active {
      background: rgba(204, 120, 92, 0.08);
      border-color: #CC785C;
      cursor: default;
    }
    .dcfw-session-row.active:hover { transform: none; box-shadow: none; }
    .dcfw-session-info { flex: 1; min-width: 0; }
    .dcfw-session-name {
      font-size: 13px;
      color: #1F1E1B;
      font-weight: 600;
      word-break: break-all;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }
    .dcfw-active-tag { color: #CC785C; font-weight: 500; font-size: 11px; }
    .dcfw-session-meta { font-size: 11px; color: #8B7355; margin-top: 2px; }
    .dcfw-session-buttons { display: flex; gap: 4px; flex-shrink: 0; }
    .dcfw-session-buttons button {
      width: 28px;
      height: 28px;
      border: none;
      background: transparent;
      color: #6B7280;
      font-size: 14px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .dcfw-session-buttons button:hover { background: #F5F0E8; color: #1F1E1B; }
    .dcfw-session-buttons .dcfw-session-delete:hover { color: #DC2626; }
  `;

  const PANEL_HTML = `
    <div class="dcfw-titlebar">
      <span class="dcfw-titlebar-title">Dify Claude 助手</span>
      <span class="dcfw-titlebar-actions">
        <button class="dcfw-user-badge" id="dcfw-user-badge" title="我是谁（点击切换 / 改 display_name）">👤</button>
        <button class="dcfw-close-btn" id="dcfw-close-btn" title="关闭面板">✕</button>
      </span>
    </div>
    <!-- ★ 0.3.7: 第二行状态栏 —— 拟终端 prompt 链
         视觉：▸ ⚡AUTO │ ● agent │ ~/dify-page
         第一个 cell 用 ▸ (主 prompt)，其它 cell 用 │ 分隔 -->
    <div class="dcfw-statusbar">
      <div class="dcfw-statusbar-cell" id="dcfw-mode-cell" title="点击切换 Claude 权限模式">
        <span class="dcfw-statusbar-prompt">▸</span>
        <span class="dcfw-mode-badge mode-bypass" id="dcfw-mode-badge">⚡AUTO</span>
      </div>
      <div class="dcfw-statusbar-cell" id="dcfw-agent-cell" title="Agent 连接状态">
        <span class="dcfw-statusbar-label">agent</span>
        <span class="dcfw-statusbar-value dcfw-titlebar-status" id="dcfw-status" title="未连接">○</span>
        <span class="dcfw-bridge-badge probing" id="dcfw-bridge-badge" title="正在探测 bridge 可用地址">
          <span class="dcfw-bridge-dot pulse"></span>
          <span id="dcfw-bridge-badge-text">探测</span>
        </span>
      </div>
      <div class="dcfw-statusbar-cell dcfw-statusbar-cell-grow" id="dcfw-url-cell" title="当前页面 URL 检测">
        <span class="dcfw-statusbar-label">url</span>
        <span class="dcfw-statusbar-value dcfw-page-badge" id="dcfw-page-badge" title="尚未捕获页面">—</span>
      </div>
    </div>
    <!-- ★ 0.2.8: 徽章内嵌下拉，点 badge 触发 -->
    <div class="dcfw-mode-popover-anchor" style="position:relative;">
      <div class="dcfw-mode-popover" id="dcfw-mode-popover" style="display:none;">
        <div class="dcfw-mode-popover-item" data-mode="bypass">⚡ AUTO <span class="dcfw-mode-popover-desc">自动批准全部</span></div>
        <div class="dcfw-mode-popover-item" data-mode="plan">📋 PLAN <span class="dcfw-mode-popover-desc">先规划后执行</span></div>
        <div class="dcfw-mode-popover-item" data-mode="acceptEdits">✏️ EDIT <span class="dcfw-mode-popover-desc">仅自动批准编辑</span></div>
        <div class="dcfw-mode-popover-item" data-mode="default">🔒 SAFE <span class="dcfw-mode-popover-desc">每次确认</span></div>
      </div>
      <!-- ★ 0.3.0: 👤 用户 popover（display_name 选择器） -->
      <div class="dcfw-user-popover" id="dcfw-user-popover" style="display:none;">
        <div class="dcfw-user-popover-title">我是谁（display_name）</div>
        <div class="dcfw-user-popover-info" id="dcfw-user-popover-info">—</div>
        <div class="dcfw-user-popover-candidates" id="dcfw-user-popover-candidates"></div>
        <div class="dcfw-user-popover-input">
          <input type="text" id="dcfw-user-popover-newinput" placeholder="新建 display_name（≤ 32 字）" maxlength="32" />
          <button id="dcfw-user-popover-newbtn">设为「我」</button>
        </div>
        <div class="dcfw-user-popover-hint" id="dcfw-user-popover-hint">
          撞库时用 display_name 区分（同一 IP+UA 不同人）。点 ✕ 关闭。
        </div>
        <div class="dcfw-user-popover-clear">
          <button id="dcfw-user-popover-clearbtn" title="清除当前 display_name">清除 display_name（仅靠 IP+UA 区分）</button>
        </div>
      </div>
    </div>
    <div class="dcfw-tabs">
      <div class="dcfw-tab active" data-tab="chat">对话</div>
      <div class="dcfw-tab" data-tab="session">会话</div>
      <div class="dcfw-tab" data-tab="resource">资源</div>
      <div class="dcfw-tab" data-tab="quick">快捷</div>
    </div>

    <div id="dcfw-debug-panel">
      <div class="dcfw-debug-header" id="dcfw-debug-toggle">
        <span>🔧 调试面板（点击展开/收起）</span>
        <span id="dcfw-debug-stats">0 events</span>
      </div>
      <div class="dcfw-debug-body" id="dcfw-debug-body">
        <div class="dcfw-debug-info">
          <div><strong>Bridge:</strong> <span id="dcfw-debug-bridge">探测中...</span></div>
          <div><strong>Session:</strong> <span id="dcfw-debug-session">—</span></div>
          <div><strong>SSE 状态:</strong> <span id="dcfw-debug-sse">未连接</span></div>
          <div><strong>当前页面:</strong> <span id="dcfw-debug-page" style="color:#d1d5db;"></span></div>
        </div>
        <div class="dcfw-debug-probes" id="dcfw-debug-probes">
          <div class="dcfw-debug-probes-head">
            <strong>Bridge 探测结果</strong>
            <button class="dcfw-debug-copy" id="dcfw-debug-copy">复制诊断</button>
          </div>
          <div style="color:#6b7280;">等待探测...</div>
        </div>
        <div class="dcfw-console-panel" id="dcfw-console-panel">
          <div class="dcfw-console-head">
            <strong>Console 捕获 (<span id="dcfw-console-count">0</span>/200)</strong>
            <span>
              <button class="dcfw-console-toggle on" id="dcfw-console-toggle">📡 ON</button>
              <button class="dcfw-console-clear" id="dcfw-console-clear">清空</button>
            </span>
          </div>
          <div id="dcfw-console-list" style="max-height:160px;overflow-y:auto;"></div>
        </div>
        <div id="dcfw-debug-events"></div>
      </div>
    </div>
    
    <div class="dcfw-tab-content active" id="dcfw-tab-chat">
      <div id="dcfw-chat-messages" class="dcfw-scroll"></div>
      <div class="dcfw-input-area">
        <div class="dcfw-cmd-palette" id="dcfw-cmd-palette"></div>
        <textarea id="dcfw-chat-input" placeholder="输入消息，或输入 / 查看指令..." rows="1"></textarea>
        <button class="dcfw-send-btn" id="dcfw-send-btn">➤</button>
      </div>
    </div>
    
    <div class="dcfw-tab-content" id="dcfw-tab-resource">
      <div id="dcfw-resource-list" class="dcfw-scroll">
        <div class="dcfw-loading">加载中...</div>
      </div>
    </div>

    <div class="dcfw-tab-content" id="dcfw-tab-session">
      <div id="dcfw-session-list" class="dcfw-scroll"></div>
      <div class="dcfw-session-actions">
        <button class="dcfw-new-session-btn" id="dcfw-new-session-btn">+ 新建会话</button>
      </div>
    </div>

    <div class="dcfw-tab-content" id="dcfw-tab-quick">
      <div id="dcfw-quick-list"></div>
    </div>
  `;

  // ==================== 事件绑定 ====================

  function bindPanelEvents() {
    // Tab 切换
    shadowRoot.querySelectorAll(".dcfw-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const tabName = tab.dataset.tab;
        switchTab(tabName);
      });
    });

    // 输入框
    const input = shadowRoot.getElementById("dcfw-chat-input");
    const sendBtn = shadowRoot.getElementById("dcfw-send-btn");

    input.addEventListener("input", () => {
      autoResize(input);
      handleSlashInput(input.value);
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (state.isSending) {
          stopCurrentRun();
        } else {
          sendMessage();
        }
      }
      // 斜杠指令面板导航
      const palette = shadowRoot.getElementById("dcfw-cmd-palette");
      if (palette.style.display === "block") {
        const items = palette.querySelectorAll(".dcfw-cmd-item");
        const selected = palette.querySelector(".dcfw-cmd-item.selected");
        let idx = selected ? Array.from(items).indexOf(selected) : -1;
        if (e.key === "ArrowDown") {
          e.preventDefault();
          if (selected) selected.classList.remove("selected");
          idx = Math.min(idx + 1, items.length - 1);
          if (items[idx]) items[idx].classList.add("selected");
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          if (selected) selected.classList.remove("selected");
          idx = Math.max(idx - 1, 0);
          if (items[idx]) items[idx].classList.add("selected");
        } else if (e.key === "Tab" || (e.key === "Enter" && idx >= 0)) {
          e.preventDefault();
          if (items[idx]) {
            const cmd = items[idx].dataset.cmd;
            input.value = cmd + " ";
            palette.style.display = "none";
            autoResize(input);
            input.focus();
          }
        } else if (e.key === "Escape") {
          palette.style.display = "none";
        }
      }
    });

    sendBtn.addEventListener("click", () => {
      if (state.isSending) {
        stopCurrentRun();
      } else {
        sendMessage();
      }
    });

    // ESC 关闭面板（仅在面板打开时生效；输入框按 ESC 走原生行为，不关面板）
    shadowRoot.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.panelOpen) {
        // 输入框聚焦时不抢 ESC（让用户能正常取消 IME / 清空输入）
        const active = shadowRoot.activeElement;
        const isInputFocused =
          active && active.id === "dcfw-chat-input" &&
          (active.value.length > 0 || active === document.activeElement && active.tagName === "TEXTAREA");
        if (isInputFocused && active.value.length > 0) return;
        togglePanel();
        e.preventDefault();
      }
    });

    // 调试面板折叠/展开
    const debugToggle = shadowRoot.getElementById("dcfw-debug-toggle");
    const debugBody = shadowRoot.getElementById("dcfw-debug-body");
    debugToggle.addEventListener("click", () => {
      debugBody.classList.toggle("open");
    });

    // 调试面板：复制诊断按钮（事件委托，renderProbeResults 会重建按钮 DOM）
    debugBody.addEventListener("click", (e) => {
      if (e.target && e.target.id === "dcfw-debug-copy") {
        copyDiagnostic();
      } else if (e.target && e.target.id === "dcfw-console-toggle") {
        toggleConsoleCapture();
      } else if (e.target && e.target.id === "dcfw-console-clear") {
        clearConsoleCapture();
      }
    });

    // 渲染快捷按钮
    renderQuickActions();

    // ★ 0.2.15: 会话 tab 「+ 新建会话」按钮
    const newSessionBtn = shadowRoot.getElementById("dcfw-new-session-btn");
    if (newSessionBtn) {
      newSessionBtn.addEventListener("click", async () => {
        const newId = await createNewSession();
        if (newId) {
          await switchToSession(newId);
          await loadSessionList();
        }
      });
    }
    // ★ 0.2.15: 会话列表点击委托（行 = 切换 / ✎ = 重命名 / 🗑 = 删除）
    const sessionListEl = shadowRoot.getElementById("dcfw-session-list");
    if (sessionListEl) {
      sessionListEl.addEventListener("click", (e) => {
        const renameBtn = e.target.closest(".dcfw-session-rename");
        const deleteBtn = e.target.closest(".dcfw-session-delete");
        const row = e.target.closest(".dcfw-session-row");
        if (renameBtn) {
          e.stopPropagation();
          const id = renameBtn.dataset.id;
          const current = state.sessionList.find((s) => s.id === id);
          const defaultName = current ? (current.name || "") : "";
          const input = prompt("输入新名称（留空清空，退到首条消息预览）", defaultName);
          if (input !== null) renameActive(input.trim() || null);
          return;
        }
        if (deleteBtn) {
          e.stopPropagation();
          const id = deleteBtn.dataset.id;
          if (confirm("删除此会话？不可恢复。")) deleteSession(id);
          return;
        }
        if (row && !row.classList.contains("active")) {
          switchToSession(row.dataset.id);
        }
      });
    }

    // ★ 0.2.8: 模式徽章 = 下拉触发器（取代 0.2.7 的 <select>）
    const modeBadge = shadowRoot.getElementById("dcfw-mode-badge");
    if (modeBadge) {
      modeBadge.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleModePopover();
      });
    }

    // ★ 0.3.7: statusbar 三 cell —— 整 cell 可点，UX 比点 badge 体感大
    const modeCell = shadowRoot.getElementById("dcfw-mode-cell");
    if (modeCell) {
      modeCell.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleModePopover();
      });
    }
    const agentCell = shadowRoot.getElementById("dcfw-agent-cell");
    if (agentCell) {
      agentCell.addEventListener("click", (e) => {
        // ★ 0.3.7: agent cell = 重新探测 bridge（强制重跑）
        e.stopPropagation();
        if (typeof detectBridge === "function") {
          addSystemMessage("🔄 正在重新探测 bridge...");
          detectBridge();
        }
      });
    }
    const urlCell = shadowRoot.getElementById("dcfw-url-cell");
    if (urlCell) {
      urlCell.addEventListener("click", (e) => {
        // ★ 0.3.7: url cell = 显示当前 url + 复制到剪贴板（信息型）
        e.stopPropagation();
        const ctx = state.activePageContext || {};
        const url = ctx.url || location.href;
        const shown = url.length > 80 ? url.slice(0, 77) + "..." : url;
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url);
            addSystemMessage(`🔗 已复制 URL：${shown}`);
          } else {
            addSystemMessage(`🔗 当前 URL：${shown}`);
          }
        } catch (err) {
          addSystemMessage(`🔗 当前 URL：${shown}`);
        }
      });
    }

    // ★ 0.2.14: 显式 ✕ 关闭按钮（替代 setupClickOutsideClose）
    //   - stopPropagation 防止冒泡到 titlebar 触发 pointerdown → setPointerCapture
    //   - 不在这里 preventDefault（点 ✕ 不会触发 setPointerCapture 流程）
    const closeBtn = shadowRoot.getElementById("dcfw-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        togglePanel();
      });
    }
    // popover 内选项 click（事件委托）
    const modePopover = shadowRoot.getElementById("dcfw-mode-popover");
    if (modePopover) {
      modePopover.addEventListener("click", (e) => {
        const item = e.target.closest(".dcfw-mode-popover-item");
        if (!item) return;
        const newMode = item.dataset.mode;
        toggleModePopover(false);
        setMode(newMode);
      });
    }
    // 首次渲染时刷新徽章（state.currentMode 可能是默认 bypass）
    refreshModeBadge();

    // 拖拽标题栏
    setupDrag();

    // ★ 0.3.0: 👤 user badge click → 弹 display_name popover
    const userBadge = shadowRoot.getElementById("dcfw-user-badge");
    const userPopover = shadowRoot.getElementById("dcfw-user-popover");
    if (userBadge && userPopover) {
      userBadge.addEventListener("click", (e) => {
        e.stopPropagation();
        const visible = userPopover.style.display !== "none";
        toggleUserPopover(!visible);
      });
      // candidate click（事件委托）
      const candBox = shadowRoot.getElementById("dcfw-user-popover-candidates");
      if (candBox) {
        candBox.addEventListener("click", (e) => {
          const el = e.target.closest(".dcfw-user-popover-candidate");
          if (!el) return;
          const name = el.dataset.name;
          if (name) setDisplayName(name);
        });
      }
      // 新建 input + button
      const newInput = shadowRoot.getElementById("dcfw-user-popover-newinput");
      const newBtn   = shadowRoot.getElementById("dcfw-user-popover-newbtn");
      if (newBtn && newInput) {
        const doSet = () => {
          const v = (newInput.value || "").trim();
          if (!v) return;
          if (v.length > 32) {
            const hint = shadowRoot.getElementById("dcfw-user-popover-hint");
            if (hint) hint.textContent = "display_name 限 32 字符以内";
            return;
          }
          setDisplayName(v);
        };
        newBtn.addEventListener("click", doSet);
        newInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); doSet(); }
        });
      }
      // 清除 display_name
      const clearBtn = shadowRoot.getElementById("dcfw-user-popover-clearbtn");
      if (clearBtn) clearBtn.addEventListener("click", () => clearDisplayName());
      // ★ 0.3.4: 点 popover 外部关闭改用 mousedown + capture + composedPath
      // （shadow DOM 事件 retarget 会让 document click 的 e.target 变成 hostEl，
      //   userPopover.contains(hostEl) 永远为 false，导致 popover 打开后立刻闪退）
    }
    // 初始渲染一次（按当前 state）
    refreshUserBadge();
  }

  // ==================== ★ 0.3.0: display_name UI ====================

  function toggleUserPopover(show) {
    const p = shadowRoot && shadowRoot.getElementById("dcfw-user-popover");
    if (!p) return;
    const shouldShow = show ?? (p.style.display === "none");
    p.style.display = shouldShow ? "block" : "none";
    if (shouldShow) {
      renderUserPopover();
      // ★ 0.3.4: 先清理上次的监听器（开→关→开 时防止重复 add）
      if (_userPopoverDocClickHandler) {
        document.removeEventListener("mousedown", _userPopoverDocClickHandler, true);
        _userPopoverDocClickHandler = null;
      }
      // 用 capture 阶段 + composedPath 判定（shadow 内部事件 retarget 到 host，要用 composedPath 拿真实 target）
      setTimeout(() => {
        _userPopoverDocClickHandler = (e) => {
          const tgt = e.composedPath ? e.composedPath()[0] : e.target;
          // 命中 badge 或 popover 内部 → 不关
          if (tgt && tgt.closest && tgt.closest("#dcfw-user-badge, .dcfw-user-popover")) return;
          toggleUserPopover(false);
          if (_userPopoverDocClickHandler) {
            document.removeEventListener("mousedown", _userPopoverDocClickHandler, true);
            _userPopoverDocClickHandler = null;
          }
        };
        document.addEventListener("mousedown", _userPopoverDocClickHandler, true);
      }, 0);
    } else {
      // ★ 0.3.4: 显式关闭时也清理监听器（点自身 badge 关闭的场景）
      if (_userPopoverDocClickHandler) {
        document.removeEventListener("mousedown", _userPopoverDocClickHandler, true);
        _userPopoverDocClickHandler = null;
      }
    }
  }

  async function renderUserPopover() {
    const infoEl = shadowRoot.getElementById("dcfw-user-popover-info");
    const candEl = shadowRoot.getElementById("dcfw-user-popover-candidates");
    const newInput = shadowRoot.getElementById("dcfw-user-popover-newinput");
    if (!infoEl || !candEl) return;
    const fpShort = state.fingerprint ? state.fingerprint.slice(0, 12) : "(无 fingerprint)";
    const ip = (state.userId ? "user=" + state.userId.slice(0, 8) + "..." : "user=?");
    const name = state.displayName ? "「" + state.displayName + "」" : "(无 display_name)";
    infoEl.textContent = `fingerprint: ${fpShort} | ${ip} | 当前: ${name}${state.isLegacy ? " | LEGACY" : ""}`;
    // 拉候选（同步 /auth/whoami 重新拉一次以拿到最新 candidates）
    try {
      const who = await gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/auth/whoami");
      const cands = (who.candidates || []).filter((n) => n && n !== state.displayName);
      candEl.innerHTML = "";
      if (cands.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "font-size:11px;color:#8B7355;padding:4px 0;";
        empty.textContent = "（无撞库候选）";
        candEl.appendChild(empty);
      } else {
        cands.slice(0, 20).forEach((n) => {
          const el = document.createElement("div");
          el.className = "dcfw-user-popover-candidate";
          el.dataset.name = n;
          el.textContent = "👤 " + n;
          el.title = "切换到「" + n + "」";
          candEl.appendChild(el);
        });
      }
    } catch (e) {
      candEl.innerHTML = '<div style="font-size:11px;color:#8B7355;">(拉取候选失败)</div>';
    }
    if (newInput) newInput.value = "";
  }

  function refreshUserBadge() {
    const badge = shadowRoot && shadowRoot.getElementById("dcfw-user-badge");
    if (!badge) return;
    badge.classList.toggle("has-name", !!state.displayName);
    badge.classList.toggle("legacy", !!state.isLegacy);
    // 撞库时由 bootstrap() 调用 showDisplayNamePicker 时再上 collision class
    if (state.displayName) {
      badge.textContent = "👤 " + state.displayName.slice(0, 10);
      badge.title = "当前: 「" + state.displayName + "」" + (state.isLegacy ? " (LEGACY)" : "");
    } else if (state.fingerprint) {
      badge.textContent = "👤";
      badge.title = "未设置 display_name，点击设置（fingerprint: " + state.fingerprint.slice(0, 8) + "）";
    } else {
      badge.textContent = "👤?";
      badge.title = "未拿到 fingerprint（旧版 bridge？）";
    }
  }

  function showDisplayNamePicker(candidates, currentName) {
    // 撞库自动弹 — 延迟到 UI 注入后再弹
    setTimeout(() => {
      if (!shadowRoot) return;
      const badge = shadowRoot.getElementById("dcfw-user-badge");
      if (badge) badge.classList.add("collision");
      toggleUserPopover(true);
    }, 200);
  }

  async function setDisplayName(name) {
    try {
      state.displayName = name;
      GM_setValue(CONFIG.DISPLAY_NAME_KEY, name);
      refreshUserBadge();
      toggleUserPopover(false);
      const badge = shadowRoot && shadowRoot.getElementById("dcfw-user-badge");
      if (badge) badge.classList.remove("collision");
      // ★ 0.3.1: addSystemMessage 用 try/catch 包裹 — 用户报"点击闪退"，可能是
      //   panel 未打开时调 scrollMessagesToBottom 或 chat-messages 找不到导致 throw
      try {
        addSystemMessage("👤 已设置 display_name = 「" + name + "」，下次 bridge 请求会用新身份。");
      } catch (e) {
        console.warn("[bridge] addSystemMessage 失败（不影响 display_name 持久化）", e);
      }
    } catch (e) {
      console.error("[bridge] setDisplayName 失败", e);
    }
    // ★ 0.3.1: 不立即重 bootstrap — 下次 init 即可；如要立即生效可加 reload()
  }

  async function clearDisplayName() {
    try {
      state.displayName = null;
      GM_deleteValue(CONFIG.DISPLAY_NAME_KEY);
      refreshUserBadge();
      toggleUserPopover(false);
      try {
        addSystemMessage("👤 已清除 display_name，恢复为仅 (IP+UA) 区分。");
      } catch (e) {
        console.warn("[bridge] addSystemMessage 失败", e);
      }
    } catch (e) {
      console.error("[bridge] clearDisplayName 失败", e);
    }
  }

  function autoResize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
  }

  function switchTab(tabName) {
    state.activeTab = tabName;
    shadowRoot.querySelectorAll(".dcfw-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.tab === tabName);
    });
    shadowRoot.querySelectorAll(".dcfw-tab-content").forEach((c) => {
      c.classList.remove("active");
    });
    shadowRoot.getElementById("dcfw-tab-" + tabName).classList.add("active");
    if (tabName === "resource" && !state.resourceLoaded) {
      loadResources();
    }
  }

  function setupDrag() {
    // ★ 0.2.6: 用 Pointer Events API + setPointerCapture 替代 mouse events
    // 1) pointer capture 让 move/up 一定回到 titlebar，避免 mouseup 丢失导致 isDragging 卡 true
    // 2) 拖拽状态用闭包内单一 pointerId 标识，与 textarea 焦点事件完全隔离
    // ★ 0.2.9: 缓存 panel 尺寸（pointermove 期间不读 offsetWidth/Height，避免强制 reflow）
    const titlebar = shadowRoot.querySelector(".dcfw-titlebar");
    const panel = shadowRoot.getElementById("dcfw-panel");
    let activePointer = null;
    let startX = 0, startY = 0, startLeft = 0, startTop = 0;
    let panelW = 0, panelH = 0;

    titlebar.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      // ★ 0.2.8/0.2.14: 排除标题栏内可交互元素；点 ✕ 按钮 (close-btn) 也必须排除，否则
      //   ✕ click 同时触发 pointerdown → setPointerCapture，click 不再触发 toggle
      // 之前缺这行：点 <select> 触发 setPointerCapture，抑制原生下拉 + 改写 panel.style.left/top，
      // 用户视觉上看到「闪退」（page 抖一下，select 不展开）
      if (e.target.closest("select, button, input, .dcfw-mode-badge, .dcfw-bridge-badge, .dcfw-mode-popover, .dcfw-close-btn, .dcfw-statusbar-cell")) return;
      activePointer = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      const panelRect = panel.getBoundingClientRect();
      // ★ 0.2.14 关键修复：#dcfw-panel 是 position:absolute，锚定到 0×0 host（position:fixed）。
      //   panel.style.left 实际是 host-relative 偏移，不是 viewport 坐标。
      //   之前用 viewport 坐标写 → host 一动 panel 错位巨大（被拖出屏外）。
      //   修正：startLeft = panelRect.left - hostRect.left（host-relative 坐标）
      const hostRect = hostEl.getBoundingClientRect();
      startLeft = panelRect.left - hostRect.left;
      startTop = panelRect.top - hostRect.top;
      panelW = panel.offsetWidth;   // ★ 0.2.9: 缓存尺寸，pointermove 内复用
      panelH = panel.offsetHeight;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      panel.style.left = startLeft + "px";
      panel.style.top = startTop + "px";
      try { titlebar.setPointerCapture(e.pointerId); } catch (_) {}
      // 不要 preventDefault——会让 textarea 内点击/拖选失效
    });

    titlebar.addEventListener("pointermove", (e) => {
      if (activePointer === null || e.pointerId !== activePointer) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      // ★ 0.2.14: clampToViewport 期望 viewport 坐标；但 startLeft 已是 host-relative。
      //   先换算到 viewport（hostRect.left + rel + dx），clamp 后再换回 host-relative。
      //   这样即便 host 在拖拽期间被同时移动（理论上不会），panel 也能正确跟随。
      const hostRect = hostEl.getBoundingClientRect();
      const viewportX = hostRect.left + startLeft + dx;
      const viewportY = hostRect.top + startTop + dy;
      // ★ 0.2.9: 视口 clamp（保证至少 40px 可见，避免面板被拖出屏幕）
      const c = clampToViewport(viewportX, viewportY, panelW, panelH, 40);
      // 转回 host-relative 坐标
      panel.style.left = (c.x - hostRect.left) + "px";
      panel.style.top = (c.y - hostRect.top) + "px";
    });

    const endDrag = (e) => {
      if (activePointer === null || e.pointerId !== activePointer) return;
      activePointer = null;
      try { titlebar.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    titlebar.addEventListener("pointerup", endDrag);
    titlebar.addEventListener("pointercancel", endDrag);
  }

  // 悬浮按钮拖拽：移动整个 host（fab + panel 一起跟着走）
  function setupFabDrag() {
    // ★ 0.2.6: 同样改用 Pointer Events API + setPointerCapture
    // ★ 0.2.9: 缓存 fab 尺寸 + 视口 clamp（保证至少 16px 可见）
    // ★ 0.2.10: 用"虚拟 host 边界" clamp——panel 是 host-relative 锚定，必须保证
    //   host 不出能让 panel 完全可见的范围，否则 panel 跟着 host 飞出视口
    // ★ 0.2.11: 0.2.10 的"虚拟边界"数学错了。
    //   panel 是 position:absolute; right:0; bottom:72px 锚定到 host 内，
    //   host 0×0 在 (hostLeft, hostTop)，所以 panel 实际占据:
    //     panel.left   = hostLeft - 440
    //     panel.right  = hostLeft
    //     panel.top    = hostTop  - 692  (620 height + 72 bottom offset)
    //     panel.bottom = hostTop  - 72
    //   fab-wrap 在 host 内 right:0; bottom:0，fab 实际占据:
    //     fab.left   = hostLeft - 56
    //     fab.right  = hostLeft
    //     fab.top    = hostTop  - 56
    //     fab.bottom = hostTop
    //   所以 host 必须满足: hostLeft ∈ [440, vw - 16], hostTop ∈ [692, vh - 16]
    //   （panel 完全可见 + FAB 留 16px）
    //   用 panel 实际位置直接 clamp，不再用"虚拟 box"抽象
    const fab = shadowRoot.getElementById("dcfw-fab");
    const PANEL_W = 440;
    const PANEL_H = 620;
    const PANEL_BOTTOM_OFFSET = 72;  // panel bottom 距 host bottom 的偏移
    const FAB_SIZE = 56;
    let activePointer = null;
    let didMove = false;
    let startX = 0, startY = 0;
    let hostStartLeft = 0, hostStartTop = 0;
    let fabW = 0, fabH = 0;

    function getViewportPos() {
      const rect = hostEl.getBoundingClientRect();
      return { left: rect.left, top: rect.top };
    }

    fab.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      activePointer = e.pointerId;
      didMove = false;
      startX = e.clientX;
      startY = e.clientY;
      fabW = fab.offsetWidth;   // ★ 0.2.9: 缓存尺寸
      fabH = fab.offsetHeight;
      fab.classList.add("dragging");
      try { fab.setPointerCapture(e.pointerId); } catch (_) {}
      // ⚠️ 不要在这里 preventDefault/stopPropagation！
      // 在 Shadow DOM + Tampermonkey 环境下，会吞掉紧随其后的 click 事件，
      // 导致 fab 点击后无法触发 togglePanel。
    });

    fab.addEventListener("pointermove", (e) => {
      if (activePointer === null || e.pointerId !== activePointer) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      // 移动超过 4px 才算真拖拽，避免与 click 冲突
      if (!didMove && Math.hypot(dx, dy) > 4) {
        didMove = true;
        // 第一次拖拽时把 host 从 bottom/right 切到 top/left 绝对定位
        const pos = getViewportPos();
        hostStartLeft = pos.left;
        hostStartTop = pos.top;
        hostEl.style.bottom = "auto";
        hostEl.style.right = "auto";
        hostEl.style.left = hostStartLeft + "px";
        hostEl.style.top = hostStartTop + "px";
      }
      if (didMove) {
        // ★ 0.2.11: 直接 clamp host 位置（保证 panel + fab 都可见）
        // hostLeft ≥ PANEL_W：panel.left ≥ 0
        // hostLeft ≤ vw - 16：fab 右边 + panel 右边留 16px（panel.right = hostLeft ≤ vw - 16）
        // hostTop ≥ PANEL_H + PANEL_BOTTOM_OFFSET = 692：panel.top = hostTop - 692 ≥ 0
        // hostTop ≤ vh - 16：fab 底部留 16px
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const minVis = 16;
        const newLeft = Math.max(PANEL_W, Math.min(vw - minVis, hostStartLeft + dx));
        const newTop = Math.max(PANEL_H + PANEL_BOTTOM_OFFSET, Math.min(vh - minVis, hostStartTop + dy));
        hostEl.style.left = newLeft + "px";
        hostEl.style.top = newTop + "px";
      }
    });

    const endFabDrag = (e) => {
      if (activePointer === null || e.pointerId !== activePointer) return;
      activePointer = null;
      fab.classList.remove("dragging");
      try { fab.releasePointerCapture(e.pointerId); } catch (_) {}
      // 【修复】指针在 FAB 外释放时 click 不会触发，didMove 会卡在 true，
      // 导致下一次 FAB 点击被吞。统一在 pointerup 重置。
      didMove = false;
    };
    fab.addEventListener("pointerup", endFabDrag);
    fab.addEventListener("pointercancel", endFabDrag);

    // ★ 0.2.14: FAB click 状态机重写——单一 listener 而非 0.2.6 的双 listener 串联。
    //   之前 0.2.6 的设计：第一个 listener 检查 didMove 决定是否吞 click，
    //   第二个才调 togglePanel。两 listener 按注册顺序执行。
    //   Bug：若 didMove 卡在 true（pointerup 没正确触发），下一次 FAB click：
    //     (1) 第一个 listener 吞 click + 重置 didMove
    //     (2) togglePanel 根本不会被调用（已经被 stopImmediatePropagation 截断）
    //     用户体验：FAB 第一次"无响应"，必须再点一次才能 toggle
    //   修正：单一 listener 同时检查 + 处理，若 didMove 漏 reset 也只会丢一次 toggle
    //   （下次正常 toggle），不会卡死。
    fab.addEventListener("click", (e) => {
      if (didMove) {
        // 防御性重置（pointerup 没正确触发的边缘情况）
        didMove = false;
        e.stopImmediatePropagation();
        return;
      }
      togglePanel();
    });
  }

  // ★ 0.2.9: 窗口 resize 时重新 clamp 面板（防止缩小窗口后面板部分出屏）
  // ★ 0.2.11: host 也需要 clamp（panel 是 host-relative 锚定在 host 顶部）
  //   host 位置约束: hostLeft ∈ [440, vw - 16], hostTop ∈ [692, vh - 16]
  window.addEventListener("resize", () => {
    try {
      const panel = shadowRoot.getElementById("dcfw-panel");
      if (panel && panel.style.left && panel.style.top) {
        // ★ 0.2.14: panel.style.left/top 是 host-relative，clampToViewport 期望 viewport。
        //   换算：viewport = hostRect.left + relLeft，clamp 后转回 host-relative。
        const hostRect = hostEl.getBoundingClientRect();
        const relLeft = parseFloat(panel.style.left);
        const relTop = parseFloat(panel.style.top);
        const viewportX = hostRect.left + relLeft;
        const viewportY = hostRect.top + relTop;
        const c = clampToViewport(
          viewportX, viewportY,
          panel.offsetWidth, panel.offsetHeight, 40
        );
        const newRelLeft = c.x - hostRect.left;
        const newRelTop = c.y - hostRect.top;
        if (relLeft !== newRelLeft) panel.style.left = newRelLeft + "px";
        if (relTop !== newRelTop) panel.style.top = newRelTop + "px";
      }
      // ★ 0.2.11: host 也 clamp（保证 panel + fab 都可见）
      // hostLeft ≥ 440 (panel.left ≥ 0), hostLeft ≤ vw - 16 (panel.right 留 16)
      // hostTop  ≥ 692 (panel.top  ≥ 0), hostTop  ≤ vh - 16 (fab 底留 16)
      if (hostEl && hostEl.style.left && hostEl.style.top) {
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const minVis = 16;
        const PANEL_W = 440;
        const PANEL_H = 620;
        const PANEL_BOTTOM_OFFSET = 72;
        const curL = parseFloat(hostEl.style.left);
        const curT = parseFloat(hostEl.style.top);
        const newL = Math.max(PANEL_W, Math.min(vw - minVis, curL));
        const newT = Math.max(PANEL_H + PANEL_BOTTOM_OFFSET, Math.min(vh - minVis, curT));
        if (curL !== newL) hostEl.style.left = newL + "px";
        if (curT !== newT) hostEl.style.top = newT + "px";
      }
    } catch (e) {
      console.warn("[bridge] resize clamp 失败", e);
    }
  });

  // ==================== 斜杠指令面板 ====================

  function handleSlashInput(value) {
    const palette = shadowRoot.getElementById("dcfw-cmd-palette");
    if (!value.startsWith("/")) {
      palette.style.display = "none";
      return;
    }
    const query = value.split(/\s/)[0].toLowerCase(); // 取首个单词
    const matches = [];
    for (const group of SLASH_COMMANDS) {
      const groupMatches = group.items.filter(
        (it) => it.cmd.toLowerCase().startsWith(query) || it.cmd.toLowerCase().includes(query.slice(1))
      );
      if (groupMatches.length > 0) {
        matches.push({ group: group.group, items: groupMatches });
      }
    }

    if (matches.length === 0) {
      palette.style.display = "none";
      return;
    }

    let html = "";
    for (const m of matches) {
      html += `<div class="dcfw-cmd-group">`;
      html += `<div class="dcfw-cmd-group-title">${escapeHtml(m.group)}</div>`;
      for (const it of m.items) {
        const disabledCls = it.type === "disabled" ? " disabled" : "";
        html += `<div class="dcfw-cmd-item${disabledCls}" data-cmd="${escapeHtml(it.cmd)}" data-type="${it.type}">`;
        html += `<span><span class="dcfw-cmd-item-cmd">${escapeHtml(it.cmd)}</span><span class="dcfw-cmd-item-desc">${escapeHtml(it.desc)}</span></span>`;
        html += `</div>`;
      }
      html += `</div>`;
    }
    palette.innerHTML = html;
    palette.style.display = "block";

    // 点击选择
    const inputEl = shadowRoot.getElementById("dcfw-chat-input");
    palette.querySelectorAll(".dcfw-cmd-item").forEach((item) => {
      item.addEventListener("click", () => {
        const cmd = item.dataset.cmd;
        inputEl.value = cmd + " ";
        palette.style.display = "none";
        autoResize(inputEl);
        inputEl.focus();
      });
    });
  }

  // ==================== 会话管理 ====================

  async function initSession() {
    // ★ 0.2.15: 先恢复 MRU，再走原本的 stored → 新建 fallback
    state.sessionMRU = (GM_getValue(getSessionMRUKey(), []) || []).slice(0, CONFIG.SESSION_MRU_CAP);

    // 1. 优先复用已存储的 session_id
    const stored = GM_getValue(getSessionIdKey(), null);
    if (stored) {
      try {
        const list = await gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/sessions");
        state.sessionList = (list.sessions || []).slice(); // 顺便缓存列表
        const exists = (list.sessions || []).some((s) => s.id === stored && s.status !== "closed");
        if (exists) {
          state.sessionId = stored;
          updateStatus("已连接");
          await syncModeFromStatus();
          pushMRU(stored);                     // ★ 0.2.15: 刷新 MRU 顺序
          return;
        }
      } catch (e) {
        // 验证失败，继续 fallback
      }
    }

    // 2. ★ 0.2.15: fallback 到 MRU[0]（用户最近活跃的会话）
    if (state.sessionMRU.length > 0) {
      try {
        const list = await gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/sessions");
        state.sessionList = (list.sessions || []).slice();
        const mruTop = state.sessionMRU[0].id;
        const exists = (list.sessions || []).some((s) => s.id === mruTop && s.status !== "closed");
        if (exists) {
          state.sessionId = mruTop;
          GM_setValue(getSessionIdKey(), mruTop);
          updateStatus("已连接");
          await syncModeFromStatus();
          addSystemMessage("恢复最近会话「" + (state.sessionMRU[0].name || state.sessionMRU[0].preview || mruTop.slice(0, 6)) + "」。");
          return;
        }
      } catch (e) {
        // 继续走新建
      }
    }

    // 3. 创建新会话
    try {
      updateStatus("连接中...");
      const resp = await gmFetchJSON("POST", CONFIG.BRIDGE_URL + "/sessions", {});
      state.sessionId = resp.session_id;
      if (resp.mode) state.currentMode = resp.mode;
      GM_setValue(getSessionIdKey(), state.sessionId);
      updateStatus("已连接");
      updateDebugInfo();
      // ★ 0.2.16: 新建后也走一次 /status 复核，保证 mode 准确
      await syncModeFromStatus();
      refreshModeBadge();
      pushMRU(state.sessionId);                // ★ 0.2.15
      addSystemMessage("会话已就绪。输入消息或 / 查看指令。");
    } catch (e) {
      updateStatus("连接失败");
      // ★ 0.3.10: 把 bridge 探测结果也带出来 — 用户常见踩坑：
      //   1) 远程访问没配 GM __bridge_remote_host__（仅 loopback fallback）
      //   2) 公网 IP 配了但路由器 8002 端口转发没配
      // 让用户一眼看清每个候选的探测状态
      const probes = state.bridgeProbes || [];
      const summary = probes.length === 0
        ? "(尚未探测)"
        : probes.map((p) => {
            const status = p.status === "ok" ? "✅" : p.status === "fail" ? "❌" : "⏳";
            return `${status} ${p.url} ${p.error ? "(" + p.error + ")" : ""}`;
          }).join("\n  ");
      const errMsg = (e && e.message) ? e.message : String(e);
      addErrorMessage(
        "无法连接 bridge 服务: " + errMsg + "\n\n" +
        "BRIDGE 探测结果：\n  " + summary + "\n\n" +
        "如果是远程访问，请：\n" +
        "  1) 油猴 → 编辑此脚本 → Values 标签\n" +
        "  2) 新增键 __bridge_remote_host__ = 你的服务器公网 IP\n" +
        "  3) 路由器 8002 端口必须转发到服务器 LAN IP:8002"
      );
    }
  }

  // ==================== ★ 0.2.15: 会话管理核心函数 ====================

  // 拉取 bridge 上所有会话，更新 state.sessionList 并渲染会话 tab
  async function loadSessionList() {
    try {
      const resp = await gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/sessions");
      state.sessionList = (resp.sessions || []).slice();
    } catch (e) {
      console.warn("[bridge] loadSessionList 失败", e);
      state.sessionList = [];
    }
    renderSessionTab();
  }

  // 切到指定会话：abort SSE → 暂存 draft → 切 ID → 加载历史 → 恢复 draft → sync mode
  async function switchToSession(newId) {
    if (!newId || newId === state.sessionId) return;

    // 1. 终止当前 SSE（避免响应串到错误会话）
    if (state.sseRequest) {
      try { state.sseRequest.abort(); } catch (_) {}
      state.sseRequest = null;
    }
    state.isSending = false;

    // 2. 暂存当前 draft 到旧会话 key
    const oldId = state.sessionId;
    if (oldId) {
      const input = shadowRoot.getElementById("dcfw-chat-input");
      if (input) {
        GM_setValue(getDraftKey(oldId), input.value || "");
      }
    }

    // 3. 切到新会话
    state.sessionId = newId;
    GM_setValue(getSessionIdKey(), newId);
    pushMRU(newId);

    // 4. 清空消息区，加载新会话历史
    clearMessages();
    await loadSessionHistory(newId);

    // 5. 恢复草稿
    const draft = GM_getValue(getDraftKey(newId), "");
    const input = shadowRoot.getElementById("dcfw-chat-input");
    if (input) {
      input.value = draft || "";
      autoResize(input);
    }

    // 6. 同步 mode + 刷新 UI
    await syncModeFromStatus();
    updateDebugInfo();
    renderSessionTab();
  }

  // 拉取指定会话的历史消息并按 role 渲染到消息区
  async function loadSessionHistory(sessionId) {
    try {
      const resp = await gmFetchJSON(
        "GET",
        CONFIG.BRIDGE_URL + "/sessions/" + sessionId + "/history"
      );
      const msgs = resp.messages || [];
      for (const m of msgs) {
        const text = m.content || "";
        if (m.role === "user") addUserMessage(text);
        else if (m.role === "assistant") addClaudeMessage(text);
        else if (m.role === "system") addSystemMessage(text);
      }
      scrollMessagesToBottom();
    } catch (e) {
      addErrorMessage("加载历史失败: " + (e && e.message ? e.message : String(e)));
    }
  }

  // 调用 bridge POST /sessions，返回新会话 ID（失败返 null）
  async function createNewSession() {
    try {
      const resp = await gmFetchJSON("POST", CONFIG.BRIDGE_URL + "/sessions", {});
      return resp.session_id || null;
    } catch (e) {
      addErrorMessage("新建会话失败: " + (e && e.message ? e.message : String(e)));
      return null;
    }
  }

  // 重命名当前活跃会话（newName 空字符串/全空白视为清空）
  async function renameActive(newName) {
    if (!state.sessionId) return;
    try {
      await gmFetch(
        "PATCH",
        CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/rename",
        {
          headers: { "Content-Type": "application/json" },
          data: JSON.stringify({ name: newName || null }),
        }
      );
      pushMRU(state.sessionId);
      await loadSessionList();
    } catch (e) {
      addErrorMessage("重命名失败: " + (e && e.message ? e.message : String(e)));
    }
  }

  // 删除指定会话。若删除的是当前活跃，先 abort SSE 再 fallback 到 MRU 下一个或 initSession
  async function deleteSession(idToDelete) {
    if (!idToDelete) return;
    try {
      await gmFetch("DELETE", CONFIG.BRIDGE_URL + "/sessions/" + idToDelete);
    } catch (e) {
      addErrorMessage("删除失败: " + (e && e.message ? e.message : String(e)));
      return;
    }
    // 清理 draft
    GM_setValue(getDraftKey(idToDelete), "");
    // 清理 MRU
    state.sessionMRU = state.sessionMRU.filter((s) => s.id !== idToDelete);
    GM_setValue(getSessionMRUKey(), state.sessionMRU);

    // 若删的是当前活跃，abort SSE 并 fallback
    if (state.sessionId === idToDelete) {
      if (state.sseRequest) {
        try { state.sseRequest.abort(); } catch (_) {}
        state.sseRequest = null;
      }
      state.isSending = false;
      state.sessionId = null;
      GM_setValue(getSessionIdKey(), null);
      clearMessages();
      const fallback = state.sessionMRU.length > 0 ? state.sessionMRU[0].id : null;
      if (fallback) {
        await switchToSession(fallback);
      } else {
        await initSession();
      }
    }
    await loadSessionList();
  }

  // 把指定会话推到 MRU 顶部（去重 + cap）
  function pushMRU(sessionId) {
    if (!sessionId) return;
    const info =
      state.sessionList.find((s) => s.id === sessionId) ||
      state.sessionMRU.find((s) => s.id === sessionId) ||
      { id: sessionId, name: null, first_message_preview: null, last_active_at: null };
    const entry = {
      id: sessionId,
      name: info.name || null,
      preview: info.first_message_preview || null,
      last_active_at: info.last_active_at || new Date().toISOString(),
    };
    state.sessionMRU = [
      entry,
      ...state.sessionMRU.filter((s) => s.id !== sessionId),
    ].slice(0, CONFIG.SESSION_MRU_CAP);
    GM_setValue(getSessionMRUKey(), state.sessionMRU);
  }

  // 渲染会话 tab 内容（list + 新建按钮在 PANEL_HTML 里）
  function renderSessionTab() {
    const container = shadowRoot.getElementById("dcfw-session-list");
    if (!container) return;
    const list = state.sessionList;
    if (!list || list.length === 0) {
      container.innerHTML = '<div class="dcfw-empty">还没有活跃会话。点下方「+ 新建会话」。</div>';
      return;
    }
    // 当前活跃置顶；其他按 last_active_at 倒序
    const sorted = list.slice().sort((a, b) => {
      if (a.id === state.sessionId) return -1;
      if (b.id === state.sessionId) return 1;
      return (b.last_active_at || "").localeCompare(a.last_active_at || "");
    });
    container.innerHTML = sorted.map((s) => {
      const isActive = s.id === state.sessionId;
      const labelText = s.name
        ? s.name
        : (s.first_message_preview
            ? s.first_message_preview
            : "会话-" + s.id.slice(0, 6));
      const label = escapeHtml(labelText);
      const meta =
        (s.mode || "?") + " · " +
        (s.message_count || 0) + " 条 · " +
        formatRelativeTime(s.last_active_at);
      return (
        '<div class="dcfw-session-row' + (isActive ? " active" : "") + '" data-id="' + escapeHtml(s.id) + '">' +
          '<div class="dcfw-session-info">' +
            '<div class="dcfw-session-name">' + label + (isActive ? ' <span class="dcfw-active-tag">← 当前</span>' : '') + '</div>' +
            '<div class="dcfw-session-meta">' + escapeHtml(meta) + '</div>' +
          '</div>' +
          '<div class="dcfw-session-buttons">' +
            '<button class="dcfw-session-rename" data-id="' + escapeHtml(s.id) + '" title="重命名">✎</button>' +
            '<button class="dcfw-session-delete" data-id="' + escapeHtml(s.id) + '" title="删除">🗑</button>' +
          '</div>' +
        '</div>'
      );
    }).join("");
  }

  // 相对时间格式化（给 session list meta 用）
  function formatRelativeTime(iso) {
    if (!iso) return "—";
    try {
      const ts = new Date(iso).getTime();
      if (isNaN(ts)) return iso;
      const diff = Date.now() - ts;
      if (diff < 60000) return "刚刚";
      if (diff < 3600000) return Math.floor(diff / 60000) + " 分钟前";
      if (diff < 86400000) return Math.floor(diff / 3600000) + " 小时前";
      return new Date(iso).toLocaleDateString("zh-CN");
    } catch (_) {
      return iso;
    }
  }

  // ★ 0.2.7: 从 /sessions/{id}/status 拉取 mode，写回 state + UI
  // status 端点不阻塞主路径（失败时保持 currentMode 默认 bypass）
  async function syncModeFromStatus() {
    if (!state.sessionId) return;
    try {
      const st = await gmFetchJSON(
        "GET",
        CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/status"
      );
      if (st && st.mode) {
        state.currentMode = st.mode;
        refreshModeBadge();
      }
    } catch (e) {
      // 静默忽略（status 失败不应阻塞会话恢复）
      console.warn("[bridge] sync mode 失败", e);
    }
  }

  // ★ 0.2.7: Claude 模式映射
  const MODE_LABELS = {
    bypass: "⚡ AUTO",
    plan: "📋 PLAN",
    acceptEdits: "✏️ EDIT",
    default: "🔒 SAFE",
  };

  // ★ 0.2.9: 视口 clamp（防止面板/FAB 被拖出屏幕）
  // 返回 (x, y)，保证矩形 [x, x+w] × [y, y+h] 至少有 minVis px 在视口内
  // top 允许负值（最多 -40px）：常见 UX，让 titlebar 刚好"贴"在视口上沿
  function clampToViewport(x, y, w, h, minVis) {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const minX = -(w - minVis);   // 左边最多出 (w - minVis) px
    const maxX = vw - minVis;     // 右边至少保留 minVis px
    const minY = -40;             // 顶部允许 -40px
    const maxY = vh - minVis;     // 底部至少保留 minVis px
    return {
      x: Math.max(minX, Math.min(x, maxX)),
      y: Math.max(minY, Math.min(y, maxY)),
    };
  }

  // ★ 0.2.9: 检测面板是否完全在视口外（任何边超出视口就算离屏）
  // ★ 0.2.10: 同时检查 FAB（host 离屏 FAB 也跟着飞，panel 跟着 host 也飞）
  function isPanelFullyOffscreen() {
    try {
      const fab = shadowRoot.getElementById("dcfw-fab");
      if (fab) {
        const fr = fab.getBoundingClientRect();
        if (fr.right < 0 || fr.bottom < 0 || fr.left > window.innerWidth || fr.top > window.innerHeight) {
          return true;
        }
      }
      const r = shadowRoot.getElementById("dcfw-panel").getBoundingClientRect();
      return r.right < 0 || r.bottom < 0 || r.left > window.innerWidth || r.top > window.innerHeight;
    } catch (_) {
      return false;
    }
  }

  // ★ 0.2.9: 重置面板到默认右下角位置（CSS 默认是 bottom:72px right:0）
  // ★ 0.2.10: 同步重置 host（panel 是 host-relative 锚定，只重置 panel 没用）
  // ★ 0.2.14: 0.2.13 之前的版本 panel.style.left/top 可能存了错误的 viewport 坐标，
  //   必须显式清掉让 CSS 锚定（right:0; bottom:72px）重新生效。
  function resetPanelPosition() {
    const panel = shadowRoot.getElementById("dcfw-panel");
    if (!panel) return;
    // ★ 0.2.10: 先把 host 拉回默认（CSS: bottom:24px right:24px）
    if (hostEl) {
      hostEl.style.left = "auto";
      hostEl.style.top = "auto";
      hostEl.style.right = "24px";
      hostEl.style.bottom = "24px";
    }
    // panel 自身重置（host-relative 锚定）
    panel.style.left = "";
    panel.style.top = "";
    panel.style.right = "";
    panel.style.bottom = "";
    // ★ 0.2.14: CSS 里 default 是 right:0; bottom:72px，重置后这些会自然生效。
    //   显式重新写一次兼容老浏览器（Firefox inline style 优先级覆盖 CSS）
    panel.style.right = "0";
    panel.style.bottom = "72px";
  }

  // ★ 0.2.7: 切换 Claude 模式（调桥接 /sessions/{id}/mode，会重启子进程）
  async function setMode(newMode) {
    if (newMode === state.currentMode) return;
    if (!state.sessionId) {
      addErrorMessage("会话未就绪，无法切换模式");
      return;
    }
    const badge = shadowRoot.getElementById("dcfw-mode-badge");
    if (badge) {
      badge.classList.add("switching");
      badge.textContent = "切换中...";
    }
    try {
      const resp = await gmFetchJSON(
        "POST",
        CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/mode",
        { mode: newMode }
      );
      // ★ 0.2.16: 防御性 — 只有 resp.mode 是已知 mode 才写 state。否则 bridge
      // 返回 undefined 时会让 badge 渲染 "undefined" 并丢 CSS class。
      if (resp && MODE_LABELS[resp.mode]) {
        state.currentMode = resp.mode;
      } else {
        console.warn("[bridge] setMode 响应缺少/无效 mode，从 /status 复核:", resp);
      }
      // ★ 0.2.16: 无条件从 bridge 复核（authoritative）。覆盖 (a) 模式未在 resp，
      // (b) 用户在 proc 重启期间又切了一次。
      await syncModeFromStatus();
      const shown = MODE_LABELS[state.currentMode] || state.currentMode;
      addSystemMessage(`✅ 已切换到 ${shown}（Claude 子进程已重启）`);
    } catch (e) {
      addErrorMessage("切换模式失败: " + (e && e.message ? e.message : String(e)));
      // ★ 0.2.8: 失败时刷新徽章（保持旧 mode 显示）
      refreshModeBadge();
    } finally {
      if (badge) badge.classList.remove("switching");
    }
  }

  // ★ 0.2.7/0.2.8: 刷新徽章颜色 + 标签 + popover current 标记
  function refreshModeBadge() {
    try {
      const badge = shadowRoot.getElementById("dcfw-mode-badge");
      if (!badge) return;
      badge.textContent = MODE_LABELS[state.currentMode] || state.currentMode;
      badge.className = "dcfw-mode-badge mode-" + state.currentMode;
      // ★ 0.2.8: 同步更新 popover 内 current 标记
      const popover = shadowRoot.getElementById("dcfw-mode-popover");
      if (popover) {
        popover.querySelectorAll(".dcfw-mode-popover-item").forEach((it) => {
          it.classList.toggle("current", it.dataset.mode === state.currentMode);
        });
      }
    } catch (e) {
      console.warn("[bridge] refreshModeBadge 失败", e);
    }
  }

  // ★ 0.2.8: 切换模式 popover 显示状态 + 自动绑定外部 click 关闭
  // ★ 0.2.10: 模块级引用 _popoverDocClickHandler，避免 setTimeout 内 onDocClick 闭包
  //   每次新建后没被外部点击清理会泄漏（旧实现：开→关→开→关... → N 个监听器）
  let _popoverDocClickHandler = null;
  let _userPopoverDocClickHandler = null;   // ★ 0.3.4: display_name popover 同理
  function toggleModePopover(show) {
    const pop = shadowRoot.getElementById("dcfw-mode-popover");
    if (!pop) return;
    const shouldShow = show ?? (pop.style.display === "none");
    pop.style.display = shouldShow ? "block" : "none";
    if (shouldShow) {
      // 打开时同步 current 标记
      pop.querySelectorAll(".dcfw-mode-popover-item").forEach((it) => {
        it.classList.toggle("current", it.dataset.mode === state.currentMode);
      });
      // ★ 0.2.10: 先清理上次的监听器（开→关→开 时防止重复 add）
      if (_popoverDocClickHandler) {
        document.removeEventListener("mousedown", _popoverDocClickHandler, true);
        _popoverDocClickHandler = null;
      }
      // 用 capture 阶段 + composedPath 判定（shadow 内部事件 retarget 到 host，要用 composedPath 拿真实 target）
      // 用 mousedown 比 click 更早，避开 Dify 自己的 click 拦截
      setTimeout(() => {
        _popoverDocClickHandler = (e) => {
          const tgt = e.composedPath ? e.composedPath()[0] : e.target;
          // 命中 badge 或 popover 内部 → 不关
          if (tgt && tgt.closest && tgt.closest("#dcfw-mode-badge, .dcfw-mode-popover")) return;
          toggleModePopover(false);
          if (_popoverDocClickHandler) {
            document.removeEventListener("mousedown", _popoverDocClickHandler, true);
            _popoverDocClickHandler = null;
          }
        };
        document.addEventListener("mousedown", _popoverDocClickHandler, true);
      }, 0);
    } else {
      // ★ 0.2.10: 显式关闭时也清理监听器（点自身 badge 关闭的场景）
      if (_popoverDocClickHandler) {
        document.removeEventListener("mousedown", _popoverDocClickHandler, true);
        _popoverDocClickHandler = null;
      }
    }
  }


  async function sendMessage() {
    const input = shadowRoot.getElementById("dcfw-chat-input");
    const text = input.value.trim();
    if (!text) return;
    if (!state.sessionId) {
      addErrorMessage("会话未就绪，请稍候");
      return;
    }

    input.value = "";
    autoResize(input);
    shadowRoot.getElementById("dcfw-cmd-palette").style.display = "none";

    // ★ 0.2.6: 新一轮发送前清空 SSE / rAF 缓冲
    resetStreamBuffers();
    addUserMessage(text);

    // 判断指令类型
    if (text.startsWith("/")) {
      const cmdWord = text.split(/\s/)[0];
      const cmdDef = findCommand(cmdWord);
      if (cmdDef) {
        if (cmdDef.type === "disabled") {
          addSystemMessage("指令 " + cmdWord + " 仅在交互式终端可用，headless 模式不支持。");
          return;
        }
        if (cmdDef.type === "local") {
          await handleLocalCommand(text);
          return;
        }
        // claude-native 走正常发送流程
      }
    }

    // 发送给 Claude
    setSending(true);
    try {
      // ★ 0.2.16: 发送前刷新页面上下文，避免 stale
      capturePageContext();
      const payload = { content: text };
      if (state.activePageContext && state.activePageContext.url) {
        payload.page_context = state.activePageContext;
      }
      const resp = await gmFetchJSON(
        "POST",
        CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/messages",
        payload
      );
      if (resp.accepted && !resp.local_command) {
        // 启动事件监听（0.2.22: HTTP 轮询替代 SSE，remote 场景更稳）
        connectPolling();
      } else if (resp.local_command) {
        // 本地指令结果
        addClaudeMessage(resp.message || "(无输出)");
        setSending(false);
      } else {
        addErrorMessage(resp.message || "发送失败");
        setSending(false);
      }
    } catch (e) {
      addErrorMessage("发送失败: " + (e && e.message ? e.message : String(e)));
      setSending(false);
    }
  }

  function findCommand(cmdWord) {
    for (const group of SLASH_COMMANDS) {
      for (const it of group.items) {
        if (it.cmd === cmdWord) return it;
      }
    }
    return null;
  }

  async function handleLocalCommand(text) {
    const cmdWord = text.split(/\s/)[0];
    setSending(true);
    try {
      if (cmdWord === "/reset") {
        const resp = await gmFetchJSON(
          "POST",
          CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/reset"
        );
        state.sessionId = resp.session_id;
        GM_setValue(getSessionIdKey(), state.sessionId);
        clearMessages();
        addSystemMessage("会话已重置，新 session_id: " + state.sessionId.slice(0, 8) + "...");
      } else if (cmdWord === "/export") {
        const resp = await gmFetchJSON(
          "GET",
          CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/export?format=md"
        );
        downloadText("claude-session.md", resp.content);
        addSystemMessage("会话已导出为 claude-session.md");
      } else {
        // /history /list-sessions /switch /dify-help 走 messages 端点
        const resp = await gmFetchJSON(
          "POST",
          CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/messages",
          { content: text }
        );
        if (resp.local_command && resp.message) {
          addClaudeMessage(resp.message);
        } else {
          addErrorMessage(resp.message || "指令执行失败");
        }
      }
    } catch (e) {
      addErrorMessage("本地指令失败: " + (e && e.message ? e.message : String(e)));
    }
    setSending(false);
  }

  function downloadText(filename, content) {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ==================== SSE 客户端 ====================

  function connectSSE() {
    if (state.sseRequest) {
      // 已有连接，复用
      console.log("[Dify Bridge] connectSSE skipped, already connected");
      return;
    }
    state.sseLastIndex = 0;
    state.currentAssistantBubble = null;
    state.sseOnprogressCount = 0;
    updateDebugInfo();

    const sseUrl = CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/events";
    console.log("[Dify Bridge] opening SSE →", sseUrl);

    state.sseRequest = GM_xmlhttpRequest({
      method: "GET",
      url: sseUrl,
      headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
      timeout: CONFIG.SSE_TIMEOUT_MS,
      onprogress: function (response) {
        state.sseOnprogressCount++;
        const fullText = response.responseText || "";
        const chunk = fullText.slice(state.sseLastIndex);
        state.sseLastIndex = fullText.length;
        if (state.sseOnprogressCount === 1) {
          console.log("[Dify Bridge] SSE onprogress #1, responseText.length=" + fullText.length);
        }
        parseSSEChunk(chunk);
      },
      onerror: function (err) {
        console.log("[Dify Bridge] SSE onerror:", JSON.stringify(err), "onprogress#=", state.sseOnprogressCount);
        state.sseRequest = null;
        resetStreamBuffers();
        setSending(false);
        updateDebugInfo();
        if (err && err.error && err.error.includes("aborted")) {
          // 主动取消，忽略
        } else {
          addErrorMessage("SSE 连接错误: " + (err.error || JSON.stringify(err)));
        }
      },
      ontimeout: function () {
        console.log("[Dify Bridge] SSE ontimeout, onprogress#=", state.sseOnprogressCount);
        state.sseRequest = null;
        resetStreamBuffers();
        setSending(false);
        updateDebugInfo();
        addErrorMessage("SSE 超时");
      },
      onload: function (response) {
        const fullText = response.responseText || "";
        console.log("[Dify Bridge] SSE onload, status=" + (response.status || "?") +
                    ", onprogress#=" + state.sseOnprogressCount +
                    ", responseText.length=" + fullText.length +
                    ", sseLastIndex=" + state.sseLastIndex);
        // 兜底：用 sseLastIndex 计算剩余未解析部分（覆盖 onprogress 拿到空 responseText 的情况）
        const remaining = fullText.slice(state.sseLastIndex);
        if (remaining) {
          console.log("[Dify Bridge] 兜底解析剩余 " + remaining.length + " 字节");
          parseSSEChunk(remaining);
        } else if (state.sseOnprogressCount > 0) {
          console.log("[Dify Bridge] onprogress 已处理完所有数据，无需兜底");
        } else {
          console.warn("[Dify Bridge] 完整响应为空！");
        }
        state.sseRequest = null;
        resetStreamBuffers();
        setSending(false);
        updateDebugInfo();
      },
    });
  }

  // ★ 0.2.22: HTTP 轮询订阅（替代 SSE 解决远程场景实时事件丢失）
  // 复用所有 handleSSEEvent / flushDeltas / 气泡渲染逻辑，仅改变"事件来源"
  function connectPolling() {
    if (state.pollingActive || state.sseRequest) {
      console.log("[Dify Bridge] connectPolling skipped, already listening");
      return;
    }
    state.sseLastIndex = 0;
    state.sseLastEventId = 0;
    state.currentAssistantBubble = null;
    state.sseOnprogressCount = 0;
    state.pollingActive = true;
    // 给 abort() 兼容，保持 state.sseRequest 形态（所有 abort 代码继续工作）
    state.sseRequest = {
      type: "polling",
      abort() {
        console.log("[Dify Bridge] polling abort requested");
        state.pollingActive = false;
      },
    };
    updateDebugInfo();
    console.log("[Dify Bridge] starting event polling →", CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/events/poll");
    pollOnce();
  }

  async function pollOnce() {
    if (!state.pollingActive) {
      console.log("[Dify Bridge] poll stopped");
      return;
    }
    if (!state.sessionId) {
      state.pollingActive = false;
      return;
    }
    const url = CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId +
                "/events/poll?since=" + state.sseLastEventId + "&max_wait=1.0";
    state.sseOnprogressCount++;
    try {
      const resp = await gmFetchJSON("GET", url);
      const events = (resp && resp.events) || [];
      if (events.length > 0) {
        console.log("[Dify Bridge] polled", events.length, "events, last=" + resp.last_event_id);
        for (const evt of events) {
          handleSSEEvent(evt);
          // 推进 since：每个事件自带 event_id
          if (typeof evt.event_id === "number" && evt.event_id > state.sseLastEventId) {
            state.sseLastEventId = evt.event_id;
          }
        }
        // 兜底：用响应 last_event_id 强推一次
        if (typeof resp.last_event_id === "number" && resp.last_event_id > state.sseLastEventId) {
          state.sseLastEventId = resp.last_event_id;
        }
      }
    } catch (e) {
      console.warn("[Dify Bridge] poll error:", (e && e.message) || e);
      // 静默继续，下一轮重试（网络抖动很常见）
    }
    // 立即再 poll（busy-loop），pollingActive=false 时退出
    if (state.pollingActive) {
      setTimeout(pollOnce, 50);  // 50ms 间隔，密集时接近 SSE 体验
    }
  }

  function parseSSEChunk(chunk) {
    if (!chunk) return;
    // ★ 0.2.6: 用模块级 sseBuffer 缓冲不完整事件
    state.sseBuffer += chunk.replace(/\r\n/g, "\n");
    const lastBoundary = state.sseBuffer.lastIndexOf("\n\n");
    if (lastBoundary === -1) return;
    const complete = state.sseBuffer.slice(0, lastBoundary);
    state.sseBuffer = state.sseBuffer.slice(lastBoundary + 2);
    const events = complete.split("\n\n");
    let parsedCount = 0;
    for (const evt of events) {
      const lines = evt.split("\n");
      let dataLine = "";
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          dataLine = line.slice(6);
        }
      }
      if (!dataLine) continue;
      let data;
      try {
        data = JSON.parse(dataLine);
      } catch (e) {
        console.warn("[Dify Bridge] SSE parse error:", e, "raw:", dataLine.slice(0, 200));
        continue;
      }
      parsedCount++;
      logSSEEvent(data);
      handleSSEEvent(data);
    }
    if (parsedCount > 0) {
      console.log("[Dify Bridge] parsed", parsedCount, "events, buf残余=" + state.sseBuffer.length);
    }
  }

  // ★ 0.2.6: rAF 合并渲染（避免每个 delta 都触发 reflow）
  function scheduleFlush() {
    if (state.pendingFlush !== null) return;
    state.pendingFlush = requestAnimationFrame(flushDeltas);
  }

  function flushDeltas() {
    state.pendingFlush = null;
    // ★ 0.2.16: 迭代单有序队列，按到达顺序分发到 text / thinking 渲染
    if (!state.pendingDeltaQueue || state.pendingDeltaQueue.length === 0) return;
    let needsScroll = false;
    for (const entry of state.pendingDeltaQueue) {
      if (entry.type === "text") {
        if (!state.currentAssistantBubble) {
          state.currentAssistantBubble = addClaudeMessage("");
        }
        const bubble = state.currentAssistantBubble;
        const tail = bubble.lastChild;
        if (tail && tail.nodeType === 3 /* TEXT_NODE */) {
          tail.data += entry.text;
        } else {
          bubble.appendChild(document.createTextNode(entry.text));
        }
        needsScroll = true;
      } else if (entry.type === "thinking") {
        appendThinking(entry.text);
        needsScroll = true;
      }
    }
    state.pendingDeltaQueue = [];
    if (needsScroll) scrollMessagesToBottom();
    // producer 可能在 flush 期间继续 push——下一帧 rAF 会重新调度（scheduleFlush 自带去重）
    if (state.pendingDeltaQueue.length > 0) {
      state.pendingFlush = requestAnimationFrame(flushDeltas);
    }
  }

  // ★ 0.2.6: 新一轮对话开始前清空所有 SSE 缓冲
  // ★ 0.2.16: 改为清空单一有序队列
  function resetStreamBuffers() {
    state.sseBuffer = "";
    state.pendingDeltaQueue = [];
    if (state.pendingFlush !== null) {
      cancelAnimationFrame(state.pendingFlush);
      state.pendingFlush = null;
    }
  }

  function handleSSEEvent(data) {
    switch (data.type) {
      case "text_delta":
        // ★ 0.2.16: push 到有序队列（不再按类型 concat 到独立 buffer）
        state.pendingDeltaQueue.push({ type: "text", text: data.text || "" });
        scheduleFlush();
        break;

      case "thinking_delta":
        state.pendingDeltaQueue.push({ type: "thinking", text: data.text || "" });
        scheduleFlush();
        break;

      case "tool_call":
        appendToolCall(data.tool || "unknown", data.input);
        scrollMessagesToBottom();
        break;

      case "tool_result":
        appendToolResult(data.tool_use_id, data.content);
        scrollMessagesToBottom();
        break;

      case "assistant_complete":
        // 完整 assistant 消息：先关掉当前 thinking 块（0.2.16），再清 bubble 引用
        finalizeThinkingBlock();
        state.currentAssistantBubble = null;
        break;

      case "result":
        // 一次输入处理完成
        finalizeThinkingBlock();              // ★ 0.2.16
        state.currentAssistantBubble = null;
        flushDeltas();
        resetStreamBuffers();
        setSending(false);
        if (data.is_error) {
          addErrorMessage("Claude 返回错误: " + (data.result || "").slice(0, 200));
        }
        // ★ 0.2.16: 不再在 terminal 事件清 state.sseRequest。SSE listener 概念上是
        // "idle but ready"，清空导致 updateDebugInfo 永久显示 "未连接"。sseRequest
        // 现在只在显式 abort / onerror / ontimeout / deleteSession 等场景清。
        break;

      case "error":
        addErrorMessage("Bridge 错误: " + (data.message || ""));
        setSending(false);
        // ★ 0.2.16: 不要再 abort / 清 sseRequest。listener 概念上仍 "idle but ready"，
        // 下一次 sendMessage 会复用。abort/null 会让 debug 面板永久显示"未连接"。
        break;

      case "session_closed":
        // 会话已死，必须 abort + 清 listener + 清 sessionId
        addSystemMessage("会话已关闭: " + (data.message || ""));
        setSending(false);
        if (state.sseRequest) {
          try { state.sseRequest.abort(); } catch (e) {}
          state.sseRequest = null;
        }
        state.sessionId = null;
        GM_setValue(getSessionIdKey(), null);
        updateStatus("已断开");
        break;

      case "heartbeat":
        // 忽略心跳
        break;

      case "system":
      case "raw":
      case "unknown":
        // 低优先级事件，不渲染
        break;
    }
  }

  // ==================== 调试面板 ====================

  const DEBUG_MAX_ROWS = 80;
  const debugState = {
    eventCount: 0,
    textDeltaCount: 0,
    thinkingDeltaCount: 0,
    resultCount: 0,
    errorCount: 0,
    lastEventType: null,
    lastEventTime: null,
  };

  function logSSEEvent(data) {
    if (!shadowRoot) {
      console.warn("[Dify Bridge] logSSEEvent called but shadowRoot is null!");
      return;
    }
    debugState.eventCount++;
    debugState.lastEventType = data.type || "?";
    debugState.lastEventTime = new Date();
    const type = data.type || "?";
    if (type === "text_delta") debugState.textDeltaCount++;
    else if (type === "thinking_delta") debugState.thinkingDeltaCount++;
    else if (type === "result") debugState.resultCount++;
    else if (type === "error") debugState.errorCount++;

    // 更新顶部统计
    const stats = shadowRoot.getElementById("dcfw-debug-stats");
    if (stats) {
      stats.textContent =
        debugState.eventCount + " ev · " +
        "T:" + debugState.textDeltaCount +
        " K:" + debugState.thinkingDeltaCount +
        " R:" + debugState.resultCount +
        " E:" + debugState.errorCount;
    }

    // 标题栏状态栏实时反映最后事件类型（让用户即使没展开调试面板也能看到）
    // ★ 0.2.12: 文字标签改成图标（title 属性保留可读性）
    const statusEl = shadowRoot.getElementById("dcfw-status");
    if (statusEl && state.isSending) {
      const icon = type === "thinking_delta" ? "💭" :
                   type === "text_delta" ? "▍" :
                   type === "tool_call" ? "🔧" :
                   type === "tool_result" ? "📦" :
                   type === "result" ? "✓" :
                   type === "error" ? "⚠" :
                   "…";
      const label = type === "thinking_delta" ? "思考中" :
                    type === "text_delta" ? "回复中" :
                    type === "tool_call" ? "调用工具" :
                    type === "tool_result" ? "工具返回" :
                    type === "result" ? "完成" :
                    type === "error" ? "出错" :
                    "处理中";
      statusEl.textContent = icon;
      statusEl.title = label + " · " + debugState.eventCount + "ev";
    }

    // 追加一行
    const eventsEl = shadowRoot.getElementById("dcfw-debug-events");
    if (!eventsEl) return;
    const row = document.createElement("div");
    row.className = "dcfw-debug-row";
    const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    let text = "";
    if (type === "text_delta" || type === "thinking_delta") {
      text = (data.text || "").slice(0, 80);
    } else if (type === "tool_call") {
      text = (data.tool || "?") + "(" + JSON.stringify(data.input || {}).slice(0, 50) + ")";
    } else if (type === "tool_result") {
      text = JSON.stringify(data.content || "").slice(0, 80);
    } else if (type === "result") {
      text = "is_error=" + data.is_error + " · duration=" + (data.duration_ms || "?") + "ms";
    } else if (type === "error") {
      text = data.message || "";
    } else {
      text = JSON.stringify(data).slice(0, 80);
    }
    row.innerHTML =
      '<span class="dcfw-debug-time">' + time + '</span>' +
      '<span class="dcfw-debug-type ' + type + '">' + type + '</span>' +
      '<span class="dcfw-debug-text">' + escapeHtml(text) + '</span>';
    eventsEl.appendChild(row);

    // 控制行数
    while (eventsEl.childElementCount > DEBUG_MAX_ROWS) {
      eventsEl.removeChild(eventsEl.firstChild);
    }
    // 自动滚动到底
    eventsEl.scrollTop = eventsEl.scrollHeight;
  }

  function updateDebugInfo() {
    if (!shadowRoot) return;
    const bridgeEl = shadowRoot.getElementById("dcfw-debug-bridge");
    const sessionEl = shadowRoot.getElementById("dcfw-debug-session");
    const sseEl = shadowRoot.getElementById("dcfw-debug-sse");
    const pageEl = shadowRoot.getElementById("dcfw-debug-page");
    if (bridgeEl) bridgeEl.textContent = CONFIG.BRIDGE_URL;
    if (sessionEl) sessionEl.textContent = state.sessionId
      ? state.sessionId.slice(0, 8) + "..."
      : "—";
    // ★ 0.2.16: SSE 状态拆双态 — listener 挂载态 + 当前是否流式
    if (sseEl) {
      const listening = state.sseRequest ? "● 已挂载" : "○ 空闲";
      const streaming = state.isSending ? "▍ 流式中" : "等待下一条";
      sseEl.textContent = listening + " · " + streaming;
      sseEl.title =
        "Listener=" + (state.sseRequest ? "attached" : "idle") +
        ", Stream=" + (state.isSending ? "active" : "waiting");
    }
    if (pageEl) pageEl.textContent = window.location.href;
  }

  // 更新标题栏右侧 bridge 徽章（始终可见，三态：探测中/已连接/失败）
  function updateBridgeBadge() {
    if (!shadowRoot) return;
    const badge = shadowRoot.getElementById("dcfw-bridge-badge");
    const text = shadowRoot.getElementById("dcfw-bridge-badge-text");
    const dot = badge && badge.querySelector(".dcfw-bridge-dot");
    if (!badge || !text || !dot) return;

    const probes = state.bridgeProbes;
    const allDone = probes.length > 0 && probes.every((p) => p.status !== "pending");
    const chosen = probes.find((p) => p.status === "ok");

    badge.classList.remove("probing", "connected", "failed");

    if (chosen) {
      badge.classList.add("connected");
      dot.classList.remove("pulse");
      const short = chosen.url.replace(/^https?:\/\//, "");
      text.textContent = short;
      badge.title =
        `✅ Bridge 已连接：${chosen.url}\n` +
        `延迟 ${chosen.latencyMs}ms\n` +
        `展开调试面板看完整探测结果`;
    } else if (allDone) {
      badge.classList.add("failed");
      dot.classList.remove("pulse");
      const failedCount = probes.filter((p) => p.status === "fail").length;
      text.textContent = `未连接 ${failedCount}/${probes.length}`;
      badge.title =
        `❌ 所有候选地址都无法访问 bridge\n` +
        `展开调试面板查看每个地址的失败原因\n` +
        `可点调试面板里的「复制诊断」按钮把信息发给同事`;
    } else {
      badge.classList.add("probing");
      dot.classList.add("pulse");
      const pendingCount = probes.filter((p) => p.status === "pending").length;
      const okCount = probes.filter((p) => p.status === "ok").length;
      const total = probes.length;
      text.textContent = `探测中 ${okCount + (total - pendingCount - okCount)}/${total}`;
      badge.title = "正在按 BRIDGE_CANDIDATES 顺序探测 bridge 地址";
    }
  }

  // 渲染调试面板里的探测结果列表（含复制诊断功能）
  function renderProbeResults() {
    if (!shadowRoot) return;
    const container = shadowRoot.getElementById("dcfw-debug-probes");
    if (!container) return;

    const probes = state.bridgeProbes;
    if (probes.length === 0) {
      container.innerHTML =
        '<div class="dcfw-debug-probes-head"><strong>Bridge 探测结果</strong>' +
        '<button class="dcfw-debug-copy" id="dcfw-debug-copy">复制诊断</button></div>' +
        '<div style="color:#6b7280;">等待探测...</div>';
      return;
    }

    const rows = probes
      .map((p) => {
        const icon = p.status === "ok" ? "✅" : p.status === "fail" ? "❌" : "⏳";
        let meta = "";
        if (p.status === "ok") {
          meta = `<span class="dcfw-debug-probe-meta">${p.latencyMs}ms</span>`;
        } else if (p.status === "fail") {
          meta = `<span class="dcfw-debug-probe-meta">${escapeHtml(p.error || "fail")}</span>`;
        }
        const isChosen = p.url === CONFIG.BRIDGE_URL && p.status === "ok";
        const cls = `dcfw-debug-probe-row ${p.status}${isChosen ? " chosen" : ""}`;
        return (
          `<div class="${cls}">` +
          `<span class="dcfw-debug-probe-icon">${icon}</span>` +
          `<span class="dcfw-debug-probe-url">${escapeHtml(p.url)}</span>` +
          meta +
          (isChosen ? ' <span class="dcfw-debug-probe-current">← 当前</span>' : "") +
          `</div>`
        );
      })
      .join("");

    container.innerHTML =
      `<div class="dcfw-debug-probes-head">` +
      `<strong>Bridge 探测结果</strong>` +
      `<button class="dcfw-debug-copy" id="dcfw-debug-copy">复制诊断</button>` +
      `</div>${rows}`;
  }

  // 把诊断信息格式化成文本（可粘贴到 IM/邮件）
  function buildDiagnosticText() {
    const lines = [];
    lines.push("【Dify Claude Floating Window 诊断信息】");
    lines.push(`时间：${new Date().toISOString()}`);
    lines.push(`用户代理：${navigator.userAgent}`);
    lines.push(`当前页面：${window.location.href}`);
    lines.push(`当前 BRIDGE_URL：${CONFIG.BRIDGE_URL}`);
    lines.push(`@match 是否匹配：${"（已注入说明匹配成功）"}`);
    lines.push("");
    lines.push("【BRIDGE_CANDIDATES 探测结果】");
    if (state.bridgeProbes.length === 0) {
      lines.push("  (尚未开始探测)");
    } else {
      for (const p of state.bridgeProbes) {
        const status =
          p.status === "ok"
            ? `✅ OK (${p.latencyMs}ms)`
            : p.status === "fail"
            ? `❌ FAIL — ${p.error}`
            : "⏳ PENDING";
        const marker = p.url === CONFIG.BRIDGE_URL && p.status === "ok" ? " ← 当前选用" : "";
        lines.push(`  ${status}  ${p.url}${marker}`);
      }
    }
    lines.push("");
    lines.push("【建议】");
    const probes = state.bridgeProbes;
    const okCount = probes.filter((p) => p.status === "ok").length;
    const failCount = probes.filter((p) => p.status === "fail").length;
    const pendingCount = probes.filter((p) => p.status === "pending").length;
    if (probes.length === 0) {
      lines.push("  ⚠️ 探测尚未开始（脚本可能没正确加载，或 state 在 detectBridge 调用前未初始化）");
      lines.push("  请强制刷新页面（Ctrl+Shift+R），或重新安装脚本");
    } else if (pendingCount > 0) {
      lines.push(`  ⏳ 探测进行中（已完成 ${okCount + failCount}/${probes.length}），请稍候再点「复制诊断」`);
    } else if (failCount === probes.length) {
      lines.push("  所有候选地址都失败。常见原因：");
      lines.push("  - 公司/网络防火墙封锁 8002 端口");
      lines.push("  - 路由器未配置公网 8002 → 192.168.x.x:8002 端口转发");
      lines.push("  - 不在办公室 LAN 内（192.168.3.x）且无法访问公网 IP");
      lines.push("  - Bridge 服务未启动（检查 ssh server 'systemctl status dify-bridge'）");
    } else if (okCount > 0) {
      lines.push(`  ✅ Bridge 已连接（${okCount} 个候选可用，当前选用 ${CONFIG.BRIDGE_URL}）`);
      if (failCount > 0) {
        lines.push(`  ⚠️ 还有 ${failCount} 个候选不可用（如不在办公室 LAN 可能正常）`);
      }
    } else {
      lines.push("  状态未知，请刷新页面重试");
    }

    // ★ 0.2.5: console 捕获输出（最近 50 条，避免诊断文本过长）
    const cap = state.consoleCapture;
    if (cap.buffer.length > 0) {
      lines.push("");
      lines.push(`【CONSOLE 捕获】（共 ${cap.buffer.length} 条，已启用=${cap.enabled}，最多 ${cap.maxSize} 条）`);
      const recent = cap.buffer.slice(-50);
      for (const e of recent) {
        const t = new Date(e.t).toISOString();
        const lvl = (e.level || "log").toUpperCase();
        const msg = (e.args || []).map(_safeStringify).join(" ");
        lines.push(`  [${t}] ${lvl}: ${msg}`);
      }
    } else {
      lines.push("");
      lines.push(`【CONSOLE 捕获】（已启用=${cap.enabled}，0 条）`);
    }

    return lines.join("\n");
  }

  async function copyDiagnostic() {
    const btn = shadowRoot && shadowRoot.getElementById("dcfw-debug-copy");
    const text = buildDiagnosticText();
    try {
      // 优先用 clipboard API（在 HTTPS / file:// 下）
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        // fallback：临时 textarea + execCommand
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      if (btn) {
        const old = btn.textContent;
        btn.textContent = "✓ 已复制";
        btn.classList.add("copied");
        setTimeout(() => {
          btn.textContent = old;
          btn.classList.remove("copied");
        }, 1500);
      }
      console.log("[Dify Bridge] 诊断信息已复制到剪贴板：\n" + text);
    } catch (e) {
      console.error("[Dify Bridge] 复制失败:", e);
      alert("复制失败，请手动复制 console.log 中的诊断信息。");
    }
  }

  // ==================== 消息渲染 ====================

  function addUserMessage(text) {
    const div = document.createElement("div");
    div.className = "dcfw-msg dcfw-msg-user";
    div.textContent = text;
    getMessagesEl().appendChild(div);
    scrollMessagesToBottom();
  }

  function addClaudeMessage(text) {
    const div = document.createElement("div");
    div.className = "dcfw-msg dcfw-msg-claude";
    div.textContent = text;
    getMessagesEl().appendChild(div);
    scrollMessagesToBottom();
    return div;
  }

  function addSystemMessage(text) {
    const div = document.createElement("div");
    div.className = "dcfw-msg dcfw-msg-system";
    div.textContent = text;
    getMessagesEl().appendChild(div);
    scrollMessagesToBottom();
  }

  function addErrorMessage(text) {
    const div = document.createElement("div");
    div.className = "dcfw-msg dcfw-msg-error";
    div.textContent = "⚠ " + text;
    getMessagesEl().appendChild(div);
    scrollMessagesToBottom();
  }

  // ★ 0.2.16: collapsible thinking via <details>/<summary>.
// 默认折叠（当累积文本 > 200 字）；流结束后 finalizeThinkingBlock 把 summary 改为
// "💭 思考 (N 字)"，保持 _completed 标记让下一轮 delta 开启新块。
function appendThinking(text) {
    const messages = getMessagesEl();
    let think = messages.querySelector(".dcfw-thinking:last-child");
    if (!think || think.dataset.completed === "true") {
      // 拆 emoji + 文本：改用 <details>/<summary>
      think = document.createElement("details");
      think.className = "dcfw-thinking";
      const len = (text || "").length;
      think.open = len <= 200;
      const summary = document.createElement("summary");
      summary.className = "dcfw-thinking-summary";
      summary.textContent = "💭 思考";
      think.appendChild(summary);
      const body = document.createElement("div");
      body.className = "dcfw-thinking-body";
      body.appendChild(document.createTextNode(text || ""));
      think.appendChild(body);
      // 用闭包属性记录 _bodyEl / _textLength / _completed，避免 dataset 字符串转换开销
      think._bodyEl = body;
      think._textLength = len;
      think._completed = false;
      messages.appendChild(think);
    } else {
      // O(1) append 到 body 的最后一个 textNode
      const body = think._bodyEl;
      const tail = body.lastChild;
      if (tail && tail.nodeType === 3 /* TEXT_NODE */) {
        tail.data += text;
      } else {
        body.appendChild(document.createTextNode(text));
      }
      think._textLength = (think._textLength || 0) + (text || "").length;
      // ★ 0.2.18: 累积跨过 200 阈值后动态折叠（之前只判断初始 len，越长不折）
      if (think._textLength > 200 && think.open && !think._completed) {
        think.open = false;
      }
    }
  }

  // ★ 0.2.16 / 0.2.18: 在 assistant_complete / result 时调用，关闭当前 thinking 块。
  // ★ 0.2.18: 不再只在 n <= 200 时设 open=true；强制收敛最终态：
  //   - 短思考：保持展开（用户能直接看到摘要）
  //   - 长思考：强制折叠（避免大块文本占满屏幕）
  function finalizeThinkingBlock() {
    const messages = getMessagesEl();
    if (!messages) return;
    const details = messages.querySelector(".dcfw-thinking:last-child");
    if (!details || details._completed) return;
    const n = details._textLength || 0;
    const summary = details.querySelector(".dcfw-thinking-summary");
    if (summary) summary.textContent = "💭 思考 (" + n + " 字)";
    details._completed = true;
    details.dataset.completed = "true";
    // 强制收敛：不论原本 open 状态如何，最终按 N 决定 open
    details.open = n <= 200;
  }

  function appendToolCall(tool, input) {
    const div = document.createElement("div");
    div.className = "dcfw-tool";
    let inputStr = "";
    try {
      inputStr = typeof input === "string" ? input : JSON.stringify(input, null, 2);
    } catch (e) {
      inputStr = String(input);
    }
    if (inputStr.length > 300) inputStr = inputStr.slice(0, 300) + "...";
    div.textContent = "🔧 " + tool + "(" + inputStr + ")";
    getMessagesEl().appendChild(div);
  }

  function appendToolResult(toolUseId, content) {
    const div = document.createElement("div");
    div.className = "dcfw-tool-result";
    let contentStr = "";
    try {
      contentStr = typeof content === "string" ? content : JSON.stringify(content, null, 2);
    } catch (e) {
      contentStr = String(content);
    }
    if (contentStr.length > 500) contentStr = contentStr.slice(0, 500) + "...";
    div.textContent = "↩ " + contentStr;
    getMessagesEl().appendChild(div);
  }

  function getMessagesEl() {
    return shadowRoot.getElementById("dcfw-chat-messages");
  }

  function scrollMessagesToBottom() {
    const el = getMessagesEl();
    el.scrollTop = el.scrollHeight;
  }

  function clearMessages() {
    getMessagesEl().innerHTML = "";
  }

  function setSending(sending) {
    state.isSending = sending;
    const sendBtn = shadowRoot.getElementById("dcfw-send-btn");
    const input = shadowRoot.getElementById("dcfw-chat-input");
    sendBtn.disabled = sending;
    input.disabled = false; // 输入框保持可用
    // ★ 0.3.12: 复用发送按钮为停止按钮 —— agent 运行时切到 ⏹ + 红色 + 呼吸动画
    if (sending) {
      sendBtn.textContent = "⏹";
      sendBtn.title = "停止 agent（中断当前流）";
      sendBtn.classList.add("dcfw-stop-btn");
      updateStatus("思考中...");
    } else {
      sendBtn.textContent = "➤";
      sendBtn.title = "发送消息";
      sendBtn.classList.remove("dcfw-stop-btn");
      updateStatus(state.sessionId ? "已连接" : "未连接");
    }
  }

  // ★ 0.3.12: 打断 agent —— abort 当前 SSE/poll + 收尾流状态
  function stopCurrentRun() {
    // 1) 终止 SSE / polling
    if (state.sseRequest) {
      try { state.sseRequest.abort(); } catch (_) {}
      // 0.2.16 之后清 sseRequest 会让 debug 面板显示"未连接"，但 stop 是显式中断，
      // 这里清掉 + 后续由 sendMessage 重建 listener —— 比 0.2.16 注释里的 idle-but-ready
      // 更适合 stop 场景（用户明确打断了）
      state.sseRequest = null;
    }
    state.pollingActive = false;
    // 2) 关闭当前 thinking 块（让 final 状态收敛）
    if (typeof finalizeThinkingBlock === "function") {
      try { finalizeThinkingBlock(); } catch (_) {}
    }
    state.currentAssistantBubble = null;
    // 3) 清 rAF flush + 队列
    try { resetStreamBuffers(); } catch (_) {}
    // 4) UI 状态收尾
    setSending(false);
    // 5) 系统消息告知用户
    addSystemMessage("⏹ 已打断 agent（部分响应已保留在消息区）");
  }

  // ★ 0.2.12: 状态文字 → 图标映射（title 保留可读性）
  //   未连接 ○ / 连接中 ⟳ / 已连接 ● / 连接失败 ✕ / 已断开 ○ / 思考中 💭 / 回复中 ▍
  const STATUS_ICON_MAP = {
    "未连接": "○",
    "连接中...": "⟳",
    "已连接": "●",
    "连接失败": "✕",
    "已断开": "○",
    "思考中...": "💭",
    "回复中": "▍",
    "调用工具": "🔧",
    "工具返回": "📦",
    "完成": "✓",
    "出错": "⚠",
    "处理中": "…",
  };
  function updateStatus(text) {
    const el = shadowRoot.getElementById("dcfw-status");
    if (!el) return;
    el.textContent = STATUS_ICON_MAP[text] || text;
    el.title = text;  // hover 看完整文字
  }

  // ==================== 资源 Tab ====================

  async function loadResources() {
    const list = shadowRoot.getElementById("dcfw-resource-list");
    list.innerHTML = '<div class="dcfw-loading">加载中...</div>';

    try {
      const [appsResp, datasetsResp] = await Promise.all([
        gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/dify/apps?limit=50"),
        gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/dify/datasets?limit=50"),
      ]);

      let html = "";

      // 应用列表
      html += '<div class="dcfw-resource-section">';
      html += '<div class="dcfw-resource-section-title">应用 (' + ((appsResp.apps && appsResp.apps.data) || []).length + ')</div>';
      if (appsResp.ok && appsResp.apps && appsResp.apps.data) {
        for (const app of appsResp.apps.data) {
          html += renderResourceItem({
            name: app.name,
            meta: "模式: " + (app.mode || "unknown") + " · ID: " + (app.id || "").slice(0, 8),
            action: "讨论",
            actionData: "看看这个应用: " + app.name + "（app_id: " + app.id + "）",
          });
        }
      } else {
        html += '<div class="dcfw-empty">应用加载失败: ' + escapeHtml(appsResp.error ? appsResp.error.message : "unknown") + "</div>";
      }
      html += "</div>";

      // 知识库列表
      html += '<div class="dcfw-resource-section">';
      html += '<div class="dcfw-resource-section-title">知识库 (' + ((datasetsResp.datasets && datasetsResp.datasets.data) || []).length + ')</div>';
      if (datasetsResp.ok && datasetsResp.datasets && datasetsResp.datasets.data) {
        for (const ds of datasetsResp.datasets.data) {
          html += renderResourceItem({
            name: ds.name,
            meta: "文档数: " + (ds.document_count != null ? ds.document_count : "?") + " · ID: " + (ds.id || "").slice(0, 8),
            action: "讨论",
            actionData: "看看这个知识库: " + ds.name + "（dataset_id: " + ds.id + "）",
          });
        }
      } else {
        html += '<div class="dcfw-empty">知识库加载失败: ' + escapeHtml(datasetsResp.error ? datasetsResp.error.message : "unknown") + "</div>";
      }
      html += "</div>";

      list.innerHTML = html || '<div class="dcfw-empty">暂无资源</div>';
      state.resourceLoaded = true;

      // 绑定"讨论"按钮
      list.querySelectorAll(".dcfw-resource-action").forEach((btn) => {
        btn.addEventListener("click", () => {
          const prompt = btn.dataset.actionData;
          switchTab("chat");
          const input = shadowRoot.getElementById("dcfw-chat-input");
          input.value = prompt;
          autoResize(input);
          input.focus();
        });
      });
    } catch (e) {
      list.innerHTML = '<div class="dcfw-empty">加载失败: ' + escapeHtml(e.message || String(e)) + "</div>";
    }
  }

  function renderResourceItem(item) {
    return (
      '<div class="dcfw-resource-item">' +
      '<div class="dcfw-resource-info">' +
      '<div class="dcfw-resource-name">' + escapeHtml(item.name) + "</div>" +
      '<div class="dcfw-resource-meta">' + escapeHtml(item.meta) + "</div>" +
      "</div>" +
      '<button class="dcfw-resource-action" data-action-data="' + escapeHtml(item.actionData) + '">' + escapeHtml(item.action) + "</button>" +
      "</div>"
    );
  }

  // ==================== 快捷 Tab ====================

  function renderQuickActions() {
    const list = shadowRoot.getElementById("dcfw-quick-list");
    list.innerHTML = "";
    // ★ 0.2.3: 把 shadowRoot 提到局部变量，避免 for 循环内的箭头函数被 eslint no-loop-func 警告。
    // （shadowRoot 在此函数内不会变，提取不影响语义）
    const sr = shadowRoot;
    for (const action of QUICK_ACTIONS) {
      const btn = document.createElement("div");
      btn.className = "dcfw-quick-btn";
      btn.textContent = action.label;
      btn.addEventListener("click", () => {
        switchTab("chat");
        const input = sr.getElementById("dcfw-chat-input");
        input.value = action.prompt;
        autoResize(input);
        input.focus();
      });
      list.appendChild(btn);
    }
  }

  // ==================== SPA 路由跟随 ====================

  // ★ 0.2.16: 从 window.location + <title> + URL regex 抽页面上下文
  // 写入 state.activePageContext，再刷 #dcfw-page-badge
  function capturePageContext() {
    let url = "";
    let title = "";
    let appId = null;
    try {
      url = window.location.href || "";
      title = document.title || "";
      // Dify app 详情页：/apps/<uuid>/... — 抓 app_id
      const m = url.match(/\/apps\/([a-f0-9-]+)/i);
      if (m) appId = m[1];
    } catch (e) {
      console.warn("[bridge] capturePageContext 部分字段读取失败", e);
    }
    state.activePageContext = {
      url,
      title,
      app_id: appId,
      capturedAt: new Date().toISOString(),
    };
    refreshPageBadge();
  }

  // ★ 0.2.16: 标题栏页面徽章（截 30 字 + hover title 看完整 URL/App ID/Captured）
  function refreshPageBadge() {
    const el = shadowRoot && shadowRoot.getElementById("dcfw-page-badge");
    if (!el) return;
    const ctx = state.activePageContext;
    if (!ctx || !ctx.url) {
      el.textContent = "—";
      el.title = "尚未捕获页面";
      return;
    }
    const label = (ctx.title || ctx.url).slice(0, 30)
      + ((ctx.title || "").length > 30 ? "…" : "");
    el.textContent = label;
    el.title = `URL: ${ctx.url}\nTitle: ${ctx.title}\nApp ID: ${ctx.app_id || "（非应用详情页）"}\nCaptured: ${ctx.capturedAt}`;
  }

  function repositionButton() {
    if (!hostEl || !document.body.contains(hostEl)) {
      injectUI();
    }
  }

  function setupRouteWatcher() {
    window.addEventListener("popstate", repositionButton);
    window.addEventListener("hashchange", repositionButton);

    // ★ 0.2.5: 监听 SPA 路由变化，按页面类型安装/卸载 console 捕获
    const onRouteChange = () => {
      if (_isDifyPage()) {
        if (state.consoleCapture.enabled && !state.consoleCapture.originals) {
          _installConsoleHooks();
        }
      } else {
        if (state.consoleCapture.originals) {
          _uninstallConsoleHooks();
        }
      }
    };
    window.addEventListener("popstate", onRouteChange);
    window.addEventListener("hashchange", onRouteChange);

    // ★ 0.2.16: 每次路由变化后刷页面上下文（URL + title + app_id）
    const onRouteChangeCapture = () => {
      try { capturePageContext(); } catch (e) {
        console.warn("[bridge] route capture 失败", e);
      }
    };
    window.addEventListener("popstate", onRouteChangeCapture);
    window.addEventListener("hashchange", onRouteChangeCapture);
    // ★ 0.2.16: 切回 tab 时也刷（用户从其他 tab 回来后页面可能变了）
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        try { capturePageContext(); } catch (e) {
          console.warn("[bridge] visibility capture 失败", e);
        }
      }
    });

    // MutationObserver 监听 body 子节点变化
    const observer = new MutationObserver(() => {
      if (hostEl && !document.body.contains(hostEl)) {
        // host 被移除，重新注入
        hostEl = null;
        shadowRoot = null;
        injectUI();
        if (state.panelOpen) {
          // 恢复面板状态
          state.panelOpen = false;
          togglePanel();
        }
      }
    });
    observer.observe(document.body, { childList: true });

    // 劫持 history.pushState（Dify SPA 用 pushState 切页）
    const originalPushState = history.pushState;
    history.pushState = function () {
      originalPushState.apply(this, arguments);
      setTimeout(() => {
        repositionButton();
        onRouteChangeCapture();
      }, 50);
    };
    const originalReplaceState = history.replaceState;
    history.replaceState = function () {
      originalReplaceState.apply(this, arguments);
      setTimeout(() => {
        repositionButton();
        onRouteChangeCapture();
      }, 50);
    };
  }

  // ==================== 启动 ====================

  async function start() {
    injectUI();
    setupRouteWatcher();
    // ★ 0.2.16: 启动时立即抓一次页面上下文，初始化 page badge
    capturePageContext();
    // ★ 0.2.5: 仅在 Dify 页面下启用 console 捕获
    if (_isDifyPage() && state.consoleCapture.enabled) {
      _installConsoleHooks();
    }
    // ★ 0.3.0: 多用户隔离 — 一次性迁 GM key + 调 /auth/whoami 注入 fingerprint
    try { migrateLegacyKeys(); } catch (e) { console.warn("[bridge] migrateLegacyKeys 失败", e); }
    // ★ 0.3.1: 关键修复 — 先 await detectBridge() 等探测完成（或首个 ok），
    //   再 await bootstrap() 调 /auth/whoami。否则 bootstrap 在 start() 同步路径里
    //   立即读 state.bridgeProbes.find(p => p.status === "ok")，但此时探测还在
    //   async loop 中（state 全 pending），find 返回 undefined → bootstrap early-return
    //   → fingerprint 永远 null → badge 一直 👤? → 用户报"无指纹"。
    //   之前的注释（"bootstrap 在 detectBridge 解析 ok 之后跑，时序安全"）是错的。
    try {
      await detectBridge();
      await bootstrap();
      refreshUserBadge();
    } catch (e) {
      console.warn("[bridge] detectBridge/bootstrap 链失败", e);
    }
    console.log("[Dify Claude Floating Window] 已注入，bridge:", CONFIG.BRIDGE_URL);
  }

  // 等待 document.body 就绪
  if (document.body) {
    start();
  } else {
    document.addEventListener("DOMContentLoaded", start);
  }

  // ★ 0.2.3 二次防御：metadata 改用宽通配，但这里再做页面识别。
  // Dify 1.x 用 CSS Modules，className 都是 `_xxx_hash`，没明显 "dify" 字样。
  // 所以除了 DOM 标记，还要看：
  // 1. pathname 前缀（/apps /datasets /chat /tools /workflow /explore /install /signin /signup）
  // 2. meta description 含 "Dify"
  // 3. 全局变量名含 dify
  // 4. script src 含 "dify"
  // 5. window.location.host 含 dify
  // ★ 0.2.18 修复 TDZ：_DIFY_PATH_PREFIXES 声明已上移到 state 之后、detectBridge 之前
  //   （见 240 行），原位置 3408 行删除。start() 调用 _isDifyPage() 时必须先看到这个 const。
  function _isDifyPage() {
    // 1. URL pathname 前缀
    const path = (window.location.pathname || "").toLowerCase();
    for (const p of _DIFY_PATH_PREFIXES) {
      if (path === p || path.startsWith(p + "/")) return true;
    }
    // 2. host 含 dify（如 https://dify.example.com/）
    const host = (window.location.host || "").toLowerCase();
    if (host.includes("dify")) return true;
    // 3. title / meta
    const title = (document.title || "").toLowerCase();
    if (title.includes("dify")) return true;
    const desc = (document.querySelector('meta[name="description"]') || {}).content || "";
    if (desc.toLowerCase().includes("dify")) return true;
    // 4. DOM 标记
    if (document.querySelector('[class*="dify-"], [class*="Dify"], #dify-app, [data-dify], meta[name="dify"]')) {
      return true;
    }
    // 5. script src 含 dify
    const scripts = Array.from(document.querySelectorAll("script[src]"));
    for (const s of scripts) {
      const src = (s.getAttribute("src") || "").toLowerCase();
      if (src.includes("dify")) return true;
    }
    // 6. 全局变量（一些 SPA 把 config 挂 window 上）
    try {
      const keys = Object.keys(window).filter((k) => k.toLowerCase().includes("dify"));
      if (keys.length > 0) return true;
    } catch (e) { /* ignore */ }
    return false;
  }
  setTimeout(() => {
    if (hostEl && !_isDifyPage()) {
      hostEl.remove();
      hostEl = null;
      shadowRoot = null;
      console.log("[Dify Claude Floating Window] 非 Dify 页面，已自卸载");
    }
  }, 500);
})();
