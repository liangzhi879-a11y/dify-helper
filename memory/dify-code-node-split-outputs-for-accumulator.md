---
name: dify-code-node-split-outputs-for-accumulator
description: Dify code 节点输出供下游 assigner 累积时，必须按累积字段 1:1 拆 outputs（如 intro/tech/accept 分别输出），不能只输出合并后的完整 markdown
metadata:
  type: project
---

Dify loop 节点的 assigner / variable-aggregator 累积只能 append **单一字段**。
若 code 节点输出 1 个合并字段（如 `assembled_markdown` 含 3 板块），累积后下游拿到的就是 N 份"完整 markdown"副本，**无法按板块区分**。

**症状**：
- 累积字段 `rd_intro_texts / rd_tech_texts / rd_accept_texts` 永远是空数组（因为 code 节点只输出 1 个字段）
- 即便某些项目只 append 了 intro，tech/accept 数组也始终为 `[]`
- task_summary 节点声明这些字段但拿不到内容（即使参数对得上，value 是空数组）

**正确做法**：
1. code 节点在 `outputs` 里按累积字段 1:1 拆字段输出（如 `intro_markdown / tech_markdown / accept_markdown` 3 个独立 string）
2. return dict 加对应 key，每个 key 的值是**单一板块内容**（不含其他板块）
3. outputs 条目必须同时含 `type` + `value_type`（参考 [[dify-code-node-outputs-require-value-type]]）
4. 累积节点 assigner 按"1 累积字段 ← 1 source 输出"配对，逐个 append

**反模式**：
- 只输出 1 个 `assembled_markdown`，靠下游文本解析拆 3 板块 → 脆弱、改 1 个字段影响 3 个累积
- 输出 1 个 array（如 `sections: [intro, tech, accept]`）→ assigner append 后变成嵌套数组，下游还得 flatten

**Why**: PATCH 12 (2026-07-04) 修 WF_RDReport_v2 段落组装节点，原本只输出 `assembled_markdown`（3 板块拼一起），assigner 只 append 1 次 → `rd_intro_texts` 是 N 份完整 markdown，`rd_tech_texts / rd_accept_texts` 永远是空。

**How to apply**:

1. 设计 code 节点 outputs 时先想下游累积字段 → 按 1:1 拆
2. 保留合并字段（如 `assembled_markdown`）兼容老代码，但同时输出分字段
3. assigner items 的 `variable_selector` 和 `value` 必须严格对应（如 `['loop', 'rd_intro_texts']` ← `['code_node', 'intro_markdown']`）
4. 见 [[dify-loop-iteration-builder]] 关联 loop 节点必填字段 + [[dify-code-node-outputs-require-value-type]] 关联 value_type 必含

**PATCH 12 落地证据**：

- 节点 A：`17830458386560`（段落组装 + DocHub dataJson 构建）
  - 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_12_20260704_190518.json` (145545 bytes)
  - 改完 hash：`bfef313fa5382f47`（前 `769e5a30b26856ba`）
  - code 改动：插入 3 个分板块字符串变量 + return 加 3 个新字段
  - outputs 改动：头部插入 `intro_markdown / tech_markdown / accept_markdown` 3 条
- 节点 B：`17830458757270`（assigner 累积 3 板块 + DocHub URL）
  - items 从 3 → 5（改 1 + 新增 2）
  - `rd_intro_texts` value: `assembled_markdown` → `intro_markdown`
  - 新增 `rd_tech_texts ← tech_markdown`
  - 新增 `rd_accept_texts ← accept_markdown`
- 发布版本 DSL 备份：`dsl_published_AFTER_PATCH_12_20260704_190518.yaml` (122039 bytes)
- PATCH 脚本：`_tmp_patch_p1_1_split_section.py`