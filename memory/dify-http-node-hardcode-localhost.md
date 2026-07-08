---
name: dify-http-node-hardcode-localhost
description: Dify HTTP 节点 URL 硬编码 127.0.0.1 部署后必失败；必须用 environment_variables 注入并用 {{env.XXX}} 引用
metadata:
  type: project
---

Dify HTTP 节点 URL 字段支持 `{{env.<ENV_VAR_NAME>}}` jinja 模板语法解析。
**禁止硬编码 `http://127.0.0.1:<port>` 或 `http://localhost:<port>`** —— 部署到其他机器后无法访问。

**修复 SOP**（3 步原子提交）：

1. **draft.environment_variables 追加新变量**：
   ```json
   {
     "value_type": "string",
     "id": "<new-uuid>",
     "name": "DOCS_HUB_URL",
     "value": "http://127.0.0.1:8088",   # 默认本地值
     "description": "DocHub 服务地址（部署后改为服务名）"
   }
   ```
2. **HTTP 节点 data.url 改 env var 引用**：
   - 旧：`http://127.0.0.1:8088/api/v1/generate`
   - 新：`{{env.DOCS_HUB_URL}}/api/v1/generate`
3. **部署时改 env var value**（不改 workflow）：
   - 改 `DOCS_HUB_URL` 的 value 为 `http://dochub-service:8088` 或实际地址
   - 这样 workflow 不动，只动 env var（避免再次 PATCH）

**关联沉淀**：
- code 节点里**不要**用 `os.environ.get` 读 env var（参考 [[dify-code-node-os-environ-blocked]]）→ 必须用 sys/env 选择器注入
- HTTP 节点 body 里**不要**硬编码 token/secret → 用 env var + authorization.config 字段

**Why**: PATCH 15 (2026-07-04) 修 WF_RDReport_v2 HTTP 节点 `17830458579260`，原本 URL `http://127.0.0.1:8088/api/v1/generate` 仅本地通；部署后任何非本地访问必失败。

**How to apply**:

1. 任何 HTTP 节点 URL 必须含 `{{env.XXX}}` 模板语法
2. env var 默认值可以给 `http://127.0.0.1:<port>`（本地调试用），但 description 写清楚部署后改什么
3. 部署文档要列出所有需要的 env var 名 + 推荐值
4. 见 [[dify-code-node-os-environ-blocked]] 关联 code 节点读 env var 方式

**PATCH 15 落地证据**：

- 节点：`17830458579260`（HTTP DocHub 生成文档）
- env vars: `RD_REPORT_TEMPLATE_ID` + `DOCS_HUB_URL`（2 个）
- URL: `http://127.0.0.1:8088/api/v1/generate` → `{{env.DOCS_HUB_URL}}/api/v1/generate`
- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_15_20260704_190842.json` (95640 bytes)
- 改完 hash：`0022f1e59da6a6bd`（前 `33d5211f6c6882df`）
- 发布版本 DSL 备份：`dsl_published_AFTER_PATCH_15_20260704_190842.yaml` (80260 bytes)
- PATCH 脚本：`_tmp_patch_p2_env_var_metadata.py`

**同时 PATCH 15 还做了**（综合 P2 部署/可维护性补丁）：
- loop node `output_type: None → array[object]`（隐式声明 → 显式，避免升级炸）
- 段落组装 code 节点 17 个 variables 补 `value_type`（与 [[dify-code-node-outputs-require-value-type]] 对称，PATCH 9 修了 outputs，PATCH 15 修 variables）
- 跳过 P2-3 task_summary 统计（PATCH 11 修 raise 后自动正确）
- 跳过 P2-2 iterator_selector（count-based loop 不依赖数组遍历）