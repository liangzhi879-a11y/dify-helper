---
name: dify-import-mode-yaml-content
description: Dify 1.14+ /apps/imports 走 yaml-content + yaml_content 字段，不是 yaml-only + base64 data；mcp_server/dify_client 的 dify_import_dsl 用了错形态
metadata:
  type: project
---

# Dify 1.14+ 导入应用模式枚举

`POST /apps/imports` 是新版本导入端点（注意是 **imports** 复数），请求 schema:
```json
{
  "yaml_content": "<完整 yaml 文本（UTF-8, 非 base64）>",
  "mode": "yaml-content",
  "name": "应用名",
  "icon": "📑",
  "icon_background": "#5B8DEF",
  "description": "..."
}
```

- `mode` 必须是 `"yaml-content"`（其他值如 `"yaml-only"`、`"safe-import"`、`"yaml-model-config"` 都报 `Invalid import_mode`）
- 字段名是 **`yaml_content`** 不是 `data`，原 `mcp_server/server.py:dify_import_dsl` 用 `data + base64 + mode="yaml-only"` 是错的，所以这个 MCP 工具在当前版本不可用

## 复刻应用的标准做法
1. `GET /apps/{src_id}/export?format=yaml` → 拿到 `{"data": "<完整 yaml>"}`（data 是 raw yaml，不是 base64）
2. 字符串替换 `app.name` / `app.icon` 等
3. `POST /apps/imports` body 形如上面那样，传 raw `yaml_content`
4. Dify 自动生成新 UUID 给所有节点和 graph，自动发布（不需 publish）

## 错误反查表
| 症状 | 真因 |
|---|---|
| 404 NOT FOUND | 端点用了 `/apps/import` 而不是 `/apps/imports` |
| Invalid import_mode: yaml-only | mode 字段值不对，应为 `yaml-content` |
| yaml_content is required ... | 字段名写成了 `data`/base64，正确是 raw `yaml_content` |
| field required [type=missing] | 漏了 `mode` 字段（Pydantic AppImportPayload 必填） |

**Why:** 2026-07-05 在克隆 WF_RDReport v2 doc-ext 时翻车，把 `mcp_server/dify_client.DifyClient.get()` 拿到了 `{"data": "yaml 文本"}`，**不是** base64。本地 dify_import_dsl 工具按旧版 (data=base64, mode="yaml-only") 直接 404。手动试出 `yaml_content + mode="yaml-content"` 才对。

**How to apply:** 以后调用 Dify 导入走 `/apps/imports` 用 `yaml_content`，跳过 MCP 包装层。
