---
name: dify-dochub-empty-date-cn-date-to-iso
description: DocHub dataJson schema 必填字段 (start_date_cn/finish_date_cn) 要求 RFC 3339 full-date, 拒收空串; Dify cn_date_to_iso 默认空入参返回空串会导致 DocHub 400; 必须在 cn_date_to_iso 层把空输入 → 占位日期 ("2024-01-01")
metadata:
  type: project
---

## 症状
PATCH 29 E2E run (run_id=5a168b27-186b-470b-8599-6b89050addd0) 跑通 5/6 docx 生成, RD02 (iter 2) DocHub 报 400:

```
{"code": 400, "message": "数据校验失败，共 2 个错误", "errors": [
  "字段 '$.start_date_cn' 校验失败: does not match the date pattern must be a valid RFC 3339 full-date",
  "字段 '$.finish_date_cn' 校验失败: does not match the date pattern must be a valid RFC 3339 full-date"
]}
```

`task_summary` 报 "RD 项目总数: 6 / 已生成: 5", doc_count=5, qc_passed=5。

## 根因链
1. **LLM extract (节点 1782973526197)** — RD02 的 Excel 原文确实没有日期, LLM 提取 structured_output `start_date_cn=""`, `finish_date_cn=""` (合理)
2. **defensive code (节点 17832273691320 提取字段兜底)** — 兜底逻辑 `out[f] = '' if v is None else str(v)`, 空字符串原样透传 (合理)
3. **段落组装 (节点 17830458386560) cn_date_to_iso()** — `if not cn_date: return ""`, **空 → 空** (bug 源)
4. **dataJson 构造** — `dataJson["start_date_cn"] = ""`, `dataJson["finish_date_cn"] = ""`
5. **DocHub 校验** — schema `start_date_cn` 是 RFC 3339 date 格式, 拒收空串 → 400
6. **loop error_handle_mode=terminated** (默认) → RD02 失败整个 loop 终止, 后续 RD03-06 都不跑 (但实际上 RD_count=6 + doc_count=5, 说明 RD01 跑成功了, RD02 fail, RD03-06 也 fail)

## Why (为什么不直接 throw / skip)
- 抛错: loop error_handle_mode=terminated, 1 RD fail → 5 RD 全部丢失
- skip: 累积数组里缺一个 RD, task_summary 不连续
- **占位日期 `"2024-01-01"`**: docx 里醒目提示用户"该字段未提取", 但 RFC 3339 通过, workflow 完整跑完

## 修复 (PATCH 30)
- 节点 17830458386560 `cn_date_to_iso()` 函数体:
  ```python
  def cn_date_to_iso(cn_date: str) -> str:
      if not cn_date:
-         return ""
+         return "2024-01-01"  # PATCH 30: 占位日期, DocHub RFC 3339 拒收空串
      m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", cn_date.strip())
      if not m:
          return cn_date
      y, mo, d = m.groups()
      return f"{y}-{int(mo):02d}-{int(d):02d}"
  ```
- 不动 `cn_year_to_cn_text` (project_year_cn 是 string, 无 RFC 3339 约束, 空字符串 OK)
- 不动 cn_date_to_iso 在 finish_date_cn 上的调用 (同一函数同步处理)

## How to apply (下次同类问题)
1. **任何 DocHub dataJson 字段查 schema 约束**: RFC 3339 (date/datetime), regex pattern, min/max length, etc. → 默认值必须满足约束
2. **defensive code 输出兜底值时, 要想下游 schema**: 不能"原样透传 None/空", 要"按 schema 兜底"
3. **rd02 这种 partial extract 场景常见**: Excel 没填的字段 LLM 也提取不到, defensive 透传空 → 下游 schema 校验 fail → **必须 schema-aware 兜底**
4. **E2E 跑通不等于成功**: PATCH 29 跑通 5/6 但 RD02 fail, 必须看 task_summary 的 doc_count + 逐 docx URL 验证
5. **不要改 loop error_handle_mode 来"绕过"**: 从 terminated 改 remove_abnormal 或 continue 会让坏数据累积, 正确做法是**单点 schema 兜底**

## 关联
- [[dify-qc-3node-soften-at-once]] — 同策略: 单点兜底, 不动 loop 全局
- [[dify-llm-output-truncation-breaks-downstream]] — LLM 输出缺字段 → 下游崩, 同根因(LLM 不一定返回 schema 完整字段)
- [[dify-code-node-split-outputs-for-accumulator]] — 1:1 拆分字段避免累积错位
- PATCH 29 → 30 E2E run trace: `e2e_result_patch29_*.json` (RD02 docx 缺失)
- PATCH 30 脚本: `backups/_tmp_scripts/_patch30_cn_date_placeholder.py`