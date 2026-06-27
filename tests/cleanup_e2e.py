"""清理 E2E 测试创建的资源（应用 + 数据集）。"""
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

    # 清理 E2E 测试应用
    r = await c.get("/apps", params={"limit": 50})
    apps = r.get("data", [])
    e2e_apps = [a for a in apps if "E2E测试" in a.get("name", "")]
    for app in e2e_apps:
        app_id = app["id"]
        name = app.get("name")
        print(f"删除应用: {name} ({app_id})")
        try:
            await c.delete(f"/apps/{app_id}")
            print(f"  ✓ 已删除")
        except Exception as e:
            print(f"  ✗ 失败: {e}")

    # 清理 E2E 测试数据集
    r = await c.get("/datasets", params={"limit": 50})
    data = r if isinstance(r, list) else r.get("data", r.get("data", []))
    if isinstance(data, dict):
        data = data.get("data", [])
    e2e_datasets = [d for d in data if "E2E测试" in d.get("name", "")]
    for ds in e2e_datasets:
        ds_id = ds["id"]
        name = ds.get("name")
        print(f"删除数据集: {name} ({ds_id})")
        try:
            await c.delete(f"/datasets/{ds_id}")
            print(f"  ✓ 已删除")
        except Exception as e:
            print(f"  ✗ 失败: {e}")

    print("\n清理完成")

asyncio.run(main())
