# 项目：Dify Helper（Dify 应用开发专用 Claude Code 实例）

## 项目定位

本实例**专门用于 Dify 调试**，配置与全局 `~/.claude/` 隔离。

- 本实例专属配置在 `/home/sutai/dify-helper/.claude/` 下（不被其他 Claude Code 实例加载）
- 模型继承全局锁定（见 [[dify-bridge-deployment]]）：`MiniMax-M3`，未授权模型会被白名单拒掉
- 全局 Bash hook（`~/.claude/hooks/block-no-verify`）保留生效，不要绕过

## 真实路径与端口（实测）

| 项 | 值 | 说明 |
|---|---|---|
| 项目根 | `/home/sutai/dify-helper/` | Linux 路径（不是 Windows `d:\Dify Helper\`） |
| Bridge 服务端口 | **8002** | 部署时改了（避开 vllm 占用的 8000），不是 `config.py` 默认 8000 |
| vllm | 8000 | 占用，不要让 bridge 撞上去 |
| bge-m3 embedding | 8001 | 参考 [[dify-bridge-deployment]] |
| Dify 实例 | `http://127.0.0.1/` | nginx 80 端口，`http://REDACTED_HOST:9980` 不可用 |

## 项目结构

```
/home/sutai/dify-helper/
├── bridge/                    # FastAPI 桥接服务（端口 8002）
│   └── bridge/
│       ├── app.py             # FastAPI 入口（17 个端点）
│       ├── worker.py          # 一次性 headless 任务 worker
│       ├── session.py         # ChatSession 数据模型
│       ├── session_manager.py # SSE 会话管理器
│       ├── claude_cli_utils.py  # Claude CLI 调用共享
│       ├── task_queue.py      # 一次性任务队列
│       ├── event_store.py     # 事件存储（带 event_id 单调推进）
│       ├── models.py          # Task 模型
│       └── config.py          # BridgeConfig（模型白名单 + 端口）
├── mcp_server/                # Dify MCP Server（41 个工具）
│   └── mcp_server/
│       ├── server.py          # FastMCP 入口（41 个 dify_* 工具）
│       └── dify_client.py     # Dify Console API 客户端
├── dify_plugin/               # Dify Tool 插件
├── skills/                    # 旧 skill 池（仅作 git 历史参考，不再被 harness 加载）
├── tests/                     # 测试套件
├── tampermonkey/              # Tampermonkey 悬浮窗脚本
├── .claude/                   # 本实例专属配置（不入 git）
│   ├── skills/                # 15 个真 Skill manifest（Claude Code 标准格式）
│   │   └── <name>/SKILL.md
│   ├── PLAN_UPGRADE_V2.md
│   └── PLAN_UPGRADE_V2.md → plans/zany-snacking-liskov.md
├── CLAUDE.md                  # 本文件
├── .mcp.json                  # 项目级 MCP 配置（cwd 必须用 Linux 绝对路径）
└── README.md
```

## MCP 工具（41 个）

> 分类基于用户实测（2026-07-01 验证）。早期 CLAUDE.md 误写 App 9 / Workflow 7 / Dataset 14，已纠正。

| 类别 | 数量 | 工具名 |
|---|---|---|
| App | 10 | `list_apps`, `create_app`, `get_app`, `delete_app`, `enable_app`, `disable_app`, `update_app_model_config`, `export_dsl`, `import_dsl`, `list_apps_summary` |
| Workflow | 6 | `get_workflow`, `get_app_node`, `update_workflow`, `publish_workflow`, `run_workflow_debug`, `get_run_status` |
| Dataset | 15 | `create_dataset`, `get_dataset`, `update_dataset`, `list_datasets`, `add_document_by_text`, `add_document_by_file`, `list_documents`, `delete_document`, `get_indexing_status`, `batch_get_indexing_status`, `list_segments`, `add_segment`, `update_segment`, `delete_segment`, `hit_test` |
| Model | 3 | `list_configured_models`, `list_providers`, `list_provider_models` |
| Workspace | 1 | `get_current_workspace` |
| **Diagnose（Phase B 新增）** | **6** | `validate_draft`, `export_draft_dsl`, `get_node_schema`, `rollback_workflow`, `duplicate_workflow`, `get_run_trace` |

**安全网**：所有工具的返回过 `_safe_serialize()`（`mcp_server/server.py:77` `MAX_RESPONSE_BYTES = 14_000`），超阈值返回降级摘要。

### 诊断工具设计原则

每个诊断工具都遵循"先尝试 Dify 后端 → 不支持时本地 fallback"模式：

| 工具 | 后端端点 | Fallback 行为 |
|---|---|---|
| `validate_draft` | `POST /apps/{id}/workflows/draft?dry_run=true` | 本地 JSON schema 校验（节点必填、边引用、UUID、loop children） |
| `export_draft_dsl` | `GET /apps/{id}/workflows/draft/export` | 拿 draft + 本地 PyYAML/JSON 序列化 |
| `get_node_schema` | （无，纯本地缓存） | 直接查 `_NODE_SCHEMAS` 字典 |
| `rollback_workflow` | `POST /apps/{id}/workflows/rollback` | **无 fallback**（不可逆操作，宁可失败） |
| `duplicate_workflow` | `POST /apps/{id}/copy` | export + import 链式回退 |
| `get_run_trace` | `GET /apps/{id}/workflow-runs/{run_id}/node-executions` | 用 `get_run_status` 拿 summary |

## Bridge 端点（21 个）

新增 4 个诊断端点（Phase C）：

| 端点 | 方法 | 用途 | 是否调 Dify 后端 |
|---|---|---|---|
| `/validate-dsl` | POST | 本地 DSL 校验（纯 Python，无 Dify 调用） | 否 |
| `/diagnose/render-error` | GET | 自动化渲染错误诊断（拿 draft + 列假设） | 是 |
| `/diagnose/compare` | POST | 两 workflow 结构 diff | 是 |
| `/diagnose/node-schema` | GET | 离线节点 schema 查询（与 MCP `dify_get_node_schema` 同步） | 否 |

**跳过**：`POST /dify/screenshot`（需要 puppeteer + Chromium，单独排期）

## 多用户隔离（v0.3.0 实施，v0.3.1 修复 race condition）

**目标**：内部团队多用户共存，A 和 B 同开 Dify 悬浮窗互不串话；A 慢任务不阻塞 B；bridge 重启后 A 的 session/历史可恢复。

**身份识别**：`HMAC-SHA256(BRIDGE_FINGERPRINT_SALT, ip|ua|lang)` → `uuid5(NAMESPACE_DNS, digest)`。
服务端权威重算，client 头（`X-Bridge-Fingerprint` / `X-Bridge-Display-Name`）仅作二次细分。
同 IP+UA 不同 `display_name`（油猴 👤 弹窗设置）→ 派生 `uuid5(NAMESPACE_OID, raw|dn)` 作为独立 user_id。

**隔离范围**：
- 16 个 session/task 端点 + `/auth/whoami` — `Depends(get_current_user)` 注入，越权返 404（不泄露存在性）
- `/dify/*` / `/diagnose/*` / `/dochub/*` / `/validate-dsl` — 保持匿名（团队共享 Dify workspace）
- SQLite 表 `PRIMARY KEY (user_id, ...)` 联合主键 + `UNIQUE(display_name)` 撞库合并

**Phase 4 开关 `BRIDGE_LEGACY_DISABLED`**：
- `false`（默认）：无 `X-Bridge-*` header 走 `b4fed778-2ba0-...` 兜底 user_id，老油猴 / curl 仍能用
- `true`：无 `X-Bridge-*` header 返 401，强制 client 升级到油猴 v0.3.0+
- **升级顺序**：Phase 3 油猴 v0.3.0+ 发布 → 1 周观察期 → flip 开关 → 删 `BRIDGE_LEGACY_USER_ID`

**油猴版本号对照**：
- **v0.3.0**：基础多用户隔离（bootstrap / GM 命名空间 / header 注入 / 👤 UI）—— **有 race condition**：badge 永远 👤?
- **v0.3.1**（2026-07-08 修复）：`start()` 改 async，await detectBridge → bootstrap 顺序执行；setDisplayName 用 try/catch 兜底
- **v0.3.2**（Firefox 错误兜底）：window 全局 error + unhandledrejection 监听 → FAB title + 屏幕顶部 overlay，让不开 F12 也能看到根因；togglePanel 全函数 try/catch + 元素存在检查
- **v0.3.3-remote**（Firefox FAB 闪退真根因）：远程版 togglePanel 在 v0.3.2 改动时被错误写成两段重复定义 → IIFE SyntaxError → 油猴静默吞掉 → "闪退"。修复：合并为单一定义（与 local 一致）。本地版无此问题。**测试加 `function togglePanel` 计数 == 1 防复发。**
- **升级必做**：Firefox 用户装 v0.3.3-remote；其他浏览器 v0.3.2+；Phase 4 flip 前必须全量升级到 v0.3.1+

**详细架构 + 踩坑** → `memory/bridge-multi-user-isolation.md`

## Skill 注册（15 个）

加载 `/home/sutai/dify-helper/.claude/skills/<name>/SKILL.md`（Claude Code 标准 manifest 格式）。

按 description 中的触发关键词激活：

### 第一梯队（直接命中翻车场景，4 个）

- `dify-render-error-debugger` — 渲染错误专用
- `dify-workflow-canvas-debugger` — workflow 修改前强制预检
- `dify-loop-iteration-builder` — loop/iteration 节点构建/修复
- `dify-debug-runner` — debug run + run status 解析

### 第二梯队（4 个）

- `dify-dsl-architect` — DSL 导入导出 / diff / 大改
- `dify-model-provider-checker` — 模型可用性预检
- `dify-dataset-debugger` — 知识库全链路诊断
- `dify-app-mode-selector` — 5 种 app mode 选型

### 第三梯队（吸收旧 skills/，5 个）

- `dify-app-architect` — 应用整体架构
- `dify-prompt-engineer` — prompt 编写与调优
- `dify-dataset-curator` — 知识库策略（indexing_technique + chunk + doc_form）
- `dify-dsl-importer` — DSL 跨实例迁移
- `dify-model-router` — 按任务类型推荐 model

### 通用（2 个）

- `bug-diagnostician` — 强制"复现→假设→验证→修复→回归"流程（critical）
- `systematic-thinking` — 强制"理解→拆解→方案→影响→验证"流程（critical）

**旧 skills/*.md 已废弃**，保留作 git 历史参考。`/skills/README.md` 有迁移说明。

## Dify 实例信息

- URL: `http://127.0.0.1/`（nginx 80）
- API 前缀: `/console/api`
- 认证：邮箱密码自动登录（REDACTED_EMAIL@example.com，凭据在 `mcp_server/.env`）
- 可用 MCP 工具：`mcp__dify__*` 共 41 个（分类见上表）
- Bridge 服务：`http://127.0.0.1:8002`（SSE 会话 + 一次性任务 + **21 个端点**，含 4 个 Phase C 诊断端点）

## Dify 1.14+ 开发文档摘要

### App Mode（5 种）

| Mode | 名称 | 适用场景 | 是否有 workflow graph | 是否多轮对话 |
|---|---|---|---|---|
| `chat` | 基础聊天助手 | 简单问答 | 否 | 是 |
| `completion` | 文本生成 | 单次生成 | 否 | 否 |
| `advanced-chat` | 聊天流 | 复杂对话+编排 | 是（用 answer 节点回复） | 是 |
| `workflow` | 工作流 | 自动化批处理 | 是（用 end 节点输出） | 否 |
| `agent-chat` | Agent | 自主工具调用 | 否（用 agent_mode + tools） | 是 |

DSL 中：chat/completion/agent-chat 用 `model_config` 块；advanced-chat/workflow 用 `workflow.graph` 块。

### Workflow 节点类型（18 种）

`start` / `end` / `answer` / `llm` / `knowledge-retrieval` / `if-else` / `code` / `template-transform` / `question-classifier` / `parameter-extractor` / `variable-assigner` / `variable-aggregator` / `assigner` / `iteration` / `http-request` / `tool` / `document-extractor` / `list-operator`

- start/end 用于 workflow；answer 用于 advanced-chat
- 节点定义在 `api/core/workflow/nodes/<type>/`（Dify 后端，本实例未直接访问）

### 变量传递语法

- 引用其他节点变量：`{{#start.query#}}` `{{#llm.text#}}` `{{#code.result#}}`
- 在 prompt_template 中用 jinja2：`{{query}}`（需先在 variables 中映射）
- 会话变量：`{{#sys.user_id#}}` `{{#sys.conversation_id#}}` `{{#sys.query#}}`

### DSL 结构

```yaml
app:
  name: "应用名"
  description: "..."
  mode: chat | completion | advanced-chat | workflow | agent-chat
  icon: "🤖"
  icon_background: "#FFEAD5"
  icon_type: emoji
kind: app
version: 0.1.5

# 二选一：
model_config:        # chat/completion/agent-chat 用
  model: {...}
  prompts: [...]
workflow:            # advanced-chat/workflow 用
  features: {...}
  graph: {nodes: [...], edges: [...]}
  environment_variables: []
  conversation_variables: []
```

### 核心 Console API 端点

- **App**: GET/POST /apps, GET/DELETE /apps/{id}, GET /apps/{id}/export, POST /apps/import
- **Workflow**:
  - GET /apps/{id}/workflows/draft（读取草稿）
  - POST /apps/{id}/workflows/draft（更新草稿）
  - POST /apps/{id}/workflows/publish（发布）
  - POST /apps/{id}/workflows/draft/run（调试运行）
  - GET /apps/{id}/workflow-runs/{run_id}（查询运行状态）
- **Dataset**:
  - POST /datasets（创建）
  - GET /datasets（列表）
  - POST /datasets/{id}/documents（创建文档，需先 /files/upload）
  - GET /datasets/{id}/documents/{doc_id}/indexing-status（**GET 不是 POST**）
  - POST /datasets/{id}/hit-testing（召回测试）
- **File**: POST /files/upload（创建文档前需先上传拿 file_id）

### 认证要点（Dify 1.14+）

- **登录**：POST /console/api/login，密码需 base64 编码
- **双提交模式**：每个请求需同时携带 `Authorization: Bearer <token>` + `X-CSRF-Token: <csrf>` + Cookie
- **Token 刷新**：POST /console/api/refresh-token（参考 [[dify-bridge-deployment]]）
- **自动登录链**：401 → refresh_token → 失败则 email+password 重新登录 → 重试

## 调试 Playbook（**新增节，直击上一轮翻车痛点**）

**使用原则**：任何报错**先查 Playbook**，按表格的"第一步"操作，不要直接改字段。

| 症状 | 第一步 | 第二步 | 陷阱 |
|---|---|---|---|
| "渲染此组件时发生了意外错误" | 让用户从 F12 console 复制红字堆栈 | `dify_get_app(app_id, detail="full")` 看 graph | UUID 含 `g` 等非法字符前端容错，**不要凭直觉改 UUID** |
| workflow run 失败 | `dify_run_workflow_debug` + `dify_get_run_status` 看 `error.node_id` | `dify_get_app_node(app_id, node_id)` 看具体配置 | 失败可能是上游，**先看上游再决定改哪** |
| loop/iteration 渲染异常 | 触发 `dify-loop-iteration-builder` Skill | 检查 `iterator_selector` + `start_node_id` + `output_type` 必填 | **不要一次性改 6 字段**，1 个 1 个改 + 用户验证 |
| 知识库索引失败 | `dify_get_indexing_status` | `dify_list_configured_models` 确认 embedding 模型 | 索引端点是 **GET 不是 POST** |
| "model not found" / provider 报错 | `dify_list_providers` + `dify_list_provider_models(provider)` | 让用户在 Dify 设置页配 | **不要凭名字改 model**，先列实际名 |
| MCP 工具返回 `response_too_large` | 改用 `detail="summary"` 或 `detail="node"` | 警告用户详情被截断 | 不是真的错误，是 14KB 安全网降级 |
| Bash EROFS | 本 session 无法用 Bash | 用 Write 工具做文件改动 | 不要试 `mkdir` / `cat` 等子进程命令 |
| TaskCreate lock 错误 | 不要硬试 | 用本文件的 todo 列表跟踪 | 本实例环境问题 |
| **改 draft 前** | 触发 `dify-workflow-canvas-debugger` + `dify-patch-codegen` | 跑 `python scripts/dify_schema.py drift` 看是否有字段漂移 | **不要凭记忆写字段**，必查 `docs/dify-raw/` |
| **UI 显示 "0/1/2/3/4"（outputs array index）** | 触发 `dify-schema-drift-detector` + 查 [[dify-code-node-outputs-require-value-type]] | code 节点 `outputs[]` 补 `value_type = type` | **根因 = value_type 缺失**，不是 label 或 variable 名 |
| **改了 draft 但 UI 还显示旧** | 触发 `dify-debug-cache` 清浏览器缓存 | 还不行 → 触发 `dify-published-draft-diff` 看用户看的是 draft 还是 published | IndexedDB 是 Dify SPA 主缓存，普通刷新没用 |
| **改完发现错了想恢复** | 触发 `dify-dsl-architect` rollback | 检查 `backups/_tmp_scripts/_tmp_*.py` 找最近 PATCH 脚本 | **不要试图"覆盖"**，先 rollback 再 patch |
| **怀疑权威源变更 / docs.dify.ai 不可达** | 跑 `curl -I https://raw.githubusercontent.com/langgenius/dify/1.14.2/...` | 全失败 → AskUserQuestion 让用户复制 raw 文件 | 不要凭记忆写字段，全部走 `docs/dify-raw/` |

## 工作约定

- 调用 MCP 工具前无需请求授权（bypassPermissions 模式生效于本实例）
- 修改 Dify 应用前先用 `dify_get_app` 确认存在
- 创建知识库文档需先 `/files/upload` 再 `/datasets/{id}/documents`
- workflow 节点 prompt_template 必须用 jinja2 `{{}}`，不能用 f-string
- indexing-status 端点是 GET 不是 POST
- workflow 模式用 `end` 节点输出，advanced-chat 用 `answer` 节点回复
- 任何 workflow 修改前必先触发 `dify-workflow-canvas-debugger` Skill
- 任何 debug 必先触发 `bug-diagnostician` Skill

### PATCH 后沉淀协议（**强制**）

每次 PATCH 闭环后必须做 **5 件事**（PATCH 9 已验证成本：5 次翻车才找对根因）：

1. `dify-helper/memory/<slug>.md` 写 1 行症状 + 1 行根因（frontmatter 格式照全局 memory）
2. 更新 `dify-helper/memory/MEMORY.md` 索引
3. `docs/CHANGELOG_diy_apps.md` 加 5 行记录（日期/app_id/症状/修复字段/脚本路径）
4. `docs/dify-debug-trace.log.md` 加 PATCH 详情 + 错误反查表更新
5. `_tmp_patch_*.py` 移到 `backups/_tmp_scripts/` + .gitignore 已屏蔽

跳过任一步 → 下次同类问题重新翻车。详见 `docs/DEBUG_DIFY_PATCH.md` 5 步 SOP。

### Dify 官方文档本地化（**强制查证**）

`docs/dify-raw/` 内置 langgenius/dify 仓库 1.14.2 tag 的**节点 schema 真值**（B1 精简版 ≈ 80KB），
PATCH 决策**第一查证处**就是这里，不靠记忆或外网搜索。

- 抓取协议 / 维护命令：`docs/dify-raw/README.md`
- 抓取日志：`docs/dify-raw/FETCH_LOG.md`
- 节点真值：`docs/dify-raw/nodes/<7 节点>/entities.py`（dify 自带 7 个）
- ~~引擎真值：`docs/dify-raw/graph_engine/node_factory.py`~~（**B1 2026-07-04 已删**，按需 `python scripts/dify_sync.py --fetch-engine`）
- ~~DSL 真值：`docs/dify-raw/api_console/app_dsl_service.py`~~（**B1 2026-07-04 已删**，按需同上）
- graphon 18 节点真值：PyPI 外部包 `graphon~=0.4.0`，按需 `pip download graphon==0.4.0` 后展开

**架构事实**（2026-07-04 验证）：
- Dify 1.13+ 把 18 个老节点迁移到 PyPI 包 `graphon~=0.4.0`（dify 仓库外）
- dify 仓库内 `api/core/workflow/nodes/` 现在只有 **7 个节点**（agent / datasource / knowledge_* / trigger_*）
- `_NODE_SCHEMAS` 字典（mcp_server）只覆盖 10 种，**缺 15 种**且 **code 节点缺 value_type**（PATCH 9 根因未沉淀）
- 跑 `python scripts/dify_schema.py drift` 看完整 drift 列表

### 项目本地 memory（**触发即查**）

调试经验沉淀在 `/home/sutai/dify-helper/memory/`，按触发词查阅：

- "outputs 显示 0/1/2/3/4" → [[dify-code-node-outputs-require-value-type]]
- "PATCH 出错 / 一次改多字段失败" → [[dify-patch-first-compare-normal-node]]
- "暗色网站下面板字看不清 / 油猴插件主题适配" → [[tampermonkey-shadow-dom-color-inheritance]]
- 完整索引见 `memory/MEMORY.md`（5 条）

**新踩坑必追加**（按 frontmatter 格式）：name + description + metadata.type + 症状 + 根因 + How to apply。

## 开发命令（Linux bash）

```bash
# 启动 bridge 服务
cd /home/sutai/dify-helper/bridge
python -m bridge.app

# 启动 MCP server（独立调试）
cd /home/sutai/dify-helper
python -m mcp_server

# 运行 E2E 测试
python tests/test_e2e_workflow.py
python tests/test_e2e_dataset.py

# 验证认证
python tests/test_auth.py
```

## 隔离声明

- 本实例配置**独立**于 `~/.claude/`，全局模型锁 `MiniMax-M3` 和 Bash hook 由全局 settings 控制
- 15 个 Skill 在 `/home/sutai/dify-helper/.claude/skills/`，其他 Claude Code 实例加载不到
- 调试 Playbook 是本实例经验沉淀，**不属于通用 Claude Code 配置**

## 留痕上下文

- 升级计划：`/home/sutai/dify-helper/.claude/PLAN_UPGRADE_V2.md`（已批准）
- 正式计划：`/home/sutai/.claude/plans/zany-snacking-liskov.md`
- 部署笔记：[[dify-bridge-deployment]]