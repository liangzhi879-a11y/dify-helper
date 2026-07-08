# Dify 节点本地 Schema 参考（人可读版）

> **目的**：`mcp_server/server.py:155 _NODE_SCHEMAS` 字典的人可读展开。
> **权威源对照**：每个节点都标 `★ 权威源：docs/dify-raw/...`（dify 自带 7 节点）或 `★ PyPI 外部：graphon~=0.4.0`（旧 18 节点）。
> **架构发现（2026-07-04）**：Dify 1.13.0 重构后，节点分两组：
> - **dify 仓库内**：`api/core/workflow/nodes/<7 节点>` — 已抓 `docs/dify-raw/nodes/`
> - **PyPI 外部包 `graphon~=0.4.0`**：`graphon.nodes.<旧 18 节点>` — 不在 dify 仓库，需 `pip download graphon==0.4.0` 单独抓

---

## 1. dify 仓库内节点（7 个，`api/core/workflow/nodes/`）

### agent

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`agent_strategy_provider`, `agent_strategy_name`, `agent_parameters`
- **★ 权威源**：[docs/dify-raw/nodes/agent/entities.py](dify-raw/nodes/agent/entities.py)（1.4KB）
- **常见错误**：agent_strategy 未配置或 agent_parameters JSON 格式错误

### datasource

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`datasource_type`, `datasource_config`
- **★ 权威源**：[docs/dify-raw/nodes/datasource/entities.py](dify-raw/nodes/datasource/entities.py)（1.9KB）
- **常见错误**：datasource_type 不在白名单 / datasource_config 缺 API key

### knowledge_index

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`dataset_id`, `indexing_technique`, `index_chunk_variable_selector`
- **★ 权威源**：[docs/dify-raw/nodes/knowledge_index/entities.py](dify-raw/nodes/knowledge_index/entities.py)（2.6KB）
- **常见错误**：`indexing_technique` 不是 `high_quality` / `economy` 之一；dataset_id 无效

### knowledge_retrieval

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`dataset_ids`, `query_variable_selector`, `retrieval_mode`
- **★ 权威源**：[docs/dify-raw/nodes/knowledge_retrieval/entities.py](dify-raw/nodes/knowledge_retrieval/entities.py)（1.9KB）
- **常见错误**：retrieval_mode 不是 `single` / `multiple` 之一；dataset_ids 列表为空

### trigger_plugin

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`plugin_id`, `event_name`, `event_parameters`
- **★ 权威源**：[docs/dify-raw/nodes/trigger_plugin/entities.py](dify-raw/nodes/trigger_plugin/entities.py)（3.1KB）

### trigger_schedule

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`cron_expression`, `timezone`
- **★ 权威源**：[docs/dify-raw/nodes/trigger_schedule/entities.py](dify-raw/nodes/trigger_schedule/entities.py)（1.9KB）

### trigger_webhook

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`webhook_url`, `http_method`, `headers`, `payload`
- **★ 权威源**：[docs/dify-raw/nodes/trigger_webhook/entities.py](dify-raw/nodes/trigger_webhook/entities.py)（4.2KB）

---

## 2. PyPI 外部包节点（18 个，`graphon~=0.4.0`，dify 1.14.2 仍在用）

> 这些节点**不在 dify 仓库**，源码在 PyPI 包 `graphon~=0.4.0`。本地有：
> `node_factory.py:119 _import_node_package("graphon.nodes")` 间接确认它们存在。
> **实际抓取**：`pip download graphon==0.4.0 -d /tmp/graphon && tar -xzf /tmp/graphon/graphon-0.4.0.tar.gz -C docs/dify-raw/graphon/`（未执行，按需）。

### code ★ 关键（PATCH 9 根因）

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`code`, `variables`, `outputs`
- **`outputs[]` 必含 3 字段**：`variable` + `type` + **`value_type`**（⚠️ PATCH 9 根因）
  ```python
  outputs = [
      {"variable": "name", "type": "string", "value_type": "string"},  # 必含 value_type
      ...
  ]
  ```
- **`outputs[].type` 可选值**：`string` / `number` / `boolean` / `array[string]` / `object`
- **`outputs[].value_type`**：与 `type` 同值（必须同步）
- **★ 权威源**：PyPI `graphon/nodes/code/entities.py`（B1 后 graph_engine/ 已删；按需 `pip download graphon==0.4.0` 单抓）
- **PATCH 历史**：[PATCH 9](dify-debug-trace.log.md#patch-9--value-type-缺失最关键)（修复了缺 value_type 翻车 5 次）

### llm

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`model.provider`, `model.name`, `model.mode`, `prompt_template`
- **`model.mode`** 可选值：`chat` / `completion`
- **★ 权威源**：PyPI `graphon/nodes/llm/entities.py`（未抓）+ `node_factory.py:51` 间接确认

### http_request

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`url`, `method`, `authorization`
- **`method`** 可选值：`GET` / `POST` / `PUT` / `PATCH` / `DELETE` / `HEAD`
- **★ 权威源**：PyPI `graphon/nodes/http_request/entities.py`（未抓）

### document_extractor

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`variable_selector`（指向文件变量）
- **★ 权威源**：PyPI `graphon/nodes/document_extractor/entities.py`（未抓）

### parameter_extractor

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`model`, `query`, `parameters`（每个含 name + type + description + required）
- **★ 权威源**：PyPI `graphon/nodes/parameter_extractor/entities.py`（未抓）

### question_classifier

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`model`, `query`, `categories`（每个含 name + description）
- **★ 权威源**：PyPI `graphon/nodes/question_classifier/entities.py`（未抓）

### iteration / loop ⚠️ 双重副本

- **必填顶层**：`id`, `type`, `data.type`, **`children`**（⚠️ 顶层字段而非 data）
- **必填 data**：`iterator_selector`（iteration）/ `start_node_id`, `output_selector`, `loop_variable`（loop）
- **★ 关键**：`children` 是**顶层字段**（不在 `data` 里），改 loop 字段要同时改顶层 `children` 副本
- **★ 权威源**：PyPI `graphon/nodes/iteration/entities.py` + `graphon/nodes/loop/entities.py`（未抓）
- **PATCH 历史**：[PATCH 7](dify-debug-trace.log.md#patch-7--loop-children-副本不同步)

### template_transform

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`template`, `variables`
- **★ 权威源**：PyPI `graphon/nodes/template_transform/entities.py`（未抓）

### if_else

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`cases`（每个含 `case_id`, `logical_operator`, `conditions`）
- **★ 权威源**：PyPI `graphon/nodes/if_else/entities.py`（未抓）

### answer

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`answer`（文本或 `variable_selector`）
- **★ 权威源**：PyPI `graphon/nodes/answer/entities.py`（未抓）

### start

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`variables`（每个含 variable + label + type + required + max_length 等）
- **★ 权威源**：PyPI `graphon/nodes/start/entities.py`（未抓）

### end

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`outputs`（每个含 variable + value_type）
- **★ 权威源**：PyPI `graphon/nodes/end/entities.py`（未抓）

### knowledge_retrieval（与 dify 自带同名）

- 与 dify 自带 `knowledge_retrieval` 字段相同。但注册位置在 `graphon.nodes` 而非 `core.workflow.nodes`
- **★ 权威源**：[docs/dify-raw/nodes/knowledge_retrieval/entities.py](dify-raw/nodes/knowledge_retrieval/entities.py)（dify 自带版本）+ `graphon/nodes/knowledge_retrieval/entities.py`（未抓）

### variable_assigner

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`assigned_variable_selector`, `operations`（每个含 operation_type + variable_selector + value）
- **★ 权威源**：PyPI `graphon/nodes/variable_assigner/entities.py`（未抓）

### variable_aggregator

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`variables`（输入列表）, `output_variable_selector`
- **★ 权威源**：PyPI `graphon/nodes/variable_aggregator/entities.py`（未抓）

### list_operator

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`variable_selector`, `operation`, `filter_by`
- **`operation`** 可选值：`filter` / `map` / `reduce` / `sort` / `deduplicate`
- **★ 权威源**：PyPI `graphon/nodes/list_operator/entities.py`（未抓）

### tool

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`provider_id`, `tool_name`, `tool_parameters`
- **★ 权威源**：PyPI `graphon/nodes/tool/entities.py`（未抓）

### assigner

- **必填顶层**：`id`, `type`, `data.type`
- **必填 data**：`assigned_variable_selector`, `write_mode`, `value`
- **`write_mode`** 可选值：`overwrite` / `append` / `clear`
- **★ 权威源**：PyPI `graphon/nodes/assigner/entities.py`（未抓）

---

## 3. 5 种 App Mode

| mode | 适用 | workflow graph | 多轮对话 |
|------|------|----------------|----------|
| `chat` | 基础聊天助手 | ❌（用 `model_config`） | ✅ |
| `completion` | 文本生成 | ❌（用 `model_config`） | ❌ |
| `agent-chat` | Agent | ❌（用 `agent_mode` + `tools`） | ✅ |
| `advanced-chat` | 聊天流 | ✅（用 `answer` 节点回复） | ✅ |
| `workflow` | 工作流 | ✅（用 `end` 节点输出） | ❌ |

**DSL 区别**：
- `chat` / `completion` / `agent-chat` → 顶层 `model_config` 块
- `advanced-chat` / `workflow` → 顶层 `workflow.graph` 块

---

## 4. 与 `_NODE_SCHEMAS` 字典的对照

**当前 `mcp_server/server.py:155 _NODE_SCHEMAS` 覆盖 10 种**：
```python
{
    "start", "end", "answer", "llm",
    "knowledge-retrieval", "loop", "iteration",
    "if-else", "code", "http-request",
}
```

**本参考文档覆盖 25 种**（dify 仓库 7 + graphon 18）：

**缺失（需补到 `_NODE_SCHEMAS`）**：
- `agent`, `datasource`, `knowledge_index`, `trigger_plugin`, `trigger_schedule`, `trigger_webhook`（dify 自带 5）
- `document_extractor`, `parameter_extractor`, `question_classifier`, `template_transform`, `variable_assigner`, `variable_aggregator`, `list_operator`, `tool`, `assigner`（graphon 9）

**注意**：`code` 节点 `_NODE_SCHEMAS` 的 `data_required` 缺 `outputs[].value_type` — **PATCH 9 根因未沉淀进字典**。

---

## 5. 抓取 / 更新协议

- **本文件**自动从 `_NODE_SCHEMAS` 字典 dump + `docs/dify-raw/` 真值对照
- 改 `_NODE_SCHEMAS` 后**必须**同步更新本文件（详见 `docs/DEBUG_DIFY_PATCH.md` 第 5 步）
- graphon 节点（PyPI 外部）**首次抓取**：
  ```bash
  pip download graphon==0.4.0 -d /tmp/graphon --no-deps
  tar -xzf /tmp/graphon/graphon-0.4.0.tar.gz -C /home/sutai/dify-helper/docs/dify-raw/graphon_src/
  ```
  然后展开每个 `graphon_src/graphon/nodes/<type>/entities.py` 到 `docs/dify-raw/graphon_nodes/<type>/entities.py`
- 30 天 re-fetch（Dify 发布新 minor version 立即 re-fetch + diff）

---

## 6. 相关文档

- 抓取协议：`docs/dify-raw/README.md`
- 抓取日志：`docs/dify-raw/FETCH_LOG.md`
- 节点注册入口：`docs/dify-raw/README.md` 第 2 节（已记录的 node_factory 注册逻辑摘录）
- PATCH SOP：`docs/DEBUG_DIFY_PATCH.md`
- PATCH 反查表：`docs/dify-debug-trace.log.md`
- PATCH CHANGELOG：`docs/CHANGELOG_diy_apps.md`
- DSL 真值：B1 后 `docs/dify-raw/api_console/` 已删；按需 `python scripts/dify_sync.py --fetch-engine` 重新拉
- mcp_server 字典：`mcp_server/mcp_server/server.py:155 _NODE_SCHEMAS`