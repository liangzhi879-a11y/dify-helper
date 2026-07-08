---
name: dify-llm-output-truncation-breaks-downstream
description: Dify LLM 节点的输出 token 超 max_tokens 4096 时会被截断，触发 finish_reason=length，整个 structured_output 失效，下游拿不到值 → 整个 workflow 像"卡在某节点"假象
metadata:
  type: project
---

# LLM 输出 token 截断 = 下游链路全断（"卡住"假象）

Dify 1.14+ graphon Pydantic 严格校验下，LLM 节点输出超模型 max_tokens（默认 4096 for `minimax-m2.7-highspeed`）会被截断，**`finish_reason=length`**、`completion_tokens` 报错值。

后续触发两层故障：

1. **structured_output 解析失败**：截断的 JSON 不合法（缺 `}` 或字符串未闭合），Dify 后端把 structured_output 当 None。
2. **下游节点"无声"终止**：依赖 `RD_count` / `text` 等 output 的节点（如 loop.iterator_selector、downstream LLM prompt `{{#xxx.text#}}`）拿不到值，可能：
   - 当成空 list 静默 0 次循环
   - 当成 None 不渲染 prompt
   - 整个 workflow status=succeeded 但 outputs={}（看起来"卡住了"）

## 症状

- debug-run 总 elapsed 远小于预期（例：9.5s 跑完，但实际应跑 30s+）
- workflow_finished `total_steps` 等于上游节点数（不含下游）
- `node_execution` 里下游节点**完全 NOT IN TRACE**
- LLM node trace 看 `usage.completion_tokens` 接近或等于 4096/8192（max_tokens 上限）
- LLM node trace 看 `finish_reason: length`

## Why（具体案例）

2026-07-05 调试 WF_RDReport 复刻 app：

| 节点 | 之前（PATCH 19 前） | 之后（PATCH 19） |
|---|---|---|
| llm 结构化提取 schema 字段 | 8 字段含 `RD_PS_excel + TO_AI_excel`（让 LLM 原样保留 2 份完整 markdown） | 删 2 字段留 6 字段 |
| 输出 token | **10240+**（撞 4096 截断） | **619**（正常 stop） |
| LLM 节点 elapsed | 84s | 9.5s |
| structured_output | 解析失败（JSON 缺 `}`）| 完整 6 字段 |
| `RD_count` | null | 18 ✅ |

下游 loop 节点**两次都不跑**（与 PATCH 无关 — SRC 原 app 8b0a043c run 也只跑 1 次 loop），但**至少 PATCH 解决了 JSON 解析失败**这一层。

## How to apply

### 排查"输出 token 截断"
```python
runs = await c.get(f'/apps/{app_id}/workflow-runs?limit=1')
r2 = await c.get(f'/apps/{app_id}/workflow-runs/{runs.data[0].id}/node-executions')
for ne in r2.data:
    out = ne.get('outputs', {}) or {}
    finish = out.get('finish_reason')
    usage = out.get('usage', {})
    if finish == 'length':
        print(f"  ⚠️ {ne.node_id} truncated, tokens={usage.completion_tokens}")
```

### 修法：**缩短 LLM 输出**（不要升级 max_tokens）

LLM 输出量大通常是 prompt 让 LLM 输出**太大对象**（markdown 原样保留、长文 narrative 等）。优先改：

1. **删 schema 中冗余字段** — 原 markdown 喂别的节点用 jinja `{{#doc_xxx.text#}}` 直接拿，不需要 LLM 再 echo
2. **改 prompt** — 给 LLM 摘要/结构化指令，避免原样保留
3. **拆 schema** — 多个大型 markdown 字段拆到不同节点分别调用

### 真正的下游"卡住"陷阱

即便修了 token 截断、JSON 完整，**loop 节点可能仍然不跑**。需要单独排查：
- loop `outputs.*.value_selector` 是否指向存在节点
- loop `break_conditions.value` jinja 是否能解析
- llm_outputs 是否有显式 `outputs: [...]` 字段（隐式空数组可能被 Pydantic strict 拒）

具体见 [[dify-loop-output-selector-not-required]] 和 SRC run trace `8b0a043c`。

## 关联记忆

- [[dify-tool-node-data-required-fields]] — 同一类 Pydantic 严格化问题
- [[dify-code-node-outputs-require-value-type]] — 同样是"虽然 schema 看似松，实际严格拒"
- [[dify-dochub-container-dns-not-loopback]] — plugin daemon / 127.0.0.1 寻址（loop 跑通后的下一步常见错误）
