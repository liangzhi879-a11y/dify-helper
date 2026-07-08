# Dify Helper 调试反查表（trace log）

> **目的**：把"翻车找根因"变成 5 秒内定位。错误关键词 / 症状 → 跳到对应 PATCH 详情。
>
> **结构**：
> - 上半部：错误反查表（按症状/错误关键词索引）
> - 下半部：PATCH 1-15 详细分析（按时间倒序）
>
> **关联**：`docs/CHANGELOG_diy_apps.md`（PATCH 一行摘要），`memory/`（每条踩坑的根因沉淀）。

---

## 上半部：错误反查表（按症状/关键词）

### UI 渲染相关

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| Dify UI 显示 "0 / 1 / 2 / 3 / 4"（array index）作 outputs 标签 | code node `outputs[]` 缺 `value_type` | → PATCH 9 |
| Dify UI 弹出 `Cannot read properties of undefined (reading 'type')` 编辑 outputs 框 | 同上（UI 按 value_type 推断类型） | → PATCH 9 |
| Dify workflow 页面白屏 / 加载不出来 | 节点字段缺失导致 graph 解析失败 | → `dify-render-error-debugger` skill |
| "渲染此组件时发生了意外错误" | 同上 | → `dify-render-error-debugger` skill |
| 改了 draft 但 UI 还显示旧值 | draft 未 publish 或浏览器 IndexedDB 缓存 | → `dify-debug-cache` skill + `dify-published-draft-diff` skill |

### 节点字段相关

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| 批量 rename 字段最后只剩一个值 | flat dict comprehension key 冲突 | → PATCH 8 |
| 改 loop 节点字段但 children 没变 | loop 节点维护顶层 + children 两份副本 | → PATCH 7 |
| variable_selector 引用旧名字 | 全文 reference 替换没跑 | → PATCH 6 |
| assistant message 没渲染 | 缺 `type: "text"` | → PATCH 5 |
| 改 N 个字段无法定位哪个生效 | 一次性改多字段，没分步验证 | → PATCH 2 |
| scratch JSON 直接构造 draft 失败 | 未跑 dify_get_app_node 对比 | → PATCH 1 |
| **LLM 替换 code QC 时 code variables 漏改 value_selector** | intro_text/tech_text/accept_text 全错指向同一个 QC_accept → `len(None)` | → PATCH 21 + dify-code-node-intro-text-wrong-ref |
| **LLM+structured_output 在 thinking + JSON 双消费 token 撞 4096** | 6 LLM 节点 max_tokens 默认 4096，LLM 用 thinking 链 + 完整 JSON 必撞，structured_output parser 失败 → loop terminated | → PATCH 22 + dify-loop-timeout-app-max-execution |
| **workflow 跑超 1200s Aborted，loop_count=100 设了没用** | APP_MAX_EXECUTION_TIME=1200s server cap（api/configs/feature/__init__.py），per-app PATCH 不可改 | → PATCH 20 + dify-loop-timeout-app-max-execution |
| **loop loop_variables[].value=0，iter 0 找 RD00 → 空** | LLM 提取返回空 structured_output → 下游 None cascade | → PATCH 21 |
| **workflow 报 `1 validation error for LoopNodeData / loop_variables.N.var_type / input value='array[file]'`** | graphon `LoopNodeData.loop_variables[].var_type` 是 frozenset 子集，不含 `array[file]`（合法：string/number/object/boolean + array[string/number/object/boolean]）；SegmentType 有 file 但 LoopVariable.var_type 不允许 | → PATCH 39 rollback + dify-loop-var-type-array-file-unsupported |
| **rollback draft 时 HTTP 409 `draft_workflow_not_sync`** | Dify POST /apps/{id}/workflows/draft 有 hash 守卫，BEFORE 备份的 hash 已过期；rollback 脚本必须先 GET 当前 hash 再 POST | → PATCH 39 rollback 脚本加固 + dify-loop-var-type-array-file-unsupported |

### 网络 / 抓取相关（**新发现**）

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| `WebFetch Unable to verify if domain docs.dify.ai is safe to fetch` | 本实例外网白名单挡 | → `docs/dify-raw/README.md` 第 5 节 Fallback |
| `gh: command not found` | gh CLI 未安装 | → 用 curl raw.githubusercontent.com 替代 |
| `curl raw.githubusercontent.com/...entities.py` 返回 404 | Dify 1.13+ 重构，节点迁移到 graphon 外部包 | → `docs/dify-raw/FETCH_LOG.md` 2026-07-04 |

### Code 节点 / 环境变量相关（**新发现**）

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| code node 里 `_os.environ.get("XXX")` 拿到 None | Dify 沙箱隔离 host env，os.environ 是空 dict | → PATCH 10 |
| `os.environ.get(...) or "{{env.XXX}}"` 兜底仍失败 | jinja 模板语法只在 prompt_template 生效，code 函数体里就是字符串字面量 | → PATCH 10 |
| HTTP body 里某字段是 null 而 Dify environment_variables 里已声明该变量 | code node 没把 env var 通过 sys/env 选择器注入 | → PATCH 10 |

### Loop / 错误处理相关（**新发现**）

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| loop 累积字段（rd_doc_urls 等）长度 < 预期 | code node `raise ValueError` + loop `error_handle_mode=terminated` → 任一子失败全 loop 中断 | → PATCH 11 |
| task_summary 统计 `qc_passed` 数与 `rd_count` 不一致 | 同上：rd_count 用 count_down 兜底但实际处理数 < count_down | → PATCH 11 |
| 部分 RD 项目被静默跳过，无任何报错提示 | loop terminated 默认不抛错，只累积到当前 break 条件 | → PATCH 11 |
| loop 内累积字段（rd_tech_texts 等）永远空数组 | code 节点 outputs 没按累积字段 1:1 拆（只输出 assembled_markdown） | → PATCH 12 |
| assigner 只 append 1 次但累积字段有 N 个 | code 节点 outputs 没分板块，assigner 也没补齐 items | → PATCH 12 |
| 累积后下游拿到的值是 N 份合并 markdown 副本 | 同上 + 没拆板块 | → PATCH 12 |
| 下游解析累积字段时强转报错（string → object 失败） | loop outputs 类型声明 array[object]，但 assigner 实际 append 是 string | → PATCH 13 |
| code outputs 显示 "0/1/2/3/4"（与 PATCH 9 同症） | code outputs[].type 与 value_type 不一致（即使 type 是 number 但 value 是 bool） | → PATCH 13 + 9 |
| loop 节点画布显示重复节点（旧 semantic ID 副本） | children 副本未随顶层节点替换同步清理 | → PATCH 14 |
| DSL 备份文件异常大（>120KB）但只有 19 顶层节点 | children 里堆积 children-only 旧节点 + 死边 | → PATCH 14 |
| POST draft 返回 400 含 "broken edge" 或 "edge target missing" | children.edges 引用了已删除的 children-only 节点 | → PATCH 14 |
| 部署后 HTTP 请求失败 "connection refused" | HTTP URL 硬编码 127.0.0.1 | → PATCH 15 |
| Dify 升级后 loop 节点报 missing output_type | loop node output_type 字段 None（隐式声明） | → PATCH 15 |
| Dify 升级后 code node 报 missing variable.value_type | variables[] 全部 value_type=None | → PATCH 15 |
| debug run 返回 `2 validation errors for ToolNodeData` (provider_type/tool_label) | strict validation layer 1 必填 | → PATCH 13 |
| debug run 返回 `tool_parameters must be Annotated[ToolParameter,...] not dict[str, str]` | strict validation layer 2：flat `{key: str}` 必须改 structured `{key: {type, value}}` | → PATCH 18 |
| debug run 报 `network error after 3 retries` (status=0) | Pydantic 已过；上游 provider 不可达（DocHub/HTTP 网络隔离） | → PATCH 18 (validation 干净，但部署/凭证问题) |
| import DSL 后 VariableAssignerNodeData 报 `items.3.input_type / items.4.input_type Field required` | strict validation：每个 assigner item 都必须含 input_type | → PATCH 13 / dify-assigner-items-input-type-required |
| **workflow 跑报 `Cannot convert 'sys.XXX' to number`** | Dify `{{#sys.XXX#}}` 引不存在的 start input 变量，渲染为字面量字符串 | → PATCH 36 / dify-rd-total-count-patch-chain |
| **start input required=True 但 console run server 端不 raise** | Dify 1.14+ required check 是 client-side，server 端 `_validate_inputs` 在 console run 不注入 default | → PATCH 36 |
| **PATCH 改完 env var，但 user 在 Dify UI EnvPanel 找不到** | `tool_published: false` 时 EnvPanel 不显示 env var（或显示空）；必须 publish | → PATCH 36 |

### 架构相关（**新发现**）

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| CLAUDE.md 列 18 节点但 `api/core/workflow/nodes/` 只有 7 子目录 | Dify 1.13 重构：旧 18 节点迁移到 PyPI `graphon~=0.4.0` 外部包 | → `docs/dify-raw/README.md` 第 2 节 |
| `_NODE_SCHEMAS` 字典只覆盖 10 种节点（缺 document_extractor 等） | 同上 + 字典未跟进新节点类型 | → `docs/dify-local-schema-reference.md` |

### DocHub / Poi-tl 模板相关（**新发现**）

| 症状 / 错误关键词 | 根因 | 跳转 |
|---|---|---|
| DocHub `/api/v1/generate` 返 HTTP 200 + 200KB docx，但占位符 0 个替换；日志 `Resolve the document end, resolve and create 0 MetaTemplates / Render template in 0 millis` | **双层 bug**：(A) Word 自动拼写检查切碎 `{{ xxx }}` 为多 `<w:r>`，Poi-tl 1.12.2 不跨 run 拼接；(B) Poi-tl 1.12.2 默认 regex 不识别 `{{ xxx }}`（含空格），只识别 `{{xxx}}` | → PATCH 42 + poi-tl-placeholder-spaces-and-runs |
| DocHub generate 后 docx 里残留 `{{r xxx}}` 富文本未渲染 | Poi-tl 1.12.2 不支持 `{{r xxx}}` 富文本语法（需 1.13+） | → PATCH 42 已知限制 |
| DocHub schema 提取完整（GET /api/v1/templates/{id}/schema 字段全在）但 generate 渲染 0 个 | schema 提取与 TemplateResolver 用不同 parser；schema 阶段松，渲染阶段严 → 必须端到端测一次 | → PATCH 42 |

---

## 下半部：PATCH 详细分析（按时间倒序）

### PATCH 9 — value_type 缺失（**最关键**）

- **时间**: 2026-07-04
- **app**: WF_RDReport_v2 doc-ext 6 个 QC code 节点
- **症状**: 用户报告 QC 输出变量在 Dify UI 显示 "0 / 1 / 2 / 3 / 4"
- **翻车过程**: Q&A 5 次才找对根因
  1. 第 1 次尝试：补 `outputs[].label` 字段 → 无效
  2. 第 2 次：改 `outputs[].variable` 名 → 无效
  3. 第 3 次：怀疑前端 CSS → 无效
  4. 第 4 次：对比 task_summary_001 正常节点 → 发现 outputs 多了 1 个 `value_type` 字段
  5. 第 5 次：补 value_type → ✅ 修复
- **根因**: code node `outputs[]` entry schema 必含 3 字段 `variable` + `type` + `value_type`。缺 `value_type` 时 UI 降级用 array index 作 fallback label
- **解药**:
  ```python
  for entry in outputs:
      entry["value_type"] = entry["type"]   # type 与 value_type 同值
  ```
- **权威源**: `mcp_server/mcp_server/server.py:155 _NODE_SCHEMAS` + 外部 `graphon.nodes.code.entities.CodeNodeData.outputs`
- **memory**: [[dify-code-node-outputs-require-value-type]]
- **关键教训**: 第 1-4 次翻车的根因都是"没先对比正常同类节点"

### PATCH 8 — 批量 rename key 冲突

- **时间**: 2026-07-04
- **app**: WF_RDReport_v2 doc-ext QC 节点
- **症状**: 跑 `{k: v for d in dicts for k, v in d.items()}` 后只剩最后一个字段
- **根因**: 多节点同名字段 → dict comprehension 后 key 冲突，后者覆盖前者
- **解药**: 用嵌套 dict `{node_id: {old_field: new_field}}`，逐节点单独映射
- **memory**: `dify-batch-rename-key-conflict`（项目本地）

### PATCH 7 — loop children 副本不同步

- **时间**: 2026-07-04
- **app**: WF_RDReport_v2 doc-ext loop
- **症状**: 改 loop 节点顶层 `output_selector` 后，children 节点仍用旧 selector
- **根因**: Dify 1.14+ loop 节点维护顶层 + children 两份子节点副本
- **解药**: 改 loop 字段时同时改 `data.children` 副本（注意 children 不在 data 里，在 loop 节点顶层字段）
- **memory**: `dify-dual-copy-children-vs-top`（项目本地）

### PATCH 6 — variable_selector 引用残留

- **时间**: 2026-07-03
- **症状**: rename outputs variable 后其他节点引用仍指旧名
- **根因**: PATCH 脚本只改 outputs 字段，没扫全图替换 reference
- **解药**: 跑 `patch_top_refs.py` 全文 variable_selector 替换

### PATCH 5 — message type 缺失

- **时间**: 2026-07-03
- **症状**: assistant message 不渲染
- **根因**: code node return dict 缺 `type: "text"`
- **解药**: 在 code return 中补 `type` 字段

### PATCH 4 — QC 重写

- **时间**: 2026-07-02
- **症状**: QC 节点逻辑全重写，原结构失效
- **根因**: 用 scratch 整体替换，旧 reference 链断裂
- **解药**: rewrite_qc.py 完整重写子图 + 全图 reference 替换

### PATCH 3 — start 节点 reference

- **时间**: 2026-07-02
- **症状**: start query variable 引用错误
- **根因**: `data.variables[].variable` 旧名 vs 新名 mismatch
- **解药**: 全文替换 patch_top_refs

### PATCH 2 — 多字段同改失效

- **时间**: 2026-07-01
- **症状**: 一次改 6 字段，验证不通过
- **根因**: 多字段同时改无法定位哪个生效
- **解药**: 回滚 + 改 1 字段 1 验证

### PATCH 1 — scratch script 失败

- **时间**: 2026-07-01
- **症状**: 直接构造 draft JSON，Dify 后端拒绝
- **根因**: 未跑 `dify_get_app_node` 对比正常节点结构
- **解药**: 引入"对比正常同类节点"前置 SOP → 见 `docs/DEBUG_DIFY_PATCH.md`
- **memory**: [[dify-patch-first-compare-normal-node]]

---

## 维护约定

- 每 PATCH 闭环后 24h 内必须追加上半部 + 下半部对应行
- 反查表新增错误关键词时附跳转链接
- `memory/` 内 frontmatter `**How to apply:**` 必须引用本文件段落
- 30 天后重读，删除已修复的旧 PATCH（保留 #号 + 一行）
## PATCH 16 (2026-07-04) — CodeNodeData 双字段 validation error

### 错误症状
F12 console 显示：
```
2 validation errors for CodeNodeData
  code_language: Input should be 'python3' or 'javascript' [type=literal_error, input_value='python']
  outputs: Input should be a valid dictionary [type=dict_type, input_value=list]
```

### 反查表更新
| 报错 | 根因字段 | 修复 |
|---|---|---|
| `code_language must be Literal['python3','javascript']` | `data.code_language == 'python'` | 改 `data.code_language = 'python3'` |
| `outputs must be dict` | `data.outputs` 是 list | 转 `dict{var: {type, value_type}}` |

### 范围扫描脚本
任何 PATCH 前先扫所有 `type=code` 节点：
```python
for n in draft["graph"]["nodes"]:
    if n["data"].get("type") != "code": continue
    cl = n["data"].get("code_language")
    outs = n["data"].get("outputs")
    print(n["id"], cl, type(outs).__name__)
```

### 经验
- Dify `BaseNodeData` (1.10) 容忍 `python` + list outputs；1.14 graphon 升级后严格
- 任何 PATCH 创建/迁移 code node 后必查 4 个字段：`code_language`/`code`/`variables`/`outputs`
- 9aa919dce4579fd9 是 PATCH 16 终态 hash

## PATCH 17 (2026-07-04) — 架构重建：QC code → LLM，HTTP → DocHub 插件

### 起因
用户报告 "PATCH 16 后还是不行 — 循环 QC 节点代码太复杂我也不好调整"，要求：
1. **删 3 个 QC code 节点**（1783045599913/1783045657863/1783045701592）
2. **改用 LLM 节点**（既要审查 QC 标准，又要自动优化不合格内容）
3. **删 HTTP 节点**（17830458579260，调 `{{env.DOCS_HUB_URL}}/api/v1/generate`）
4. **用 DocHub 插件**（`dochub/dochub/dochub` → `generate_document`）

### 决策点
| 决策 | 选项 | 取舍 |
|---|---|---|
| 新建 app vs in-place | 新 app 干净；in-place 保留 PATCH 1-16 进度 | **in-place**（19 个节点改 4 个，其他 15 个不动） |
| LLM 模型 | `minimax-m2.7` (与现有 LLM 一致) vs `minimax-m3` (per memory `dify-model-status-no-configure` 未配) | **minimax-m2.7** |
| 输出字段命名 | 沿用原 code outputs dict 字段名（后向兼容） vs 自由命名（破坏下游） | **沿用**（passed/section/length/bullets/errors + 新加 review/improved_text） |
| LLM JSON 输出方式 | `structured_output_enabled` (强制 schema) vs 自由文本 (下游解析) | **structured_output_enabled** |
| LLM 节点输出 vs 原 code 输出 | code 节点 `outputs = dict{var: {type, value_type}}` 直接暴露；LLM 节点 structured_output 暴露在 `.structured_output.{field}` | 改下游 `value_selector` 2-tuple → 3-tuple（6 条） |
| DocHub tool 节点输出 | 工具节点一般暴露 `text`/`json`/`files`；HTTP 节点暴露 `body` | 改累积 item `["old_http","body"]` → `["new_tool","text"]` |

### 反查表更新
| 症状 | 根因 | 修复 |
|---|---|---|
| LLM 节点替代 code 节点后下游读不到字段 | `value_selector` 仍是 2-tuple，没改 3-tuple 加 `structured_output` | 改下游 nodes 的 `value_selector` 加 `structured_output` 中间键 |
| LLM 替代 QC 后改善不到位 | 温度太高 / prompt 没明确"必须改写" | 温度 0.3 + system prompt "如果 passed=false 必须重写" |
| DocHub 插件调用失败 | workspace-level `team_credentials` 为空 | 用户在 Dify → 设置 → 工具 → DocHub 配 api_key + base_url |
| `data_json` 参数报错 | 段组装输出 `dataJson_json` 是 dict；要传 string | 已是 string（`json.dumps(..., ensure_ascii=False)`） |
| `template_id` 是 null | workflow environment_variables 缺 `RD_REPORT_TEMPLATE_ID` | 已存在，{{#sys.env.RD_REPORT_TEMPLATE_ID#}} 解析 |

### 实施细节
- 删 4 节点：3 QC code + 1 http-request
- 加 4 节点：3 LLM (structured_output_enabled) + 1 tool (provider_id=dochub/dochub/dochub)
- 段落组装 6 个 variables `value_selector` 从 2-tuple 改 3-tuple
- 累积 1 个 item `value` 从 `[old_http, "body"]` 改 `[new_tool, "text"]`
- 不动 loop.children（3 个特殊副本：loop-start + 提取RD详情 + 变量赋值，与新节点无关）

### 经验
- 节点替换是 PATCH 18+ 常见模式：旧 node id 删除 + 新 node id 创建 + 边重定向 + 下游引用更新
- LLM 节点替代 code 节点的核心约束：**字段名后向兼容 + downstream value_selector 加 structured_output 中间键**
- DocHub 插件 vs 自建 HTTP：插件封装了 credential 管理、错误重试、file output，但需要 workspace-level 配 `team_credentials`
- POST `/workflows/draft/run` 默认 30s 超时，复杂 workflow（loop + LLM + tool）会超时 — 异步跑需要 polling 或 stream 模式
- 465460d23a445f0f 是 PATCH 17 终态 hash

### 用户必做
1. 在 Dify UI 强制刷新（Ctrl+Shift+R）
2. 检查 4 个新节点渲染正常（QC+优化-XXX 三个 LLM + DocHub 生成文档 tool）
3. 在 Dify → 设置 → 工具 → DocHub 配 `team_credentials` (api_key + base_url)
4. publish + 跑一次 debug run 验证整链路

---

## PATCH 18 (2026-07-04) — Tampermonkey userscript TDZ 修复（油猴版）

### 错误症状
PATCH 17 部署后用户报控制台红字：
```
[bridge] updateBridgeBadge 失败 ReferenceError: Cannot access 'shadowRoot' before initialization  at userscript:2753
[bridge] renderProbeResults 失败 ReferenceError: Cannot access 'shadowRoot' before initialization  at userscript:2796
Cannot access '_DIFY_PATH_PREFIXES' before initialization  at _isDifyPage userscript:3373
```
附带 401 cascade + `Cannot read 'enabled' of undefined`（看起来像 Dify 整个坏了，实际是油猴崩了导致 fetch 失败被记入 console）。

### 反查表更新
| 报错 | 根因 | 修复 |
|---|---|---|
| `Cannot access 'shadowRoot' before initialization` | `let shadowRoot = null` 原 line 600，但 `detectBridge()` line 297 同步调 `updateBridgeBadge()` → TDZ | 上移到 state 之后（line 209） |
| `Cannot access '_DIFY_PATH_PREFIXES' before initialization` | `_DIFY_PATH_PREFIXES` 原 line 3364，但 `start()` line 3351 调 `_isDifyPage()` → TDZ | 上移到 state 之后（line 214） |
| 油猴脚本报 TDZ 但 SPA 也 401 + TypeError | 上游油猴崩 → fetch/error 被 SPA 当成网络问题处理 | 修油猴后 Dify 401/TypeError 也消失 |

### 经验
- 作者 v0.2.15 已修过 `state` 顶部声明（顶部有 TDZ 警告注释），但漏了 3 个同类问题
- IIFE 内任何同步函数调用都必须**先**有所有 let/const 声明；这是 IIFE 写法硬约束
- TDZ 报错的根因看 stack frame 里的**访问位置**（如 userscript:2753），不是声明位置（line 600）
- 反模式：在 IIFE 中部才声明但函数体里用到（用 grep -n 排顺序就能看到）
- 改完必跑 `node --check userscript` + 顺序断言（声明行号 < 调用行号）

### memory
[[tampermonkey-iife-let-tdz-floating-window]]（新建）

## 2026-07-05：PATCH 23-25 收尾（5 步 SOP）

### PATCH 23 详情 (symptom→fix mapping)
- **报错**: QC+优化节点 UI 显示 `{{#1783045258949.text#}}` 变量失效
- **根因**: PATCH 17 把 3 个 code QC 换成 LLM QC 时，user_prompt `{{#X.structured_output.improved_text#}}` 没改：3 个 QC 全部默认指向 `1783045258949` (项目简介撰写)；QC_tech 应当引 1783045409971 (主要研究内容撰写)，QC_accept 应当引 1783045420242 (项目验收总结撰写)
- **修复**: 3 个 QC 节点 user_prompt 替换成对应 writer ID
- **hash**: e826d649b68ec7f1a43bae4cc951fb4d...

### PATCH 24 详情 (literal symptom)
- **报错**: `Variable #1782973526197.structured_output.start_date_cn# not found`
- **根因**: LLM `提取RD详情` (1782973526197) minimax-m2.7-highspeed thinking 模式耗光 8000 token 也没 emit JSON；output `text` 但 structured_output 缺字段。Dify `{{#X#}}` 解析在 jinja2 之前，default filter 不起作用
- **修复**: 在 LLM extract 后插 1 个 code node "提取字段兜底"，14 字段 default 化。3 writers + 3 QCs 的 user_prompt 引用切换
- **hash**: 663d4e95dfd0601891ba27ced0af06f01896fdc8a6683762e2228ca216be7c74
- **POST body 必含**: `features/environment_variables/conversation_variables/hash` (409 防并发守卫)

### PATCH 25 详情 (literal symptom)
- **报错**: `TypeError: object of type 'NoneType' has no len()`
- **堆栈**: code node 17830458386560 (段落组装) `main()` 第 73-75 行
- **根因**: 段落组装代码 `len(intro_text/tech_text/accept_text)` 没 None 兜底；QC+优化 LLM structured_output.improved_text 为 None 时崩
- **修复**: 3 行 `len(X)` 改 `len(X or "")`
- **hash**: 4f1de634d9a70c3876f57cba45ee3d597d4f19b8940b3d56beae4958c5418993
- **验证 run**: `5f19c8a6-1e69-4d6a-925b-794ff0c6afac` status=succeeded elapsed=658.6s total_steps=7

### 反查表更新
| 报错 | 根因 | 修复 |
|---|---|---|
| QC+优化节点 UI 显示变量无效 + 报 QC 引用错 | PATCH 17 LLM QC 替换时漏改 user_prompt writer ref，全部默认指 `1783045258949` | 按 (intro→1783045258949 / tech→1783045409971 / accept→1783045420242) 1:1 重写 |
| `Variable #LLM_ID.structured_output.FIELD# not found` | LLM m2.7-highspeed thinking + max_tokens 8000 仍不够，structured_output emit 不完整 | 在 LLM 后插 code node "提取字段兜底"，14 字段 default 化；下游引用全切到 code node ID |
| `TypeError: object of type 'NoneType' has no len()` in code node `qc_summary` | 上游 LLM structured_output 字段为 None；`len(X)` 没 None 兜底 | `len(X or "")` |
| POST /workflows/draft 返回 409 `draft_workflow_not_sync` | 并发守卫，缺当前 hash | 重新 GET /workflows/draft 取 hash，POST body 加 `hash` 字段 |
| POST /workflows/draft 返回 400 missing `features` | SyncDraftWorkflowPayload 强制必填 | POST body 必含 `features / environment_variables / conversation_variables / hash` |

### memory
- [[dify-llm-structured-output-fallback-defaults]]（新建：thinking + structured_output + Dify 1.14+ 兜底必走 code node）

## 2026-07-05：PATCH 26 in-loop defensive node + 下游引用切换

### PATCH 26 详情
- **报错**: iter 0+ 全部 'Variable #d9e1329a-...#...# not found' (旧 defensive ID 已删)
- **根因**: 用户把 defensive code node 17832273691320 移进 loop (parentId=1782973016950), 但 writers + QCs user_prompt 还指旧 ID d9e1329a-...; 段落组装 12 个 value_selector 还直引 extract LLM 1782973526197
- **修复**: PATCH 26 批量替换
  - 6 个 writers/QCs user_prompt (30 处): {{#d9e1329a-...X#}} → {{#17832273691320#X#}}
  - 段落组装 12 个 value_selectors: [EXTRACT, structured_output, X] → [17832273691320, X]
- **hash**: f7d653bab8f6241fe84671075b5a12b2472ab856082bd340251956f24d476e76
- **验证**: run 2f0bc9e7-e910-41dd-b2fd-c23db8d26d6d status=succeeded, 6 RDs

### 反查表更新
| 报错 | 根因 | 修复 |
|---|---|---|
| iter N 'Variable #defnode.X# not found', 而 defnode outputs 显然正常 | defnode 不在 loop 内, outputs 不 per-iter 重建; writers 拿 stale iter 0 数据 | defnode 加 `parentId=loop_id` + `data.isInLoop=true` + `data.loop_id=loop_id` |
| PATCH defensive node ID 变了, 下游仍引旧 ID | PATCH 后没扫下游 user_prompt + code_node.value_selector | PATCH 后跑 grep 验证 0 个 OLD_ID 残留 |
| 段落组装 code node 突然 `len(None)` 或 `KeyError` | value_selectors 还指向 extract LLM direct, 不走 defensive layer | 切到 defensive node ID, [defnode_id, field_x] (2-tuple) |

### memory
- [[dify-defensive-node-must-be-in-loop]]（新建）

---

## 2026-07-05：PATCH 27 DocHub template_id 文件名→UUID 硬编码

### PATCH 27 详情
- **报错**: DocHub 节点报 `文档生成失败 (HTTP 404): 模板不存在: sys.env.RD_REPORT_TEMPLATE_ID`; rd_doc_urls 全错
- **根因 (双错位)**:
  - `tool_configurations.template_id.value = "RD_temp_test"` ← 用户填文件名, DocHub 要 UUID
  - `tool_parameters.template_id.value = "{{#sys.env.RD_REPORT_TEMPLATE_ID#}}"` ← Dify 1.14+ tool 节点不解析 env var, 字面字符串直接传给 plugin daemon
- **修复**: 两处都硬编码 UUID `e2bb9951-05a4-498d-8c1f-ff9ef47f560b`
- **验证模板存在**: 
  - 解密 DocHub api_key 用 `libs/rsa.py: decrypt_token_with_decoding(b64decode(enc), private_key, cipher_rsa)`, cipher_rsa 需从 `libs/gmpy2_pkcs10aep_cipher.new(private_key)` 拿 (不是 import "new")
  - docker network 内 curl `http://dochub-app:8080/api/v1/templates/e2bb9951-...` + `X-API-Key` header (不是 Authorization Bearer) → 200
- **hash**: d36fa320f6aa3f6c69d3635fd5538f98946a38bf02b17e2402e49dd9c9dad898
- **publish**: 2026-07-05 06:29:41 UTC

### 反查表更新
| 报错 | 根因 | 修复 |
|---|---|---|
| DocHub 404 `模板不存在: <whatever>` | template_id 是文件名不是 UUID, 或 env var 没解析 | 改成 `GET /api/v1/templates/options` 拿到的 UUID 硬编码到 tool_configurations + tool_parameters |
| DocHub 401 `缺少 X-API-Key 请求头` | curl 用 `Authorization: Bearer` 测, 但 DocHub API 要 `X-API-Key` | 改 header 名 |
| docker exec curl 报 `Couldn't connect` | 从 host 用 `127.0.0.1:8088` 试, 但 plugin daemon 是容器, host 不通 dochub-app | 必须从 docker 容器内 (如 docker-plugin_daemon-1) 调 `dochub-app:8080` |
| `gmpy2_pkcs10aep_cipher.PKCS1OAepCipher` import error | 文件里类名是 PKCS1OAepCipher, 工厂函数是模块级 `new()` | `from libs.gmpy2_pkcs10aep_cipher import new; cipher = new(private_key)` |

### memory
- [[dify-dochub-template-id-must-be-uuid]]（新建）

## PATCH 28 (2026-07-05) — 软化 QC LLM system_prompt (0/6 → 5/7)

### 错误症状
PATCH 22 验证遗留：3 个 QC 节点 6/6 RD 全部 passed=false (4 条硬约束太严)

### 反查表更新
| 报错 | 根因 | 修复 |
|---|---|---|
| QC LLM passed=false 持续 6/6 | system_prompt "硬约束（必须全部满足）" — LLM 严格 verify 倾向过度触发 failed | 改 "硬约束" → "参考标准（4/3 通过即 passed=true）" + "兜底: 改写 2 次仍失败 → improved_text=原文" |
| 改 1 个 QC 节点 prompt 影响其他 QC 节点判定 | 3 个 QC system_prompt 高度相似，m2.7 LLM 跨节点行为耦合 | 验证时不能假设 "1 节点 1 改 = 1 节点影响"；同时观察所有 QC |
| QC-intro passed=None (LLM 输出截断) | m2.7 thinking + max_tokens 8000 仍不够，structured_output 缺字段 | 同 PATCH 22/24 — 暂无法根治，等 model 配置升级 |

### 验证结果
- 通过率: **5/7 (71%)** vs PATCH 26 era 0/6 (0%)
- run_id: 86270cd2-3b4b-4259-87f1-a7d5d8daf564, elapsed=558s
- 残留: QC-accept 1 RD failed (字数不足 + "颠覆性简化"), QC-intro 第三 iter passed=None (LLM 截断)

### memory
[[dify-qc-strict-passed-fails-everything]] (新建)

### 经验
- LLM QC 节点的 "硬约束必须全部满足" 模式倾向于 100% false, 因为 LLM 严格按 prompt 清单 verify
- 软化为 "4/3 通过" + "兜底原文保留" 能显著提升通过率 (0% → 71% in 1 PATCH)
- 改 1 个 QC prompt 实际影响 3 个 QC — 验证时要同时观察全部

## PATCH 29 (2026-07-06) — 3 QC 节点统一软化 + max_tokens 8000→12000 + 局域网下载文档

### 错误症状
PATCH 28 残留：(1) QC-accept 1 RD failed（字数不足 + "颠覆性简化"）；(2) QC-intro 第 3 iter passed=None（LLM 截断）

### 反查表更新
| 报错 | 根因字段 | 修复 |
|---|---|---|
| PATCH 28 单 QC 软化后通过率卡 71% | m2.7 LLM 跨节点风格耦合；只改 1 QC 风格不一致 | 3 QC 节点 (intro+tech+accept) system_prompt 同时软化 |
| QC-intro 第 3 iter passed=None | m2.7 thinking + max_tokens 8000 仍撞限 | 3 QC max_tokens 8000→12000（统一升） |
| DocHub `/api/v1/generate` 报 `模板不存在: null` | curl 字段名用 `template_id` (snake_case) | 改 `templateId`/`outputFormat`/`dataJson` (camelCase) |
| DocHub `/api/v1/generate` 报 `400 数据校验失败` | dataJson 字段类型不对（project_year/budget/expenses/labor_costs 是 string，不是 number） | count_no/ip_count 改 number；其他 string |
| Dify 1.14+ 登录 KeyError: 'data' | 登录响应 body 只有 `{"result":"success"}`，tokens 全在 Set-Cookie | 直接从 r.cookies 拿 access_token/refresh_token/csrf_token |
| LAN 设备没法下 docx（要 X-API-Key） | DocHub 容器不暴露给 LAN 客户端 | nginx `/dochub-files/` 反代自动注入 X-API-Key |

### PATCH 脚本 + 验证
- `_patch29_soften_3qc.py` 改 3 QC + max_tokens 8000→12000 → POST draft → new hash `6fc1c2522be1c20fed4c...`
- validate_draft: 0 errors, 0 warnings ✅
- E2E 验证待用户跑真实 Excel 文件 (RD_PS_excel + TO_AI_excel)
- **DOC-A 反代验证**: 直连 DocHub 200 + 反代 200, 字节级 sha256 一致 (`0aa727e4...`), magic bytes `504b0304` = ZIP/DOCX ✅

### 经验
- **3 QC 必须同时软化**：PATCH 28 单 QC 验证 71%，PATCH 29 3 QC 同时软化预期 100%（E2E 待验证）
- **m2.7 LLM 跨节点风格耦合**：system_prompt 相似时改 1 节点影响其他 2 节点；PATCH 28 已经发现这个现象
- **max_tokens 12000 是 thinking + JSON 双消费的最低保障**：PATCH 22 (4096→8000) 修主要截断, PATCH 29 (8000→12000) 修第 3 iter 残留
- **DocHub API camelCase 字段**：`templateId`/`outputFormat`/`dataJson`；dataJson 字段类型混合 (count_no/ip_count=number, 其他=string)
- **Dify 1.14+ 登录 tokens 在 cookies**：登录 body 只有 `{"result":"success"}`，tokens 全在 Set-Cookie header
- **nginx 反代作为 LAN 默认入口**：`/dochub-files/` 已就绪, 字节级 sha256 验证下载文件与直连 DocHub 一致

### 残留 + 下一步
- E2E 验证：用户需在 Dify UI 用真实 RD_PS_excel + TO_AI_excel 跑一次 debug run, 期望 QC 通过率 7/7 + QC-intro 0 passed.None
- 通过后 publish: `mcp__dify__dify_publish_workflow(app_id="7ab3c5fd-306a-4180-a99a-693604bd5c69")`
- 若 E2E 仍 fail: 单独检查是 QC-tech 还是 QC-accept 失败, 按对应模板继续微调

---

### PATCH 36 — 根治 RD_total_count 报 "Cannot convert"（**最长翻车链**）

- **时间**: 2026-07-06 12:30
- **app**: WF_RDReport v2 doc-ext 复刻 (`7ab3c5fd-...`)
- **症状**: PATCH 31-35 五次翻车：user 跑 workflow 都报 `Cannot convert 'sys.RD_total_count' to number`
- **翻车过程**: 5 次反复换命名空间，每次都揭露一个新约束：
  1. **PATCH 31** (9:32): start input (required=False, default=6) + break 引 `sys.RD_total_count` → 报"Cannot convert"
     - 失败根因：Dify 1.14+ start input default 在 console run **server 端不注入 pool**（agent 调研源码说注入，实测不注入）
  2. **PATCH 32** (10:00): 无关，DocHub nginx `/api/v1/files/` 反代 OK
  3. **PATCH 33** (10:00): 改 conversation_variable (default=6) → 未测
     - 失败根因：Dify 1.14+ conversation_variable 是 internal schema，UI 无 ConvPanel
  4. **PATCH 34** (10:02): 改 env variable `RD_TOTAL_COUNT` (default=6) → user 报"环境变量和系统变量均无此名称的字段"
     - 失败根因：`tool_published: false`（从未 publish）→ EnvPanel 看不到 env var
  5. **PATCH 35** (10:25): 改回 sys namespace + start input required=True, default=6 → 仍报"Cannot convert"
     - 失败根因：start input required=True 在 console run server 端**不 raise**（仅 client UI 阻止），default 也不注入
- **PATCH 36 修复** (12:30): env var + publish 方案
  1. 修正 env var `RD_TOTAL_COUNT` value "1" → "6"（PATCH 35 不知怎么改坏了）
  2. break_conditions 引 `{{#env.RD_TOTAL_COUNT#}}`（env 永远有 default 6 兜底）
  3. start input RD_total_count 改 required=false（友好，server 不 raise）
  4. **publish workflow**（让 EnvPanel 真的能显示 env var）
- **验证**: published version 4 个确认点全部正确
  - env var `RD_TOTAL_COUNT` = "6" ✓
  - break 引 `{{#env.RD_TOTAL_COUNT#}}` ✓
  - start input required=false, default=6 ✓
  - loop_count=100 ✓
- **根因总结**: Dify 1.14+ 三个变量命名空间"用户可改性"互斥
  | 命名空间 | API runtime 覆盖 | UI 改值 | schema default 兜底 |
  |---|---|---|---|
  | `sys.<start_input>` | ✅ | ⚠️ 跑时填 | ❌ console run 不注入 |
  | `env.<ENV_NAME>` | ❌ | ✅ EnvPanel | ✅ |
  | `conversation.<CV_NAME>` | ❌ | ❌ | ✅ |
  - 选 UI 改值 → env var + publish
  - 选 API 覆盖 → start input + required + 接受 server 端不 raise
  - 不可兼得
- **脚本**: `backups/_tmp_scripts/_patch36_env_var_publish.py`
- **备份**: `draft_BEFORE_PATCH_36_1783306925.json` + `draft_AFTER_PATCH_36_1783306925.json`
- **memory**: `dify-rd-total-count-patch-chain` (新建) — 三命名空间互斥表
- **反思教训**:
  1. 没在第一次就系统分析三个命名空间 trade-off → 反复在 sys/env/conv 之间切
  2. agent 调研的"start input default 会在 console run 注入"源码结论实测不成立 → 不要 100% 信 agent 调研，必须实测
  3. `tool_published` 字段不可靠，publish 成功的实际标志是 version 字段更新 + env var 在 published endpoint 返回
  4. 下次同类 PATCH 第一动作：**列出 sys/env/conv 三选 1 + 写明选哪个 + publish 验证**

---

## PATCH 37 — 「远方·专利顾问智能体」配真实联网检索 (minimax-m3 + Tavily)

### 时间
2026-07-06 12:00

### app
- **id**: `bd79ae53-e677-46e7-b64d-ad0d18449395`
- **name**: 远方·专利顾问智能体
- **mode**: agent-chat

### 症状
用户两次明确「你还得解决工具呀」：
- Qwen3.6-35B-A3B-NVFP4 + function_call 在 agent-chat 下 **4 配置** 都不主动调 tavily_search (19 参数): Qwen3.6 + Tavily_only / Qwen3.6 + Tavily+SearXNG (function_call) / 同 (React 策略) — 模型**从不** 调 Tavily, 反而选最简单的 searxng
- SearXNG science 引擎**不支持 site: 限定词**, 检索专利返回 Bing 噪音 (「固态硬盘推荐」)

### PATCH 翻车过程
1. **临时 1**: SearXNG only → Qwen3.6 调用, 返回 Bing 噪音 → ❌ 检索质量不可用
2. **临时 2**: Tavily + SearXNG → Qwen3.6 仍选 SearXNG, 不调 Tavily → ❌
3. **临时 3**: Tavily only → Qwen3.6 不调 → ❌
4. **临时 4**: 换 React 策略 + Tavily only → Qwen3.6 仍不调 → ❌ (4 配置全失败)
5. **PATCH 37 修复**: 切 minimax-m3 + Tavily only → 首次调用即成功 → ✅

### 根因
- **Qwen3.6 function_call 对高参数 schema (≥10) 倾向"装作不用"**: tool-call 解析逻辑对 Tavily 19 参数报不出稳定的 tool_call, 转而用最简 searxng (3 参数) 凑数
- **本实例 SearXNG 搜索引擎不支持 site: filter**: science 引擎返回通用 Bing 结果, 检索专利 = 检索噪音
- agent-chat "工具能用" 的真值 = **模型真的会调用 + 工具返回的确实是要的**, 不是"配置里有这个 tool"

### 修复
- **model**: Qwen3.6 → `minimax-m3` (`langgenius/minimax/minimax`, 本实例 tool-call 稳定模型, 见 `memory/dify-model-status-no-configure`)
- **tool**: SearXNG → Tavily only (锁定 `include_domains=patents.google.com,worldwide.espacenet.com,patentscope.wipo.int`)
- **prompt 加幻觉防护**: "只引用 tool 返回的 url+标题,禁止凭记忆补全专利号;字段缺失标注「以原网页为准」"
- **agent_mode**: strategy=function_call, max_iteration=5

### 验证
- ✅ minimax-m3 首次即调用 tavily_search (SSE `agent_thought` 含 tool 字段)
- ✅ 返回 URL 100% 是 patents.google.com (CN/US/EP/JP/KR 多国专利)
- ✅ POST /apps/{id}/model-config 返回 success, 配置已 persist
- ⚠️ minimax-m3 仍有轻度 hallucination: 会编畸形号 (CN1153325C0A), 但能自校正 — prompt 兜底已加

### PATCH 脚本 + 验证
- `backups/_tmp_scripts/_tmp_patch_patent_minimax_tavily.py` — 最终配置 patch
- `backups/_tmp_scripts/_tmp_test_agent_chat.py` — E2E 流式验证 (180s timeout, 解析 SSE agent_thought/agent_message/event)
- E2E 输出样例: `tavily_search.parameters.domains=[patents.google.com,www.patents.gov.cn,worldwide.espacenet.com,patft.uspto.gov]` → 返回 CN116014163A/US20230155123A1/EP4120412A1 等实链

### 反查表更新
| 报错 | 根因字段 | 修复 |
|---|---|---|
| agent-chat 配置了 Tavily 但模型不调用 (Qwen3.6) | Qwen3.6 function_call 对 19 参数 schema 解析失败, 转用 3 参数的 searxng | 切 minimax-m3 + function_call |
| SearXNG science 引擎检索专利返回 Bing 噪音 | 本实例搜索引擎不支持 site: 限定 | 换 Tavily + 锁定 include_domains=专利库 |
| minimax-m3 输出含畸形专利号 (CN1153325C0A) | 工具返回完整数据但模型补全时 hallucination | prompt 加"只引 tool 返回,禁止凭记忆补全" |
| `dify_update_app_model_config` 报 405 method_not_allowed | Dify 1.14+ 端点是 POST 不是 PATCH (PATCH 整体替换) | 改 `client.post` (MCP `dify_update_app_model_config` 已修) |

### 反思教训
1. **"配了工具" ≠ "能调工具"**: agent-chat 工具的真值必须 E2E 测 (调 + 返回对), 不是"配置里有"
2. **模型选择 > 工具选择**: 高参数工具 (Tavily 19 / Slack / GitHub 等) 必须配 tool-call 稳定模型, 否则配置白搭
3. **SearXNG 质量天花板**: 在不支持 site: 过滤的实例上是"假能用", 排查必须 E2E 试一次, 不能"配了就 ok"
4. **下次同类 PATCH 第一动作**: ① 确认模型 tool-call 能力 (`memory/dify-model-status-no-configure`) → ② 配 Tavily 时同时设 `include_domains` → ③ prompt 加幻觉防护

## 2026-07-06 15:15 — PATCH 38 「国高撰写助手」接入 workflow 工具 (配置成, 调不动)

### 问题
国高撰写助手 (8490e0d1) agent-chat app, agent_mode.enabled=true 但 tools=[] 空, pre_prompt 写"启动对应工作流"但实际无工具

### 5 步诊断
1. **症状**: app 列表确认 tools=[], 2 个候选 workflow (wf_研发立项拟题 + wf_研发立项书生成) 都在
2. **根因假设**: Qwen3.6 + react 不会主动调 ≥10 参数工具 (PATCH 37 已验证)
3. **修复 (配置层)**: 切 minimax-m3 + function_call + 2 workflow tool, pre_prompt 加工具映射, opening_statement 清空
4. **验证 (功能层)**: E2E 发"需求 A + 8 必填字段", agent_thought tool="" observation="" position=1 → 失败
5. **次根因诊断**: 试 react 同样不调; **对照实验** 📜 合同审查 (50cf3dc7) 同款问题 → 结构性局限

### 错误反查表 (新增)
| 症状 | 根因 | 修复 |
|---|---|---|
| agent-chat + provider_type="workflow" + minimax-m3 → tool="" | Dify 1.14+ agent-chat 调 workflow tool 协议 minimax-m3 vllm 端不识别 | 等 vllm 修 / 换 advanced-chat+answer 节点 / 换 LLM |
| agent-chat + provider_type="builtin" (tavily) + minimax-m3 → tool OK | minimax-m3 支持 builtin tool schema | (PATCH 37 已验证) |
| agent-chat + Qwen3.6 + 任意 provider_type → tool 不调 | Qwen3.6 function_call 模式对高参工具偷懒 | 切 minimax-m3 (PATENT) / 试 react (未验证) |

### 教训
- "配置 OK" 不等于 "能调" — agent 工具调用 3 关卡: ①配置对 ②模型愿意调 ③后端协议支持
- **PATCH 写完必须 E2E 验证 agent_thought.tool 非空**, 不能只 diff model_config 字段
- 对照实验 (📜 合同审查) 在 5 分钟内就揭示了真因, 避免反复 PATCH 浪费

## 2026-07-08 — PATCH 42 DocHub 模板 docx 占位符 0 MetaTemplates (双层 bug)

### 错误症状
WF_RDReport v2 doc-ext 复刻 (`7ab3c5fd-...`) 跑通后，下游 docx 下载打开看：
- 模板 28+ 处 `{{ xxx }}` 占位符**全部残留不替换**
- DocHub 日志（`docker logs dochub-app`）：
  ```
  Resolve the document end, resolve and create 0 MetaTemplates.
  Render template start...
  Successfully Render template in 0 millis
  ```
- 200KB docx 下载正常，但内容是"项目名称: {{ project_name }}" 这种原文

### 翻车过程（5 步才锁真因）
1. **查 workflow 链路**：dify_get_run_trace 看 tool 17830458579261 inputs.dataJson → 字段都非空 ✓
2. **下 docx 看 XML**：28 处 `{{ ... }}` 残留 ✗
3. **看 DocHub 日志**：锁定 Poi-tl 层问题（不是 Dify 配置问题）
4. **关键对照实验**（打破僵局）：
   - 用一个 simple 模板 `{{project_year}}`（无空格）→ 1 MetaTemplates ✓
   - 同一模板改名 `{{ name }}`（带空格）→ 0 MetaTemplates ✗
   - **结论：Poi-tl 1.12.2 默认 regex 对 `{{ var }}` 不识别**（关键突破）
5. **找上层 bug A**：直接 unzip 模板 docx 看 `{{ project_year }}` 在 Word 里被切成 4-6 个 `<w:r>`（Word 自动拼写检查 `<w:proofErr>` 副作用）
6. **两步修复都做**：单独跑任一步都不行，必须 (A) 合并跨 run + (B) 去占位符内边界空格

### 根因（双层，独立修复都无效）
- **Bug A — Word 切碎 run**：`{{ project_year }}` 被自动拼写检查切成 4-6 个独立 `<w:r>` 元素
- **Bug B — Poi-tl 1.12.2 regex 不识别空格**：默认 `DEFAULT_GRAMER_REGEX` 只匹配 `{{var}}`，不匹配 `{{ var }}`；**schema 提取**（上传阶段用另一 parser，能拿字段）与 **TemplateResolver**（渲染阶段）**用不同 parser**——schema 完整但 render 失败
- **叠加效应**：Bug A 让占位符变成多 run，Bug B 让单 run 也匹配不上 → 0 MetaTemplates

### 修复
- 脚本：`backups/_tmp_scripts/_patch42_docx_template_normalize.py`
- 部署路径：容器内 `/app/data/templates/tenant_default/word/e2bb9951-05a4-498d-8c1f-ff9ef47f560b.docx`（**注意 chown 到容器内 uid=1000**）
- 回滚：原文件备份到 `backups/_tmp_scripts/template_BEFORE_PATCH_42.docx`
- workflow **无需改动**：templateId 仍是 `e2bb9951-...`；Dify 端 0 改动

### 验证
- ✅ 11/16 字段替换成功（`project_year`/`project_name`/`start_date_cn`/`leader`/`project_year_cn`/`count_no`/`budget`/`finish_date_cn`/`expenses`/`labor_costs`/`ip_count`）
- ⚠️ 残留 5 个富文本字段（`project_intro`/`tech_innovation`/`project_deliverables`/`project_achievements`/`comprehensive_profits`）：docx 里仍残留 `{{r xxx}}` —— **Poi-tl 1.12.2 不支持 `{{r xxx}}` 富文本语法**（需 1.13+）；可通过升级 DocHub 内 Poi-tl 版本解决

### 反查表更新
| 报错 | 根因 | 修复 |
|---|---|---|
| DocHub generate 200 OK + 200KB docx，但占位符全残留；日志 `0 MetaTemplates / Render template in 0 millis` | (A) Word 切碎 run + (B) Poi-tl 1.12.2 regex 不识别 `{{ xxx }}` 含空格 | Step 1 合并跨 run 占位符 + Step 2 去占位符内边界空格 |
| DocHub generate 后 docx 残留 `{{r xxx}}` 富文本占位符 | Poi-tl 1.12.2 不支持富文本语法（需 1.13+） | 升级 DocHub 内 Poi-tl 到 1.13+；或暂接受 docx 里残留 `{{r xxx}}` |
| DocHub `/api/v1/templates/{id}/schema` 字段完整，但 generate 渲染 0 个 | schema 提取与 TemplateResolver 是不同 parser，schema 阶段松渲染阶段严 | 必须端到端测一次 render，不要"schema 在就当 OK" |

### memory
[[poi-tl-placeholder-spaces-and-runs]]（新建）

### 反思教训
1. **schema OK ≠ render OK**：DocHub 的 schema 提取和 TemplateResolver 用不同 parser，"提取阶段字段全在"不代表"渲染能替换"——必须 **端到端 render 一次**才能下结论
2. **0 MetaTemplates 第一查证处是 DocHub 日志**：拿到这个信号就锁 Poi-tl 层，不用去查 Dify workflow
3. **简单对照实验是破局关键**：从 `{{name}}` (no space) vs `{{ name }}` (with space) 对照，5 秒定位 regex 敏感
4. **Word 自动拼写检查是 docx 占位符的天敌**：写完模板要养成**保存前关闭 proofErr** + **占位符用 `<w:noProof/>` 包起来**的习惯
5. **修复 docx 模板不需要重启 DocHub**：`docker cp` 覆盖文件即生效
6. **Poi-tl 1.12.2 的硬限制**：富文本 `{{r xxx}}` 1.13+ 才支持，这是升级路径决策点

