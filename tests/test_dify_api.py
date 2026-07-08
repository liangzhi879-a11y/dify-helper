"""Dify API 连通性测试（需配置真实凭据）。

运行前：
  1. 复制 mcp_server/.env.example 为 mcp_server/.env
  2. 填入真实的 DIFY_CONSOLE_BASE_URL 和 DIFY_CONSOLE_TOKEN
  3. python tests/test_dify_api.py
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv("mcp_server/.env")
from mcp_server.dify_client import DifyClient, DifyApiError

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "http://REDACTED_HOST:9980")
TOKEN = os.getenv("DIFY_CONSOLE_TOKEN", "")

async def test_connectivity():
    if not TOKEN:
        print("⚠ 跳过：未配置 DIFY_CONSOLE_TOKEN")
        return False
    client = DifyClient(BASE_URL, TOKEN)
    try:
        # 测试 1：获取当前工作空间
        ws = await client.get("/workspaces/current")
        print(f"✓ 工作空间: {ws.get('name', ws.get('id', 'unknown'))}")
        # 测试 2：列出应用
        apps = await client.get("/apps", params={"limit": 5})
        count = len(apps.get("data", apps)) if isinstance(apps, dict) else len(apps)
        print(f"✓ 应用列表: {count} 个")
        # 测试 3：列出已配置模型
        models = await client.get("/workspaces/current/model-providers/models")
        print(f"✓ 模型供应商响应正常")
        return True
    except DifyApiError as e:
        print(f"✗ Dify API 错误: [{e.status_code}] {e.message}")
        return False

if __name__ == "__main__":
    print(f"测试目标: {BASE_URL}")
    ok = asyncio.run(test_connectivity())
    if ok:
        print("\n✓ Dify API 连通性测试通过")
    else:
        print("\n✗ 测试未通过")
