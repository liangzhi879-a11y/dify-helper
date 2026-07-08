---
name: dify-defensive-node-must-be-in-loop
description: Dify defensive code node 必须放在 loop 内 (parentId=loop_id, data.isInLoop=true)，否则 every-iter 重建，outputs 跨 iter 不一致；下游 nodes (writers/QCs/段落组装) 引用要切到 in-loop node ID 才能拿到 per-iter 字段
metadata:
  type: project
---

Dify 1.14+ loop 节点的特殊结构：**节点可"逻辑上属于 loop"但物理上在顶层 graph.nodes**，标志是 `parentId=<loop_id>` + `data.isInLoop=true` + `data.loop_id=<loop_id>`。loop.children[] 只装真正的循环起点-终点 mini-workflow (3 个: loop-start → 入口 node → 变量赋值) — 其他"参与 iter"的节点都靠 parentId 标记。

**PATCH 24 翻车教训**: 我把 defensive code node "提取字段兜底" 放在 wf.graph.nodes 但**没有 parentId**，等于放在 loop 外侧；它在 workflow 启动时跑一次（不参与 iter），结果 writers/QCs 的 per-iter 输出拿不到。所以 iter 0~5 跑到 writer 时 "Variable #defnode.field# not found"。

**用户修复方式 (PATCH 26 setup)**: 在 UI 把 defensive node **拖进 loop 框内**，Dify 自动给它加 `parentId=1782973016950` + `data.isInLoop=true` + `data.loop_id=1782973016950` —— 这时它在 every-iter 重建，outputs 14 字段都是该 iter 的。

**PATCH 26 修下游引用**:
- writers + QCs (6 个) user_prompt: `{{#OLD_ID.field#}}` → `{{#NEW_INLOOP_ID.field#}}`
- 段落组装 code node (17830458386560) value_selectors: `["EXTRACT_LLM_ID", "structured_output", "X"]` → `["NEW_INLOOP_ID", "X"]` (走 defensive layer 而不是 direct extract LLM)

**关键校验**:
- 不在 loop 内的 defensive node: outputs 是单次执行值 (不会随 iter 变), writers 拿到的永远是 iter=0 时的值或 stale
- 在 loop 内 (parentId=loop_id) 的 defensive node: outputs 是 per-iter 值, writers 拿到本 iter 的 14 字段 ✓

**Why:** 上一轮 PATCH 24 我光顾修 "Variable not found" 忘记 loop iter 语义，导致 patch 24 看似跑通 iter 0 实则 writers 拿到 stale data。rerun 时还是 fail。

**How to apply:** 加 defensive code node 时**第一步**确认它是不是在 loop 内:
1. GET draft, 检查 `node.parentId == loop_id`
2. 若不在, 必须把 `parentId/loop_id/isInLoop` 写入 (UI 拖放或者 PATCH 直接写)
3. 加边 EXTRACT_LLM → DEFNODE → DOWNSTREAM 时, parentId 必须一致 (Dify 会校验)
4. POST body 必含 `hash` 防 409
5. 验证用 E2E run `total_steps >= 6` + check `node_executions[def_node].loop_index` 出现在每 iter (per-iter 字段)

关联: [[dify-dual-copy-children-vs-top]] (children + 顶层副本一致性) + [[dify-llm-structured-output-fallback-defaults]]
