// ==UserScript==
// @name         Dify Claude Floating Window
// @namespace    https://github.com/dify-helper
// @version      0.1.0
// @description  在 Dify 页面注入 Claude 实时对话悬浮窗，调用 MCP 工具直接操作 Dify
// @match        http://218.17.137.219:9980/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      218.17.137.219
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // ==================== 配置区 ====================

  const CONFIG = {
    BRIDGE_URL: "http://218.17.137.219:8001",
    DIFY_URL: "http://218.17.137.219:9980",
    SESSION_ID_KEY: "dify_claude_session_id",
    SSE_TIMEOUT_MS: 600000, // 10 分钟（长对话）
    HEARTBEAT_IGNORE: true,
  };

  // 斜杠指令数据驱动分组
  // type: claude-native（转发给 Claude）/ local（bridge 本地处理）/ disabled（TUI 专属，拦截提示）
  const SLASH_COMMANDS = [
    {
      group: "会话控制",
      items: [
        { cmd: "/clear", desc: "清空当前对话历史", type: "claude-native" },
        { cmd: "/compact", desc: "压缩上下文（保留摘要）", type: "claude-native" },
        { cmd: "/resume", desc: "恢复之前的会话", type: "claude-native" },
        { cmd: "/continue", desc: "继续上次未完成的任务", type: "claude-native" },
      ],
    },
    {
      group: "项目记忆",
      items: [
        { cmd: "/memory", desc: "编辑项目记忆（CLAUDE.md）", type: "claude-native" },
        { cmd: "/add-dir", desc: "添加工作目录", type: "claude-native" },
        { cmd: "/init", desc: "初始化项目记忆文件", type: "claude-native" },
      ],
    },
    {
      group: "开发辅助",
      items: [
        { cmd: "/help", desc: "查看帮助", type: "claude-native" },
        { cmd: "/config", desc: "查看/修改配置", type: "claude-native" },
        { cmd: "/model", desc: "切换模型", type: "claude-native" },
        { cmd: "/permissions", desc: "管理工具权限", type: "claude-native" },
        { cmd: "/mcp", desc: "查看 MCP 服务器状态", type: "claude-native" },
        { cmd: "/skills", desc: "查看可用 Skill", type: "claude-native" },
      ],
    },
    {
      group: "监控诊断",
      items: [
        { cmd: "/cost", desc: "查看本次会话 token 消耗", type: "claude-native" },
        { cmd: "/status", desc: "查看账户状态", type: "claude-native" },
        { cmd: "/doctor", desc: "诊断 Claude Code 安装", type: "claude-native" },
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

  const state = {
    sessionId: null,
    sseRequest: null,
    sseLastIndex: 0,
    isSending: false,
    currentAssistantBubble: null,
    panelOpen: false,
    activeTab: "chat",
    resourceLoaded: false,
  };

  // ==================== 工具函数 ====================

  function gmFetch(method, url, options) {
    return new Promise((resolve, reject) => {
      const opts = Object.assign(
        {
          method: method,
          url: url,
          timeout: CONFIG.SSE_TIMEOUT_MS,
          onload: function (resp) {
            resolve(resp);
          },
          onerror: function (err) {
            reject(err);
          },
          ontimeout: function () {
            reject(new Error("GM_xmlhttpRequest timeout: " + url));
          },
        },
        options || {}
      );
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

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ==================== UI 渲染（Shadow DOM 隔离） ====================

  let shadowRoot = null;
  let hostEl = null;

  function injectUI() {
    if (hostEl && document.body.contains(hostEl)) {
      return; // 已注入
    }

    hostEl = document.createElement("div");
    hostEl.id = "dify-claude-floating-window-host";
    hostEl.style.cssText =
      "position:fixed; bottom:24px; right:24px; z-index:2147483647; all:initial;";
    document.body.appendChild(hostEl);

    shadowRoot = hostEl.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = STYLES;
    shadowRoot.appendChild(style);

    // 悬浮按钮
    const btn = document.createElement("div");
    btn.id = "dcfw-fab";
    btn.innerHTML = "💬";
    btn.title = "Dify Claude 助手";
    btn.addEventListener("click", togglePanel);
    shadowRoot.appendChild(btn);

    // 面板容器
    const panel = document.createElement("div");
    panel.id = "dcfw-panel";
    panel.style.display = "none";
    panel.innerHTML = PANEL_HTML;
    shadowRoot.appendChild(panel);

    bindPanelEvents();
  }

  function togglePanel() {
    state.panelOpen = !state.panelOpen;
    const panel = shadowRoot.getElementById("dcfw-panel");
    const fab = shadowRoot.getElementById("dcfw-fab");
    if (state.panelOpen) {
      panel.style.display = "flex";
      fab.innerHTML = "✕";
      if (!state.sessionId) {
        initSession();
      }
      if (state.activeTab === "resource" && !state.resourceLoaded) {
        loadResources();
      }
    } else {
      panel.style.display = "none";
      fab.innerHTML = "💬";
    }
  }

  // ==================== 样式 ====================

  const STYLES = `
    * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
    
    #dcfw-fab {
      width: 56px; height: 56px; border-radius: 50%;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #fff; font-size: 24px; text-align: center; line-height: 56px;
      cursor: pointer; box-shadow: 0 4px 16px rgba(102, 126, 234, 0.4);
      transition: transform 0.2s, box-shadow 0.2s;
      user-select: none;
    }
    #dcfw-fab:hover { transform: scale(1.08); box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6); }
    
    #dcfw-panel {
      position: absolute; bottom: 72px; right: 0;
      width: 440px; height: 620px;
      background: #ffffff; border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
      display: none; flex-direction: column; overflow: hidden;
      border: 1px solid #e5e7eb;
    }
    
    .dcfw-titlebar {
      padding: 12px 16px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #fff; display: flex; align-items: center; justify-content: space-between;
      cursor: move; user-select: none; font-size: 14px; font-weight: 600;
    }
    .dcfw-titlebar-status { font-size: 12px; opacity: 0.85; font-weight: 400; }
    
    .dcfw-tabs {
      display: flex; border-bottom: 1px solid #e5e7eb; background: #fafafa;
    }
    .dcfw-tab {
      flex: 1; padding: 10px 0; text-align: center; cursor: pointer;
      font-size: 13px; color: #6b7280; border-bottom: 2px solid transparent;
      transition: all 0.15s;
    }
    .dcfw-tab:hover { color: #374151; background: #f3f4f6; }
    .dcfw-tab.active { color: #667eea; border-bottom-color: #667eea; font-weight: 600; }
    
    .dcfw-tab-content { flex: 1; overflow: hidden; display: none; flex-direction: column; }
    .dcfw-tab-content.active { display: flex; }
    
    /* 对话 Tab */
    #dcfw-chat-messages {
      flex: 1; overflow-y: auto; padding: 12px; background: #f9fafb;
      display: flex; flex-direction: column; gap: 8px;
    }
    .dcfw-msg { max-width: 85%; padding: 8px 12px; border-radius: 10px; font-size: 13px; line-height: 1.5; word-wrap: break-word; white-space: pre-wrap; }
    .dcfw-msg-user { align-self: flex-end; background: #667eea; color: #fff; }
    .dcfw-msg-claude { align-self: flex-start; background: #fff; color: #1f2937; border: 1px solid #e5e7eb; }
    .dcfw-msg-system { align-self: center; background: #fef3c7; color: #92400e; font-size: 12px; }
    .dcfw-msg-error { align-self: center; background: #fee2e2; color: #991b1b; font-size: 12px; }
    .dcfw-thinking { align-self: flex-start; background: #f3f4f6; color: #6b7280; font-style: italic; font-size: 12px; padding: 6px 10px; border-radius: 8px; border-left: 3px solid #9ca3af; margin-left: 8px; }
    .dcfw-tool { align-self: flex-start; background: #ecfdf5; color: #065f46; font-size: 12px; padding: 6px 10px; border-radius: 8px; border-left: 3px solid #10b981; margin-left: 8px; font-family: monospace; }
    .dcfw-tool-result { align-self: flex-start; background: #f0f9ff; color: #0c4a6e; font-size: 12px; padding: 6px 10px; border-radius: 8px; border-left: 3px solid #0284c7; margin-left: 8px; font-family: monospace; max-height: 120px; overflow-y: auto; }
    
    .dcfw-input-area { border-top: 1px solid #e5e7eb; padding: 8px; background: #fff; position: relative; }
    #dcfw-chat-input {
      width: 100%; min-height: 40px; max-height: 120px; padding: 8px 10px; padding-right: 40px;
      border: 1px solid #d1d5db; border-radius: 8px; font-size: 13px; resize: none; outline: none;
      font-family: inherit;
    }
    #dcfw-chat-input:focus { border-color: #667eea; }
    #dcfw-chat-input::placeholder { color: #9ca3af; }
    .dcfw-send-btn {
      position: absolute; right: 14px; bottom: 16px; width: 28px; height: 28px;
      border: none; border-radius: 6px; background: #667eea; color: #fff; cursor: pointer;
      font-size: 14px; display: flex; align-items: center; justify-content: center;
    }
    .dcfw-send-btn:disabled { background: #d1d5db; cursor: not-allowed; }
    
    /* 斜杠指令面板 */
    .dcfw-cmd-palette {
      position: absolute; bottom: 60px; left: 8px; right: 8px; max-height: 280px;
      background: #fff; border: 1px solid #d1d5db; border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow-y: auto; z-index: 10; display: none;
    }
    .dcfw-cmd-group { padding: 4px 0; }
    .dcfw-cmd-group-title { padding: 6px 12px; font-size: 11px; color: #9ca3af; font-weight: 600; text-transform: uppercase; background: #f9fafb; }
    .dcfw-cmd-item { padding: 8px 12px; cursor: pointer; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
    .dcfw-cmd-item:hover, .dcfw-cmd-item.selected { background: #f3f4f6; }
    .dcfw-cmd-item-cmd { font-family: monospace; color: #667eea; font-weight: 600; }
    .dcfw-cmd-item-desc { color: #6b7280; font-size: 12px; margin-left: 8px; }
    .dcfw-cmd-item.disabled .dcfw-cmd-item-cmd { color: #9ca3af; }
    
    /* 资源 Tab */
    #dcfw-resource-list { flex: 1; overflow-y: auto; padding: 12px; }
    .dcfw-resource-section { margin-bottom: 16px; }
    .dcfw-resource-section-title { font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #e5e7eb; }
    .dcfw-resource-item { padding: 8px 10px; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; background: #fff; }
    .dcfw-resource-info { flex: 1; min-width: 0; }
    .dcfw-resource-name { font-size: 13px; color: #1f2937; font-weight: 500; }
    .dcfw-resource-meta { font-size: 11px; color: #9ca3af; margin-top: 2px; }
    .dcfw-resource-action { padding: 4px 8px; font-size: 11px; background: #f3f4f6; color: #667eea; border: none; border-radius: 4px; cursor: pointer; white-space: nowrap; }
    .dcfw-resource-action:hover { background: #e5e7eb; }
    .dcfw-loading { text-align: center; padding: 20px; color: #9ca3af; font-size: 13px; }
    .dcfw-empty { text-align: center; padding: 40px 20px; color: #9ca3af; font-size: 13px; }
    
    /* 快捷 Tab */
    #dcfw-quick-list { flex: 1; overflow-y: auto; padding: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .dcfw-quick-btn { padding: 16px 12px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; cursor: pointer; text-align: center; font-size: 13px; color: #374151; transition: all 0.15s; }
    .dcfw-quick-btn:hover { border-color: #667eea; color: #667eea; background: #f5f3ff; transform: translateY(-1px); }
    
    .dcfw-scroll::-webkit-scrollbar { width: 6px; }
    .dcfw-scroll::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
    .dcfw-scroll::-webkit-scrollbar-track { background: transparent; }
  `;

  const PANEL_HTML = `
    <div class="dcfw-titlebar">
      <span>Dify Claude 助手</span>
      <span class="dcfw-titlebar-status" id="dcfw-status">未连接</span>
    </div>
    <div class="dcfw-tabs">
      <div class="dcfw-tab active" data-tab="chat">对话</div>
      <div class="dcfw-tab" data-tab="resource">资源</div>
      <div class="dcfw-tab" data-tab="quick">快捷</div>
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
        if (!state.isSending) sendMessage();
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
      if (!state.isSending) sendMessage();
    });

    // 渲染快捷按钮
    renderQuickActions();

    // 拖拽标题栏
    setupDrag();
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
    const titlebar = shadowRoot.querySelector(".dcfw-titlebar");
    const panel = shadowRoot.getElementById("dcfw-panel");
    let isDragging = false;
    let startX, startY, startLeft, startTop;

    titlebar.addEventListener("mousedown", (e) => {
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = panel.getBoundingClientRect();
      startLeft = rect.left;
      startTop = rect.top;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      panel.style.left = startLeft + "px";
      panel.style.top = startTop + "px";
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      panel.style.left = startLeft + dx + "px";
      panel.style.top = startTop + dy + "px";
    });

    document.addEventListener("mouseup", () => {
      isDragging = false;
    });
  }

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
    // 优先复用已存储的 session_id
    const stored = GM_getValue(CONFIG.SESSION_ID_KEY, null);
    if (stored) {
      // 验证会话是否还存在
      try {
        const list = await gmFetchJSON("GET", CONFIG.BRIDGE_URL + "/sessions");
        const exists = (list.sessions || []).some((s) => s.id === stored && s.status !== "closed");
        if (exists) {
          state.sessionId = stored;
          updateStatus("已连接");
          return;
        }
      } catch (e) {
        // 验证失败，继续创建新会话
      }
    }

    // 创建新会话
    try {
      updateStatus("连接中...");
      const resp = await gmFetchJSON("POST", CONFIG.BRIDGE_URL + "/sessions", {});
      state.sessionId = resp.session_id;
      GM_setValue(CONFIG.SESSION_ID_KEY, state.sessionId);
      updateStatus("已连接");
      addSystemMessage("会话已就绪。输入消息或 / 查看指令。");
    } catch (e) {
      updateStatus("连接失败");
      addErrorMessage("无法连接 bridge 服务: " + (e.message || e));
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
      const resp = await gmFetchJSON(
        "POST",
        CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/messages",
        { content: text }
      );
      if (resp.accepted && !resp.local_command) {
        // 启动 SSE 监听
        connectSSE();
      } else if (resp.local_command) {
        // 本地指令结果
        addClaudeMessage(resp.message || "(无输出)");
        setSending(false);
      } else {
        addErrorMessage(resp.message || "发送失败");
        setSending(false);
      }
    } catch (e) {
      addErrorMessage("发送失败: " + (e.message || e));
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
        GM_setValue(CONFIG.SESSION_ID_KEY, state.sessionId);
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
      addErrorMessage("本地指令失败: " + (e.message || e));
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
      return;
    }
    state.sseLastIndex = 0;
    state.currentAssistantBubble = null;

    state.sseRequest = GM_xmlhttpRequest({
      method: "GET",
      url: CONFIG.BRIDGE_URL + "/sessions/" + state.sessionId + "/events",
      headers: { Accept: "text/event-stream" },
      timeout: CONFIG.SSE_TIMEOUT_MS,
      onprogress: function (response) {
        const fullText = response.responseText || "";
        const chunk = fullText.slice(state.sseLastIndex);
        state.sseLastIndex = fullText.length;
        parseSSEChunk(chunk);
      },
      onerror: function (err) {
        state.sseRequest = null;
        setSending(false);
        if (err && err.error && err.error.includes("aborted")) {
          // 主动取消，忽略
        } else {
          addErrorMessage("SSE 连接错误: " + (err.error || JSON.stringify(err)));
        }
      },
      ontimeout: function () {
        state.sseRequest = null;
        setSending(false);
        addErrorMessage("SSE 超时");
      },
      onload: function () {
        state.sseRequest = null;
        setSending(false);
      },
    });
  }

  function parseSSEChunk(chunk) {
    const events = chunk.split("\n\n");
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
        continue;
      }
      handleSSEEvent(data);
    }
  }

  function handleSSEEvent(data) {
    switch (data.type) {
      case "text_delta":
        if (!state.currentAssistantBubble) {
          state.currentAssistantBubble = addClaudeMessage("");
        }
        state.currentAssistantBubble.textContent += data.text || "";
        scrollMessagesToBottom();
        break;

      case "thinking_delta":
        appendThinking(data.text || "");
        scrollMessagesToBottom();
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
        // 完整 assistant 消息，text_delta 已累积，无需重复
        state.currentAssistantBubble = null;
        break;

      case "result":
        // 一次输入处理完成
        state.currentAssistantBubble = null;
        setSending(false);
        if (data.is_error) {
          addErrorMessage("Claude 返回错误: " + (data.result || "").slice(0, 200));
        }
        // 关闭 SSE 流
        if (state.sseRequest) {
          try {
            state.sseRequest.abort();
          } catch (e) {}
          state.sseRequest = null;
        }
        break;

      case "error":
        addErrorMessage("Bridge 错误: " + (data.message || ""));
        setSending(false);
        if (state.sseRequest) {
          try {
            state.sseRequest.abort();
          } catch (e) {}
          state.sseRequest = null;
        }
        break;

      case "session_closed":
        addSystemMessage("会话已关闭: " + (data.message || ""));
        setSending(false);
        state.sseRequest = null;
        state.sessionId = null;
        GM_setValue(CONFIG.SESSION_ID_KEY, null);
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

  function appendThinking(text) {
    const messages = getMessagesEl();
    let think = messages.querySelector(".dcfw-thinking:last-child");
    if (!think || think.dataset.completed === "true") {
      think = document.createElement("div");
      think.className = "dcfw-thinking";
      think.textContent = "💭 " + text;
      messages.appendChild(think);
    } else {
      think.textContent += text;
    }
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
    if (sending) {
      updateStatus("思考中...");
    } else {
      updateStatus(state.sessionId ? "已连接" : "未连接");
    }
  }

  function updateStatus(text) {
    const el = shadowRoot.getElementById("dcfw-status");
    if (el) el.textContent = text;
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
    for (const action of QUICK_ACTIONS) {
      const btn = document.createElement("div");
      btn.className = "dcfw-quick-btn";
      btn.textContent = action.label;
      btn.addEventListener("click", () => {
        switchTab("chat");
        const input = shadowRoot.getElementById("dcfw-chat-input");
        input.value = action.prompt;
        autoResize(input);
        input.focus();
      });
      list.appendChild(btn);
    }
  }

  // ==================== SPA 路由跟随 ====================

  function repositionButton() {
    if (!hostEl || !document.body.contains(hostEl)) {
      injectUI();
    }
  }

  function setupRouteWatcher() {
    window.addEventListener("popstate", repositionButton);
    window.addEventListener("hashchange", repositionButton);

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
      setTimeout(repositionButton, 50);
    };
    const originalReplaceState = history.replaceState;
    history.replaceState = function () {
      originalReplaceState.apply(this, arguments);
      setTimeout(repositionButton, 50);
    };
  }

  // ==================== 启动 ====================

  function start() {
    injectUI();
    setupRouteWatcher();
    console.log("[Dify Claude Floating Window] 已注入，bridge:", CONFIG.BRIDGE_URL);
  }

  // 等待 document.body 就绪
  if (document.body) {
    start();
  } else {
    document.addEventListener("DOMContentLoaded", start);
  }
})();
