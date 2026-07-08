---
name: dify-loop-output-selector-not-required
description: Dify 1.10-1.14 loop 节点的 output_selector 不是后端必填字段（BaseLoopNodeData 不含），是 frontend UI 残留；可保持 3-tuple 指向内部 LLM 不影响 backend 执行
metadata:
  type: project
---

Dify loop 节点的 `output_selector` 字段在 `BaseLoopNodeData` (api/core/workflow/nodes/base/entities.py) 里**根本不存**。

**重要**：该字段是 frontend UI 用来追踪"loop 主要输出是哪个"的元数据，**backend 执行不校验**。

**症状（误判）**：
- mcp_server `_NODE_SCHEMAS` 误把 `output_selector` 列在 `data_required` → 让人以为 backend 要求
- 看到 `output_selector: ["<inner_node>", "<field>", "<subfield>"]` 3-tuple 指向 loop 内部节点会以为这是 BUG
- 其实该字段可保留旧值不影响 run，**下游消费方**用 `value_selector` 读 loop 的 `.outputs` dict keys（rd_intro_texts / rd_qc_summaries 等），格式是 `["<loop_id>", "<output_key>"]` 2-tuple

**正确做法**：
1. 修改 loop 相关 PATCH 时**不要改 `output_selector` 字段**，除非确证用户在前端看到它
2. 下游读取 loop 输出用 `value_selector` 而非 `output_selector`
3. 不要被 `_NODE_SCHEMAS` 误列表误导
4. 当用户报"循环节点配置问题"时，第一动作是**看 run 的实际 error**（如 `Operation += is not supported for type array[any]`），不是去翻 `output_selector`

**Why**: 2026-07-04 调研 WF_RDReport_v2 (cb154f61) loop node，`output_selector` 是 `['<inner_llm>', 'structured_output', 'project_name']`，3-tuple 指向内部 LLM。最成功的 run (88c2f6c6, 36 RD) 用该 draft 跑通，说明 backend 不读这字段。

**How to apply**:
1. 任何 loop/iteration PATCH 调研时，先用 `diffy_get_app_node` 看实际 `data`，**不要靠 `_NODE_SCHEMAS` 的 required 推断是否缺字段**
2. 如果只是看到 `output_selector` 长相怪异但 run 能通，**不动它**
3. 见 [[dify-loop-iteration-builder]] 关联 loop 必填字段判别

**追溯证据**：
- Dify 1.10 `api/core/workflow/nodes/loop/entities.py` 43 行 `LoopNodeData(BaseLoopNodeData)` 没有 output_selector
- Dify 1.10 `api/core/workflow/nodes/base/entities.py` 159 行 `class BaseLoopNodeData(BaseNodeData)` 也只有 `start_node_id`
- 唯一 `output_selector` 字段出现在 `BaseIterationNodeData` 的延伸使用（iteration 节点专属），loop 不复用
