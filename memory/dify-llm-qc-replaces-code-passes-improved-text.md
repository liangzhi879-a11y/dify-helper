---
name: dify-llm-qc-replaces-code-passes-improved-text
description: Dify QC code 节点用 LLM 节点替代时，structured_output 字段名必须后向兼容原 code outputs dict；段落组装 value_selector 要从 2-tuple 改 3-tuple ['structured_output','improved_text']
metadata:
  type: project
---

Dify 工作流里 QC code 节点（review-only）改造成 LLM 节点（review + auto-improve）时，**必须**保留原 outputs dict 字段名让下游代码 0 改动。

**核心约束**：
- 原 code 节点 `data.outputs = {"<prefix>_section": {...}, "<prefix>_passed": {...}, ...}`，下游用 `value_selector = ["<node_id>", "<prefix>_section"]`（2-tuple）读取
- 新 LLM 节点用 `structured_output_enabled: True` + JSON schema，输出在 `data.outputs.structured_output` 下面
- 下游必须改用 3-tuple：`value_selector = ["<node_id>", "structured_output", "<new_field>"]`
- LLM 输出的"最终文本"字段（如 `improved_text`）替代原 code 输出的"原始段落"字段（如 `<prefix>_section`）

**正确做法**：
1. LLM system prompt 明确"审核 + 自动优化改写"双重职责，passed=false 时必须重写
2. JSON schema 字段命名**沿用原 code outputs 字段名**做最小破坏（passed/section/length/bullets/errors 可直接复用；review 是新加的可选调试字段）
3. 段落组装/累积 nodes 的 `value_selector` 同步更新：每条 QC 输出 2-tuple → 3-tuple
4. 累积 items 读 tool 节点输出从 `["http_node_id", "body"]` 改 `["tool_node_id", "text"]`（tool 节点暴露 text 而非 body）

**Why**: PATCH 17 (2026-07-04) 重建 WF_RDReport_v2 (cb154f61) — 用户报告"循环 QC 节点代码太复杂不好调整"，要求用 LLM 替代 3 个 QC code 节点（既审查又自动优化） + 用 DocHub 插件替代 HTTP 节点。

**How to apply**：
1. 听到"用 LLM 替代 QC code"或"review + auto-improve"先查原 code outputs dict 字段名
2. 新 LLM JSON schema 用相同字段名 + 加 `improved_text` 字段保存改写结果
3. 段落组装 / 累积 等下游节点的 `value_selector` 从 2-tuple 改 3-tuple，每改一条单独 PATCH + 用户验证（**不要一次全改**）
4. 关联 [[dify-dual-copy-children-vs-top]] loop children 不要动（PATCH 17 重建的 4 个新节点都在 top-level，不进 children）
5. 关联 [[dify-code-node-outputs-dict]] 原 code outputs dict 格式；schema 字段命名要与原 dict key 对齐

**PATCH 17 落地证据**：
- 删 4 节点：1783045599913/1783045657863/1783045701592 (3 QC code) + 17830458579260 (http)
- 加 4 节点：1783045599914/1783045657864/1783045701593 (3 LLM QC) + 17830458579261 (DocHub tool)
- 段落组装 6 个 variables 改 value_selector 2-tuple → 3-tuple
- 累积 1 个 item 改 value [old_http, "body"] → [new_tool, "text"]
- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_17_20260704_231433.json`
- PATCH 脚本：`backups/_tmp_scripts/_tmp_patch_p17_llm_qc_dochub.py`
- hash：`9aa919dce4579fd9 → 465460d23a445f0f`
- 模型：`langgenius/minimax/minimax` + `minimax-m2.7`（与现有 LLM 一致）
- DocHub 插件：`dochub/dochub/dochub` + tool `generate_document`（参数 template_id/data_json/output_format）

**DocHub 插件前置条件**（用户需在 Dify 设置页配置）：
- workspace-level `team_credentials`: `api_key` + `base_url`（不在 workflow 节点里）
- workflow 环境变量 `RD_REPORT_TEMPLATE_ID`（已有）
- 当前 `team_credentials` 是空的 `{"api_key": "", "base_url": ""}`，**用户需要去 Dify 设置页配**