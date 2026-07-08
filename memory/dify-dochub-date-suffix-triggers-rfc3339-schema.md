---
name: dify-dochub-date-suffix-triggers-rfc3339-schema
description: DocHub 自动 schema 推断把 _cn 后缀的日期字段（start_date_cn / finish_date_cn）当作 RFC 3339 date 校验，**拒绝中文格式**；要中文显示必须双字段（_cn 传 ISO + _cn_text 传中文）
metadata:
  type: project
---

**症状**: DocHub /api/v1/generate 返回 `HTTP 400 "数据校验失败"` 报错：
```json
{"field": "$.start_date_cn", "message": "字段 '$.start_date_cn' 校验失败：$.start_date_cn: does not match the date pattern must be a valid RFC 3339 full-date"}
```

**根因（实测 PATCH 50 验证）**: DocHub 的 dataJson schema auto-inference 看到 `start_date_cn` / `finish_date_cn` 字段名（_cn 后缀）就把它们推断成 `date` 类型，然后按 RFC 3339 校验（`YYYY-MM-DD`）。**原 PATCH 48 移除 `cn_date_to_iso()` 想直接传中文"2023年1月3日"导致 2 个 schema 错误，文档生成失败。**

**原作者 `cn_date_to_iso()` 的注释是对的**（"DocHub schema 要求 RFC 3339"），不能去掉。

**修复（双字段方案）**:
1. code 节点里恢复 `cn_date_to_iso()` 给 `start_date_cn` / `finish_date_cn`（ISO，给 DocHub schema 校验用）
2. 同时新增 `start_date_cn_text` / `finish_date_cn_text` 字段存中文（DocHub 不会校验 `_text` 后缀）
3. 模板里把所有 `{{start_date_cn}}` 改成 `{{start_date_cn_text}}`（3 处），`{{finish_date_cn}}` 改成 `{{finish_date_cn_text}}`（2 处）

**Why**: DocHub 的 schema 不是用户配的，是看 dataJson 字段名 pattern 自动推的；`_cn` 后缀被识别为日期，`_text` / `_display` / 任何非 `_cn` 后缀被识别为 string。

**How to apply**:
1. 任何 DocHub 模板里出现 `*_cn` 命名的日期字段，**必须**传 ISO 给 DocHub 校验
2. 想要中文显示就必须**额外**加一个字段（如 `*_cn_text` / `*_cn_zh`）给模板渲染用
3. 改模板时同步用 Python 脚本处理：`replace('{{start_date_cn}}', '{{start_date_cn_text}}')` 然后 repack
4. 提交时 PATCH 后必跑一次完整 workflow 验证 RFC 3339 错误是否消失

**反查表**:
| 症状 | 根因 | 修复 |
|---|---|---|
| `$.start_date_cn: does not match RFC 3339` | 传了中文给 _cn 字段 | 改回 ISO + 加 _text 双字段 |
| `$.finish_date_cn: does not match RFC 3339` | 同上 | 同上 |
| 模板显示 2023-01-03 但用户要中文 | 模板用了 {{*_cn}} 而不是 {{*_cn_text}} | 改模板字段名 |

**关联**: [[dify-dochub-empty-date-cn-date-to-iso]] (PATCH 30, 同样要 ISO 不能空) + PATCH 50 脚本 `backups/_tmp_scripts/_patch50_dochub_dual_date_field.py`
