# Dify 源码抓取日志

> 每次抓取追加一行（时间倒序），表头：`时间 / tag / 触发人 / 抓取项 / size 合计 / 失败项 / 备注`

## 2026-07-04 — B1 瘦身决策

- **触发人**: 用户拍板（chat 中选 B1）
- **删除**:
  - `docs/dify-raw/graph_engine/` (9 文件, ≈130KB)
  - `docs/dify-raw/api_console/` (2 文件, ≈45KB)
- **保留**: `docs/dify-raw/nodes/` (7 entities.py, ≈16KB) + README + FETCH_LOG
- **当前体量**: ≈80KB（原来 ≈400KB 全部 + graphon_nodes 空目录 ≈104KB）
- **重新拉回**: `python scripts/dify_sync.py --fetch-engine`（未来需要时）
- **理由**: 节点 schema 真值是 PATCH 第一查证频次最高的；engine / DSL 在 PATCH 中**不是直接查证处**（多数情况靠 `dify_get_app_node` 实际拉取就够）

## 2026-07-04 — 初次抓取（用户本机 session）

- **tag**: 1.14.2（用户 Dify 实例版本）
- **触发人**: Claude (P0.5 阶段)
- **抓取项**:
  - `api/core/workflow/nodes/{agent,datasource,knowledge_index,knowledge_retrieval,trigger_plugin,trigger_schedule,trigger_webhook}/entities.py`（7 文件，约 16.5KB 合计）
  - `api/core/workflow/{graph_topology,node_factory,node_runtime,workflow_entry,system_variables,variable_pool_initializer,template_rendering,variable_prefixes,human_input_adapter}.py`（9 文件，约 130KB 合计）
  - `api/services/app_dsl_service.py`（34.6KB）
  - `api/pyproject.toml`（9.6KB）
- **size 合计**: ~190KB
- **失败项**:
  - `api/core/workflow/graphon/` — graphon 是 PyPI 外部包（`graphon~=0.4.0`），不在 dify 仓库内。旧 18 节点（code/llm/if-else/etc）实际在此包内
  - `api/core/workflow/generator/` — 在 1.14.2 中不存在（重构移除）
- **重大发现**:
  1. **架构重构**（1.13.0 前后）：`api/core/workflow/nodes/` 从 27 子目录（含旧 18 节点）压到 7 子目录（agent/datasource/knowledge_*/trigger_*）。旧 18 节点迁移到 PyPI `graphon~=0.4.0`
  2. **CLAUDE.md "18 节点类型" 表仍有效**：code/llm/if-else/code/template-transform 等节点仍被 Dify 1.14.2 支持，只是源码不在 dify 主仓库
  3. **node_factory.py:119** 是所有节点的注册入口：
     ```
     _import_node_package("graphon.nodes")        # 旧 18 节点
     _import_node_package("core.workflow.nodes")  # 新 7 节点
     ```
- **下次 re-fetch**: 2026-08-04（30 天后）；或 Dify 发布 1.15.0 立即