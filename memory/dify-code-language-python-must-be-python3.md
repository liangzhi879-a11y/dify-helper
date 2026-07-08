---
name: dify-code-language-python-must-be-python3
description: Dify 1.14+ (graphon 包) CodeNodeData 的 code_language 枚举值必须是 'python3' 或 'javascript'，'python' (无 3) 会触发 pydantic literal error
metadata:
  type: project
---

Dify 1.14+ 的 `graphon.nodes.code.entities.CodeNodeData` 用 pydantic `Literal["python3", "javascript"]` 校验 `code_language`，**不接受 `'python'`**。

**症状**：
```
2 validation errors for CodeNodeData
  code_language: Input should be 'python3' or 'javascript' [type=literal_error, input_value='python']
  outputs: Input should be a valid dictionary [type=dict_type, input_value=list]
```

**根因**：code node 创建/迁移过程把 `code_language` 写成 `python`，Dify 早期版本容忍，新版 graphon 拒绝。同时新 schema 要求 `outputs` 是 dict（不是 list）。

**正确做法**：
1. 创建 code node 时 `code_language: "python3"`（注意带 3）
2. outputs 必须 dict 格式：`{"var_name": {"type": "string", "value_type": "string", ...}, ...}`
3. PATCH 旧 code node：批量扫 `data.type == "code"`，统一 `code_language="python3"` + 转换 outputs

**Why**: PATCH 16 (2026-07-04) 修 WF_RDReport_v2 doc-ext — 2 个 code 节点（task_summary_001 + 段落组装）用 `'python'`，5 个 nodes outputs 是 list。全部 PATCH 后 hash `a707ac71ef3fd5b5 → 9aa919dce4579fd9`。

**How to apply**:
1. 任何 PATCH/创建 code node 前，**先 `dify_get_app_node` 校对** code_language 是 `"python3"`
2. 听到 "CodeNodeData validation error" 必看 `code_language` 字段
3. 看到 `outputs` 是 `[{variable, type, value_type}, ...]` 必转 dict
4. 见 [[dify-code-node-outputs-dict]] 关联 outputs dict 格式 + [[dify-loop-qc-raise-terminates]] 关联 loop 内 code 节点 raise 终止问题

**PATCH 16 落地证据**：
- 节点：5 个 code nodes（task_summary_001 + 3 个 QC + 段落组装）
- 改：2 个 code_language + 5 个 outputs 格式
- 备份：`backups/_tmp_scripts/draft_BEFORE_PATCH_CODE_OUTPUTS_20260704_224831.json`
- PATCH 脚本：`backups/_tmp_scripts/_tmp_patch_code_outputs_format.py`
- hash：`a707ac71ef3fd5b5 → 9aa919dce4579fd9`
