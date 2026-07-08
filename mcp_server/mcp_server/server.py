"""Dify MCP Server 入口。

基于 mcp 官方 SDK 的 FastMCP，封装 Dify Console API 为 MCP 工具。
所有工具均为 async 函数，返回 JSON 编码的字符串；
遇到 DifyApiError 时返回 {"error": {...}} 而非抛异常，便于调用方处理。
"""
from __future__ import annotations

import base64
import json
import os
import re

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .dify_client import DifyApiError, DifyClient

# 加载 .env（优先从 mcp_server/.env 加载，override=True 覆盖已有环境变量）
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

DIFY_CONSOLE_BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "")
DIFY_CONSOLE_TOKEN = os.getenv("DIFY_CONSOLE_TOKEN", "")        # access_token
DIFY_SESSION_ID = os.getenv("DIFY_SESSION_ID", "")
DIFY_EMAIL = os.getenv("DIFY_EMAIL", "")
DIFY_PASSWORD = os.getenv("DIFY_PASSWORD", "")
DIFY_CSRF_TOKEN = os.getenv("DIFY_CSRF_TOKEN", "")
DIFY_REFRESH_TOKEN = os.getenv("DIFY_REFRESH_TOKEN", "")
# 多 workspace 环境下，填此项可让所有 list/get 请求带上 ?workspace_id=
# （Dify 1.14+ 多数 list 端点支持 workspace 过滤，但创建端点以 token 隐含为准）
DIFY_WORKSPACE_ID = os.getenv("DIFY_WORKSPACE_ID", "").strip()

# 创建 Dify API 客户端实例，按优先级选择认证方式：
# access_token + csrf_token（Dify 1.14+ 浏览器 cookie）> session_id > email+password
client = DifyClient(
    DIFY_CONSOLE_BASE_URL,
    token=DIFY_CONSOLE_TOKEN or None,
    session_id=DIFY_SESSION_ID or None,
    email=DIFY_EMAIL or None,
    password=DIFY_PASSWORD or None,
    csrf_token=DIFY_CSRF_TOKEN or None,
    refresh_token=DIFY_REFRESH_TOKEN or None,
)

# 创建 MCP Server（名为 "dify"），通过 stdio 传输
mcp = FastMCP("dify")


def _err(e: DifyApiError) -> str:
    """将 DifyApiError 序列化为标准 error JSON 字符串。"""
    return json.dumps(
        {
            "error": {
                "status_code": e.status_code,
                "message": e.message,
                "payload": e.payload,
            }
        },
        ensure_ascii=False,
    )


# 大响应硬上限（字节）：超过就强制返回 compact + 提示 Claude 分批查询
# 避免 claude CLI stream-json 解析器因单次响应过大而崩溃。
# 实测 claude CLI tool_result 单行限制约 < 22KB（含 MCP ~2KB + stream-json ~2KB 包装），
# 取 14KB 安全阈值（包装后约 18KB，留 4KB 余量）。
MAX_RESPONSE_BYTES = 14_000


def _serialize(data: dict) -> str:
    """序列化 + 检查大小，超过阈值抛 RuntimeError 触发上层截断逻辑。"""
    s = json.dumps(data, ensure_ascii=False)
    return s


def _safe_serialize(data, max_bytes: int = MAX_RESPONSE_BYTES) -> str:
    """全局安全网：序列化后超过 max_bytes 就返回降级摘要。

    所有 MCP 工具的 return 都应该过这个函数，确保不会返回过大响应触发
    claude CLI stream-json 解析器崩溃。
    """
    s = _serialize(data)
    size = len(s.encode("utf-8"))
    if size <= max_bytes:
        return s
    # 超阈值：返回降级提示
    return _serialize({
        "_error": "response_too_large",
        "_size_bytes": size,
        "_max_bytes": max_bytes,
        "_hint": (
            f"响应 {size // 1024}KB 超过 {max_bytes // 1024}KB 安全阈值。"
            f"这是一个安全限制，避免触发 claude CLI stream-json 解析器崩溃。"
            f"如需详细数据，请用更具体的参数重试（如按节点 ID 分批查询）。"
        ),
        "_data_preview": s[:200] + "..." if size > 500 else s,
    })


def _compress_app_response(app: dict) -> dict:
    """压缩应用响应：只保留 graph 框架，去掉每节点的 prompt 模板等大字段。

    compact 视图保留：
      - 顶层 meta（id/name/mode/description/created_at 等）
      - workflow.graph.nodes: 每个节点仅保留 id/type/title/position
      - workflow.graph.edges: 全保留（通常小）
      - workflow.environment_variables / features / conversation_variables

    移除：每个节点的 data 字段（含 prompt_template、model、code 脚本等大块文本）
    """
    compressed = dict(app)  # shallow copy of top-level fields
    workflow = compressed.get("workflow")
    if isinstance(workflow, dict):
        new_workflow = dict(workflow)
        graph = new_workflow.get("graph")
        if isinstance(graph, dict):
            new_graph = dict(graph)
            nodes = graph.get("nodes") or []
            compact_nodes = []
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                compact_nodes.append({
                    "id": n.get("id"),
                    "type": n.get("type"),
                    "title": n.get("title"),
                    "position": n.get("position"),
                })
            new_graph["nodes"] = compact_nodes
            new_workflow["graph"] = new_graph
        compressed["workflow"] = new_workflow
    return compressed


def _build_app_node_lookup(app: dict) -> dict[str, dict]:
    """从完整应用 JSON 提取 node_id → node 完整数据 的查找表。"""
    nodes = (((app.get("workflow") or {}).get("graph") or {}).get("nodes")) or []
    return {n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")}


# ==================== App 工具组（6 个）====================


# ★ 修复 B4：icon_background 必须是 6 位十六进制颜色（Dify 1.14+ 端点严格校验），
# 否则直接 400。预先在 client 侧拦截，避免白跑一次 API 调用。
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# ★ Phase B：本地节点 schema 缓存（dify_get_node_schema 用）。
# 注意：Dify 实际后端 schema 会随版本变化，这里只覆盖最常用类型。
# 未知类型用 dify_get_app_node(app_id, node_id) 实际拿 data 字段推断。
_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_NODE_SCHEMAS: dict[str, dict] = {
    "start":               {"required": ["id", "type"], "data_required": []},
    "end":                 {"required": ["id", "type"], "data_required": []},
    "answer":              {"required": ["id", "type"], "data_required": ["answer"]},
    "llm":                 {"required": ["id", "type"], "data_required": ["model.provider", "model.name", "model.mode", "prompt_template"]},
    "knowledge-retrieval": {"required": ["id", "type"], "data_required": ["dataset_ids", "query_variable_selector", "retrieval_mode"]},
    "loop":                {"required": ["id", "type"], "data_required": ["start_node_id", "output_selector", "loop_variable"]},
    "iteration":           {"required": ["id", "type"], "data_required": ["iterator_selector", "output_selector", "start_node_id"]},
    "if-else":             {"required": ["id", "type"], "data_required": ["cases"]},
    "code":                {"required": ["id", "type"], "data_required": ["code", "variables"]},
    "http-request":        {"required": ["id", "type"], "data_required": ["url", "method"]},
}


@mcp.tool()
async def dify_list_apps(page: int = 1, limit: int = 20) -> str:
    """列出当前工作空间下所有 Dify 应用。

    Args:
        page: 页码，从 1 开始
        limit: 每页数量
    """
    try:
        result = await client.get("/apps", params={"page": page, "limit": limit})
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_create_app(
    name: str,
    mode: str = "chat",
    description: str = "",
    icon: str = "🤖",
    icon_background: str = "#FFEAD5",
) -> str:
    """创建一个新的 Dify 应用。

    Args:
        name: 应用名称
        mode: 应用模式，可选值：chat / completion / advanced-chat / workflow / agent-chat
        description: 应用描述
        icon: 应用图标（emoji）
        icon_background: 图标背景色，必须是 #RRGGBB 格式（如 #FFEAD5）
    """
    # ★ 修复 B4：icon_background 格式预校验。Dify 1.14+ 后端用正则严格校验，
    # 客户端非法值会被 400 退回，提前拦截节省一次 round-trip。
    if not _HEX_COLOR_RE.match(icon_background):
        return _err(DifyApiError(
            status_code=400,
            message=f"icon_background 格式错误：{icon_background!r} 必须匹配 #RRGGBB（如 #FFEAD5）",
            payload={"field": "icon_background", "expected_format": "#RRGGBB"},
        ))
    try:
        body = {
            "name": name,
            "mode": mode,
            "description": description,
            "icon_type": "emoji",
            "icon": icon,
            "icon_background": icon_background,
        }
        result = await client.post("/apps", json=body)
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_app(
    app_id: str,
    detail: str = "full",
    node_id: str = "",
) -> str:
    """获取指定 Dify 应用的详细信息。

    **默认 full 模式**：返回完整 JSON（含每个节点的 prompt_template / model / code），
    让 Claude 能真正读懂应用源码、定位 bug、设计修改方案。debug/重构场景必须 full。

    14KB 全局安全网会自动降级：完整 JSON 超过阈值 → 返回 compact + _warning 提示。
    此时再用 dify_get_app_node(app_id, node_id) 分批取感兴趣的节点。

    视图级别：
    - 'full'（默认）：完整 JSON，能看到 prompt 模板、模型配置、代码等
    - 'summary'：只返回 graph 框架（id/type/title/position + 边），仅用于快速浏览结构
    - 'node'：配合 node_id 取单节点完整 data（用于大应用分批读取）

    Args:
        app_id: 应用 ID
        detail: 'full'（默认）| 'summary' | 'node'
        node_id: 当 detail='node' 时必填
    """
    try:
        result = await client.get(f"/apps/{app_id}")

        # Dify 1.14+ API quirk：workflow / advanced-chat 模式应用的 GET /apps/{id}
        # 返回的 workflow 字段为 null，真实数据在 /apps/{id}/workflows/draft。
        # 这里自动拉 draft 端点合并到 workflow 字段，让 Claude 一次调用拿到完整数据。
        # ★ 修复：加空值守卫。某些 Dify 版本 GET /apps/{id} 已经返回 workflow=dict，
        # 无条件覆盖会把合法数据替换掉（与 dify_get_app_node 不一致，统一行为）。
        app_mode = result.get("mode", "")
        if app_mode in ("workflow", "advanced-chat") and not (result.get("workflow") or {}).get("graph"):
            try:
                draft = await client.get(f"/apps/{app_id}/workflows/draft")
                if draft:
                    result["workflow"] = draft
            except DifyApiError:
                # 拉 draft 失败就保留原样（workflow=null），claude 可手动调 dify_get_workflow
                pass

        if detail == "full":
            # 调用方明确要求全量：直接返回，但加 size 警告
            payload = _serialize(result)
            if len(payload.encode("utf-8")) > MAX_RESPONSE_BYTES:
                # 即使是 full 也要控制 size，超阈值就降级到 compact + 提示
                compressed = _compress_app_response(result)
                compressed["_warning"] = (
                    f"完整 JSON 超过 {MAX_RESPONSE_BYTES // 1000}KB 阈值，已自动降级为 compact。"
                    f"如需查看某个节点详情，请用 detail='node' + node_id='...' 分批查询。"
                )
                return _serialize(compressed)
            return payload

        if detail == "node":
            if not node_id:
                return _err(DifyApiError(
                    status_code=400,
                    message="detail='node' 必须指定 node_id",
                    payload={},
                ))
            lookup = _build_app_node_lookup(result)
            node = lookup.get(node_id)
            if not node:
                # 列出可用节点 ID 帮调用方排错
                available = list(lookup.keys())[:20]
                return _err(DifyApiError(
                    status_code=404,
                    message=f"node_id={node_id!r} 不存在。可用节点（最多 20 个）: {available}",
                    payload={"available_node_ids": available},
                ))
            return _serialize({"app_id": app_id, "node": node})

        # summary：compact 框架
        compressed = _compress_app_response(result)
        full_size = len(_serialize(result).encode("utf-8"))
        nodes_total = len((result.get("workflow") or {}).get("graph", {}).get("nodes") or [])
        hint_too_big = (
            f"此为 compact 视图（节点只保留 id/type/title/position，data 已剥离）。"
            f"完整 JSON {full_size // 1024}KB / {nodes_total} 节点。"
            f"debug 时建议 detail='full' 一次性看真实 prompt 模板（14KB 内自动）；"
            f"大工作流用 dify_get_app_node(app_id, node_id) 分批读单节点。"
        )
        compressed["_meta"] = {
            "view": "summary",
            "full_size_bytes": full_size,
            "node_count": nodes_total,
            "hint": hint_too_big,
        }
        return _serialize(compressed)

    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_delete_app(app_id: str) -> str:
    """删除指定的 Dify 应用。

    Args:
        app_id: 应用 ID
    """
    try:
        result = await client.delete(f"/apps/{app_id}")
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_enable_app(app_id: str) -> str:
    """启用（恢复）指定的 Dify 应用。

    与 dify_disable_app 配对使用。应用默认即 enabled，仅当曾被 disable 后想恢复时调用。

    Args:
        app_id: 应用 ID
    """
    try:
        result = await client.post(f"/apps/{app_id}/enable", json={})
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_disable_app(app_id: str) -> str:
    """禁用（暂停）指定的 Dify 应用。

    禁用后应用仍存在但 API 调用会被拒绝（返回 403 app_not_active）。
    之后用 dify_enable_app 恢复。

    Args:
        app_id: 应用 ID
    """
    try:
        result = await client.post(f"/apps/{app_id}/disable", json={})
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_update_app_model_config(
    app_id: str,
    model_config_json: str,
) -> str:
    """更新指定应用的模型配置（model_config 块）。

    适用于 chat / completion / agent-chat 三种模式的应用（advanced-chat/workflow
    模式的模型在节点内，不在此端点）。

    Args:
        app_id: 应用 ID
        model_config_json: 完整 model_config JSON 字符串，含 model / prompts /
            completion_params 等字段。结构参考 dify_get_app 返回的 model_config 字段。
            注意：Dify 后端 `POST /apps/{id}/model-config` 是【整体替换】语义（非 PATCH），
            必须传【完整】的 model_config，未传字段会被清空/回默认。
    """
    try:
        body = json.loads(model_config_json)
        if not isinstance(body, dict):
            return _err(DifyApiError(
                status_code=400,
                message="model_config_json 必须是 JSON 对象（dict），不是数组/字符串",
                payload={"received_type": type(body).__name__},
            ))
        # Dify Console 的 model-config 端点只接受 POST（用 PATCH 会 405 method_not_allowed）
        result = await client.post(f"/apps/{app_id}/model-config", json=body)
        return _safe_serialize(result)
    except json.JSONDecodeError as e:
        return _err(DifyApiError(
            status_code=400,
            message=f"model_config_json 不是合法 JSON: {e}",
            payload={},
        ))
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_export_dsl(app_id: str, format: str = "yaml") -> str:
    """导出指定应用的 DSL 配置。

    Args:
        app_id: 应用 ID
        format: 导出格式，可选 yaml 或 json
    """
    try:
        result = await client.get(
            f"/apps/{app_id}/export", params={"format": format}
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_import_dsl(
    name: str,
    mode: str = "yaml-only",
    description: str = "",
    dsl_content: str = "",
) -> str:
    """通过 DSL 内容导入创建新应用。

    Args:
        name: 新应用名称（覆盖 DSL 内的 name）
        mode: 兼容旧参数，已忽略。Dify 1.x 导入端点用 source mode=yaml-content。
        description: 应用描述
        dsl_content: DSL 文本内容（YAML 或 JSON 字符串，原文传入，不做 base64）
    """
    try:
        # Dify 1.x 导入端点为 POST /apps/imports，body 用 {mode:"yaml-content", yaml_content:<raw>}
        # 旧路径 POST /apps/import + base64 data 已在 1.14+ 移除（404）。
        body = {
            "mode": "yaml-content",
            "yaml_content": dsl_content,
            "name": name,
            "description": description,
        }
        result = await client.post("/apps/imports", json=body)
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


# ==================== Workflow 工具组（5 个）====================


@mcp.tool()
async def dify_get_workflow(app_id: str, detail: str = "full") -> str:
    """获取指定应用的工作流草稿定义（Dify 1.14+ 路径）。

    **默认 full 模式**：返回完整工作流 JSON（含每个节点的 prompt_template / model / code），
    让 Claude 能看到真实的 prompt 模板和模型配置。debug/重构工作流必备。

    14KB 安全网自动降级：完整工作流超阈值 → compact + _warning。
    此时用 dify_get_app_node(app_id, node_id) 分批读感兴趣的节点。

    视图级别：
    - 'full'（默认）：完整工作流 JSON
    - 'summary'：只返回 graph 框架，仅用于快速浏览结构

    Args:
        app_id: 应用 ID（需为 workflow 或 advanced-chat 模式）
        detail: 'full'（默认）| 'summary'
    """
    try:
        result = await client.get(f"/apps/{app_id}/workflows/draft")
        full_size = len(_serialize(result).encode("utf-8"))

        if detail == "full":
            if full_size > MAX_RESPONSE_BYTES:
                compressed = _compress_app_response({"workflow": result})
                compressed["_warning"] = (
                    f"完整工作流 {full_size // 1000}KB 超过 {MAX_RESPONSE_BYTES // 1000}KB 阈值，"
                    f"已降级为 compact。请用 dify_get_app_node(app_id, node_id) 分批读单节点。"
                )
                return _serialize(compressed)
            return _serialize(result)

        # summary
        compressed = _compress_app_response({"workflow": result})
        nodes_total = len(result.get("graph", {}).get("nodes") or [])
        compressed["_meta"] = {
            "view": "summary",
            "full_size_bytes": full_size,
            "node_count": nodes_total,
            "hint": (
                f"compact 视图，共 {nodes_total} 节点 / 完整 {full_size // 1024}KB。"
                f"debug 时建议用 detail='full' 看真实 prompt 模板；"
                f"大工作流用 dify_get_app_node(app_id, node_id) 分批读单节点。"
            ),
        }
        return _serialize(compressed)

    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_app_node(app_id: str, node_id: str) -> str:
    """获取指定应用里单个节点的完整数据（含 prompt 模板、模型配置、变量等）。

    当 dify_get_app/dify_get_workflow 返回 summary 后，调用本工具读取单个节点详情。
    适用于 workflow/advanced-chat 应用；chat/completion 应用节点通常无 data 字段。

    单节点超 16KB 时会自动截断 prompt/code 等长字段到 3000 字符（仍标注文本长度）。

    Args:
        app_id: 应用 ID
        node_id: 节点 ID（在 summary 视图的 nodes[].id 里）
    """
    try:
        app = await client.get(f"/apps/{app_id}")
        # Dify 1.14+ quirk：workflow 模式应用的 GET /apps/{id} 返回的 workflow=null，
        # 真实数据在 /apps/{id}/workflows/draft。这里自动拉 draft 让 lookup 能找到节点。
        app_mode = app.get("mode", "")
        if app_mode in ("workflow", "advanced-chat") and not (app.get("workflow") or {}).get("graph"):
            try:
                draft = await client.get(f"/apps/{app_id}/workflows/draft")
                if draft:
                    app["workflow"] = draft
            except DifyApiError:
                pass
        lookup = _build_app_node_lookup(app)
        node = lookup.get(node_id)
        if not node:
            available = list(lookup.keys())[:20]
            return _err(DifyApiError(
                status_code=404,
                message=f"node_id={node_id!r} 不存在。可用节点（最多 20 个）: {available}",
                payload={"available_node_ids": available},
            ))
        payload = {"app_id": app_id, "node": node}
        size = len(_serialize(payload).encode("utf-8"))
        if size > MAX_RESPONSE_BYTES:
            # 单节点也超阈值：截断 prompt/code 字段
            data = node.get("data") or {}
            for field in ("prompt_template", "code", "script", "text"):
                v = data.get(field)
                if isinstance(v, str) and len(v) > 3000:
                    data[field] = v[:3000] + f"... [截断，原文 {len(v)} 字符]"
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, dict) and isinstance(item.get("text"), str) and len(item["text"]) > 3000:
                            item["text"] = item["text"][:3000] + f"... [截断，原文 {len(item['text'])} 字符]"
            # 重算大小
            payload = {"app_id": app_id, "node": node, "_warning": f"单节点原始 {size // 1024}KB 超过 16KB 阈值，prompt/code 已截断到 3000 字符"}
            new_size = len(_serialize(payload).encode("utf-8"))
            if new_size > MAX_RESPONSE_BYTES:
                # 还超？再截一轮
                data = node.get("data") or {}
                for field in ("prompt_template", "code", "script", "text"):
                    v = data.get(field)
                    if isinstance(v, str) and len(v) > 1000:
                        data[field] = v[:1000] + f"... [再次截断，原文 {len(v)} 字符]"
                    elif isinstance(v, list):
                        for i, item in enumerate(v):
                            if isinstance(item, dict) and isinstance(item.get("text"), str) and len(item["text"]) > 1000:
                                item["text"] = item["text"][:1000] + f"... [再次截断，原文 {len(item['text'])} 字符]"
                payload["_warning"] = f"单节点极端大（{size // 1024}KB），已截断到 1000 字符，仍可能需要再分批"
        return _serialize(payload)

    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_update_workflow(
    app_id: str,
    graph: str,
    features: str = "{}",
    environment_variables: str = "[]",
    conversation_variables: str = "",
) -> str:
    """更新指定应用的工作流草稿。

    Args:
        app_id: 应用 ID
        graph: 工作流图定义（JSON 字符串）
        features: 功能特性配置（JSON 字符串，默认空对象）
        environment_variables: 环境变量列表（JSON 字符串，默认空数组）
        conversation_variables: 会话变量列表（JSON 字符串，默认空字符串=不修改该字段）。
            为兼容历史调用，默认空字符串代表"不发送此字段"，由 Dify 保留现有值；
            需要显式 patch（如修复非法 UUID）时传入完整列表。
    """
    body: dict = {
        "graph": json.loads(graph),
        "features": json.loads(features),
        "environment_variables": json.loads(environment_variables),
    }
    # 只有显式传入时才把 conversation_variables 放进 body（默认空字符串=不修改）
    if conversation_variables:
        body["conversation_variables"] = json.loads(conversation_variables)
    try:
        result = await client.post(f"/apps/{app_id}/workflows/draft", json=body)
        return _safe_serialize(result)
    except DifyApiError as e:
        # Dify 1.14+ 并发守卫：客户端提交时必须带最新 hash（来自 GET /workflows/draft），
        # 否则返回 409 `draft_workflow_not_sync`。这里透明刷一次 hash 再 POST 一次，
        # 用户原本提供的 graph/features/conv_vars 完全保留，不会被 Dify 的草稿回填覆盖。
        if (
            e.status_code == 409
            and isinstance(e.payload, dict)
            and e.payload.get("code") == "draft_workflow_not_sync"
        ):
            try:
                draft = await client.get(f"/apps/{app_id}/workflows/draft")
                if isinstance(draft, dict) and draft.get("hash"):
                    body["hash"] = draft["hash"]
                    result = await client.post(f"/apps/{app_id}/workflows/draft", json=body)
                    return _safe_serialize(result)
            except DifyApiError:
                # 重试仍失败（或拿不到 hash）：落到下方把原始 409 返回给调用方。
                pass
        return _err(e)


@mcp.tool()
async def dify_publish_workflow(app_id: str) -> str:
    """发布指定应用的工作流草稿为正式版本。

    Args:
        app_id: 应用 ID
    """
    try:
        # 用 json={} 让 httpx 自动注入 Content-Type: application/json（Dify 1.14+
        # 对空 body POST 不带 Content-Type 会返回 415 unsupported_media_type）。
        result = await client.post(f"/apps/{app_id}/workflows/publish", json={})
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_run_workflow_debug(
    app_id: str,
    inputs: str = "{}",
    response_mode: str = "blocking",
    timeout: int = 60,
) -> str:
    """以调试模式运行指定应用的工作流。

    Args:
        app_id: 应用 ID
        inputs: 输入参数（JSON 字符串），键名对应工作流开始节点的输入变量
        response_mode: 响应模式，blocking（默认，同步等结果）/ streaming（SSE 流式）
        timeout: blocking 模式最长等待秒数，超时返回 504。范围 1-600。
    """
    # ★ 修复 B6：Dify 1.14+ 端点支持 response_mode + timeout 两个参数，
    # 之前硬编码默认 streaming，对 MCP 同步调用不友好（需另起 poll 拿 run_id）。
    # 默认 blocking + 60s 超时，单次 MCP 调用即可拿到 workflow_run_result。
    if response_mode not in ("blocking", "streaming"):
        return _err(DifyApiError(
            status_code=400,
            message=f"response_mode 必须是 blocking 或 streaming，当前: {response_mode!r}",
            payload={"field": "response_mode", "allowed": ["blocking", "streaming"]},
        ))
    if not (1 <= timeout <= 600):
        return _err(DifyApiError(
            status_code=400,
            message=f"timeout 必须在 1-600 秒之间，当前: {timeout}",
            payload={"field": "timeout", "min": 1, "max": 600},
        ))
    try:
        body = {
            "inputs": json.loads(inputs),
            "response_mode": response_mode,
        }
        # 仅 blocking 模式才带 timeout，streaming 模式由 client 端管理
        if response_mode == "blocking":
            body["timeout"] = timeout
        result = await client.post(f"/apps/{app_id}/workflows/draft/run", json=body)
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_run_status(app_id: str, run_id: str) -> str:
    """获取工作流某次运行的状态与结果。

    Args:
        app_id: 应用 ID
        run_id: 运行 ID
    """
    try:
        result = await client.get(f"/apps/{app_id}/workflow-runs/{run_id}")
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


# ==================== Dataset 工具组（11 个）====================


@mcp.tool()
async def dify_create_dataset(
    name: str,
    description: str = "",
    indexing_technique: str = "high_quality",
    permission: str = "only_me",
    provider: str = "",
) -> str:
    """创建一个新的知识库数据集。

    Args:
        name: 数据集名称
        description: 数据集描述
        indexing_technique: 索引方式，可选 high_quality / economical
        permission: 访问权限，可选 only_me / all_team_members / partial_members
        provider: 数据源 provider。vendor（默认，本地知识库）/ external（外挂知识库 API）。
            当 provider=external 时还需通过 dify_update_dataset 补 external_knowledge_api_id
            和 external_knowledge_id（Dify 1.14+ 创建端点需要先有 API 凭据记录）。
    """
    try:
        # ★ 修复 B3：去掉显式的 external_knowledge_api_id/external_knowledge_id: None。
        # 旧版本硬塞两个 null 字段，Dify 1.14+ pydantic 校验在某些版本会 422 拒绝。
        # 不传这两个字段时后端默认 vendor + None，是合法状态。
        body: dict = {
            "name": name,
            "indexing_technique": indexing_technique,
            "permission": permission,
        }
        if description:
            body["description"] = description
        if provider:
            body["provider"] = provider
        result = await client.post("/datasets", json=body)
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_dataset(dataset_id: str) -> str:
    """获取指定数据集的详细配置（含 embedding 模型、检索参数、权限等）。

    Args:
        dataset_id: 数据集 ID
    """
    try:
        result = await client.get(f"/datasets/{dataset_id}")
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_update_dataset(
    dataset_id: str,
    name: str = "",
    description: str = "",
    indexing_technique: str = "",
    permission: str = "",
    retrieval_model_json: str = "",
    embedding_model: str = "",
    embedding_model_provider: str = "",
    external_knowledge_api_id: str = "",
    external_knowledge_id: str = "",
) -> str:
    """更新指定数据集的配置（Dify 1.14+ PATCH 语义）。

    所有参数默认空字符串代表"不修改该字段"，避免误改。
    Dify 1.14+ 该端点支持部分更新（只覆盖传入的字段），未传的字段保留原值。

    Args:
        dataset_id: 数据集 ID
        name: 新名称（空=不修改）
        description: 新描述（空=不修改）
        indexing_technique: 索引方式 high_quality / economical（空=不修改）
        permission: 访问权限 only_me / all_team_members / partial_members（空=不修改）
        retrieval_model_json: 检索模型配置 JSON 字符串（空=不修改）。结构:
            {"search_method": "semantic_search|full_text_search|hybrid_search",
             "top_k": int, "score_threshold": float, "score_threshold_enabled": bool}
        embedding_model: embedding 模型名（如 bge-m3，空=不修改）
        embedding_model_provider: embedding 模型供应商（如 langgenius/bge-m3，空=不修改）
        external_knowledge_api_id: 外挂知识库 API ID（仅 external provider，空=不修改）
        external_knowledge_id: 外挂知识库 ID（仅 external provider，空=不修改）
    """
    try:
        body: dict = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        if indexing_technique:
            body["indexing_technique"] = indexing_technique
        if permission:
            body["permission"] = permission
        if retrieval_model_json:
            rm = json.loads(retrieval_model_json)
            if not isinstance(rm, dict):
                return _err(DifyApiError(
                    status_code=400,
                    message="retrieval_model_json 必须是 JSON 对象",
                    payload={"received_type": type(rm).__name__},
                ))
            body["retrieval_model"] = rm
        if embedding_model:
            body["embedding_model"] = embedding_model
        if embedding_model_provider:
            body["embedding_model_provider"] = embedding_model_provider
        if external_knowledge_api_id:
            body["external_knowledge_api_id"] = external_knowledge_api_id
        if external_knowledge_id:
            body["external_knowledge_id"] = external_knowledge_id
        if not body:
            return _err(DifyApiError(
                status_code=400,
                message="所有字段都为空，没有需要更新的内容",
                payload={},
            ))
        result = await client.patch(f"/datasets/{dataset_id}", json=body)
        return _safe_serialize(result)
    except json.JSONDecodeError as e:
        return _err(DifyApiError(
            status_code=400,
            message=f"retrieval_model_json 不是合法 JSON: {e}",
            payload={},
        ))
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_datasets(page: int = 1, limit: int = 20) -> str:
    """列出当前工作空间下所有数据集。

    Args:
        page: 页码，从 1 开始
        limit: 每页数量
    """
    try:
        result = await client.get("/datasets", params={"page": page, "limit": limit})
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_add_document_by_text(
    dataset_id: str,
    name: str,
    text: str,
    process_mode: str = "automatic",
    indexing_technique: str = "high_quality",
) -> str:
    """通过纯文本为指定数据集新增文档。

    Dify 1.14+ 文本文档创建流程：
    1. 先调用 /files/upload 上传纯文本文件获取 upload_file_id
    2. 再调用 /datasets/{id}/documents 引用该 file_id

    Args:
        dataset_id: 数据集 ID
        name: 文档名称
        text: 文档正文内容
        process_mode: 处理模式，可选 automatic / custom
        indexing_technique: 索引方式，可选 high_quality / economical
    """
    try:
        # 确保已认证（触发自动登录）
        if client.email and client.password:
            await client._ensure_authenticated()

        # 用 client 的完整 headers（含 Authorization + X-CSRF-Token + Cookie 双提交）
        upload_url = f"{client._api_base}/files/upload"
        async with httpx.AsyncClient(timeout=client.TIMEOUT) as http_client:
            upload_resp = await http_client.post(
                upload_url,
                headers=client._headers,
                files={"file": (f"{name}.txt", text.encode("utf-8"), "text/plain")},
            )
        if upload_resp.status_code >= 400:
            try:
                payload = upload_resp.json()
            except ValueError:
                payload = upload_resp.text
            message = (
                payload.get("message") if isinstance(payload, dict) else upload_resp.reason_phrase
            ) or upload_resp.reason_phrase
            raise DifyApiError(upload_resp.status_code, f"file upload failed: {message}", payload)
        file_id = upload_resp.json().get("id")
        if not file_id:
            raise DifyApiError(upload_resp.status_code, f"file upload returned no id: {upload_resp.text[:200]}")

        body = {
            "name": name,
            "indexing_technique": indexing_technique,
            "process_rule": {"mode": process_mode},
            "doc_form": "text_model",
            "data_source": {
                "info_list": {
                    "data_source_type": "upload_file",
                    "file_info_list": {"file_ids": [file_id]},
                }
            },
        }
        result = await client.post(f"/datasets/{dataset_id}/documents", json=body)
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_add_document_by_file(
    dataset_id: str,
    file_path: str,
    process_mode: str = "automatic",
    indexing_technique: str = "high_quality",
) -> str:
    """通过上传本地文件为指定数据集新增文档。

    Args:
        dataset_id: 数据集 ID
        file_path: 本地文件绝对路径
        process_mode: 处理模式，可选 automatic / custom
        indexing_technique: 索引方式，可选 high_quality / economical
    """
    try:
        # 确保已认证（邮箱密码模式下触发自动登录），与 dify_add_document_by_text 一致
        if client.email and client.password:
            await client._ensure_authenticated()

        # ★ 修复：路径 /documents/create_by_file（documents 复数），不是 /document/
        # ★ 修复：使用 client._headers（含 Authorization + X-CSRF-Token + Cookie 双提交），
        #   而不是只塞 Bearer token。Dify 1.14+ 强制双提交，缺 CSRF/Cookie 会 401/403
        url = f"{client._api_base}/datasets/{dataset_id}/documents/create_by_file"
        file_name = os.path.basename(file_path)
        data_payload = {
            "name": file_name,
            "process_rule": {"mode": process_mode},
            "indexing_technique": indexing_technique,
            "doc_form": "text_model",
        }
        async with httpx.AsyncClient(timeout=client.TIMEOUT) as http_client:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f)}
                data = {"data": json.dumps(data_payload, ensure_ascii=False)}
                response = await http_client.post(
                    url, headers=client._headers, files=files, data=data
                )
        if response.status_code < 400:
            try:
                result = response.json()
            except ValueError:
                result = response.text
            return _safe_serialize(result)
        # 解析错误响应
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        message = (
            payload.get("message") if isinstance(payload, dict) else response.reason_phrase
        ) or response.reason_phrase
        raise DifyApiError(response.status_code, message, payload)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_documents(
    dataset_id: str, page: int = 1, limit: int = 20
) -> str:
    """列出指定数据集下的所有文档。

    Args:
        dataset_id: 数据集 ID
        page: 页码，从 1 开始
        limit: 每页数量
    """
    try:
        result = await client.get(
            f"/datasets/{dataset_id}/documents",
            params={"page": page, "limit": limit},
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_delete_document(dataset_id: str, document_id: str) -> str:
    """删除指定数据集下的一个文档（含其全部 segments）。

    Args:
        dataset_id: 数据集 ID
        document_id: 文档 ID
    """
    try:
        result = await client.delete(
            f"/datasets/{dataset_id}/documents/{document_id}"
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_indexing_status(dataset_id: str, document_id: str) -> str:
    """查询指定文档的索引构建状态。

    Args:
        dataset_id: 数据集 ID
        document_id: 文档 ID
    """
    try:
        # Dify 1.14+ indexing-status 是 GET 端点（POST 返回 405）
        result = await client.get(
            f"/datasets/{dataset_id}/documents/{document_id}/indexing-status"
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_batch_get_indexing_status(
    dataset_id: str, document_ids: str
) -> str:
    """批量查询数据集下多个文档的索引构建状态。

    Dify 1.14+ 提供 POST /datasets/{id}/documents/batch-indexing-status 端点，
    单次最多 100 个文档 ID。比循环调用 dify_get_indexing_status 节省 N-1 次 round-trip。

    Args:
        dataset_id: 数据集 ID
        document_ids: 文档 ID 列表（JSON 数组字符串），如 '["doc-id-1", "doc-id-2"]'
    """
    try:
        ids = json.loads(document_ids)
        if not isinstance(ids, list) or not ids:
            return _err(DifyApiError(
                status_code=400,
                message="document_ids 必须是非空 JSON 数组",
                payload={"received_type": type(ids).__name__},
            ))
        if len(ids) > 100:
            return _err(DifyApiError(
                status_code=400,
                message=f"document_ids 最多 100 个，当前 {len(ids)}",
                payload={"max": 100, "received": len(ids)},
            ))
        result = await client.post(
            f"/datasets/{dataset_id}/documents/batch-indexing-status",
            json={"document_ids": ids},
        )
        return _safe_serialize(result)
    except json.JSONDecodeError as e:
        return _err(DifyApiError(
            status_code=400,
            message=f"document_ids 不是合法 JSON: {e}",
            payload={},
        ))
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_segments(
    dataset_id: str,
    document_id: str,
    page: int = 1,
    limit: int = 20,
) -> str:
    """列出指定文档的所有分段。

    Args:
        dataset_id: 数据集 ID
        document_id: 文档 ID
        page: 页码，从 1 开始
        limit: 每页数量
    """
    try:
        result = await client.get(
            f"/datasets/{dataset_id}/documents/{document_id}/segments",
            params={"page": page, "limit": limit},
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_add_segment(
    dataset_id: str,
    document_id: str,
    content: str,
    answer: str = "",
) -> str:
    """为指定文档新增一个分段。

    Args:
        dataset_id: 数据集 ID
        document_id: 文档 ID
        content: 分段正文内容
        answer: 分段对应的问答答案（可选，Q&A 模式使用）
    """
    try:
        body = {
            "segments": [
                {
                    "content": content,
                    "answer": answer,
                    "keywords": [],
                    "enabled": True,
                }
            ]
        }
        result = await client.post(
            f"/datasets/{dataset_id}/documents/{document_id}/segments", json=body
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_update_segment(
    dataset_id: str,
    document_id: str,
    segment_id: str,
    content: str = "",
    answer: str = "",
) -> str:
    """更新指定文档的一个分段内容。

    Args:
        dataset_id: 数据集 ID
        document_id: 文档 ID
        segment_id: 分段 ID
        content: 新的分段正文内容（为空则不更新）
        answer: 新的问答答案（为空则不更新）
    """
    try:
        body: dict = {}
        if content:
            body["content"] = content
        if answer:
            body["answer"] = answer
        result = await client.post(
            f"/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}",
            json=body,
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_delete_segment(
    dataset_id: str, document_id: str, segment_id: str
) -> str:
    """删除指定文档的一个分段。

    Args:
        dataset_id: 数据集 ID
        document_id: 文档 ID
        segment_id: 分段 ID
    """
    try:
        result = await client.delete(
            f"/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}"
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_hit_test(
    dataset_id: str, query: str, top_k: int = 3
) -> str:
    """对指定数据集执行召回测试。

    Args:
        dataset_id: 数据集 ID
        query: 测试查询文本
        top_k: 召回分段数量
    """
    try:
        body = {
            "query": query,
            "retrieval_model": {
                "search_method": "semantic_search",
                "top_k": top_k,
                "score_threshold_enabled": False,
            },
        }
        result = await client.post(
            f"/datasets/{dataset_id}/hit-testing", json=body
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


# ==================== Model 工具组（3 个）====================


@mcp.tool()
async def dify_list_configured_models() -> str:
    """列出当前工作空间已配置的所有模型供应商及其模型。

    Dify 1.14+ 端点为 /workspaces/current/model-providers，返回每个供应商
    的配置信息（含已配置模型列表）。
    """
    try:
        result = await client.get("/workspaces/current/model-providers")
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_providers() -> str:
    """列出当前工作空间可用的所有模型供应商（含未配置的供应商）。

    与 dify_list_configured_models 区分：后者只返回已配置；本工具带
    include_unconfigured=true 拿到完整供应商目录，方便 Claude 推荐模型时
    看到所有可选 provider。
    """
    try:
        result = await client.get(
            "/workspaces/current/model-providers",
            params={"include_unconfigured": "true"},
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_provider_models(provider: str) -> str:
    """列出指定供应商提供的可用模型列表。

    Args:
        provider: 模型供应商标识，如 openai / anthropic / wenxin 等
    """
    try:
        result = await client.get(
            f"/workspaces/current/model-providers/{provider}/models"
        )
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


# ==================== Workspace 工具组（2 个）====================


@mcp.tool()
async def dify_get_current_workspace() -> str:
    """获取当前工作空间的详细信息。

    Dify 1.14+ 的 /workspaces/current 端点已移除，改用 /workspaces 列表端点。
    响应顶层可能含 current_workspace_id（Dify 后端并不总是把当前 workspace 排在第一个），
    优先按它匹配，没有则退回 workspaces[0]。
    """
    try:
        result = await client.get("/workspaces")
        if isinstance(result, dict) and "workspaces" in result:
            workspaces = result["workspaces"]
            if not workspaces:
                return json.dumps({"error": "no workspace found"}, ensure_ascii=False)
            # ★ 修复：优先按 current_workspace_id 匹配，避免被后端排序骗到错误 workspace
            current_id = result.get("current_workspace_id")
            if current_id:
                for ws in workspaces:
                    if ws.get("id") == current_id:
                        return json.dumps(ws, ensure_ascii=False)
            return json.dumps(workspaces[0], ensure_ascii=False)
        return _safe_serialize(result)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_apps_summary() -> str:
    """列出工作空间内全部应用的摘要信息（精简版）。

    仅返回每个应用的 id / name / mode / status 字段，
    便于 Claude Code 快速了解工作空间内有哪些应用。
    """
    try:
        result = await client.get("/apps", params={"limit": 100})
        # 兼容 result 可能是 dict（含 data 字段）或 list 的两种返回结构
        if isinstance(result, dict):
            apps = result.get("data", result)
        else:
            apps = result
        summary = []
        if isinstance(apps, list):
            for app in apps:
                if not isinstance(app, dict):
                    continue
                summary.append(
                    {
                        "id": app.get("id"),
                        "name": app.get("name"),
                        "mode": app.get("mode"),
                        "status": app.get("status"),
                    }
                )
        return json.dumps(summary, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


# ==================== Phase B 诊断工具（6 个，新增）====================
#
# 设计原则：每个工具都先尝试 Dify 后端"理想"端点；不支持时 fallback 到本地逻辑。
# 所有 return 都过 _safe_serialize 14KB 安全网。
# 所有工具都返回结构化错误（不要抛异常），调用方易于处理。


@mcp.tool()
async def dify_validate_draft(app_id: str) -> str:
    """校验工作流 draft 的合法性，返回字段级错误清单。

    行为：
    1. 先尝试 Dify 后端 dry-run 端点（POST ...?dry_run=true），后端能直接校验就用它
    2. 后端不支持（如 404）：fallback 到本地 JSON schema 校验（节点必填、边引用、UUID 合法性）

    本地校验包括：
    - 节点 ID 唯一性
    - 边 source/target 引用完整性
    - start 节点唯一性
    - conversation_variables.id UUID v4 合法性（warning 级，前端常容错）
    - 节点必填字段（基于 _NODE_SCHEMAS）

    Args:
        app_id: 应用 ID（需为 workflow 或 advanced-chat 模式）
    """
    errors: list[dict] = []

    # 1. 尝试 Dify 后端 dry-run 端点
    # 注意：Dify 1.14+ 没有官方 dry-run 端点。`?dry_run=true` 会被当成未知 query param
    # 拒掉（400），所以**直接走本地校验**，不再尝试后端端点。
    # 留着这段注释让未来读者知道为什么没有 backend 路径可走。

    # 2. 本地校验
    try:
        workflow = await client.get(f"/apps/{app_id}/workflows/draft")
    except DifyApiError as e:
        return _err(e)

    if not isinstance(workflow, dict):
        return _safe_serialize({
            "valid": False,
            "validated_by": "local",
            "errors": [{"source": "local", "message": "draft workflow 不是 dict 类型"}],
        })

    graph = workflow.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    # 校验 A：节点 ID 唯一性
    node_ids: list[str] = [n.get("id") for n in nodes if isinstance(n, dict)]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for nid in node_ids:
        if nid in seen:
            duplicates.add(nid)
        seen.add(nid)
    if duplicates:
        errors.append({
            "source": "local",
            "type": "duplicate_node_id",
            "severity": "error",
            "message": f"节点 ID 重复: {sorted(duplicates)}",
        })

    # 校验 B：边引用完整性
    node_id_set = set(node_ids)
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        eid = edge.get("id")
        if src and src not in node_id_set:
            errors.append({
                "source": "local",
                "type": "edge_source_missing",
                "severity": "error",
                "message": f"边 source={src!r} 指向不存在的节点",
                "edge_id": eid,
            })
        if tgt and tgt not in node_id_set:
            errors.append({
                "source": "local",
                "type": "edge_target_missing",
                "severity": "error",
                "message": f"边 target={tgt!r} 指向不存在的节点",
                "edge_id": eid,
            })

    # 校验 C：start 节点唯一
    # ★ Dify 1.14+ 关键 quirk：顶层 node.type 永远是 "custom"，
    # 真实类型在 node.data.type 里。判断 start 节点要查 data.type。
    def _real_type(node: dict) -> str:
        if not isinstance(node, dict):
            return ""
        data = node.get("data") or {}
        return (data.get("type") or node.get("type") or "").strip()

    start_nodes = [n for n in nodes if isinstance(n, dict) and _real_type(n) == "start"]
    if len(start_nodes) != 1:
        errors.append({
            "source": "local",
            "type": "start_node_count",
            "severity": "error",
            "message": f"start 节点应有且仅有 1 个，实际 {len(start_nodes)} 个",
        })

    # 校验 D：UUID 合法性（仅 conversation_variables，warning 级）
    conv_vars = workflow.get("conversation_variables") or []
    for var in conv_vars:
        if isinstance(var, dict):
            var_id = var.get("id", "")
            if not _UUID_V4_RE.match(var_id):
                errors.append({
                    "source": "local",
                    "type": "invalid_uuid",
                    "severity": "warning",
                    "message": f"conversation_variables.id 不是合法 UUID v4: {var_id!r}",
                    "var_name": var.get("name"),
                    "hint": "前端常容错，可能不是渲染错误的根因。建议先看 console 报错再决定是否改 UUID",
                })

    # 校验 E：节点必填字段（基于 _NODE_SCHEMAS）
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = _real_type(node)
        schema = _NODE_SCHEMAS.get(ntype)
        if not schema:
            continue
        data = node.get("data") or {}
        for path in schema.get("data_required", []):
            keys = path.split(".")
            current = data
            missing = False
            for k in keys:
                if not isinstance(current, dict) or k not in current:
                    missing = True
                    break
                v = current[k]
                if v is None or v == "" or v == []:
                    missing = True
                    break
                current = v
            if missing:
                errors.append({
                    "source": "local",
                    "type": "missing_required_field",
                    "severity": "error",
                    "message": f"节点 {node.get('id')!r} ({ntype}) 缺少必填字段: {path}",
                    "node_id": node.get("id"),
                    "field": path,
                })

    # 校验 F：loop children 节点是否缺 positionAbsolute
    # ★ Dify 1.14+ quirk：loop/iteration 的 children 是 dict {"nodes": [...]}，
    # 不是直接的 list。
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _real_type(node) in ("loop", "iteration"):
            children_container = node.get("children") or {}
            if isinstance(children_container, dict):
                children = children_container.get("nodes") or []
            elif isinstance(children_container, list):
                children = children_container
            else:
                children = []
            for child in children:
                if isinstance(child, dict) and "positionAbsolute" not in child:
                    errors.append({
                        "source": "local",
                        "type": "loop_child_missing_position",
                        "severity": "warning",
                        "message": f"loop/iteration 子节点缺 positionAbsolute 字段，可能导致渲染异常",
                        "parent_id": node.get("id"),
                        "child_id": child.get("id"),
                    })

    error_count = sum(1 for e in errors if e.get("severity") == "error")
    warning_count = sum(1 for e in errors if e.get("severity") == "warning")

    return _safe_serialize({
        "valid": error_count == 0,
        "validated_by": "local",
        "fallback_reason": "Dify 后端不支持 dry-run 端点，使用本地 JSON schema 校验",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "error_count": error_count,
        "warning_count": warning_count,
        "errors": errors,
    })


@mcp.tool()
async def dify_export_draft_dsl(app_id: str, format: str = "yaml") -> str:
    """导出 draft workflow 的 DSL（未发布版本）。

    与 dify_export_dsl（导出已发布版本）不同，本工具拿 draft 的当前状态。
    行为：
    1. 尝试 GET /apps/{id}/workflows/draft/export?format=yaml
    2. 后端不支持：fallback 到拿 draft workflow + 本地 PyYAML 序列化

    Args:
        app_id: 应用 ID
        format: 导出格式，yaml（默认）或 json
    """
    if format not in ("yaml", "json"):
        return _err(DifyApiError(
            status_code=400,
            message=f"format 必须是 yaml 或 json，当前: {format!r}",
            payload={"field": "format", "allowed": ["yaml", "json"]},
        ))

    # 1. 尝试后端 draft export 端点
    try:
        result = await client.get(
            f"/apps/{app_id}/workflows/draft/export",
            params={"format": format},
        )
        return _safe_serialize({
            "format": format,
            "backend_export": True,
            "content": result,
        })
    except DifyApiError as e:
        if e.status_code not in (404, 405):
            return _err(e)
        # 404/405：fallback

    # 2. Fallback：拿 draft workflow + 本地序列化
    try:
        workflow = await client.get(f"/apps/{app_id}/workflows/draft")
    except DifyApiError as e:
        return _err(e)

    if format == "yaml":
        try:
            import yaml  # type: ignore
            content = yaml.safe_dump(workflow, allow_unicode=True, sort_keys=False)
            return _safe_serialize({
                "format": "yaml",
                "backend_export": False,
                "fallback_reason": "Dify 后端无 draft export 端点，使用本地 PyYAML 序列化",
                "content": content,
            })
        except ImportError:
            # PyYAML 不可用：返回 JSON（YAML 1.2 是 JSON 的超集，JSON 语法 YAML 解析器可读）
            return _safe_serialize({
                "format": "json-as-yaml-fallback",
                "backend_export": False,
                "fallback_reason": "Dify 后端无 draft export 端点，且 PyYAML 未安装",
                "content": workflow,
            })

    # format == "json"
    return _safe_serialize({
        "format": "json",
        "backend_export": False,
        "fallback_reason": "Dify 后端无 draft export 端点",
        "content": workflow,
    })


@mcp.tool()
async def dify_get_node_schema(node_type: str = "") -> str:
    """获取节点类型的必填字段（本地缓存，离线可用）。

    行为：
    - node_type 为空：返回所有支持的类型清单
    - node_type 已知：返回该类型的必填字段列表
    - node_type 未知：提示用 dify_get_app_node 推断

    本地缓存的 schema 不一定 100% 准确（Dify 实际后端 schema 会随版本变化），
    建议同时调 dify_get_app_node(app_id, node_id) 看实际节点的 data 字段对比。

    Args:
        node_type: 节点类型（llm/loop/iteration/if-else 等），空=列出所有类型
    """
    if not node_type:
        return _safe_serialize({
            "supported_types": list(_NODE_SCHEMAS.keys()),
            "note": "传入 node_type 参数获取具体类型的必填字段",
        })

    schema = _NODE_SCHEMAS.get(node_type)
    if not schema:
        return _safe_serialize({
            "node_type": node_type,
            "supported": False,
            "supported_types": list(_NODE_SCHEMAS.keys()),
            "suggestion": f"类型 {node_type!r} 未在本地缓存。建议调 dify_get_app_node(app_id, node_id) 看实际节点的 data 字段推断必填项。",
        })

    return _safe_serialize({
        "node_type": node_type,
        "supported": True,
        "schema": schema,
        "note": "此为本地缓存，Dify 实际后端可能略有差异。建议同时调 dify_get_app_node 看实际节点配置。",
    })


@mcp.tool()
async def dify_rollback_workflow(app_id: str, version: str = "") -> str:
    """回滚工作流到指定版本（如果后端支持）。

    Dify 1.14+ 后端可能支持 POST /apps/{id}/workflows/rollback。
    本工具**不做 fallback**（回滚是不可逆操作，宁可失败也不要乱猜）。

    常见错误：
    - 404：Dify 后端无 rollback 端点（提示用户去 UI 手动回滚）
    - 403：权限不够 / 该 App 没有历史版本

    Args:
        app_id: 应用 ID
        version: 目标版本号（可选）。空=回滚到上一版本（行为取决于后端）。
    """
    try:
        body: dict = {}
        if version:
            body["version"] = version
        result = await client.post(f"/apps/{app_id}/workflows/rollback", json=body)
        return _safe_serialize({
            "rolled_back": True,
            "result": result,
            "warning": "回滚是不可逆操作。请刷新 Dify UI 验证回滚后的 workflow 渲染正常。",
        })
    except DifyApiError as e:
        if e.status_code == 404:
            return _safe_serialize({
                "rolled_back": False,
                "status_code": 404,
                "error": "Dify 后端无 rollback 端点（HTTP 404）",
                "suggestion": "手动方案：在 Dify UI → App 设置 → 版本历史 → 选旧版本 → 点'恢复到此版本'。",
            })
        if e.status_code == 403:
            return _safe_serialize({
                "rolled_back": False,
                "status_code": 403,
                "error": f"Dify 后端拒绝回滚：{e.message}",
                "suggestion": "可能权限不够，或该 App 没有可回滚的历史版本。",
            })
        return _err(e)


@mcp.tool()
async def dify_duplicate_workflow(app_id: str, name: str = "") -> str:
    """复制指定 app 为新 app（用于克隆已知能跑的工作流当模板）。

    行为：
    1. 尝试 Dify 后端 copy 端点（POST /apps/{id}/copy）
    2. 后端不支持：fallback 到 export_dsl + import_dsl

    Args:
        app_id: 源应用 ID
        name: 新应用名称（可选，默认在 import fallback 时用 "[app_id] Copy"）
    """
    # 1. 尝试后端 copy 端点
    try:
        body: dict = {}
        if name:
            body["name"] = name
        result = await client.post(f"/apps/{app_id}/copy", json=body)
        return _safe_serialize({
            "duplicated": True,
            "method": "backend_copy",
            "result": result,
        })
    except DifyApiError as e:
        if e.status_code not in (404, 405):
            return _err(e)
        # 404/405：fallback

    # 2. Fallback：export + import
    try:
        # 拿源 app 的 DSL
        try:
            dsl_resp = await client.get(f"/apps/{app_id}/export", params={"format": "yaml"})
            # Dify export 端点返回 {"data": "...", "...": ...} 格式
            if isinstance(dsl_resp, dict) and isinstance(dsl_resp.get("data"), str):
                dsl_content = dsl_resp["data"]
            else:
                dsl_content = json.dumps(dsl_resp, ensure_ascii=False)
        except DifyApiError as e:
            return _safe_serialize({
                "duplicated": False,
                "method": "fallback_failed",
                "error": f"无法拿源 app 的 DSL：{e.message}",
                "suggestion": "请手动在 Dify UI 复制 app。",
            })

        # 用 import 端点创建新 app（Dify 1.x: POST /apps/imports + yaml_content 原文）
        new_name = name or f"Copy of {app_id}"
        import_body = {
            "mode": "yaml-content",
            "yaml_content": dsl_content,
            "name": new_name,
        }
        result = await client.post("/apps/imports", json=import_body)
        return _safe_serialize({
            "duplicated": True,
            "method": "export_then_import_fallback",
            "result": result,
            "note": "Dify 后端无 copy 端点，已通过 export + import 实现复制",
        })
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_run_trace(app_id: str, run_id: str) -> str:
    """获取工作流某次运行的节点级 trace（含每节点 inputs/outputs/elapsed_ms/error）。

    行为：
    1. 尝试 Dify 后端 node-executions 端点（GET /apps/{id}/workflow-runs/{run_id}/node-executions）
    2. 后端不支持：fallback 到 dify_get_run_status（仅 summary，节点级信息缺失）

    Args:
        app_id: 应用 ID
        run_id: 运行 ID（dify_run_workflow_debug 返回的 workflow_run_id）
    """
    # 1. 尝试后端 node-executions 端点
    try:
        result = await client.get(f"/apps/{app_id}/workflow-runs/{run_id}/node-executions")
        return _safe_serialize({
            "trace_source": "backend_node_executions",
            "trace": result,
        })
    except DifyApiError as e:
        if e.status_code not in (404, 405):
            return _err(e)
        # 404/405：fallback

    # 2. Fallback：拿 run summary
    try:
        summary = await client.get(f"/apps/{app_id}/workflow-runs/{run_id}")
        return _safe_serialize({
            "trace_source": "backend_run_summary_fallback",
            "trace": summary,
            "fallback_reason": "Dify 后端无 node-executions 端点，返回 run summary（节点级信息有限）",
            "note": "如需详细 trace，建议升级 Dify 后端或用日志/审计系统。",
        })
    except DifyApiError as e:
        return _err(e)


def main() -> None:
    """通过 stdio 运行 MCP Server。"""
    mcp.run()


if __name__ == "__main__":
    main()
