---
name: dify-break-conditions-jinja-no-fallback
description: Dify 的 {{#xxx#}} 是 regex 替换不是 jinja2；break_conditions.value 引用的变量若不存在，渲染为字面量字符串，processor 报 "Cannot convert 'xxx' to number"。必须用 conversation_variable (有 default) 或 required input 保证变量始终有值
metadata:
  type: feedback
---

# Dify {{#xxx#}} 引用系统变量的陷阱 (PATCH 33 根因)

## 症状
- loop 节点 break_conditions.value = `"{{#sys.RD_total_count#}}"`
- start input RD_total_count 必填 + default="6" 都加了
- 用户跑 workflow（不填 RD_total_count）报 **"Cannot convert 'sys.RD_total_count' to number"**
- 即使填了 RD_total_count 也会报（因为 Dify 1.3.0 的 `mapping_user_inputs_to_variable_pool:358` 不 fallback 到 default）

## 根因（重要发现 2026-07-06）

**Dify 的 `{{#xxx#}}` 不是 jinja2 模板，是专用 regex 替换！**

源码位置: `api/core/workflow/entities/variable_pool.py:18`
```python
VARIABLE_PATTERN = re.compile(r"\{\{#([a-zA-Z0-9_]{1,50}(?:\.[a-zA-Z_][a-zA-Z0-9_]{0,29}){1,10})#\}\}")
def convert_template(self, template, /):
    parts = VARIABLE_PATTERN.split(template)
    for part in filter(lambda x: x, parts):
        if "." in part and (variable := self.get(part.split("."))):
            segments.append(variable)
        else:
            segments.append(variable_factory.build_segment(part))  # ← 字面量
```

**不支持任何 jinja2 filter / if-else / |default / |int**

当 `sys.RD_total_count` 不存在时:
- `{{#sys.RD_total_count#}}` 被保留为字面量 `"sys.RD_total_count"`
- condition processor 拿 expected_value = "sys.RD_total_count"（字符串）
- `_assert_greater_than_or_equal(value=1, expected="sys.RD_total_count")` 抛 "Cannot convert"

## Why
- 我之前误以为 Dify 用 jinja2，所以改了 `{{#sys.RD_total_count|default(6)|int#}}` 想兜底
- 实际跑测试发现 jinja2 syntax 完全不工作
- 应该一开始先 grep 源码确认，而不是靠记忆/常识假设

## How to apply

### 修复模式
**永远不要在 condition.value / prompt_template 引"用户可能不传的变量"**。

必须先用 conversation_variable (有 default value 兜底):
```json
{
  "break_conditions": [{
    "comparison_operator": "≥",
    "value": "{{#conversation.RD_total_count#}}",  // 引 conversation_variable
    "varType": "number",
    "variable_selector": ["<loop_id>", "count_down"]
  }]
}
```

并加 conversation_variable:
```json
{
  "conversation_variables": [{
    "id": "<合法 UUID v4>",
    "name": "RD_total_count",
    "value_type": "number",
    "value": 6,
    "description": "..."
  }]
}
```

### 用户使用模式
1. 在 Dify UI 顶部"全局变量"面板改 `RD_total_count` 值（默认 6）
2. 跑 workflow 时自动用 conversation_variable 当前值
3. 不需要在 start input 传（但 PATCH 31 加了 start input 仍保留作 UI 友好提示）

### 触发词
- "Cannot convert 'sys.xxx' to number"
- "Cannot convert 'env.xxx' to number"
- loop break_conditions 用变量引用但跑不通
- condition value 是 jinja2 模板但被原样保留

### 验证清单
1. `grep "VARIABLE_PATTERN" /home/sutai/source_code/dify*/api/core/workflow/entities/variable_pool.py` 确认 regex 替换
2. `python3 -c "import uuid; uuid.UUID('xxx')"` 验证 conversation_variable.id 是合法 v4
3. dify_validate_draft 看 error_count=0

### 关联
- [[dify-loop-output-selector-not-required]]
- [[dify-patch-first-compare-normal-node]]