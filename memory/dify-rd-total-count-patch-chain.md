---
name: dify-rd-total-count-patch-chain
description: PATCH 31-35 五次翻车链：让 user 改 RD 数量看似简单，实际涉及 start input(API 覆盖) vs env variable(UI 改) vs conversation_variable(不可改) 三个 Dify 变量命名空间的不可调和矛盾；根治 = env var + publish
metadata:
  type: feedback
---

# Dify 改"用户可配置 loop 上限"翻车链 (PATCH 31-35 → PATCH 36 根因)

## 症状
- user 跑 workflow 报 **"Cannot convert 'sys.RD_total_count' to number"**
- 期望：让 user 在 UI 改 RD 数量上限（5 改 10），不需改 workflow 重 publish
- 5 个 PATCH 都没根治

## 翻车时间线
| PATCH | 改动 | user 反馈 | 失败根因 |
|---|---|---|---|
| 31 | start input (required=False, default=6) + break 引 `sys.RD_total_count` | "Cannot convert sys.RD_total_count to number" | start input default 在 console run **不注入** pool（agent 调研源码说注入，实测不注入）|
| 32 | (无关 DocHub nginx) | 文档下载 OK | — |
| 33 | 改 conversation_variable (default=6) | "环境变量和系统变量均无此名称的字段" | Dify 1.14+ conversation_variable 是 internal schema，UI 无面板 |
| 34 | 改 environment_variable `RD_TOTAL_COUNT` (default=6) | "环境变量和系统变量均无此名称的字段" | EnvPanel 实际**只读 draft**，user 看的是 published（无 env var）|
| 35 | 改回 sys + start input required=True, default=6 | "Cannot convert sys.RD_total_count to number" | required=True 在 console run server 端**不 raise**（仅 client 端 UI 阻止），default 不注入 → sys 变量不存在 → 字面量 |

## 根因（2026-07-06 综合诊断）

**Dify 1.14+ 三个变量命名空间的"用户可改"性互斥**：

| 命名空间 | API runtime 覆盖 | UI 改值 | schema default 兜底 |
|---|---|---|---|
| `sys.<start_input>` (start input) | ✅ | ⚠️ 跑时填对话框 | ❌ console run 不注入 default |
| `env.<ENV_NAME>` (environment_variable) | ❌ | ✅ EnvPanel | ✅ deploy-time 默认 |
| `conversation.<CV_NAME>` (conversation_variable) | ❌ | ❌ UI 无面板 | ✅ deploy-time 默认 |

**结论：**
- 想"UI 改值 + 自动兜底" → 用 env var + **必须 publish**（让 EnvPanel 看到）
- 想"API caller runtime 覆盖" → 用 start input，但**必填**且**接受 console run 不兜底**
- 想"两者兼得" → 不可能（Dify 1.14+ 设计如此）

## Why (翻车原因)
- 我反复在 3 个命名空间之间换，没意识到这是**三元悖论**
- 没意识到"tool_published=false" → EnvPanel 在 published workflow page 看到的是空
- 没意识到 Dify 1.14+ start input required=True 在 server 端**不 raise**（实测）

## How to apply (PATCH 36 方案)

### 选 1：UI 改值优先（推荐 — 适合本场景 user 是终端操作员）
```python
# 1. env var (string, default="6")
environment_variables.append({
    "id": "<uuid>",
    "name": "RD_TOTAL_COUNT",
    "value_type": "string",
    "value": "6",   # ← 关键：value 是 string 不是 number
    "description": "RD 数量上限 (默认 6, 在 Dify UI 顶部 EnvPanel 可改)"
})

# 2. break_conditions 引 env (string → processor 自动 int 转换)
break_conditions = [{
    "comparison_operator": "≥",
    "value": "{{#env.RD_TOTAL_COUNT#}}",   # ← env namespace
    "varType": "number",
    "variable_selector": ["<loop_id>", "count_down"]
}]

# 3. start input 保留但 required=False (友好, 但 server 不兜底)
start_input = {
    "variable": "RD_total_count",
    "type": "number",
    "default": "6",
    "required": False,   # ← 必填 True 反而更糟（client 不阻止也跑不下去）
    "label": "RD 数量上限 (可选, 默认走 env var)",
}

# 4. publish
await dify_publish_workflow(app_id)
```

### 选 2：API 覆盖优先（适合 user 是开发者）
```python
# 1. start input (number, required=True, default="6")
# 2. break_conditions 引 sys
# 3. 不 publish（或 publish）
# 接受 console run server 端不 raise 但 default 不注入 → UI 必填
```

### 验证清单（必做）
1. `dify_get_app_node(app_id, start_id, detail="full")` 确认 default 实际值
2. `dify_publish_workflow(app_id)` **必须** publish
3. user 在 Dify UI published workflow page 顶部 **EnvPanel** 找 `RD_TOTAL_COUNT`
4. 改值 → 跑 workflow → 验证循环次数 = env var 值
5. 不传 RD_total_count + env var=10 → 应跑 10 次（env 兜底）
6. API `inputs.RD_total_count=15` → **不**生效（env 优先）

### 触发词
- "Cannot convert 'sys.xxx' to number"
- "环境变量和系统变量均无此名称的字段"
- "API 覆盖 RD 数量"
- "loop 跑 X 次不对"

### 关联
- [[dify-break-conditions-jinja-no-fallback]] — jinja 不支持 fallback，必须用有 default 的变量
- [[dify-conversation-variable-not-ui-editable]] — conv var 不可改
- [[dify-patch-first-compare-normal-node]] — PATCH 出错先对比正常节点

### 沉淀来源
PATCH 31 (9:32) → PATCH 35 (10:25) 五次翻车，最终 PATCH 36 (12:30) 根治。完整调试见 `docs/dify-debug-trace.log.md` PATCH 31-36 段。
