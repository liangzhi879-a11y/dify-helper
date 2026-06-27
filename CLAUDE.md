# 项目：Dify Helper（Dify 应用开发专用 Claude Code）

## 项目目标

让 Claude Code 通过 MCP 工具直接在 Dify 中搭建 Agent/工作流/知识库。
本项目部署在服务器 218.17.137.219 上，配合 Dify 实例（http://218.17.137.219:9980）使用。

## 项目结构

```
d:\Dify Helper\
├── bridge/                 # FastAPI 桥接服务（端口 8001）
│   └── bridge/
│       ├── app.py          # FastAPI 入口（一次性任务 + SSE 会话）
│       ├── worker.py       # 一次性 headless 任务 worker
│       ├── session.py      # ChatSession 数据模型
│       ├── session_manager.py  # SSE 会话管理器
│       ├── claude_cli_utils.py  # Claude CLI 调用共享函数
│       ├── task_queue.py   # 一次性任务队列
│       ├── models.py       # Task 模型
│       └── config.py       # BridgeConfig
├── mcp_server/             # Dify MCP Server（27 个工具）
│   └── mcp_server/
│       ├── server.py       # FastMCP 入口
│       └── dify_client.py  # Dify Console API 客户端
├── dify_plugin/            # Dify Tool 插件（3 工具，待打包）
├── skills/                 # Skill 池（13 个：7 Dify + 6 通用）
├── tests/                  # 测试套件
├── tampermonkey/           # Tampermonkey 悬浮窗脚本
├── CLAUDE.md               # 本文件
└── .mcp.json               # 项目级 MCP 配置
```

## Skills 注册

加载 `skills/` 目录下所有 .md 文件作为可用 Skill。
按 frontmatter 的 trigger 字段匹配用户意图自动激活。

### Dify 专属 Skill（7）
- `dify-app-architect` (high): 应用架构选型（chat/completion/advanced-chat/workflow/agent-chat）
- `dify-workflow-builder` (high): 工作流编排（18 种节点 + graph schema + 变量传递）
- `dify-dataset-curator` (high): 知识库策略（indexing_technique + chunk + doc_form）
- `dify-dsl-importer` (medium): DSL 导入导出（yaml-only / yaml-customize）
- `dify-prompt-engineer` (medium): 提示词工程（Dify 变量语法 + temperature 调优）
- `dify-model-router` (medium): 模型路由（按任务类型推荐 + provider 配置）
- `dify-debug-runner` (high): 调试运行（run_workflow_debug + indexing-status 定位）

### 通用应用开发 Skill（6）
- `systematic-thinking` (critical): 系统化思考（理解→拆解→方案→影响→验证）
- `code-review-strict` (high): 严格代码审查 checklist
- `bug-diagnostician` (high): 科学调试（复现→假设→验证→修复→回归）
- `test-first-thinking` (medium): 测试驱动思维
- `refactor-patterns` (medium): 重构与设计模式（识别坏味道 + 模式应用）
- `security-mindset` (high): 安全意识（OWASP Top 10 + 最小权限 + 输入校验）

### Skill 激活规则
1. priority=critical 的 Skill 在所有非平凡任务上自动激活
2. 其他 Skill 按用户输入匹配 trigger 关键词激活
3. 多个 Skill 可同时激活，按 priority 排序应用
4. 用户可用 `/skills` 查看 Claude Code 内置 Skill 状态

## Dify 实例信息

- URL: http://218.17.137.219:9980
- API 前缀: /console/api
- 认证：邮箱密码自动登录（9062656286@qq.com）
- 可用 MCP 工具：`mcp__dify__*` 共 27 个（App 6 / Workflow 5 / Dataset 11 / Model 3 / Workspace 2）
- Bridge 服务：http://218.17.137.219:8001（SSE 会话 + 一次性任务）

## Dify 1.14+ 开发文档摘要

### App Mode（5 种）

| Mode | 名称 | 适用场景 | 是否有 workflow graph | 是否多轮对话 |
|---|---|---|---|---|
| `chat` | 基础聊天助手 | 简单问答 | 否（仅 Prompt + Model） | 是 |
| `completion` | 文本生成 | 单次生成：翻译/摘要 | 否 | 否 |
| `advanced-chat` | 聊天流 | 复杂对话+编排 | 是（用 answer 节点回复） | 是 |
| `workflow` | 工作流 | 自动化批处理 | 是（用 end 节点输出） | 否（单次执行） |
| `agent-chat` | Agent | 自主工具调用 | 否（用 agent_mode + tools） | 是 |

DSL 中：chat/completion/agent-chat 用 `model_config` 块；advanced-chat/workflow 用 `workflow.graph` 块。

### Workflow 节点类型（18 种）

`start` / `end` / `answer` / `llm` / `knowledge-retrieval` / `if-else` / `code` / `template-transform` / `question-classifier` / `parameter-extractor` / `variable-assigner` / `variable-aggregator` / `assigner` / `iteration` / `http-request` / `tool` / `document-extractor` / `list-operator`

- start/end 用于 workflow；answer 用于 advanced-chat
- 节点定义在 `api/core/workflow/nodes/<type>/`

### 节点对象 schema

```json
{
  "id": "node-uuid",
  "type": "llm",
  "title": "LLM 回复",
  "data": {
    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {...}},
    "prompt_template": [{"role": "system", "text": "..."}],
    "context": {"enabled": false, "variable_selector": []},
    "vision": {"enabled": false}
  },
  "position": {"x": 100, "y": 200},
  "extent": null
}
```

### 边对象 schema

```json
{
  "id": "edge-uuid",
  "source": "start-node-id",
  "target": "llm-node-id",
  "sourceHandle": "source",
  "targetHandle": "target",
  "type": "custom",
  "data": {"isInIteration": false}
}
```

`if-else` 节点用 `sourceHandle` 区分分支：`true` / `false` / `<condition_id>`

### 变量传递语法

- 引用其他节点变量：`{{#start.query#}}` `{{#llm.text#}}` `{{#code.result#}}`
- 在 prompt_template 中用 jinja2：`{{query}}`（需先在 variables 中映射）
- 会话变量：`{{#sys.user_id#}}` `{{#sys.conversation_id#}}` `{{#sys.query#}}`

### DSL 结构

```yaml
app:
  name: "应用名"
  description: "描述"
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
  - GET /datasets/{id}/documents/{doc_id}/indexing-status（索引状态）
  - POST /datasets/{id}/hit-testing（召回测试）
- **File**: POST /files/upload（创建文档前需先上传拿 file_id）

### 认证要点（Dify 1.14+）

- **登录**：POST /console/api/login，密码需 base64 编码，token 从 Set-Cookie 头提取
- **双提交模式**：每个请求需同时携带 `Authorization: Bearer <token>` + `X-CSRF-Token: <csrf>` + Cookie（access_token + csrf_token + refresh_token）
- **Token 刷新**：POST /console/api/refresh-token
- **自动登录链**：401 → refresh_token → 失败则 email+password 重新登录 → 更新所有 headers → 重试

## 工作约定

- 调用 MCP 工具前无需请求授权（bypassPermissions 模式）
- 修改 Dify 应用前先用 `dify_get_app` 确认存在
- 创建知识库文档需先 `/files/upload` 再 `/datasets/{id}/documents`（Dify 1.14+ 必须）
- workflow 节点 prompt_template 必须用 jinja2 `{{}}`，不能用 f-string
- indexing-status 端点是 GET 不是 POST
- workflow 模式用 `end` 节点输出，advanced-chat 用 `answer` 节点回复

## 开发命令

```powershell
# 启动 bridge 服务
cd "d:\Dify Helper\bridge"
python -m bridge.app

# 启动 MCP server（独立调试）
cd "d:\Dify Helper"
python -m mcp_server

# 运行 E2E 测试
python tests\test_e2e_workflow.py
python tests\test_e2e_dataset.py

# 验证认证
python tests\test_auth.py
```

## 留痕上下文

- `.trae/working_trace.md`：会话留痕（最高优先级上下文）
- `.trae/specs/build-dify-claude-bridge/`：项目 Spec
- `.trae/documents/dify-floating-window-and-skill-pool.md`：本悬浮窗+Skill池实现计划
