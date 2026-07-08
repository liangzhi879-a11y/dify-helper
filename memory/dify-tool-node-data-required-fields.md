---
name: dify-tool-node-data-required-fields
description: Dify ToolNodeData 在 graphon strict validation 下必须同时含 provider_type (值=builtin 不是 plugin) + tool_label；marketplace plugin 的 provider_id 形态 vendor/name/name 时 provider_type 是 builtin
metadata:
  type: project
---

# ToolNodeData 必填字段：provider_type + tool_label

`graphon/entities/tool_entities.py:ToolNodeData` strict validation 会一次性报：

```
2 validation errors for ToolNodeData
provider_type   Field required [type=missing, input_value={'type':'tool', ...}]
tool_label      Field required [type=missing, input_value={'type':'tool', ...}]
```

## 字段值怎么填

### provider_type

看似枚举（`ToolProviderType` enum），但实测 marketplace plugin 实际写入 Dify draft 时是 **`"builtin"`**，不是 `"plugin"`。

取自 5 个工作 tool 节点的真实值：

| provider_id | provider_type | provider_name | tool_name | tool_label |
|---|---|---|---|---|
| `langgenius/searxng/searxng` | `builtin` | `langgenius/searxng/searxng` | `searxng_search` | `SearXNG 搜索` |
| `langgenius/searxng/searxng` | `builtin` | `langgenius/searxng/searxng` | `searxng_search` | `SearXNG 搜索` |
| `jaguarliuu/rookie_text2data/rookie_text2data` | `builtin` | `jaguarliuu/rookie_text2data/rookie_text2data` | `rookie_text2data` | `rookie_text2data` |
| `jaguarliuu/rookie_text2data/rookie_text2data` | `builtin` | `jaguarliuu/rookie_text2data/rookie_text2data` | `rookie_excute_sql` | `rookie_excute_sql` |

**判断方法**：以 `vendor/name/name` 形态（中间 `/`，3 段）的 marketplace plugin 一律 `provider_type=builtin`，不论是 `langgenius/...` 还是 `jaguarliuu/...` 还是 `dochub/dochub/dochub`。

源码定义 `ToolProviderType(enum.StrEnum)` 有 `PLUGIN="plugin"` / `BUILT_IN="builtin"` 等，**但 Dify 实际写入 draft 时序列化值是 `builtin`**（推测：Dify 在 tool_node.py 处对所有 marketplace tools 强制归为 builtin，即使该 ID 属于 plugin namespace）。

### tool_label

人类可读标签，可以与 `tool_name` 相同（参考 `rookie_text2data`），也可以是中文 description（参考 `SearXNG 搜索`）。

**取数路径**：
1. 先看 `tool_name` —— 如果是简单 snake_case，常可同值使用（兜底值）
2. 否则 `GET /workspaces/current/tool-providers` 中 `type=builtin` 那条 provider metadata 的 `label.zh_Hans` 字段（这是 provider 整体的 label，不一定等于具体 tool 的 label，但 Dify 实际不会精细校验）
3. 如果上述都不准，就在 Dify UI 上手工配一下这个 tool node，看 Dify 自动写入的 `tool_label` 是哪个字符串

## 推断补法（PATCH）

```python
data['provider_type'] = 'builtin'        # marketplace plugin 一律
data['tool_label']    = data.get('tool_name')  # 简单兜底
```

如果 tool_name 不够用户友好，再去查 provider manifest.label 升级。

## Why（具体案例）

2026-07-05 复刻 `WF_RDReport (v2 doc-ext)` (cb154f61-...) 时：

源 app tool node (17830458579261) 漏了 `provider_type` 和 `tool_label` 2 个字段。源 app 跑得好——老 graphon 是 graceful。但 `POST /apps/imports` 走 strict Pydantic，**新复刻应用** 400 拒绝。

**注意**：DSl export 不自动补字段（不像 assigner 的 input_type 这种 dict key，ToolNodeData 是 BaseModel，序列化直接丢缺字段）。

## How to apply

### 复刻场景

import 之后立刻扫描所有 tool 节点 schema：

```python
draft = await client.get(f"/apps/{new_id}/workflows/draft")
for n in draft['graph']['nodes']:
    if n.get('data', {}).get('type') != 'tool':
        continue
    d = n['data']
    needs_post = False
    if 'provider_type' not in d:
        d['provider_type'] = 'builtin'
        needs_post = True
    if 'tool_label' not in d:
        d['tool_label'] = d.get('tool_name') or d.get('title')  # 兜底
        needs_post = True
    if needs_post:
        post_draft(client, app_id, draft)
```

### 关于 strict validation 是否会再次扩大打击面

graphon Pydantic schema 越来越 strict，**已多次踩坑**：
- code node `outputs[]` 必含 `type + value_type` 一致 ← [[dify-code-node-outputs-require-value-type]]
- code `code_language` 必须是 `python3` 不是 `python` ← [[dify-code-language-python-must-be-python3]]
- assigner `items[].input_type` 必含 ← [[dify-assigner-items-input-type-required]]
- tool `data.provider_type + tool_label` 必含 ← **本条**

策略：**import DSL 之前**先用 PyYAML 解析，逐节点类型扫"已知必填字段集合"，验齐了再 POST /apps/imports。

## 第二阶必填：tool_parameters 结构化格式

除了顶层 2 个字段，**tool node 的 `data.tool_parameters` 必须是结构化 dict**，**不能**是 raw `{name: str}` flat 形式。

```python
# ✅ strict 通过 (SearXNG, DocHub 等所有工作 tool 节点)
"tool_parameters": {
    "query": {"type": "mixed", "value": "{{#1769592823333.text#}}"},
    "format": {"type": "constant", "value": "json"},
}

# ❌ strict 拒绝（legacy flat 形式，老 graphon graceful 但新版挡）
"tool_parameters": {
    "query": "{{#1769592823333.text#}}",
    "format": "json",
}
```

`type` 取值：
- `"mixed"` — 引用变量选择器 `{{#node.field#}}`，UI 允许手动覆盖
- `"variable"` — 严格只读变量（不推荐 mixed 时用）
- `"constant"` — 字面量（不可改），如 `"docx"` / `"json"`

实测所有 `vendor/name/name` marketplace plugin 的 tool parameters 都必须用结构化格式（哪怕值就是字面量也要 wrap 成 `{type: "constant", value: ...}`）。

## 第三阶必填：paramSchemas + params + tool_description

光 2 个顶层字段 + 结构化 tool_parameters 还不够 strict validation。**还必须**补：

```python
"paramSchemas": [  # 列表，每条对应 tool_parameters 一个 key
    {
        "name": "query",
        "label": {"en_US": "...", "zh_Hans": "...", "pt_BR": "...", "ja_JP": "..."},
        "placeholder": None, "scope": None, "auto_generate": None, "template": None,
        "required": True,
        "default": None,
        "min": None, "max": None, "precision": None,
        "options": [],   # select 类型才有
        "type": "string" | "number" | "select" | "boolean" | ...,
        "human_description": {"en_US":"...","zh_Hans":"...","pt_BR":"...","ja_JP":"..."},
        "form": "form" | "llm",   # form=UI 选择, llm=LLM 推断
        "llm_description": "...",
    },
    # ... 每个 parameter 一条
],
"params": {   # 默认值字典
    "query": "",
    "format": "json",
},
"tool_description": "人类可读描述（zh_Hans 多语言也接受 dict）",
"is_team_authorization": True,
"output_schema": None,
"tool_configurations": {},  # dict
```

**为什么需要 paramSchemas**：UI 渲染参数面板 + LLM 推断参数语义都靠它。从 plugin manifest 的 `provider/<v>/<n>/<n>/tools/<tool>.yaml` 直接搬。

## Why（结构化格式踩坑案例）

2026-07-05 复刻 `WF_RDReport (v2 doc-ext)` → 新 app `7ab3c5fd-...`：

- 源 app tool node `tool_parameters` 是 flat 形式（`{template_id: "{{...}}"}`），老 graphon graceful 运行 OK
- 第一次 PATCH 只补了 `provider_type+tool_label`，**仍**挡在 strict validation："tool_parameters 必须 dict[Annotated[ToolParameter, ...]"
- 第二次 PATCH 补 structured `{type, value}` + 3 个 paramSchemas → 通过

**判断**：strict validation 会在三层逐步加码：
1. 顶层必填（`provider_type` / `tool_label`）
2. tool_parameters 结构化格式（flat dict 一律拒绝）
3. meta fields（`paramSchemas` / `params` / `tool_description`）

复刻场景下三层**一齐补**。

## How to apply（完整复刻 PATCH 模板）

```python
import asyncio
from mcp_server.dify_client import DifyClient, DifyApiError

# 1. 从 plugin manifest 拉 3 个参数 schema, 塞进 paramSchemas
SCHEMAS = [
    {"name": "template_id", "label": {"zh_Hans":"模板 ID", "en_US":"Template ID",
                                       "pt_BR":"Template ID", "ja_JP":"テンプレート ID"},
     "placeholder": None, "scope": None, "auto_generate": None, "template": None,
     "required": True, "default": None, "min": None, "max": None, "precision": None,
     "options": [], "type": "string",
     "human_description": {"zh_Hans":"从可用模板列表中选择文档模板","en_US":"...","pt_BR":"...","ja_JP":"..."},
     "form": "form",
     "llm_description": "The ID of the template to use for document generation"},
    # ... 同上 data_json, output_format
]

async def fix_tool(client, app_id):
    draft = await client.get(f"/apps/{app_id}/workflows/draft")
    for n in draft['graph']['nodes']:
        if n['data'].get('type') != 'tool':
            continue
        d = n['data']

        # 1. 顶层 strict 字段
        d['provider_type'] = 'builtin'
        d['tool_label']    = d.get('tool_name') or 'Unknown Tool'

        # 2. tool_parameters 改成 structured
        raw = d.get('tool_parameters', {})
        d['tool_parameters'] = {
            k: (v if isinstance(v, dict) else
                {"type": "mixed" if str(v).startswith("{{#") else "constant",
                 "value": v})
            for k, v in raw.items()
        }

        # 3. meta fields
        d['params']  = {s['name']: s.get('default') for s in SCHEMAS}
        d['paramSchemas'] = SCHEMAS
        d['tool_description'] = '...'
        d['is_team_authorization'] = True
        d['output_schema'] = None
        d['tool_configurations'] = d.get('tool_configurations') or {}

    # POST draft back
    body = {"graph": draft['graph'],
            "features": draft.get('features',{}),
            "environment_variables": draft.get('environment_variables',[]),
            "conversation_variables": draft.get('conversation_variables',[]),
            "hash": draft['hash']}
    await client.post(f"/apps/{app_id}/workflows/draft", json=body)
```

注：上面的 `raw dict 自动转换` 启发式 (`startswith("{{#") → mixed`) 只是兜底，**实战应手写 3 个 schema**，与 plugin manifest 1:1 对齐。

## 关联记忆

- [[dify-import-mode-yaml-content]] — 复刻入口
- [[dify-assigner-items-input-type-required]] — 同样 import 严格化带来的必填问题
- [[dify-code-node-outputs-require-value-type]] / [[dify-code-language-python-must-be-python3]] — 同 vector

