#!/usr/bin/env python3
"""Dify 节点 schema CLI

P2 工具层（task #30）：把"每次 PATCH 都从零写"变成一行命令。

子命令：
  nodes [--type <type>]           列出所有节点类型 + 必填字段
  validate <node_json_path>       单节点校验（必填字段 + value_type 检查）
  drift                           对比 _NODE_SCHEMAS vs docs/dify-raw/ 真值

权威源：
  - 本地字典：mcp_server/mcp_server/server.py:155 _NODE_SCHEMAS
  - dify 自带 7 节点真值：docs/dify-raw/nodes/<type>/entities.py
  - graphon 18 节点真值（外部）：pip download graphon==0.4.0 后 tar

用法示例：
  python scripts/dify_schema.py nodes
  python scripts/dify_schema.py nodes --type code
  python scripts/dify_schema.py validate /tmp/my_node.json
  python scripts/dify_schema.py drift
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ==================== 路径 ====================

SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_ROOT = SCRIPT_DIR.parent
SERVER_PY = HELPER_ROOT / "mcp_server" / "mcp_server" / "server.py"
SCHEMA_REF_MD = HELPER_ROOT / "docs" / "dify-local-schema-reference.md"
DIFY_RAW = HELPER_ROOT / "docs" / "dify-raw" / "nodes"


# ==================== 节点注册表（★全量 25 节点，含 graphon）====================
# 这是 _NODE_SCHEMAS 字典的超集 + value_type 必含校验。
# 改 _NODE_SCHEMAS 时必须同步本表。

_NODE_REGISTRY: dict[str, dict] = {
    # ---------- dify 自带 7 节点（api/core/workflow/nodes/）----------
    "agent": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["agent_strategy_provider", "agent_strategy_name", "agent_parameters"],
        "dify_raw": "docs/dify-raw/nodes/agent/entities.py",
    },
    "datasource": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["datasource_type", "datasource_config"],
        "dify_raw": "docs/dify-raw/nodes/datasource/entities.py",
    },
    "knowledge_index": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["dataset_id", "indexing_technique", "index_chunk_variable_selector"],
        "dify_raw": "docs/dify-raw/nodes/knowledge_index/entities.py",
    },
    "knowledge-retrieval": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["dataset_ids", "query_variable_selector", "retrieval_mode"],
        "dify_raw": "docs/dify-raw/nodes/knowledge_retrieval/entities.py",
    },
    "trigger_plugin": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["plugin_id", "event_name", "event_parameters"],
        "dify_raw": "docs/dify-raw/nodes/trigger_plugin/entities.py",
    },
    "trigger_schedule": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["cron_expression", "timezone"],
        "dify_raw": "docs/dify-raw/nodes/trigger_schedule/entities.py",
    },
    "trigger_webhook": {
        "source": "core.workflow.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["webhook_url", "http_method", "headers", "payload"],
        "dify_raw": "docs/dify-raw/nodes/trigger_webhook/entities.py",
    },
    # ---------- graphon 18 节点（PyPI 外部包 graphon~=0.4.0）----------
    "start": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["variables"],
        "dify_raw": None,
    },
    "end": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["outputs"],
        "dify_raw": None,
    },
    "answer": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["answer"],
        "dify_raw": None,
    },
    "llm": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["model.provider", "model.name", "model.mode", "prompt_template"],
        "dify_raw": None,
    },
    "code": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["code", "variables", "outputs"],
        "dify_raw": None,
        # ★ PATCH 9 根因：outputs[] 必含 value_type（不能仅 type）
        "outputs_required": ["variable", "type", "value_type"],
    },
    "http-request": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["url", "method", "authorization"],
        "dify_raw": None,
    },
    "document-extractor": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["variable_selector"],
        "dify_raw": None,
    },
    "parameter-extractor": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["model", "query", "parameters"],
        "dify_raw": None,
    },
    "question-classifier": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["model", "query", "categories"],
        "dify_raw": None,
    },
    "template-transform": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["template", "variables"],
        "dify_raw": None,
    },
    "if-else": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["cases"],
        "dify_raw": None,
    },
    "iteration": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data", "children"],  # ★ children 在顶层
        "required_data": ["iterator_selector", "output_selector", "start_node_id"],
        "dify_raw": None,
    },
    "loop": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data", "children"],  # ★ children 在顶层
        "required_data": ["start_node_id", "output_selector", "loop_variable"],
        "dify_raw": None,
    },
    "variable-assigner": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["assigned_variable_selector", "operations"],
        "dify_raw": None,
    },
    "variable-aggregator": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["variables", "output_variable_selector"],
        "dify_raw": None,
    },
    "list-operator": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["variable_selector", "operation"],
        "dify_raw": None,
    },
    "tool": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["provider_id", "tool_name", "tool_parameters"],
        "dify_raw": None,
    },
    "assigner": {
        "source": "graphon.nodes",
        "required_top": ["id", "type", "data"],
        "required_data": ["assigned_variable_selector", "write_mode", "value"],
        "dify_raw": None,
    },
}


# ==================== 命令实现 ====================


def cmd_nodes(args: argparse.Namespace) -> int:
    """列出所有节点类型 + 必填字段"""
    if args.type:
        node = _NODE_REGISTRY.get(args.type)
        if not node:
            print(f"❌ 未知节点类型: {args.type}", file=sys.stderr)
            print(f"   可用类型: {', '.join(sorted(_NODE_REGISTRY.keys()))}", file=sys.stderr)
            return 1
        _print_node_detail(args.type, node)
        return 0

    # 全量列表
    by_source: dict[str, list[str]] = {}
    for ntype, info in _NODE_REGISTRY.items():
        by_source.setdefault(info["source"], []).append(ntype)

    print(f"━━━ Dify 1.14.2 节点注册表（共 {len(_NODE_REGISTRY)} 种）━━━\n")
    for source in sorted(by_source.keys()):
        ntypes = sorted(by_source[source])
        print(f"▸ {source}（{len(ntypes)} 个）")
        for ntype in ntypes:
            info = _NODE_REGISTRY[ntype]
            raw = info.get("dify_raw") or "PyPI 外部"
            marker = "★" if "outputs_required" in info else " "
            print(f"   {marker} {ntype:<22} required_data={info['required_data']}")
            print(f"     {' ' * 22} 权威源={raw}")
        print()
    return 0


def _print_node_detail(ntype: str, info: dict) -> None:
    print(f"━━━ {ntype} ━━━")
    print(f"  source         : {info['source']}")
    print(f"  required_top   : {info['required_top']}")
    print(f"  required_data  : {info['required_data']}")
    if "outputs_required" in info:
        print(f"  outputs[] 必含 : {info['outputs_required']}  ★ PATCH 9 强制")
    print(f"  权威源         : {info.get('dify_raw') or 'PyPI 外部 graphon~=0.4.0'}")
    if info.get("dify_raw"):
        raw_path = HELPER_ROOT / info["dify_raw"]
        if raw_path.exists():
            print(f"  本地存在       : ✅ {raw_path.stat().st_size} bytes")
        else:
            print(f"  本地存在       : ❌（需 re-fetch，详见 docs/dify-raw/README.md）")


def cmd_validate(args: argparse.Namespace) -> int:
    """校验单个节点 JSON"""
    path = Path(args.node_json_path)
    if not path.exists():
        print(f"❌ 文件不存在: {path}", file=sys.stderr)
        return 1
    try:
        node = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}", file=sys.stderr)
        return 1

    # data.type 优先于顶层 type（Dify 1.14+ 节点真实类型在 data.type）
    # 参考 memory: dify-1-14-node-type-quirk
    ntype = node.get("data", {}).get("type") or node.get("type")
    if not ntype:
        print(f"❌ 节点无 type 字段（顶层 + data.type 都缺）", file=sys.stderr)
        return 1

    info = _NODE_REGISTRY.get(ntype)
    if not info:
        print(f"❌ 未知节点类型: {ntype}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    # 顶层必填
    for k in info["required_top"]:
        if k not in node:
            errors.append(f"缺顶层字段: {k}")

    # data 必填（简化：只检查第一层 key；嵌套字段如 model.provider 单列）
    data = node.get("data", {})
    for k in info["required_data"]:
        if "." in k:
            # 嵌套字段：model.provider → data.model.provider
            parts = k.split(".")
            cur = data
            for p in parts:
                if not isinstance(cur, dict) or p not in cur:
                    errors.append(f"缺 data.{k}")
                    break
                cur = cur[p]
        else:
            if k not in data:
                errors.append(f"缺 data.{k}")

    # ★ PATCH 9 强制：code node outputs[] 必含 value_type
    if ntype == "code" and "outputs" in data:
        for idx, entry in enumerate(data["outputs"]):
            if not isinstance(entry, dict):
                errors.append(f"outputs[{idx}] 不是 dict")
                continue
            for k in info.get("outputs_required", []):
                if k not in entry:
                    errors.append(f"outputs[{idx}] 缺字段 {k}（★ PATCH 9 根因）")
            # value_type 应等于 type
            if "type" in entry and "value_type" in entry:
                if entry["type"] != entry["value_type"]:
                    warnings.append(
                        f"outputs[{idx}].type ({entry['type']}) "
                        f"!= value_type ({entry['value_type']})"
                    )

    # 输出
    if errors:
        print(f"❌ {ntype} 校验失败（{len(errors)} 错）:")
        for e in errors:
            print(f"   - {e}")
    else:
        print(f"✅ {ntype} 校验通过")

    if warnings:
        print(f"⚠️  警告（{len(warnings)} 条）:")
        for w in warnings:
            print(f"   - {w}")

    return 1 if errors else 0


def cmd_drift(args: argparse.Namespace) -> int:
    """对比 _NODE_SCHEMAS（mcp_server）vs _NODE_REGISTRY（本 CLI）vs docs/dify-raw/ 真值"""
    print("━━━ Schema Drift 检测 ━━━\n")

    # 解析 _NODE_SCHEMAS
    server_schemas = _parse_server_schemas()
    registry = set(_NODE_REGISTRY.keys())
    server = set(server_schemas.keys())

    # 1. _NODE_SCHEMAS 缺失的节点
    missing_in_server = registry - server
    print(f"▸ mcp_server/server.py _NODE_SCHEMAS 缺失节点（应补）:")
    if missing_in_server:
        for n in sorted(missing_in_server):
            print(f"   - {n}")
    else:
        print("   ✅ 无缺失")

    # 2. _NODE_SCHEMAS 多余的（不在 registry 的）
    extra_in_server = server - registry
    print(f"\n▸ mcp_server/server.py _NODE_SCHEMAS 多余（不在 registry）:")
    if extra_in_server:
        for n in sorted(extra_in_server):
            print(f"   - {n}")
    else:
        print("   ✅ 无多余")

    # 3. code 节点缺 value_type 检查（PATCH 9 根因未沉淀）
    code_info = server_schemas.get("code", {})
    code_data_req = code_info.get("data_required", [])
    has_value_type = any("value_type" in r for r in code_data_req)
    print(f"\n▸ code 节点 _NODE_SCHEMAS 必填字段（含 value_type？）:")
    print(f"   当前: {code_data_req}")
    if not has_value_type:
        print(f"   ⚠️  PATCH 9 根因未沉淀进字典！应补 'outputs[].value_type'")
    else:
        print(f"   ✅ 已含 value_type")

    # 4. docs/dify-raw/ 文件存在性
    print(f"\n▸ docs/dify-raw/ 真值文件存在性:")
    missing_files = []
    for ntype, info in _NODE_REGISTRY.items():
        if info.get("dify_raw"):
            full = HELPER_ROOT / info["dify_raw"]
            if not full.exists():
                missing_files.append(f"{ntype} → {info['dify_raw']}")
    if missing_files:
        for m in missing_files:
            print(f"   ❌ {m}")
    else:
        print(f"   ✅ 所有 dify-raw 真值文件就位")

    # 总结
    drift_count = len(missing_in_server) + len(extra_in_server) + (0 if has_value_type else 1) + len(missing_files)
    print(f"\n━━━ Drift 总计: {drift_count} ━━━")
    return 0 if drift_count == 0 else 1


def _parse_server_schemas() -> dict[str, dict]:
    """正则提取 server.py 的 _NODE_SCHEMAS 字典（避免 import 重依赖）"""
    if not SERVER_PY.exists():
        return {}
    src = SERVER_PY.read_text(encoding="utf-8")
    # 找 _NODE_SCHEMAS: dict[str, dict] = { ... } 块
    m = re.search(r"_NODE_SCHEMAS:\s*dict\[str,\s*dict\]\s*=\s*\{(.+?)\n\}\n", src, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, dict] = {}
    # 每行格式: "node-type":               {"required": [...], "data_required": [...]},
    for line in block.split("\n"):
        line = line.strip().rstrip(",").strip()
        if not line or not line.startswith('"'):
            continue
        m2 = re.match(r'"([^"]+)":\s*\{(.+)\}', line)
        if not m2:
            continue
        ntype = m2.group(1)
        fields_str = m2.group(2)
        required = re.findall(r'"required":\s*\[([^\]]*)\]', fields_str)
        data_required = re.findall(r'"data_required":\s*\[([^\]]*)\]', fields_str)
        result[ntype] = {
            "required": [x.strip().strip('"') for x in required[0].split(",")] if required else [],
            "data_required": [x.strip().strip('"') for x in data_required[0].split(",")] if data_required else [],
        }
    return result


# ==================== 入口 ====================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dify 节点 schema CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python scripts/dify_schema.py nodes\n"
               "  python scripts/dify_schema.py nodes --type code\n"
               "  python scripts/dify_schema.py validate /tmp/my_node.json\n"
               "  python scripts/dify_schema.py drift",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_nodes = sub.add_parser("nodes", help="列出节点类型")
    p_nodes.add_argument("--type", help="单个类型详情")

    p_val = sub.add_parser("validate", help="校验节点 JSON")
    p_val.add_argument("node_json_path", help="节点 JSON 文件路径")

    sub.add_parser("drift", help="对比 schema 字典与真值")

    args = parser.parse_args()
    if args.cmd == "nodes":
        return cmd_nodes(args)
    elif args.cmd == "validate":
        return cmd_validate(args)
    elif args.cmd == "drift":
        return cmd_drift(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())