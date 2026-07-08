---
name: dify-patch-first-compare-normal-node
description: PATCH Dify workflow 出错时，第一动作必须是"拉一个同类正常工作节点对比 schema"，而不是反复试错
metadata:
  type: feedback
---

Dify workflow 任何 PATCH 出错时（"渲染错误"、UI 显示异常、API 拒绝），**第一动作**：

1. 在同 app 内（或同租户其他 app）找**一个已知工作正常的同类节点**（QC 错就找另一个 code 节点，LLM 错就找另一个 llm 节点）
2. `mcp__dify__dify_get_app_node(app_id, normal_node_id)` 拉它的完整 data
3. **逐字段对比**：问题节点的 data 跟正常节点的 data 有什么字段差异
4. 找到差异字段 → 单独 PATCH（**1 字段 1 改**）→ 验证

**Why**: 上一轮 PATCH 1-7 在 QC node 翻车 5 次，每次都"改字段试一下"。PATCH 9 凌晨在对比 `task_summary_001` (5 outputs 都有 value_type) vs `1783045599913` QC-项目简介 (只有 2 字段) 时**立刻找到根因**。对比法是当前最有效的调试方法，不是经验。
**How to apply**:

- 任何 PATCH 前 **必须先对比正常节点 schema**（接受这个 SOP 作为强制动作）
- 见 [[dify-code-node-outputs-require-value-type]] 是这次的具体案例
- 见 [[dify-workflow-canvas-debugger]] skill 的预检流程
- bug-diagnostician skill 强调的"信号源 → 假设 → 验证 → 修复"在 Dify workflow 场景下等价于"对比正常节点 → 找假设 → 改字段 → 验证"

**反模式（已翻车过的）**：
- ❌ "改 6 字段试一下"（loop iteration 节点构建那轮翻车的根因）
- ❌ "看 console 报错就开始改字段"（不对比正常节点 = 瞎猜）
- ❌ "publish/unpublish 试触发 cache 失效"（PATCH 6/7 已验证无效）
- ❌ "PATCH 8 加 type 字段到 prompt_template messages"（修了 `.type` 报错但没真正修输出变量名问题 — 没找到真根因）
