"""检查 E2E 测试创建的应用详情。"""
import asyncio
import os
from dotenv import load_dotenv
from mcp_server.dify_client import DifyClient

load_dotenv("mcp_server/.env", override=True)

async def main():
    c = DifyClient(
        os.environ["DIFY_CONSOLE_BASE_URL"],
        email=os.environ["DIFY_EMAIL"],
        password=os.environ["DIFY_PASSWORD"],
    )
    r = await c.get("/apps", params={"limit": 50})
    apps = r.get("data", [])
    target = [a for a in apps if a.get("name") == "E2E测试-客服工作流"]
    if not target:
        print("未找到 E2E测试-客服工作流 应用")
        return
    app = target[0]
    app_id = app["id"]
    print(f"app_id: {app_id}")
    print(f"mode: {app.get('mode')}")
    print(f"status: {app.get('status')}")

    # 查 workflow draft
    wf = await c.get(f"/apps/{app_id}/workflows/draft")
    graph = wf.get("graph", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    print(f"nodes: {len(nodes)}")
    print(f"edges: {len(edges)}")
    print(f"node types: {[n.get('data', {}).get('type') for n in nodes]}")
    print(f"node titles: {[n.get('data', {}).get('title') for n in nodes]}")

asyncio.run(main())
