---
name: dify-dsl-importer
trigger: DSL, 导入, 导出, 复用, 模板, import, export
priority: medium
---

# Skill: Dify DSL Importer

你是 Dify DSL 导入导出专家。当用户要复用/迁移/备份应用时，用 DSL 实现一键迁移。

## DSL 顶层结构

```yaml
app:
  name: "应用名"
  description: "描述"
  mode: chat | completion | advanced-chat | workflow | agent-chat
  icon: "🤖"
  icon_background: "#FFEAD5"
  icon_type: emoji
kind: app
version: 0.1.5

# 二选一：
model_config:        # chat/completion/agent-chat 用
  model: {...}
  prompts: [...]
workflow:            # advanced-chat/workflow 用
  features: {...}
  graph: {nodes: [...], edges: [...]}
  environment_variables: []
  conversation_variables: []
```

## 导出端点

```
GET /apps/{app_id}/export?format=yaml|json
```

返回 DSL 原文（yaml 或 json 字符串）。

## 导入端点（Dify 1.14+）

```
POST /apps/import
body: {
  "data": "<base64 编码的 DSL>",
  "mode": "yaml-only" | "yaml-customize",
  "name": "<新应用名>",
  "description": "<描述>"
}
```

### 两种导入模式区别

| 模式 | 行为 |
|---|---|
| `yaml-only` | 完全使用 DSL 配置，不保留原 ID，重新生成所有节点 ID |
| `yaml-customize` | 导入后可自定义修改，部分字段允许覆盖 |

## 调用 MCP 工具

- `dify_export_dsl(app_id, format="yaml")` → 返回 DSL 文本
- `dify_import_dsl(name, mode="yaml-only", description, dsl_content)` → 创建新应用

## 典型场景

### 1. 应用模板复用
```
1. dify_export_dsl(source_app_id, "yaml") 拿到 DSL
2. 修改 DSL 中的 name/description/prompts
3. dify_import_dsl(new_name, "yaml-only", new_desc, modified_dsl)
```

### 2. 应用备份
```
1. dify_export_dsl(app_id, "yaml") 导出 yaml 文本
2. 写入本地 .yml 文件保存
```

### 3. 跨工作空间迁移
```
1. 源工作空间 export
2. 目标工作空间 import
```

## 常见错误规避

- DSL 内容必须 base64 编码后传 data 字段
- workflow 模式的 graph 必须合法（节点+边完整），否则导入失败
- yaml-customize 模式导入后默认是草稿状态，需手动发布
- 跨版本迁移时注意 version 字段，低版本 DSL 可能不被高版本支持
