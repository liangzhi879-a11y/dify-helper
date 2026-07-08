---
name: dify-code-node-outputs-require-value-type
description: Dify code node outputs[] entry 必须同时含 type + value_type 两字段，否则 UI 降级用 array index（"0"/"1"/...）作 label
metadata:
  type: project
---

Dify code node `outputs[]` entry schema（实测 1.14+）：

```json
{"variable": "<name>", "type": "string|number|boolean|array[string]|object", "value_type": "<同 type>"}
```

**必含 3 字段**：`variable` + `type` + `value_type`（`task_summary_001`、`assembled_markdown` 等正常节点都同时有这 3 键）。

**如果只填 `variable + type` 不填 `value_type`**：

- Dify UI 把 outputs[] 渲染时，对缺 `value_type` 的 entry **降级显示为 array index `0`、`1`、`2`、`3`、`4`**（不是 "0"/"1" 字符串，是真 array index 作 fallback label）
- 这就是用户报告的"输出变量是 0/1/2/3/4"的真相
- 同时用户在 Dify UI 点这个 outputs 编辑框改名字，会触发前端 `Cannot read properties of undefined (reading 'type')` 报错（UI 内部按 value_type 做类型推断）

**Why**: PATCH 9 (2026-07-04) 修 WF_RDReport v2 doc-ext 6 个 QC code node，Q&A 翻车 5 次才找对根因。
**How to apply**:

1. PATCH 改 code node outputs 时，**默认补全 value_type = type**
2. 调试 "UI 显示 0/1/2/3/4" 类问题时，**先拿一个已知正常的 code node 对比 schema**（如 `task_summary_001`）
3. 写新 PATCH 脚本时，把 value_type 检查写进 verify 函数（避免漏）
4. 同步到 `mcp_server/server.py` 的 `_NODE_SCHEMAS` 字典的 code 节点定义
5. 见 [[dify-dual-copy-children-vs-top]] 注意 loop 节点的 children 副本要一起改

**PATCH 9 落地证据**：

- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_VALUE_TYPE_20260704_111059.json` (143972 bytes)
- 改完 hash：`cb323480c6d94c75`
- 6 个 QC node outputs.keys set 全部 = `{('type', 'value_type', 'variable')}`
- 发布版本 DSL 备份：`dsl_published_AFTER_VALUE_TYPE_20260704_111059.yaml` (120621 bytes)
- PATCH 脚本：`_tmp_patch_add_value_type.py`
