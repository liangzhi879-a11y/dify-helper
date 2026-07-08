# Dify PATCH 强制 SOP（5 步流程）

> **目的**：把"猜字段 → 试 → 失败 → 再猜"的循环变成"对比真值 → 1 字段 1 改"的确定性流程。
> **触发条件**：任何 PATCH（改 draft / 发布版 / DSL import / 节点字段）。
> **违反此 SOP 直接退回**。

---

## 5 步强制流程

### 第 1 步 — 拿一个已知正常的同类节点做参照

**为什么**：PATCH 9 翻车 5 次才找对根因 = 因为没先对比 `task_summary_001`。任何字段缺失 / 字段名错误，对比"好的样本"立刻定位。

**操作**：
```python
# 找同 app 或同 workspace 内已知能正常工作的同类节点
# 例如 code 节点 → task_summary_001
# 例如 loop 节点 → 任意已发布的 loop 节点
ref_node = await dify_get_app_node(app_id, "<known_good_node_id>", detail="full")
print(json.dumps(ref_node["data"], indent=2, ensure_ascii=False))
```

### 第 2 步 — 同时拉 draft + published 对比

**为什么**：用户看到的可能是 draft 也可能是 published。Dify UI 通常显示 published（除非是 app owner）。改错版本等于没改。

**操作**：
```python
draft = await dify_get_app(app_id, detail="full")
# 用 dify_export_dsl 拿 published（如果 app 已发布）
# 或 dify_get_workflow(app_id, "published")
```

**对比项**：
- 节点 ID 列表（draft vs published）
- 节点 `data.*` 字段值
- 边（edge）连接

### 第 3 步 — detail=node 单独拉每个 LLM/code 节点

**为什么**：`dify_get_app(detail="full")` 触发 14KB 安全网降级（`_safe_serialize`），prompt_template / code 可能被截断。

**操作**：
```python
for node in draft["workflow"]["graph"]["nodes"]:
    if node["data"]["type"] in ("llm", "code", "knowledge-retrieval"):
        full = await dify_get_app_node(app_id, node["id"], detail="full")
        # 此时拿到完整 prompt_template / code
```

### 第 4 步 — 1 字段 1 改 + 用户验证

**为什么**：PATCH 2 翻车 = 一次改 6 字段，验证失败时不知道哪个生效。

**操作规范**：
- 每次只改 1 个字段
- 改完立即 draft 发布（用 `dify_publish_workflow`）
- 让用户刷新浏览器验证（**不要**自己猜"应该对了"）
- 用户确认后再改下一个字段

### 第 5 步 — 改完同步更新 _NODE_SCHEMAS

**为什么**：下次同类 PATCH 不再翻车 = 把新发现的必填字段加入 `mcp_server/server.py:155 _NODE_SCHEMAS` 字典 + `docs/dify-local-schema-reference.md`。

**操作**：
```python
# mcp_server/mcp_server/server.py 第 155 行 _NODE_SCHEMAS 字典
"code": {
    "required": ["id", "type"],
    "data_required": ["code", "variables", "outputs[].variable", "outputs[].type", "outputs[].value_type"],  # 新增 value_type
}
```

---

## 关键交叉引用

- **节点真实 schema 真值**：`docs/dify-raw/nodes/*/entities.py`（7 个 dify 自带节点）+ PyPI 包 `graphon~=0.4.0`（旧 18 节点外部包）
- **节点注册逻辑**：`docs/dify-raw/graph_engine/node_factory.py:119` `_import_node_package()` 同时 import `graphon.nodes` + `core.workflow.nodes`
- **DSL 导入导出真值**：`docs/dify-raw/api_console/app_dsl_service.py`
- **本地 schema 字典**：`mcp_server/mcp_server/server.py:155 _NODE_SCHEMAS` + `docs/dify-local-schema-reference.md`

---

## 禁止的反模式

- ❌ **凭记忆写字段名** — 必须查 `docs/dify-raw/` 真值或本地 `_NODE_SCHEMAS`
- ❌ **一次性改 N 个字段** — 必须 1 个 1 改
- ❌ **改完不验证就改下一个** — 必须用户验证后再继续
- ❌ **不更新 `_NODE_SCHEMAS`** — 下次同类 PATCH 仍会翻车
- ❌ **不看 published 是否一致** — 用户可能看到旧版
- ❌ **不更新 `docs/CHANGELOG_diy_apps.md`** — 下次调试不知改过什么
- ❌ **不写 memory** — 翻车经验不外化，session 重启就丢

---

## 流程可视化（ASCII）

```
                ┌────────────────────────────────┐
                │  用户报 bug / 需求改 PATCH     │
                └────────────────┬───────────────┘
                                 ↓
       ┌─────────────────────────────────────────────────┐
       │ 第 1 步：找已知正常的同类节点，对比 schema        │
       │ （★权威源 docs/dify-raw/，本地 _NODE_SCHEMAS）  │
       └────────────────────────┬────────────────────────┘
                                ↓
       ┌─────────────────────────────────────────────────┐
       │ 第 2 步：同时拉 draft + published，比对版本      │
       │ （用 dify_get_app full + dify_get_workflow）     │
       └────────────────────────┬────────────────────────┘
                                ↓
       ┌─────────────────────────────────────────────────┐
       │ 第 3 步：detail=node 单独拉 LLM/code 节点        │
       │ （避开 14KB _safe_serialize 截断）               │
       └────────────────────────┬────────────────────────┘
                                ↓
       ┌─────────────────────────────────────────────────┐
       │ 第 4 步：1 字段 1 改 → publish → 用户验证        │
       │ （不要自己猜"应该对了"，必须刷新浏览器）         │
       └────────────────────────┬────────────────────────┘
                                ↓
       ┌─────────────────────────────────────────────────┐
       │ 第 5 步：同步 _NODE_SCHEMAS + schema-reference   │
       │ + 写 memory（症状 + 根因）                       │
       │ + 更新 CHANGELOG_diy_apps.md                     │
       └─────────────────────────────────────────────────┘
```

---

## 相关 SKILL

- `dify-workflow-canvas-debugger` — 改 draft 前的强制预检
- `dify-render-error-debugger` — UI 渲染错误诊断
- `dify-published-draft-diff` — draft vs published 比对
- `dify-schema-drift-detector` — `_NODE_SCHEMAS` vs `docs/dify-raw/` 真值对比
- `dify-patch-codegen` — 自动生成 PATCH 脚本骨架（强制含 value_type 检查）

---

## 维护

- PATCH 后必须追加到 `docs/CHANGELOG_diy_apps.md`
- PATCH 后必须在 `memory/` 写 1 行症状 + 1 行根因
- 任何 SOP 改进 → 同步更新本文件 + `CLAUDE.md` Playbook 表