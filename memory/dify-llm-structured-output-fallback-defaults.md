---
name: dify-llm-structured-output-fallback-defaults
description: m2.7-highspeed LLM thinking 模式下 structured_output 可能缺字段; 必须在 LLM 后插 1 个 defensive code node 把 14 字段全部 default 化, 再让下游 read from code node (而不是直接 read from LLM), 解决 'Variable #X.field# not found'
metadata:
  type: project
---

Dify 1.14+ workflow 含 LLM `structured_output_enabled=True` 时, LLM 用 thinking 模式可能 max_tokens 用完仍没 emit JSON, 输出 `text` 字段 but no structured_output, 下游 `{{#node.field#}}` 报 "Variable #X.structured_output.Y# not found"。

**PATCH 24 修复方案 (proved on run 5f19c8a6..)**: 在 LLM extract 后插 1 个 code node "提取字段兜底" —
- `variables[0].value_selector = [EXTRACT_LLM_ID, "structured_output"]` (整个 dict 拉进去)
- `outputs` dict 14 字段每个都给 `{type, value_type, children: null}` (带 value_type 避免 UI 降级显示 array index)
- 代码 `def main(extract=None)`: 若 `not isinstance(extract, dict)`, 默认 `{}`; 每个字段 `extract.get(f)` 后 None → 默认值 (str→"" / int→0 / list→[])
- 改所有下游 user prompt `{{#EXTRACT_LLM.structured_output.X#}}` → `{{#NEWNODE.X#}}`
- 加边 `EXTRACT_LLM → NEWNODE → 所有 downstream`
- POST 时 body 必须含 `features/environment_variables/conversation_variables/hash` 否则 400/409

**PATCH 25 补充**: code node 17830458386560 里 `len(intro_text)` 等没 None 兜底, 当 LLM QC structured_output.improved_text 为 None 时崩; 改 `len(X or "")`。

**Why:** 上一轮 PATCH 22 bump max_tokens=8000 不够, thinking 仍占满; PATCH 23 改 QC writer 引用还是不够, iter 1 仍 crash; 只有在 LLM 后插兜底层才能挡出 NoneType 异常。

**How to apply:** 含 LLM `structured_output_enabled` 的 workflow 必须 double-check:
1. LLM 后是否所有引用都经过 defensive layer (新插 code node or 使用 `{{var|default('', true)}}` 但 Dify 1.14+ `{{#var#}}` 解析在 jinja2 之前, default filter 不起作用, 必须用 code node)
2. code node 里所有 len/split/iteration 都对 None 兜底
3. POST PATCH body 必含 `hash` (来自 GET /workflows/draft, 防并发守卫 409 `draft_workflow_not_sync`)
4. 验证用 E2E run `total_steps >= 6` + `status=succeeded` 才算 PATCH 闭环
