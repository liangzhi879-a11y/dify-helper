"""验证 MCP Server 工具注册完整性。

运行：python tests/test_mcp_tools.py
"""
import asyncio
from mcp_server.server import mcp

EXPECTED_TOOLS = [
    # App 工具组
    "dify_list_apps", "dify_create_app", "dify_get_app", "dify_delete_app",
    "dify_export_dsl", "dify_import_dsl",
    # Workflow 工具组
    "dify_get_workflow", "dify_update_workflow", "dify_publish_workflow",
    "dify_run_workflow_debug", "dify_get_run_status",
    # Dataset 工具组
    "dify_create_dataset", "dify_list_datasets", "dify_add_document_by_text",
    "dify_add_document_by_file", "dify_list_documents", "dify_get_indexing_status",
    "dify_list_segments", "dify_add_segment", "dify_update_segment",
    "dify_delete_segment", "dify_hit_test",
    # Model 工具组
    "dify_list_configured_models", "dify_list_providers", "dify_list_provider_models",
    # Workspace 工具组
    "dify_get_current_workspace", "dify_list_apps_summary",
]

async def get_tool_names():
    tools = await mcp.list_tools()
    return [t.name for t in tools]

def test_all_tools_registered():
    names = asyncio.run(get_tool_names())
    missing = set(EXPECTED_TOOLS) - set(names)
    assert not missing, f"缺少工具: {missing}"
    extra = set(names) - set(EXPECTED_TOOLS)
    assert not extra, f"多余工具: {extra}"
    assert len(names) == 27, f"工具数量应为 27，实际 {len(names)}"

if __name__ == "__main__":
    test_all_tools_registered()
    print(f"✓ 全部 27 个工具注册成功")
    for name in EXPECTED_TOOLS:
        print(f"  - {name}")
