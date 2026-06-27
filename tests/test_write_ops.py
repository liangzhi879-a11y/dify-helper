"""验证 MCP 写操作工具在真实 Dify 上可用。

测试范围（创建→验证→清理）：
  1. App 写操作：create_app / get_app / delete_app
  2. Dataset 写操作：create_dataset / list_datasets / delete_dataset
  3. Workflow 读操作：get_workflow（基于已有 workflow 应用）
  4. Workspace 读操作：current / model-providers

运行：python tests/test_write_ops.py
"""
import asyncio
import os
import sys
from datetime import datetime

# 加载 mcp_server/.env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"), override=True)

from mcp_server.dify_client import DifyClient, DifyApiError

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "")
TOKEN = os.getenv("DIFY_CONSOLE_TOKEN", "")
CSRF = os.getenv("DIFY_CSRF_TOKEN", "")
REFRESH = os.getenv("DIFY_REFRESH_TOKEN", "")

TS = datetime.now().strftime("%m%d-%H%M%S")
created_app_ids: list[str] = []
created_dataset_ids: list[str] = []


async def run(client: DifyClient) -> bool:
    all_ok = True

    # === 1. App 写操作 ===
    print("\n=== 1. App 写操作 ===")
    app_name = f"MCP_TEST_App_{TS}"
    try:
        r = await client.post("/apps", json={
            "name": app_name,
            "mode": "chat",
            "description": "MCP write-ops 测试，将自动清理",
            "icon_type": "emoji",
            "icon": "🧪",
            "icon_background": "#FFEAD5",
        })
        app_id = r.get("id") if isinstance(r, dict) else None
        if not app_id:
            print(f"  ✗ 创建失败：响应无 id，返回 {str(r)[:200]}")
            all_ok = False
        else:
            created_app_ids.append(app_id)
            print(f"  ✓ create_app: id={app_id}, name={r.get('name')}, mode={r.get('mode')}")
            # 验证 get
            r2 = await client.get(f"/apps/{app_id}")
            print(f"  ✓ get_app: name={r2.get('name') if isinstance(r2, dict) else r2}")
    except DifyApiError as e:
        print(f"  ✗ create_app 错误: [{e.status_code}] {e.message}")
        all_ok = False

    # === 2. Dataset 写操作 ===
    print("\n=== 2. Dataset 写操作 ===")
    ds_name = f"MCP_TEST_Dataset_{TS}"
    try:
        r = await client.post("/datasets", json={
            "name": ds_name,
            "description": "MCP write-ops 测试，将自动清理",
            "indexing_technique": "high_quality",
            "permission": "only_me",
            "provider": "vendor",
            "external_knowledge_api_id": None,
            "external_knowledge_id": None,
        })
        ds_id = r.get("id") if isinstance(r, dict) else None
        if not ds_id:
            print(f"  ✗ 创建失败：响应无 id，返回 {str(r)[:200]}")
            all_ok = False
        else:
            created_dataset_ids.append(ds_id)
            print(f"  ✓ create_dataset: id={ds_id}, name={r.get('name')}")
            # 验证 list
            r2 = await client.get("/datasets", params={"page": 1, "limit": 50})
            if isinstance(r2, dict) and "data" in r2:
                names = [d.get("name") for d in r2["data"]]
                in_list = ds_name in names
                print(f"  ✓ list_datasets: 共 {len(r2['data'])} 个，新建的在列表中: {in_list}")
                if not in_list:
                    all_ok = False
            else:
                print(f"  ✓ list_datasets: {str(r2)[:200]}")
    except DifyApiError as e:
        print(f"  ✗ create_dataset 错误: [{e.status_code}] {e.message}")
        all_ok = False

    # === 3. Workflow 读操作（找已有 workflow 应用）===
    print("\n=== 3. Workflow 读操作 ===")
    try:
        apps = await client.get("/apps", params={"page": 1, "limit": 50})
        wf_app_id = None
        if isinstance(apps, dict) and "data" in apps:
            for a in apps["data"]:
                if a.get("mode") == "workflow":
                    wf_app_id = a.get("id")
                    wf_app_name = a.get("name")
                    break
        if wf_app_id:
            r = await client.get(f"/apps/{wf_app_id}/workflows/draft")
            # workflow 响应包含 graph 节点
            if isinstance(r, dict):
                graph = r.get("graph", {})
                nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
                edges = graph.get("edges", []) if isinstance(graph, dict) else []
                print(f"  ✓ get_workflow: app={wf_app_name}, nodes={len(nodes)}, edges={len(edges)}")
            else:
                print(f"  ✓ get_workflow: {str(r)[:200]}")
        else:
            print(f"  ⚠ 跳过：未找到 workflow 模式应用")
    except DifyApiError as e:
        print(f"  ✗ get_workflow 错误: [{e.status_code}] {e.message}")
        all_ok = False

    # === 4. Workspace 读操作 ===
    print("\n=== 4. Workspace 读操作 ===")
    try:
        ws = await client.get("/workspaces")
        if isinstance(ws, dict) and "workspaces" in ws:
            wss = ws["workspaces"]
            if wss:
                cur = wss[0]
                print(f"  ✓ workspaces: name={cur.get('name', '?')}, id={cur.get('id', '?')}, plan={cur.get('plan', '?')}")
            else:
                print(f"  ✓ workspaces: 列表为空")
        else:
            print(f"  ✓ workspaces: {str(ws)[:200]}")
    except DifyApiError as e:
        print(f"  ✗ workspaces 错误: [{e.status_code}] {e.message}")
        all_ok = False

    try:
        models = await client.get("/workspaces/current/model-providers")
        if isinstance(models, dict):
            data = models.get("data", models)
            if isinstance(data, list):
                print(f"  ✓ model-providers: {len(data)} 个供应商")
                for p in data[:3]:
                    if isinstance(p, dict):
                        print(f"      - {p.get('provider', '?')}")
            else:
                print(f"  ✓ model-providers: {str(models)[:200]}")
        else:
            print(f"  ✓ model-providers: {str(models)[:200]}")
    except DifyApiError as e:
        print(f"  ✗ model-providers 错误: [{e.status_code}] {e.message}")
        all_ok = False

    return all_ok


async def cleanup(client: DifyClient) -> None:
    """清理测试创建的资源。"""
    print("\n=== 清理测试资源 ===")
    for app_id in created_app_ids:
        try:
            await client.delete(f"/apps/{app_id}")
            print(f"  ✓ 删除 app {app_id}")
        except DifyApiError as e:
            print(f"  ✗ 删除 app {app_id} 失败: [{e.status_code}] {e.message}")
    for ds_id in created_dataset_ids:
        try:
            await client.delete(f"/datasets/{ds_id}")
            print(f"  ✓ 删除 dataset {ds_id}")
        except DifyApiError as e:
            print(f"  ✗ 删除 dataset {ds_id} 失败: [{e.status_code}] {e.message}")


async def main() -> int:
    if not (TOKEN and CSRF):
        print("✗ 缺少凭据：DIFY_CONSOLE_TOKEN / DIFY_CSRF_TOKEN")
        return 1
    print(f"目标: {BASE_URL}")
    print(f"Token: {TOKEN[:30]}...")

    client = DifyClient(
        BASE_URL,
        token=TOKEN,
        csrf_token=CSRF,
        refresh_token=REFRESH,
    )
    try:
        ok = await run(client)
        return 0 if ok else 2
    finally:
        await cleanup(client)


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
