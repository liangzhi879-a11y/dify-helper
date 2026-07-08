---
name: dify-loop-children-stale-orphan-nodes
description: Dify loop node 的 children 是独立小 workflow 副本，节点替换后旧 children-only 节点变 orphan 死代码；清理时必须同步删 children.nodes 和 children.edges，否则 Dify 报 broken edge
metadata:
  type: project
---

Dify loop node 的 `children` 字段是一个**独立 mini-workflow 副本**：
- `children.nodes`: 子节点列表
- `children.edges`: 子节点之间的边
- 与顶层 `graph.nodes/edges` 平行，但只服务于 loop 内部画布渲染

**当顶层节点被替换**（如 `tmpl_assemble_001` → `17830458386560` 时间戳 ID），**children 里的旧副本不会自动删除**。结果是：
- children.nodes 里有 10+ 个旧节点的副本（semantic ID 命名）
- children.edges 里有 12+ 条边引用这些旧节点
- 顶层 edges 0 条引用旧节点 → 旧 children **运行时不执行**，仅画布展示混乱

**清理 SOP**（强制 2 步原子提交）：

```python
# 1. 收集顶层 node IDs
top_ids = {n["id"] for n in draft["graph"]["nodes"]}

# 2. children.nodes: 只保留顶层有的 ID
keep_ids = {n["id"] for n in loop["children"]["nodes"] if n["id"] in top_ids}
loop["children"]["nodes"] = [n for n in loop["children"]["nodes"] if n["id"] in keep_ids]

# 3. children.edges: 只保留 source AND target 都在 keep_ids 里的边
#    ⚠️ 必须同步清，否则 children 内部 broken edge，Dify 可能拒绝保存
loop["children"]["edges"] = [
    e for e in loop["children"]["edges"]
    if e["source"] in keep_ids and e["target"] in keep_ids
]
```

**为什么 children 不能整体删空**：保留 3 个 dual 副本节点（loop-start + 上下游共享节点）是 Dify 引擎要求，否则 loop body 无法渲染。参考 [[dify-dual-copy-children-vs-top]]。

**Why**: PATCH 14 (2026-07-04) 修 WF_RDReport_v2 loop children，原 13 nodes + 15 edges → 3 nodes + 1 edge，DSL 备份从 122040 bytes → 79463 bytes（少 38KB 死代码）。

**How to apply**:

1. 替换 loop 内子节点后，**必查 children 里的旧副本**（用 `dify_get_workflow` 拿完整 draft）
2. children.nodes / children.edges 必须在**同一次 PATCH** 里同步改（否则 broken edge）
3. 保留 ID 时严格用 `top_ids` 交集，不要凭"看着像旧"删除
4. 见 [[dify-dual-copy-children-vs-top]] 关联双份副本机制

**PATCH 14 落地证据**：

- 节点：`1782973016950`（loop node）
- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_14_20260704_190725.json` (147065 bytes)
- 改完 hash：`33d5211f6c6882df`（前 `f1af00107e0b4137`）
- children.nodes: `13 → 3`（删 10 个 children-only: tmpl_assemble_001 / http_dochub_001 / 1783046156812 / assigner_qc_001 / llm_intro_001/llm_tech_001/llm_accept_001 / qc_intro_001/llm_tech_001/llm_accept_001）
- children.edges: `15 → 1`（删 14 条引用已删节点的边，保留 loop-start → 1782973526197）
- 发布版本 DSL 备份：`dsl_published_AFTER_PATCH_14_20260704_190725.yaml` (79463 bytes, 前 122040 bytes)
- PATCH 脚本：`_tmp_patch_p1_4_clean_children.py`