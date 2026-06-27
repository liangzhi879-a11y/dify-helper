# Dify Helper

> 让 Claude Code 通过 MCP 工具直接在 Dify 中搭建 Agent / 工作流 / 知识库，并在 Dify 页面内通过悬浮窗实时对话调试。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Dify 1.14+](https://img.shields.io/badge/Dify-1.14+-green.svg)](https://github.com/langgenius/dify)

本项目通过三个组件打通"Dify 页面 → 悬浮窗 → Bridge SSE → Claude Code CLI → MCP → Dify Console API"的完整闭环，实现"用 AI 搭建 AI 应用"的自动化开发体验。

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       Dify 实例 (远程)                            │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │  Dify 页面   │  │  Dify Agent  │  │  Dify Plugin (3 工具) │    │
│  │  + 悬浮窗    │  │  (对话入口)   │  │  submit/status/result │    │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────┘    │
│         │ GM_xmlhttp      │ HTTP                  │ HTTP          │
└─────────┼─────────────────┼───────────────────────┼──────────────┘
          │                 │                       │
          ▼                 ▼                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Bridge 服务 (FastAPI :8001)                      │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │  SSE 会话管理    │  │  一次性任务队列    │  │  Dify 资源代理  │  │
│  │  SessionManager │  │  TaskQueue+Worker │  │  /dify/apps     │  │
│  │  (并发子进程)    │  │  (headless -p)    │  │  /dify/datasets │  │
│  └────────┬────────┘  └────────┬─────────┘  └────────────────┘  │
│           │ stream-json          │ -p                              │
│           ▼                     ▼                                 │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │            Claude Code CLI (bypassPermissions)            │    │
│  │            + 13 个 Skill (system prompt 注入)              │    │
│  └────────────────────────┬─────────────────────────────────┘    │
│                           │ MCP (stdio)                           │
│                           ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │            Dify MCP Server (27 个工具)                     │    │
│  │  App 6 / Workflow 5 / Dataset 11 / Model 3 / Workspace 2  │    │
│  └────────────────────────┬─────────────────────────────────┘    │
└───────────────────────────┼──────────────────────────────────────┘
                            │ HTTP (Bearer + CSRF 双提交)
                            ▼
                  Dify Console API
```

## 三大组件

| 组件 | 目录 | 说明 |
| --- | --- | --- |
| **Bridge 服务** | `bridge/` | FastAPI 服务（端口 8001），提供 SSE 实时会话 + 一次性 headless 任务 + Dify 资源代理 |
| **MCP Server** | `mcp_server/` | 封装 Dify Console API 为 27 个 MCP 工具，通过 stdio 与 Claude Code 通信 |
| **悬浮窗脚本** | `tampermonkey/` | Tampermonkey 用户脚本，在 Dify 页面注入 Shadow DOM 悬浮窗，三 Tab 界面（对话/资源/快捷）|

另含 **Dify 插件**（`dify_plugin/`，3 个工具，可选）和 **Skill 池**（`skills/`，13 个 .md 文件，作为 Claude system prompt 注入）。

## 核心特性

- **实时流式对话**：基于 Claude Code CLI stream-json 模式，SSE 推送 text_delta / thinking_delta / tool_call / tool_result 事件
- **27 个 MCP 工具**：覆盖 App / Workflow / Dataset / Model / Workspace 全量 Dify Console API
- **13 个 Skill 池**：7 个 Dify 专属（应用架构、工作流编排、知识库策展等）+ 6 个通用（系统化思考、代码审查、调试、安全等）
- **斜杠指令面板**：三层分类（Claude 原生 / bridge 本地 / TUI 禁用），输入 `/` 自动补全
- **Shadow DOM 隔离**：悬浮窗样式不污染 Dify 原生 UI
- **SPA 路由跟随**：MutationObserver + history.pushState 劫持，Dify 切页悬浮窗不丢失
- **Dify 1.14+ 认证**：邮箱密码自动登录 + token 自动刷新 + CSRF 双提交

## 快速开始

### 前置条件

- **Python** 3.10+
- **Claude Code CLI** v2.1.187+（已登录并配置模型）
- **Dify 实例** 1.14+（如 `http://218.17.137.219:9980`）
- **Tampermonkey 浏览器扩展**（用于悬浮窗）

### 第 1 步：克隆并安装

```bash
git clone https://github.com/liangzhi879-a11y/dify-helper.git
cd dify-helper

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e ./mcp_server
pip install -e ./bridge
```

### 第 2 步：配置 Dify 凭据

```bash
cp mcp_server/.env.example mcp_server/.env
# 编辑 mcp_server/.env，填入 Dify 实例地址和邮箱密码
```

`mcp_server/.env` 内容：

```env
DIFY_CONSOLE_BASE_URL=http://your-dify-host:9980
DIFY_EMAIL=your-email@example.com
DIFY_PASSWORD=your-password
```

> Dify 1.14+ 使用邮箱密码自动登录，客户端自动获取并刷新 access_token / csrf_token / refresh_token，无需手动管理 Token。

### 第 3 步：配置 Bridge

```bash
cp bridge/config.example.yaml bridge/config.yaml
# 编辑 bridge/config.yaml，确认端口和工作目录
```

### 第 4 步：启动 Bridge 服务

```bash
cd bridge
python -m bridge.app
```

预期输出：

```
[SessionManager] started, skills loaded: 5234 chars
[Worker] started
INFO:     Uvicorn running on http://0.0.0.0:8001
```

验证：访问 `http://localhost:8001/health`，应返回 `{"status":"ok"}`。

### 第 5 步：安装悬浮窗

1. 浏览器安装 [Tampermonkey](https://www.tampermonkey.net/) 扩展
2. Tampermonkey 仪表盘 → 新建脚本
3. 粘贴 `tampermonkey/dify-claude-floating-window.user.js` 全文 → 保存
4. 访问你的 Dify 实例（如 `http://218.17.137.219:9980/apps`）
5. 右下角应出现 💬 悬浮按钮，点击展开即可与 Claude 对话

### 第 6 步：验证

在悬浮窗中输入："用 dify_create_app 创建一个 chat 应用叫测试"，应看到：
- `tool_call` 事件（工具名含 `dify_create_app`）
- `tool_result` 事件（返回 app_id）
- `result` 事件（任务完成）

Dify 应用列表应新增一条记录。

## 详细配置

### MCP Server 配置（`mcp_server/.env`）

| 环境变量 | 说明 | 必填 |
| --- | --- | --- |
| `DIFY_CONSOLE_BASE_URL` | Dify 实例地址 | 是 |
| `DIFY_EMAIL` | Dify 登录邮箱 | 是（方式一）|
| `DIFY_PASSWORD` | Dify 登录密码（明文，客户端自动 base64） | 是（方式一）|
| `DIFY_CONSOLE_TOKEN` | access_token（已有则直接注入） | 否（方式二）|
| `DIFY_CSRF_TOKEN` | csrf_token | 否（方式二）|
| `DIFY_REFRESH_TOKEN` | refresh_token | 否（方式二）|

### Bridge 配置（`bridge/config.yaml`）

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| `host` | 监听地址 | `0.0.0.0` |
| `port` | 监听端口 | `8001` |
| `claude_path` | Claude CLI 路径 | `claude` |
| `work_dir` | Claude 工作目录 | `.` |
| `timeout` | 一次性任务超时（秒） | `600` |
| `mcp_server_cmd` | MCP server 启动命令 | `python -m mcp_server` |
| `max_concurrent` | 一次性任务并发数 | `1` |

### Bridge HTTP 接口

#### 一次性任务（headless）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/tasks` | 提交任务，body: `{"task_description":"..."}` |
| GET | `/tasks/{id}/status` | 查询状态 |
| GET | `/tasks/{id}/result` | 查询结果 |

#### SSE 实时会话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/sessions` | 创建会话，body: `{"initial_prompt?":"..."}` |
| GET | `/sessions` | 列出会话 |
| GET | `/sessions/{id}/events` | SSE 事件流（`text/event-stream`）|
| POST | `/sessions/{id}/messages` | 发送消息，body: `{"content":"..."}` |
| DELETE | `/sessions/{id}` | 关闭会话 |
| POST | `/sessions/{id}/reset` | 重置会话（新建子进程）|
| GET | `/sessions/{id}/export?format=md` | 导出会话 |
| GET | `/sessions/{id}/history` | 消息历史 |

#### Dify 资源代理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/dify/apps?limit=50` | Dify 应用列表 |
| GET | `/dify/datasets?limit=50` | Dify 知识库列表 |

### SSE 事件类型

| type | 含义 |
| --- | --- |
| `text_delta` | 流式文本增量 |
| `thinking_delta` | 思考过程增量 |
| `assistant_complete` | 完整 assistant 消息 |
| `tool_call` | 工具调用开始 |
| `tool_result` | 工具调用结果 |
| `result` | 一次输入处理完成（含 is_error / duration / cost）|
| `heartbeat` | 30s 心跳 |
| `error` | 错误 |
| `session_closed` | 会话关闭 |

### Skill 池（`skills/`）

13 个 Skill 文件（YAML frontmatter + Markdown body），由 SessionManager 启动时加载并注入为 Claude system prompt。

#### Dify 专属 Skill（7）

| Skill | 优先级 | 触发场景 |
| --- | --- | --- |
| `dify-app-architect` | high | 应用架构选型（5 种 mode 决策树）|
| `dify-workflow-builder` | high | 工作流编排（18 节点 + graph schema）|
| `dify-dataset-curator` | high | 知识库策略（indexing + chunk + doc_form）|
| `dify-dsl-importer` | medium | DSL 导入导出 |
| `dify-prompt-engineer` | medium | 提示词工程（Dify 变量语法）|
| `dify-model-router` | medium | 模型路由（任务→模型矩阵）|
| `dify-debug-runner` | high | 调试运行（debug run + 索引状态）|

#### 通用应用开发 Skill（6）

| Skill | 优先级 | 触发场景 |
| --- | --- | --- |
| `systematic-thinking` | critical | 系统化思考（理解→拆解→方案→影响→验证）|
| `code-review-strict` | high | 严格代码审查 checklist |
| `bug-diagnostician` | high | 科学调试（复现→假设→验证→修复→回归）|
| `test-first-thinking` | medium | 测试驱动思维 |
| `refactor-patterns` | medium | 重构与设计模式 |
| `security-mindset` | high | 安全意识（OWASP Top 10）|

### 斜杠指令

悬浮窗输入 `/` 触发指令面板，三层分类：

| 分类 | 示例 | 行为 |
| --- | --- | --- |
| Claude 原生 | `/clear` `/compact` `/model` `/mcp` `/cost` | 转发给 Claude CLI |
| bridge 本地 | `/reset` `/history` `/list-sessions` `/export` `/dify-help` | Bridge 直接处理 |
| TUI 禁用 | `/rewind` `/branch` `/exit` | 拦截并提示不可用 |

## 测试

### 单元测试（无需真实环境）

```bash
python -m pytest tests/test_session.py -v
```

验证：12 个测试覆盖健康检查、会话创建/列出/关闭、消息发送、本地指令、TUI 禁用指令、404 错误、Dify 资源端点。使用 mock 子进程避免启动真实 Claude CLI。

### 端到端测试（需完整环境）

```bash
# 终端 1：启动 bridge
cd bridge && python -m bridge.app

# 终端 2：运行 E2E
python tests/test_e2e_floating_window.py
```

验证：SSE 简单对话、本地指令、/reset 重置、SSE+MCP 创建 Dify 应用。

### 其他测试

```bash
python tests/test_auth.py              # Dify 认证链
python tests/test_e2e_workflow.py      # 工作流创建
python tests/test_e2e_dataset.py       # 知识库创建
python tests/test_bridge_e2e.py        # Bridge API 契约
python tests/test_mcp_tools.py         # MCP 工具注册
```

## 部署

完整部署文档见 [docs/deployment.md](docs/deployment.md)，涵盖：

- 服务器前置条件
- 代码同步（git clone / rsync / scp）
- 依赖安装与配置
- 防火墙开放端口
- 进程守护（systemd / pm2 / nohup / Windows 服务）
- Tampermonkey 脚本安装
- 验证清单
- 常见问题排查（8 个 Q&A）
- 安全注意事项

### 网络穿透（Dify 在远程服务器时）

| 方案 | 命令 |
| --- | --- |
| ngrok | `ngrok http 8001` |
| cloudflared | `cloudflared tunnel --url http://localhost:8001` |
| SSH 反向隧道 | `ssh -R 8001:localhost:8001 user@remote` |
| 内网直连 | `http://192.168.x.x:8001` |

## 项目结构

```
dify-helper/
├── bridge/                          # Bridge 服务
│   ├── bridge/
│   │   ├── app.py                   # FastAPI 入口（18 路由）
│   │   ├── session_manager.py       # SSE 会话管理器
│   │   ├── session.py               # ChatSession 数据模型
│   │   ├── worker.py                # 一次性任务 worker
│   │   ├── claude_cli_utils.py      # Claude CLI 调用共享函数
│   │   ├── task_queue.py            # 任务队列
│   │   ├── models.py                # Task 模型
│   │   └── config.py                # BridgeConfig
│   ├── config.example.yaml          # 配置模板
│   └── pyproject.toml
├── mcp_server/                      # MCP Server
│   ├── mcp_server/
│   │   ├── server.py                # FastMCP 入口（27 工具）
│   │   └── dify_client.py           # Dify Console API 客户端
│   ├── .env.example                 # 凭据模板
│   └── pyproject.toml
├── dify_plugin/                     # Dify 插件（可选）
│   ├── tools/                       # 3 个工具
│   ├── main.py
│   └── manifest.yaml
├── skills/                          # Skill 池（13 个）
│   ├── dify-app-architect.md
│   ├── dify-workflow-builder.md
│   ├── systematic-thinking.md
│   └── ...
├── tampermonkey/                    # 悬浮窗脚本
│   └── dify-claude-floating-window.user.js
├── tests/                           # 测试套件
│   ├── test_session.py              # 单元测试（12 个）
│   ├── test_e2e_floating_window.py  # E2E 测试
│   ├── test_auth.py
│   ├── test_e2e_workflow.py
│   └── ...
├── docs/
│   ├── deployment.md                # 部署文档
│   └── agent-prompt-template.md
├── CLAUDE.md                        # Claude Code 项目记忆
├── .gitignore
└── README.md
```

## 故障排查

### Bridge 服务

| 问题 | 排查 |
| --- | --- |
| 启动报 `address already in use` | 端口 8001 被占用，改 `config.yaml` 的 `port` |
| `/health` 正常但任务 pending | Worker 未启动，检查 `claude_path` 是否正确 |
| 任务 failed：`claude not found` | Windows 下 `shutil.which("claude")` 返回无扩展名脚本，确保 `claude.cmd` 存在 |
| SSE 流被 Nginx 切断 | 配置 `proxy_read_timeout 3600s; proxy_buffering off;` |

### Claude Code

| 问题 | 排查 |
| --- | --- |
| `claude` 命令不存在 | 未安装 Claude Code CLI |
| 任务 failed：未登录 | 终端运行 `claude` 完成登录 |
| 任务超时 | `config.yaml` 增大 `timeout`（建议 1200）|
| 多行参数被截断 | Windows batch 文件在换行处截断，已自动压单行 |

### MCP Server / Dify

| 问题 | 排查 |
| --- | --- |
| 工具返回 401 | 邮箱密码错误，或 Token 过期未刷新 |
| 工具返回 403 | CSRF token 缺失，检查双提交模式 |
| 创建文档失败 | Dify 1.14+ 需先 `/files/upload` 再 `/datasets/{id}/documents` |
| 索引状态 405 | 该端点是 GET 不是 POST |

### 悬浮窗

| 问题 | 排查 |
| --- | --- |
| 悬浮按钮不出现 | Tampermonkey 未启用脚本，或 `@match` 不匹配 Dify URL |
| 显示"无法连接 bridge" | Bridge 未运行 / 防火墙未开 8001 / `@connect` 未声明 |
| SPA 切页后消失 | 已用 MutationObserver 处理，若仍消失查看控制台报错 |

## 开发

### 技术栈

- **后端**：Python 3.10+ / FastAPI / httpx / pydantic
- **MCP**：mcp 官方 SDK (FastMCP) / stdio 传输
- **前端**：原生 JavaScript / Tampermonkey / Shadow DOM / GM_xmlhttpRequest
- **CLI**：Claude Code CLI stream-json 模式

### 关键设计

- **SessionManager vs Worker**：SessionManager 管理并发持久 SSE 会话（stream-json）；Worker 处理一次性 headless 任务（`-p`）。两者独立，互不干扰。
- **stream-json 协议**：`--input-format stream-json --output-format stream-json --include-partial-messages`，stdin 写入 user message JSON，stdout 读取流式事件。
- **bypassPermissions 模式**：`--permission-mode bypassPermissions --allow-dangerously-skip-permissions`，自动批准所有工具调用（仅用于受控环境）。
- **Skill 注入**：SessionManager 启动时读取 `skills/*.md`，解析 frontmatter，按 priority 排序，拼接为 system prompt 通过 stream-json 初始消息注入。

### 贡献

欢迎提 Issue 和 PR。提交前请确保：

```bash
python -m pytest tests/test_session.py -v  # 单元测试通过
python tests/test_auth.py                  # 认证链可用（需配置 .env）
```

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 致谢

- [Dify](https://github.com/langgenius/dify) - 开源 LLM 应用开发平台
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - Anthropic 官方 CLI
- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol
