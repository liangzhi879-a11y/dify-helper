"""Dify MCP Server 入口。

基于 mcp 官方 SDK 的 FastMCP，封装 Dify Console API 为 MCP 工具。
所有工具均为 async 函数，返回 JSON 编码的字符串；
遇到 DifyApiError 时返回 {"error": {...}} 而非抛异常，便于调用方处理。
"""
from __future__ import annotations

import base64
import json
import os

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


# ==================== App 工具组（6 个）====================


@mcp.tool()
async def dify_list_apps(page: int = 1, limit: int = 20) -> str:
    """列出当前工作空间下所有 Dify 应用。

    Args:
        page: 页码，从 1 开始
        limit: 每页数量
    """
    try:
        result = await client.get("/apps", params={"page": page, "limit": limit})
        return json.dumps(result, ensure_ascii=False)
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
        icon_background: 图标背景色（十六进制颜色码）
    """
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
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_get_app(app_id: str) -> str:
    """获取指定 Dify 应用的详细信息。

    Args:
        app_id: 应用 ID
    """
    try:
        result = await client.get(f"/apps/{app_id}")
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        name: 新应用名称
        mode: 导入模式，可选 yaml-only / yaml-customize
        description: 应用描述
        dsl_content: DSL 文本内容（YAML 或 JSON 字符串），内部会进行 base64 编码
    """
    try:
        data = base64.b64encode(dsl_content.encode("utf-8")).decode("ascii")
        body = {
            "data": data,
            "mode": mode,
            "name": name,
            "description": description,
        }
        result = await client.post("/apps/import", json=body)
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


# ==================== Workflow 工具组（5 个）====================


@mcp.tool()
async def dify_get_workflow(app_id: str) -> str:
    """获取指定应用的工作流草稿定义（Dify 1.14+ 路径）。

    Args:
        app_id: 应用 ID（需为 workflow 或 advanced-chat 模式）
    """
    try:
        result = await client.get(f"/apps/{app_id}/workflows/draft")
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_update_workflow(
    app_id: str,
    graph: str,
    features: str = "{}",
    environment_variables: str = "[]",
) -> str:
    """更新指定应用的工作流草稿。

    Args:
        app_id: 应用 ID
        graph: 工作流图定义（JSON 字符串）
        features: 功能特性配置（JSON 字符串，默认空对象）
        environment_variables: 环境变量列表（JSON 字符串，默认空数组）
    """
    try:
        body = {
            "graph": json.loads(graph),
            "features": json.loads(features),
            "environment_variables": json.loads(environment_variables),
        }
        result = await client.post(f"/apps/{app_id}/workflows/draft", json=body)
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_publish_workflow(app_id: str) -> str:
    """发布指定应用的工作流草稿为正式版本。

    Args:
        app_id: 应用 ID
    """
    try:
        result = await client.post(f"/apps/{app_id}/workflows/publish")
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_run_workflow_debug(app_id: str, inputs: str = "{}") -> str:
    """以调试模式运行指定应用的工作流。

    Args:
        app_id: 应用 ID
        inputs: 输入参数（JSON 字符串），键名对应工作流开始节点的输入变量
    """
    try:
        body = {"inputs": json.loads(inputs)}
        result = await client.post(f"/apps/{app_id}/workflows/draft/run", json=body)
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


# ==================== Dataset 工具组（11 个）====================


@mcp.tool()
async def dify_create_dataset(
    name: str,
    description: str = "",
    indexing_technique: str = "high_quality",
    permission: str = "only_me",
) -> str:
    """创建一个新的知识库数据集。

    Args:
        name: 数据集名称
        description: 数据集描述
        indexing_technique: 索引方式，可选 high_quality / economical
        permission: 访问权限，可选 only_me / all_team_members / partial_members
    """
    try:
        body = {
            "name": name,
            "description": description,
            "indexing_technique": indexing_technique,
            "permission": permission,
            "provider": "vendor",
            "external_knowledge_api_id": None,
            "external_knowledge_id": None,
        }
        result = await client.post("/datasets", json=body)
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        url = f"{client.base_url}{client.API_PREFIX}/datasets/{dataset_id}/document/create_by_file"
        file_name = os.path.basename(file_path)
        data_payload = {
            "name": file_name,
            "process_rule": {"mode": process_mode},
            "indexing_technique": indexing_technique,
            "doc_form": "text_model",
        }
        headers = {
            "Authorization": f"Bearer {client.token}",
        }
        async with httpx.AsyncClient(timeout=client.TIMEOUT) as http_client:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f)}
                data = {"data": json.dumps(data_payload, ensure_ascii=False)}
                response = await http_client.post(
                    url, headers=headers, files=files, data=data
                )
        if response.status_code < 400:
            try:
                result = response.json()
            except ValueError:
                result = response.text
            return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


@mcp.tool()
async def dify_list_providers() -> str:
    """列出当前工作空间可用的所有模型供应商。"""
    try:
        result = await client.get("/workspaces/current/model-providers")
        return json.dumps(result, ensure_ascii=False)
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
        return json.dumps(result, ensure_ascii=False)
    except DifyApiError as e:
        return _err(e)


# ==================== Workspace 工具组（2 个）====================


@mcp.tool()
async def dify_get_current_workspace() -> str:
    """获取当前工作空间的详细信息。

    Dify 1.14+ 的 /workspaces/current 端点已移除，改用 /workspaces 列表端点
    并返回第一个工作空间（用户的当前工作空间）。
    """
    try:
        result = await client.get("/workspaces")
        # 响应格式：{"workspaces": [{...}, ...]}，取第一个作为当前工作空间
        if isinstance(result, dict) and "workspaces" in result:
            workspaces = result["workspaces"]
            if workspaces:
                return json.dumps(workspaces[0], ensure_ascii=False)
            return json.dumps({"error": "no workspace found"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)
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


def main() -> None:
    """通过 stdio 运行 MCP Server。"""
    mcp.run()


if __name__ == "__main__":
    main()
