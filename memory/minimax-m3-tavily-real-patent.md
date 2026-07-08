---
name: minimax-m3-tavily-real-patent
description: agent-chat 配 tavily_search 真实调用的模型选择 — Qwen3.6-35B-A3B-NVFP4 拒绝 19 参数工具，minimax-m3 稳定调用且返回 patents.google.com 实链
metadata:
  type: project
---

PATENT 顾问 agent(PATCH 37)试 4 配置都失败(Qwen3.6 + function_call/React × Tavily_only/Tavily+SearXNG):模型**从不主动调用 tavily_search**(19 个参数,含 include_domains/max_results/search_depth),反而选最简单的 searxng(3 参数)。换 **minimax-m3**(`langgenius/minimax/minimax` provider,本实例 tool-call 稳定模型)首次调用即成功,返回全部是 `patents.google.com` 实链(CN/US/EP/JP/KR)。

**为什么:** Qwen3.6 走 function_call 时对高参数 schema 倾向"装作不用";minimax-m3 在 system prompt 加"强制调用检索工具"时会真的调。

**How to apply:** agent-chat 配 Tavily(任意 ≥10 参数工具)首选 `minimax-m3` + `function_call`,不要用 Qwen3.6;prompt 加"只引用 tool 返回的 url/title,禁止凭记忆补全专利号"以压制幻觉(minimax-m3 会补 CN1153325C0A 这种畸形号);锁定 include_domains 到 patents.google.com / worldwide.espacenet.com / patentscope.wipo.int。

关联:[[dify-model-status-no-configure]] [[mcp-modelconfig-post-import-imports]]