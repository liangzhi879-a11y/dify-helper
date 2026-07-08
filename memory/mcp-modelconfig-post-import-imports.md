---
name: mcp-modelconfig-post-import-imports
description: MCP update_app_model_config 用 PATCH 报 405、import_dsl 打 /apps/import 报 404;正解是 POST /apps/{id}/model-config(整体替换) 和 POST /apps/imports(yaml_content 原文)
metadata:
  type: reference
---

# MCP 两个写配置工具端点漂移(2026-07-06 实测修复)

## 症状
- `dify_update_app_model_config` → `405 method_not_allowed`
- `dify_import_dsl` → `404 NOT FOUND`(HTML)

## 根因
两个 MCP 工具端点/方法与 Dify 1.x 后端不匹配:

| 工具 | 旧(错) | 正解(实测 2026-07-06) |
|---|---|---|
| `update_app_model_config` | `PATCH /apps/{id}/model-config` | `POST /apps/{id}/model-config` |
| `import_dsl` | `POST /apps/import` + `{data: base64, mode: yaml-only}` | `POST /apps/imports` + `{mode:"yaml-content", yaml_content:<raw yaml>}` |

## 关键陷阱
1. **model-config 是【整体替换】语义**,不是 PATCH——必须传【完整】model_config,漏字段会被清空/回默认。
2. **imports 传 yaml 原文,不做 base64**;返回 `{id, status:"completed", app_id, error}`,status=completed 即成功,无需再 confirm。
3. 旧 `mode: yaml-only/yaml-customize` 参数在新端点无意义,新 source mode 固定 `yaml-content`。

## How to apply
- 改 `mcp_server/mcp_server/server.py`:`dify_update_app_model_config` 的 `client.patch`→`client.post`;`dify_import_dsl` + `duplicate_workflow` fallback 的 `/apps/import`+base64 → `/apps/imports`+`yaml_content`。
- **MCP server 是 stdio 由 harness 启动,改代码后需重连 `dify` MCP(或重启 session)才生效**;急用时可复用 `DifyClient`(自带 email/pwd 登录)写一次性脚本直接打后端,见 `backups/_tmp_scripts/_tmp_patch_patent_agent_modelconfig.py`。
- 相关:[[dify-model-status-no-configure]]
