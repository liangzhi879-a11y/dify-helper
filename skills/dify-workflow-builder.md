---
name: dify-workflow-builder
trigger: 工作流, workflow, 节点, graph, 编排, 流程图
priority: high
---

# Skill: Dify Workflow Builder

你是 Dify 工作流编排专家。当用户要求创建/修改工作流时，按 Dify 1.14+ graph schema 设计合法的节点和边。

## 18 种节点类型

| 类型 | 用途 | 必填字段（data） |
|---|---|---|
| `start` | 工作流入口，定义输入变量 | variables: [{name, type, label, required, max_length}] |
| `end` | workflow 模式出口，定义输出 | outputs: [{variable, selector}] |
| `answer` | advanced-chat 模式出口，流式回复 | answer: "{{#llm.text#}}"（jinja2） |
| `llm` | 调用大模型 | model, prompt_template, context |
| `knowledge-retrieval` | 知识库召回 | dataset_ids, retrieval_mode |
| `if-else` | 条件分支 | conditions: [{id, logical_operator, conditions: [...]}] |
| `code` | 执行 Python/JS | code_language, code, inputs, outputs |
| `template-transform` | Jinja2 模板转换 | template, variables |
| `question-classifier` | LLM 问题分类 | classes: [{id, name}], query_variable |
| `parameter-extractor` | LLM 参数提取 | parameters: [...], query_variable |
| `variable-assigner` | 写会话变量 | assigned_variable_selector, write_mode |
| `variable-aggregator` | 多分支变量聚合 | output_variable, variables |
| `assigner` | 会话变量赋值 | items: [{variable_selector, operation, value}] |
| `iteration` | 列表迭代 | iterator_selector, start_node_id |
| `http-request` | HTTP 调用 | method, url, headers, body |
| `tool` | 调用插件工具 | provider_id, tool_name, tool_parameters |
| `document-extractor` | 文档提取 | variable_selector |
| `list-operator` | 列表操作 | list_variable, operation, filter |

## 节点对象 schema

```json
{
  "id": "node-uuid",
  "type": "llm",
  "title": "LLM 回复",
  "data": {
    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {"temperature": 0.7}},
    "prompt_template": [{"role": "system", "text": "你是客服助手"}],
    "context": {"enabled": false, "variable_selector": []},
    "vision": {"enabled": false}
  },
  "position": {"x": 100, "y": 200},
  "extent": null
}
```

## 边对象 schema

```json
{
  "id": "edge-uuid",
  "source": "start-node-id",
  "target": "llm-node-id",
  "sourceHandle": "source",
  "targetHandle": "target",
  "type": "custom",
  "data": {"isInIteration": false}
}
```

`if-else` 节点用 `sourceHandle` 区分分支：`true` / `false` / `<condition_id>`

## 变量传递语法

- 引用其他节点变量：`{{#start.query#}}` `{{#llm.text#}}` `{{#code.result#}}`
- 在 prompt_template 中用 jinja2：`{{query}}` （需先在 variables 中映射）
- 会话变量：`{{#sys.user_id#}}` `{{#sys.conversation_id#}}`

## 调用 MCP 工具流程

1. `dify_get_workflow(app_id)` 读取当前草稿
2. 设计 graph（nodes + edges）
3. `dify_update_workflow(app_id, graph=<JSON>, features=<JSON>, environment_variables=<JSON>)`
4. `dify_publish_workflow(app_id)` 发布
5. `dify_run_workflow_debug(app_id, inputs=<JSON>)` 调试

## 常见错误规避

- LLM 节点 prompt_template 必须用 jinja2，不能用 f-string 或 .format()
- code 节点 outputs 必须声明类型，否则后续节点无法引用
- if-else 节点分支 id 不能重复
- start 节点必须有，且只能有一个
- end/answer 节点必须至少有一个
- iteration 节点的 start_node_id 指向迭代内部的子开始节点
