---
name: dify-code-node-os-environ-blocked
description: Dify code node 沙箱隔离 _os.environ，os.environ.get() 永远返回 None；模板 ID 等 Dify 环境变量必须用 sys/env 选择器从 node variables 注入，不能用 os.environ
metadata:
  type: project
---

Dify 1.x code node **沙箱里 `_os.environ` 是空的**（Dify 不把宿主环境变量注入沙箱）。

**症状**：用 `os.environ.get("XXX")` 读 Dify environment_variables 里的变量 → 拿到 `None`。
**翻车尝试**：`os.environ.get("XXX") or "{{env.XXX}}"` 兜底 — 兜底字符串是字面量，**不会被变量解析**，下游 HTTP body 里仍然是 `null`。

**正确做法**：通过 node `data.variables` 注入 Dify env var：

```python
# data.variables 末尾追加
{
  "variable": "<param_name>",
  "value_selector": ["sys", "env", "<ENV_VAR_NAME>"],   # ← 关键
  "value_type": "string"
}
```

然后 `main()` 签名加 `<param_name>` 参数，函数体直接用这个参数。

**Why**: PATCH 10 (2026-07-04) 修 WF_RDReport_v2 段落组装节点，原本 `_os.environ.get("RD_REPORT_TEMPLATE_ID")` 拿不到，导致 DocHub HTTP body 里 `templateId=null`，每次跑必报 400/500。

**How to apply**:

1. 任何 Dify code node 想读 `environment_variables` 里声明的变量 → **用 `value_selector: ["sys", "env", "<name>"]`**，**不要用 `os.environ.get`**
2. 沙箱里 `_os` 是空 dict，没有 `PATH` / `HOME` 等任何 host 环境变量
3. `{{env.XXX}}` 这种 jinja 语法只在 prompt_template / 节点配置里生效，**在 code 函数体里就是字符串字面量**
4. 若 value_selector 选错（例如 `["env", "XXX"]`），Dify 不报错但运行时拿到 None — 排查时 print 变量值能立即定位
5. 见 [[dify-code-node-outputs-require-value-type]] 关联 code 节点 outputs 必含 value_type

**PATCH 10 落地证据**：

- 节点：`17830458386560`（段落组装 + DocHub dataJson 构建）
- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_10_20260704_190058.json` (145216 bytes)
- 改完 hash：`d2d10be38e04fdfb`
- code 改动 3 处：
  - 删 `import os as _os`
  - 删 `_os.environ.get(...) or "{{env.XXX}}"` 兜底
  - `main()` 签名加 `RD_REPORT_TEMPLATE_ID` 参数
- data.variables 末尾加 `{variable: "RD_REPORT_TEMPLATE_ID", value_selector: ["sys", "env", "RD_REPORT_TEMPLATE_ID"], value_type: "string"}`
- 发布版本 DSL 备份：`dsl_published_AFTER_PATCH_10_20260704_190058.yaml` (120688 bytes)
- PATCH 脚本：`_tmp_patch_p0_1_env_var.py`