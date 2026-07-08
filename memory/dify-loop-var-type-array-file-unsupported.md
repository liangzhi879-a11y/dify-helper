---
name: dify-loop-var-type-array-file-unsupported
description: Dify 1.14+ graphon LoopNodeData.loop_variables[].var_type 不接受 array[file]，合法值只有 string/number/object/boolean + array[string/number/object/boolean]
metadata:
  type: project
---

Dify 1.14+ 后端 `LoopNodeData.loop_variables[].var_type` 是严格 enum（Pydantic v2 + graphon 包 `graphon/nodes/loop/entities.py:20-26 _VALID_VAR_TYPE`），合法值是 frozenset 子集：

```
STRING/NUMBER/OBJECT/BOOLEAN + ARRAY_STRING/NUMBER/OBJECT/BOOLEAN
```

**`array[file]` 不在合法集合中**（虽然 SegmentType 有 file，但 LoopVariable.var_type 不允许 file 类型）。

错误响应原文：
```
1 validation error for LoopNodeData
loop_variables.22.var_type
  Value error, Ellipsis [type=value_error, input_value='array[file]', input_type=str]
```

**Why**: PATCH 39 (2026-07-07) 想给 loop 节点加 `rd_doc_files` 收集 DocHub 下载的 IP 文件，用 `var_type: "array[file]"`。运行 workflow 时报 Pydantic 校验失败（draft 加载 OK 但运行 workflow 时 strict validation 触发）。rollback 已完成，draft 恢复到 PATCH 39 前可用状态。

**How to apply**:

1. **新增 loop 变量前必查合法 var_type**：合法 = `string | number | object | boolean | array[string] | array[number] | array[object] | array[boolean]`，**禁止 array[file]**
2. **想要 file 类型怎么办**：
   - 降级为 `array[object]` 存 file descriptor（语义弱，下游需自己 fetch）
   - 降级为 `array[string]` 存 URL 列表（语义清晰，需 HTTP 节点返回 files[].url）
   - 不放 loop variable 里，改用 workflow env / conversation variable 存
3. **同一字段链路要一起改**：loop var 改 var_type 时必须同步改 `loop.outputs[label].type` 和下游 `end.outputs[].value_type`（PATCH 39 改了 4 处：`loop_variables[22]` + `loop.outputs.rd_doc_files` + `end.outputs[rd_doc_files]` + `assigner.items`）
4. **rollback 前先 GET 当前 hash**：Dify 1.14+ 的 `POST /apps/{id}/workflows/draft` 有 draft_workflow_not_sync 409 守卫，必须 GET 拿当前 hash 覆盖 BEFORE 备份的旧 hash（PATCH 39 rollback 翻车 1 次 → 改脚本加 `[hash] refreshed to current` 步骤）
5. 见 [[dify-loop-outputs-type-mismatch]] loop outputs 类型要与 assigner append 实际值一致

**PATCH 39 rollback 落地证据**：

- 失败响应：`backups/_tmp_scripts/run_resp_PATCH_39.json` (完整 pydantic 错误)
- PATCH 脚本：`backups/_tmp_scripts/_patch39_workflow_outputs.py`（已加注释"已知 array[file] 不合法"）
- Rollback 脚本：`backups/_tmp_scripts/_patch39_rollback.py`（已加固：GET 当前 hash 覆盖 BEFORE hash）
- 备份：`draft_BEFORE_PATCH_39_7ab3c5fd.json` (112KB) + `draft_AFTER_PATCH_39_7ab3c5fd.json` (113KB)
- 恢复后 hash：`65cd1bed1b2e270e1189484a05b783c77d260c6f75702387e68ec1885b730f10`（PATCH 39 前的原 hash）
- 改完 validate：`dify_validate_draft` 返回 `valid=true, error_count=0, warning_count=0`