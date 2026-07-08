---
name: dify-assigner-items-input-type-required
description: Dify VariableAssignerNodeData.items[] 每一条都必须含 input_type 字段（推荐 "variable"）；同名 items 漏一个也会 Pydantic strict-validation 报 missing；DSL import/export 不保证自动补齐
metadata:
  type: project
---

# Assigner items.input_type 是 Pydantic 必填，不是可选

VariableAssignerNodeData.items[] 列表里**每一项都必须**含 `input_type` 字段，即便：

- 同一 assigner 的其它 items[0,1,2...] 都有这个字段
- 字段值是同一个（`"variable"`）
- 用 graphon DSL import/export 不会自动补齐

## 症状

Dify 后端在 **workflow 启动 / publish / debug run** 时跑 Pydantic strict validation，把 graph 序列化成 `VariableAssignerNodeData`，对每个 item 校验字段：

```
2 validation errors for VariableAssignerNodeData
items.3.input_type
  Field required [type=missing, input_value={'operation': 'append',
          'value': ['<node_id>', '<output>'], 'variable_selector': [...]}]
items.4.input_type
  Field required [type=missing, ...]
```

错误里有时给 pydantic.dev 链接 `https://errors.pydantic.dev/2.12/v/missing`。

**注意**：
- 旧版（Dify 1.13 之前 / graphon 旧版本）可能对单 item 是 `dict` 而非 `BaseModel`，所以漏字段 graceful；
- 新版 + strict validation 会硬拒，**workflow 直接不能跑**。

## 推断正确值

`input_type` 的有效值（实测）：
- `"variable"` —— 最常见，value 是某节点输出 `value_selector`
- 其它值（`"constant"` / `"mixed"`）实测目前在 v2 doc-ext 没用过，全部用 `variable`

判断方法：抄邻居 items[0,1,2...] 的 input_type，**永远是字符串 `"variable"`**。

## Why（具体案例）

2026-07-05 复刻 `WF_RDReport (v2 doc-ext)` (cb154f61-...) 时：

源 app **assigner `累积 3 板块 + DocHub URL`** 的 items 列表：
```
item[0] rd_intro_texts   ↓ 输入 intro_markdown   | input_type=variable ✓
item[1] rd_doc_urls      ↓ 输入 tool.text        | input_type=variable ✓
item[2] rd_qc_summaries  ↓ 输入 qc_summary       | input_type=variable ✓
item[3] rd_tech_texts    ↓ 输入 tech_markdown    | input_type MISSING ✗
item[4] rd_accept_texts  ↓ 输入 accept_markdown  | input_type MISSING ✗
```

源 app 跑得好好的（老 graphon 版本不当回事），但 `POST /apps/imports` 严格校验后，**新复刻应用**直接挡在 400。

## How to apply

### 写新 assigner items 时
每个 item 必须包含 4 字段：
```json
{
  "variable_selector": ["<loop_node_id>", "<accum_var_name>"],
  "input_type": "variable",
  "operation": "append" | "over-write" | "clear" | ...,
  "value": ["<source_node_id>", "<source_var_name>"]
}
```

### import 后验证
每个 `data.items[]` 列表都用同款 check：
```python
items = node['data']['items']
for i, it in enumerate(items):
    assert 'input_type' in it, f"items[{i}] missing input_type in {node['data']['title']}"
```

### 复刻场景的标准动作
1. `GET /apps/{src}/export?format=yaml` 拿 DSL
2. **`POST /apps/imports` 落 new app 之前**，先用 PyYAML 解析，加 `assert 'input_type' in it` 跑一遍验证；缺的就近填 `"variable"`
3. 或者 POST 之后立刻拉 `GET /apps/{new}/workflows/draft`，跑同一检验；漏了立刻 PATCH

### PATCH 路径
```python
draft = await client.get(f"/apps/{id}/workflows/draft")
for n in draft['graph']['nodes']:
    if n['data'].get('type') != 'assigner':
        continue
    for i, it in enumerate(n['data']['items']):
        if 'input_type' not in it:
            it['input_type'] = 'variable'   # 与邻居一致
body = {"graph": draft["graph"],
        "features": draft.get("features", {}),
        "environment_variables": draft.get("environment_variables", []),
        "conversation_variables": draft.get("conversation_variables", []),
        "hash": draft["hash"]}
await client.post(f"/apps/{id}/workflows/draft", json=body)
```

关联 [[dify-loop-outputs-type-mismatch]]（type/value_type），[[dify-code-node-outputs-require-value-type]]（value_type 必填同一类），[[dify-import-mode-yaml-content]]（import 严格校验管道）。
