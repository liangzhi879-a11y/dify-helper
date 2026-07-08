---
name: dify-conversation-variable-not-ui-editable
description: Dify 1.14+ conversation_variable 是 internal schema，UI 上 user 改不了；要想让 user 在 workflow 设置里改值，必须用 environment_variable（顶部 Env Panel 可改）
metadata:
  type: feedback
---

# Dify 1.14+ conversation_variable 不是 user-editable (PATCH 34 根因)

## 症状
- workflow 加 conversation_variable `RD_total_count` (number, default=6)
- Dify UI workflow 设置页**找不到** "全局变量" 面板让 user 改这个值
- break_conditions 引 `{{#conversation.RD_total_count#}}` 看起来对，但 user 抱怨"环境变量和系统变量均无此名称的字段"

## 根因（2026-07-06 实测）

**Dify 1.14+ 的 conversation_variable 是 internal schema，不暴露给 user 编辑 UI。**

源码证据：
- 前端代码 `/web/app/components/workflow/panel/env-panel/index.tsx` 渲染 EnvPanel，但只显示 `environmentVariables` (从 store)
- 没有对应的 ConvPanel 或 "全局变量" 面板
- conversation_variable 主要给 workflow 内部使用（如 multi-turn chat 持久化），不暴露给 workflow 设置 UI

所以 user 没法在 UI 改 conversation_variable 值，只能：
1. 重新 publish workflow（覆盖默认值）—— 不实际
2. 用 API 改 workflow.conversation_variables —— user 不会

## Why
- PATCH 33 我以为 conversation_variable 像 env var 一样有 UI 面板
- 实际查 Dify 1.3.0 web 源码 (`/web/app/components/workflow/panel/`) 只有 EnvPanel，没有 ConvPanel
- user 反馈 "环境变量和系统变量均无此名称的字段" 是因为 EnvPanel 显示的 env var 里没有 RD_total_count（我加的是 conversation_variable）

## How to apply

### 修复模式
**想让 user 在 workflow 设置里改值，必须用 environment_variable + Dify EnvPanel**：

```json
{
  "environment_variables": [{
    "value_type": "string",
    "id": "<UUID v4>",
    "name": "RD_TOTAL_COUNT",
    "value": "6",
    "description": "..."
  }]
}
```

break_conditions 引：
```json
"value": "{{#env.RD_TOTAL_COUNT#}}"
```

### env var 类型注意
- env var 只支持 `value_type: "string"` (Dify 1.14+ env panel 限制)
- break_conditions processor 会 `variable_pool.convert_template().text` 拿到字符串
- `_assert_greater_than_or_equal` 会做隐式 number conversion

### User 操作流程
1. 打开 Dify workflow 编辑页面
2. 顶部找 **"Environment Variables"** 面板 (EnvPanel)
3. 找到 `RD_TOTAL_COUNT`，点编辑，改值
4. 跑 workflow → break_conditions 引用 env.RD_TOTAL_COUNT 当前值

### 触发词
- "环境变量和系统变量均无此名称的字段"
- "全局变量面板找不到"
- "user 在 UI 改不了这个值"

### 关联
- [[dify-break-conditions-jinja-no-fallback]] — jinja 不支持 fallback，必须用 env var (有 default)