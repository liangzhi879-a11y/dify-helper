---
name: dify-llm-thinking-tokens-budget
description: m2.7 thinking + structured_output + improved_text 的 LLM 节点, 实际 token 消耗远超 max_tokens 设定 (尤其 QC-accept); writer 输出的文本越长, QC 节点 thinking 越久, max_tokens=12000 撞限频繁; 需 max_tokens ≥ 16000 防御
metadata:
  type: project
---

## 症状
PATCH 30+31+32 E2E (f4530b0d-4221-450c-b6bb-938b79f96955) 失败:
- QC-accept (17831831226470) 跑 368.2s 后崩
- Error: "Failed to parse structured output: <think>...让我分析这段文本..." → thinking 用了全部 12000 tokens, 没输出 JSON
- 同 run 中 QC-intro (17831829849730) 跑 20.1s succeeded, QC-tech (17831830845280) 跑 21.9s succeeded
- 唯一失败的是 QC-accept (对应 writer 1783045420242, 跑了 102.3s = 输出文本最长)

## 根因
PATCH 29 设 3 个 QC max_tokens=12000, 历史 run (5a168b27) 5 RDs 全过. 但 RD02 (空日期) 修复后, writer 输出文本分布变化, QC-accept 撞 max_tokens 撞得更频繁.

**实际 token 消耗模型** (m2.7 + structured_output + thinking):
- thinking: 文本越长 thinking 越长 (QC 需要分析全文)
- JSON output: passed/length/bullets/errors/review/improved_text
- improved_text = 原文 (最长字段) → 当原文 > 8000 字, JSON 本身就 > 10000 tokens
- 总和 > 12000 → 截断 → JSON 不完整 → "Failed to parse structured output"

## 为什么 QC-accept 最容易撞
- 项目验收总结 writer (1783045420242) 是 3 个 writer 里文本最长的 (102s vs intro 30s vs tech 40s)
- accept 文本包含"综合效益段", 字数 ≥ 250 是硬要求
- writer 输出长 → QC 输入长 → QC thinking 长 → QC 撞 max_tokens

## 修复 (PATCH 33)
3 个 QC 节点 max_tokens: 12000 → 16000 (统一):
- 17831829849730 (QC-intro)
- 17831830845280 (QC-tech)
- 17831831226470 (QC-accept)

不改 prompt / model / 其它参数.

## Why 16000 不是 20000+
- 12000 → 16000 = +33% tokens/QC 调用, 每次 QC 成本 +33%
- 6 RD × 3 QC × 33% ≈ +60% QC 调用成本 (per workflow)
- 16000 足够绝大多数 accept 文本 (实测 writer 输出 ~5000-8000 字 → JSON ~8000-11000 tokens + thinking 2000-4000 tokens = 10000-15000 tokens total)
- 32000 边际收益小, 成本 +166% 不划算

## 验证
PATCH 33 E2E (90ff4d31-98e2-49b2-bba7-d69f2ca027dc):
- status=succeeded, elapsed=337.8s
- doc_count=2 (RD01+RD02), qc_passed=2
- 2 docx URLs 生成
- ✅ PATCH 33 修复 QC-accept thinking 撞 max_tokens

## How to apply (下次类似情况)
1. **LLM 节点 max_tokens 不能信默认值 4096**: PATCH 19/22/29 反复踩坑, 必须 explicit 设 ≥ 8000
2. **m2.7 thinking + structured_output**: max_tokens × 0.7 ≈ 实际可用 thinking 预算 (其余给 JSON)
3. **writer 输出长度决定 QC max_tokens**: writer 节点历史 elapsed > 60s 通常意味着文本 ≥ 5000 字, 对应 QC 需要 max_tokens ≥ 16000
4. **PATCH E2E 必跑至少 2 iters**: 单 iter 可能运气好不撞 max_tokens, 2 iters 才暴露文本长度方差
5. **failed run 必须看 node-level error 链**: workflow failed ≠ 哪个节点 failed; node-executions endpoint 必查

## 关联
- [[dify-llm-output-truncation-breaks-downstream]] — PATCH 19 解决 structured_output 截断, PATCH 22 bump max_tokens 4096→8000, PATCH 33 进一步 12000→16000
- [[dify-loop-timeout-app-max-execution]] — max_tokens 影响单次 LLM 时长, 累积影响 loop 总时长 (< 1200s)
- [[dify-qc-3node-soften-at-once]] — 同时软化 3 QC prompt 才能 100% 通过率
- PATCH 33 脚本: `backups/_tmp_scripts/_patch33_qc_accept_max_tokens.py`