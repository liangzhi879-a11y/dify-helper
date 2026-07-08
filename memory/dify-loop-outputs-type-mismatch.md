---
name: dify-loop-outputs-type-mismatch
description: Dify loop node outputs[] 类型必须与 assigner 实际 append 的值类型一致（如 array[string] 而非 array[object]）；code node outputs type 和 value_type 必须一致
metadata:
  type: project
---

Dify loop / code 节点的 `outputs[]` 类型声明有 2 个常见不一致：

## 类型不一致 A：loop outputs[] 与 assigner append 值类型不符

**症状**：
- loop outputs[] 声明 `rd_doc_urls: array[object]`，但 assigner items 里 `value: ['http_node', 'body']` 实际 append 的是 string
- 下游 code node (如 task_summary) 解析时拿到 string 数组，但声明期望 object → 强转报错或默默错位

**正确做法**：
- loop outputs[] 类型必须反映 assigner 实际 append 的类型
- 若 value 是 JSON 序列化后的 string（`json.dumps(...)`），声明应是 `array[string]`
- 下游再用 `json.loads(u)` 反序列化

## 类型不一致 B：code outputs[].type 与 value_type 不一致

**症状**（参考 [[dify-code-node-outputs-require-value-type]]）：
- 声明 `type: number, value_type: boolean`
- 实际 `qc_passed: all_passed` 是 bool
- Dify UI 显示 `0/1/2/3/4` array index 作 fallback label（**只在 value_type 缺失时**）
- 即使没 UI 报错，type/value_type 不一致也是 dirty data，未来升级可能突然炸

**正确做法**：
- code outputs[] 每条 type 和 value_type 必须一致
- bool 用 `boolean`，整数用 `number`，字符串用 `string`，对象用 `object`，数组用 `array[*]`

**Why**: PATCH 13 (2026-07-04) 修 WF_RDReport_v2：
- loop outputs `rd_doc_urls/rd_qc_summaries` 原 array[object] → 改 array[string]（assigner value 是 string）
- code outputs `qc_passed` 原 type=number → 改 type=boolean（实际值是 bool）

**How to apply**:

1. 写新 code/loop node 时，type/value_type 字段同时填，且值一致
2. PATCH loop outputs 时，**先查 assigner items[].value 实际是什么类型**（string 还是 object）
3. 不要看 type 默认值（如 `array[string]` 是默认值），**实测为准**
4. 见 [[dify-code-node-outputs-require-value-type]] 关联 value_type 必含 + [[dify-loop-iteration-builder]] 关联 loop 必填字段

**PATCH 13 落地证据**：

- 节点 A：`1782973016950`（loop node）
  - outputs.rd_doc_urls.type: `array[object]` → `array[string]`
  - outputs.rd_qc_summaries.type: `array[object]` → `array[string]`
- 节点 B：`17830458386560`（段落组装 code node）
  - outputs[qc_passed].type: `number` → `boolean`（value_type 已是 boolean）
- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_13_20260704_190610.json` (147064 bytes)
- 改完 hash：`f1af00107e0b4137`（前 `bfef313fa5382f47`）
- 发布版本 DSL 备份：`dsl_published_AFTER_PATCH_13_20260704_190610.yaml` (122040 bytes)
- PATCH 脚本：`_tmp_patch_p1_2_3_type_fix.py`