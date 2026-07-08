---
name: dify-loop-timeout-app-max-execution
description: Dify 1.14+ workflow 1200s 超时是 server-side `APP_MAX_EXECUTION_TIME` 默认，per-app PATCH 不可改；解决方法是 cap loop_count + bump max_tokens
metadata:
  type: project
---

Dify 1.14+ 的 `APP_MAX_EXECUTION_TIME=1200` (默认) 在 `api/configs/feature/__init__.py`，server-side env var，**per-app PATCH 不可配置**。所以 loop 跑不动只能靠 cap loop_count 到 N（比如 5-6 iters）保证总时长 < 1200s。

per-iter 实际成本（minimax-m2.7-highspeed 6×LLM 节点 × 18 字段 schema）：~150s/iter（LLM extract 18s + 3 撰写 70s + 3 QC 60s），所以 5 iters ≈ 750s < 1200s。

QC+优化 LLM 默认 `max_tokens=4096` 不够，因为 LLM 用 `` 思维链 + JSON schema 时 thinking 耗 token 大，撞 4096 → structured_output 解析失败 → loop terminated。 **fix**: 给 3 writers + 3 QCs 都 `max_tokens=8000`。

**Why:** 这次翻车的核心 root cause 是 1200s server cap + 6 字段 thinking LLM 都吃 token；以前 PATCH 18 已知 structured_output 各种坑，没意识到 thinking + JSON 一起会撞 token。

**How to apply:** 见 [[dify-llm-output-truncation-breaks-downstream]]；每次 workflow 含 loop + LLM 时第一动作必查 `loop_count × per_iter_time < 1200s`；含 structured_output LLM 时必设 `max_tokens ≥ 6000`。
