---
name: dify-code-node-intro-text-wrong-ref
description: PATCH 17 LLM QC 替换 code QC 时漏改 value_selector；intro_text/tech_text/accept_text 全错指向 QC_accept (17831831226470)
metadata:
  type: project
---

当 workflow 含 code node 接收多 LLM QC 输出时，code node variables[].value_selector 必须 1:1 对应到正确的 LLM QC 节点； **不要假设同一字段就会自动路由**。

症状：code node 跑 `len(intro_text)` 时 `TypeError: object of type 'NoneType' has no len()`。
根因：intro_text 和 accept_text value_selector 都指向 `["17831831226470","structured_output","improved_text"]`（QC+优化-项目验收总结）。PATCH 17 把 3 个 code QC 换成 3 个 LLM QC 时，只改了 1 个 value_selector（qc_intro_passed / qc_tech_passed / qc_accept_passed），**漏改了 intro_text / tech_text / accept_text**。

**Why:** PATCH 17 翻车一次。`intro_text` 本应指向 `17831829849730`（QC+优化-项目简介）。

**How to apply:** code node variables[] 字段名 (intro_text/tech_text/accept_text) 与对应 LLM QC 节点 ID 之间必须保持 1:1 映射。每次 LLM QC 替换后扫一遍 code node variables，**先看 1:1 映射再跑**。
