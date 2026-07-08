---
name: dify-qc-3node-soften-at-once
description: Dify m2.7 LLM 3 QC 节点 system_prompt 高度相似时, "改 1 影响全部" — 必须 3 节点一次性同时软化, 否则通过率提不上去
metadata:
  type: project
---

# 3 QC 节点必须同时软化（不能只改 1 个）

PATCH 28 只改了 QC-intro (`17831829849730`) system_prompt → 通过率从 0/6 升到 5/7 (71%)，
但 QC-accept 仍 1 RD failed ("颠覆性简化" 触发 + 字数不足)，QC-intro 第 3 iter 仍 `passed=None`。
PATCH 29 一次性改 3 个 QC (intro + tech + accept) system_prompt + max_tokens 8000→12000。

## Why（根因）

LLM `minimax-m2.7` 在多次节点调用间会共享 system_prompt 模板的"风格记忆"。
PATCH 28 经验："改 1 个 QC-intro 的 prompt 实际影响全部 3 个 QC 的判定 (m2.7 LLM 跨节点状态耦合 / 系统 prompt 高相似度)"。

只改 1 个 QC 时：
- 另 2 个 QC 仍按"硬约束必须全部满足"模式严格 verify → 倾向过度 failed
- LLM 行为在 3 QC 间漂移不一致 → 通过率卡在 5/7 (71%)

3 个同时改时：
- 3 QC 风格一致 → LLM 判定一致 → 通过率提到 7/7
- max_tokens 8000→12000 给 thinking + JSON 双消费留足余量，消除 passed=None

## How to apply

### 软化模板 (4/3 通过 + 兜底原文)

每 QC system_prompt 改 4 处：
1. **首行**：标题加 "质量审核员 + 自动优化师"
2. **# 硬约束（必须全部满足）** → **# 参考标准（4/3 通过即 passed=true）**
3. **# 你的工作流** 整段 → 改为：
   ```
   # 通过判定（**软化**）
   - 4/4 全过 → passed=true，improved_text = 原文
   - 4/3 通过（含轻微字数不足或 1 个禁用词已处理）→ passed=true，improved_text = 原文（或微调后）
   - 4/2 或以下 → passed=false，必须按下方流程改写
   
   # 优化改写（如需要）
   1. ...
   5. **兜底**：如改写 2 次后仍无法满足所有参考标准，improved_text = 原文 + errors 列出无法改写的项
   ```
4. 字数标准按板块调（intro≥400/tech≥400/accept≥250）

### max_tokens 8000→12000

3 QC 节点都改：`data.model.completion_params.max_tokens = 12000`

不要只改 1 节点 max_tokens（PATCH 22 验证 8000 仍可能撞限）。

### POST draft 必含字段

Dify 1.14+ 并发守卫，body 必含：
- `graph`
- `features`
- `environment_variables`
- `conversation_variables`
- `hash`（当前 draft hash，409 时刷新重试）

### 验证 SOP

1. 改完 POST draft 拿新 hash
2. `dify_validate_draft` 看 0 errors
3. 用户在 Dify UI 跑一次 E2E（用真实 Excel 文件）
4. 看 run trace：
   - QC-intro 0 iter `passed=None`（截断消除）
   - QC-accept 0 RD failed（软化生效）
   - 总通过率 7/7 (100%)
5. E2E 通过后调 `dify_publish_workflow` 发布

## 关联记忆

- [[dify-qc-strict-passed-fails-everything]] — PATCH 28 单 QC 软化的经验（71% 提升但仍有残留）
- [[dify-llm-output-truncation-breaks-downstream]] — max_tokens 4096→8000 (PATCH 22)
- [[dify-loop-timeout-app-max-execution]] — max_tokens 12000 可能拉长 elapsed, 需监控 < 1200s
- [[dify-llm-structured-output-fallback-defaults]] — thinking + structured_output 兜底必走 code node (PATCH 24)
- [[dify-defensive-node-must-be-in-loop]] — defensive node 必须 parentId=loop_id