---
name: dify-loop-qc-raise-terminates
description: Dify code 节点里 raise ValueError 配 loop error_handle_mode=terminated 会终止整个 loop；QC 失败场景必须改成 return sentinel 让 loop 继续
metadata:
  type: project
---

Dify loop 节点默认 `error_handle_mode: terminated`，**任一子节点 raise / throw 都会终止整个 loop**。

**症状**：
- loop 累积字段（如 `rd_doc_urls`、`rd_qc_summaries`）长度 < 预期
- task_summary 节点的 `qc_passed` 统计失真（基数 `rd_count` 用 `count_down`，但实际处理的 RD 数 < count_down）
- 部分 RD 项目被静默跳过

**翻车尝试**：在 code node 里 try/except raise → 但 loop 子节点抛错会向上冒泡到 loop 引擎，触发 terminated。

**正确做法**：
- code node 里 QC 失败**不要 raise**，改成 return sentinel：
  ```python
  # ❌ 错: raise 中断 loop
  if not all_passed:
      raise ValueError(f"QC 失败: {failed}")

  # ✅ 对: 把失败信息塞进 qc_summary return
  qc_summary = {
      "all_passed": all_passed,
      "failed_sections": failed,
      ...
  }
  return {"qc_summary": json.dumps(qc_summary), "qc_passed": all_passed, ...}
  ```
- 下游累积节点（assigner / variable_aggregator）按 `qc_summary["all_passed"]` 过滤或标记
- task_summary 节点按 `qc_summary["all_passed"]` 计数

**Why**: PATCH 11 (2026-07-04) 修 WF_RDReport_v2 段落组装节点，原本 QC 失败 raise ValueError → 整个 loop terminated → 后续 50+ RD 项目全部跳过。

**How to apply**:

1. 任何 loop 里调用的 code node QC/校验逻辑，**永远不要 raise**
2. 把"失败详情"放进返回值（如 `qc_summary` / `qc_passed`），让下游决定如何处理
3. 若需"该项失败但其他项继续"，**保证 code node 一定 return**（不要依赖 raise 跳过后续逻辑）
4. 若产品需求是"任何失败就停"，那应该改 loop 节点 `error_handle_mode`，而不是在 code node raise
5. 见 [[dify-loop-iteration-builder]] 关联 loop 节点必填字段

**PATCH 11 落地证据**：

- 节点：`17830458386560`（段落组装 + DocHub dataJson 构建）
- 备份：`backups/WF_RDReport_v2_doc-ext/draft_BEFORE_PATCH_11_20260704_190342.json` (145424 bytes)
- 改完 hash：`769e5a30b26856ba`（前 `18fdf9f4841078c2`）
- code 改动 2 处：
  - 删 7 行 raise 块：`if not all_passed: ... raise ValueError(...)`
  - 新增：`qc_summary["failed_sections"] = failed`
- 发布版本 DSL 备份：`dsl_published_AFTER_PATCH_11_20260704_190342.yaml` (120835 bytes)
- PATCH 脚本：`_tmp_patch_p0_2_qc_continue.py`