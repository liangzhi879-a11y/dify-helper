---
name: dify-agent-chat-minimax-workflow-tool-not-called
description: minimax-m3 + workflow-as-tool (provider_type=workflow) 在本实例 Dify 1.14+ agent-chat 当前不调工具，agent_thought 里 tool="" position 一直 1，与 builtin 工具(tavily)可调形成对比
metadata:
  type: project
---

## 症状
PATCH 38 (国高撰写助手 8490e0d1) + 对照实验 (📜 合同审查 50cf3dc7) 都验证:
- model=minimax-m3, strategy=function_call OR react, tools=[2 workflow tools], provider_type="workflow"
- 发 query 后 stream 出现 agent_thought event, 但 `tool=""` `tool_input=""` `observation=""` 全部空
- `position` 一直 `1`（正常应该 1,2,3 递增每次 tool call）
- 第二个 thought 文本里说"立即调用 wf_研发立项拟题"但实际**没真调**, LLM 用自己知识生成内容假装是工具返回

## 根因（与 PATCH 37 对照）
- PATCH 37 (专利 agent) 验证 minimax-m3 + builtin tool (tavily_search 19 参数) **能正常调** → minimax-m3 + function_call 本身不是问题
- PATCH 38 验证 minimax-m3 + workflow-as-tool (provider_type="workflow") **不能调** → 区别在 provider_type
- 推测：Dify 1.14+ agent-chat 调 workflow-as-tool 走的协议 minimax-m3 vllm 端不识别 (function_call 模式 schema 不接受 workflow provider 的 tool descriptor?)，LLM 收到"无工具可用"信号回退到裸 LLM 生成
- react strategy 同样失败 → 不是 strategy 问题
- 📜 合同审查 (cc9003ea 创建, 1783157906) 同款问题 → 结构性局限, 创建者也没 E2E 测过

## 已知坏组合
- minimax-m3 + function_call + provider_type="workflow" → 不调
- minimax-m3 + react + provider_type="workflow" → 不调
- Qwen3.6-35B-A3B-NVFP4 + function_call + provider_type="builtin" (tavily) → 4 配置全不调 (PATCH 37)

## 怎么解决（待 user 选）
1. **换 LLM**: 试 Qwen3.6 + react (PATCH 37 只测过 function_call) 或等 vllm 上 tool-call-stable 模型
2. **换架构**: 把 agent-chat 拆成 advanced-chat + answer 节点直接调 workflow tool (绕开 agent 工具调用协议)
3. **降级**: 让 LLM 直接生成 (当前实际行为), 在 pre_prompt 里明说"工具调不动是已知问题, 我会按 LLM 知识生成草案", 但与 pre_prompt 里"启动对应工作流"承诺冲突

## How to apply
下次任何 agent-chat + workflow-as-tool PATCH:
1. **先 PATCH 38 对照** — 用现有同配置 app (📜 合同审查 / 📊 财税助手) E2E 测一次, 看 minimax-m3 + workflow tool 是否能调
2. 如果不能, **先告知 user 本实例结构性问题, 让 user 选方案**, 不要无脑切模型/strategy
3. model_config 写入后必须 E2E 验证 `agent_thought.tool` 非空, 不要只 diff 字段对不对
4. tool_parameters 写法参考 📜 合同审查 sub-dict 格式 (`{var: {type, description, required}}`) 没问题, 不是字段格式问题

## 关联
- [[minimax-m3-tavily-real-patent]] — PATCH 37 验证 minimax-m3 + builtin tavily OK
- [[dify-tool-node-data-required-fields]] — workflow 内的 tool 节点必填 3 层 (与本场景 agent→workflow 工具不同)
- PATCH 38 脚本: `backups/_tmp_scripts/_tmp_patch_38_guogao_minimax_workflow_tools.py`
- 对照实验: `backups/_tmp_scripts/_tmp_inspect_contract.py`
