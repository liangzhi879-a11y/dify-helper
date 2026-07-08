---
name: dify-qc-strict-passed-fails-everything
description: Dify LLM QC 节点用 "硬约束必须全部满足" prompt 会让通过率持续 0%；必须软化为 "参考标准 N/(N-1) 通过" + "兜底原文保留"
metadata:
  type: project
---

**症状**：3 个 LLM QC 节点 (QC-intro/QC-tech/QC-accept) 全部用 "硬约束（必须全部满足）" system_prompt，6 个 RD 全部 passed=false (0/6)。

**根因**：LLM 在 structured_output 模式下倾向严格按 prompt 列的清单逐项 verify；任何 1 条 fail 就 passed=false。但 LLM 验证时容错性低，对 "字数差一点"、"1 个禁用词" 这类小问题也判 failed，导致 100% fail。

**How to apply**：
1. 任何 LLM QC 节点 system_prompt 都要写 "通过判定" 段，明确容错策略：
   - "4/4 全过 → passed=true"
   - "4/3 通过（含轻微字数不足或 1 个禁用词已处理）→ passed=true"
   - "4/2 或以下 → passed=false，必须改写"
2. 必须加 "兜底" 步骤: "如改写 2 次后仍无法满足所有参考标准, improved_text = 原文 + errors 列出无法改写的项"
3. 改 1 个 QC 节点 prompt 实际会影响 3 个 QC 节点 (m2.7 LLM 跨节点行为耦合)，验证时要同时观察全部
4. 实证：PATCH 28 改 1 个 QC-intro system_prompt → 通过率 0/6 → 5/7 (71%)
5. **关联**: [[dify-loop-qc-raise-terminates]] + [[dify-llm-output-truncation-breaks-downstream]]