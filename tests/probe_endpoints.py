"""探测 Dify 1.14.2 Console API 端点的正确路径。

对 workflow / workspace / model-providers 三组端点，各尝试多种候选路径，
找出返回 200 的那一个，便于修正 MCP Server。
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"), override=True)

import httpx
from mcp_server.dify_client import DifyClient

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "").rstrip("/")
TOKEN = os.getenv("DIFY_CONSOLE_TOKEN", "")
CSRF = os.getenv("DIFY_CSRF_TOKEN", "")
REFRESH = os.getenv("DIFY_REFRESH_TOKEN", "")

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}",
    "X-CSRF-Token": CSRF,
    "Cookie": f"access_token={TOKEN}; csrf_token={CSRF}; refresh_token={REFRESH}",
}

CANDIDATES = {
    "workflow_draft": [
        # 先取一个 workflow 应用的 id
    ],
    "workspace": [
        ("GET", "/workspaces/current"),
        ("GET", "/workspaces"),
        ("GET", "/workspaces/me"),
        ("GET", "/workspace/current"),
        ("GET", "/workspace"),
    ],
    "model_providers": [
        ("GET", "/workspaces/current/model-providers"),
        ("GET", "/workspaces/current/model-providers/models"),
        ("GET", "/workspaces/current/models"),
        ("GET", "/workspaces/current/model-providers/llm/models"),
        ("GET", "/models"),
        ("GET", "/workspaces/current/model-providers/openai/models"),
    ],
}


async def probe(client: httpx.AsyncClient, method: str, path: str) -> tuple[int, str]:
    url = f"{BASE_URL}/console/api{path}"
    try:
        r = await client.request(method, url, headers=HEADERS, timeout=10)
        body = r.text[:120].replace("\n", " ")
        return r.status_code, body
    except Exception as e:
        return 0, f"ERR {e}"


async def main():
    async with httpx.AsyncClient() as client:
        # 1. 找一个 workflow 应用 id
        print("=== 找一个 workflow 应用 ===")
        r = await client.get(
            f"{BASE_URL}/console/api/apps",
            params={"page": 1, "limit": 50},
            headers=HEADERS,
            timeout=10,
        )
        wf_app_id = None
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"  共 {len(data)} 个应用")
            for a in data:
                if a.get("mode") == "workflow":
                    wf_app_id = a.get("id")
                    print(f"  选中 workflow 应用: {a.get('name')} ({wf_app_id})")
                    break
        else:
            print(f"  list apps 失败: {r.status_code}")

        workflow_paths = [
            ("GET", f"/apps/{wf_app_id}/workflow"),
            ("GET", f"/apps/{wf_app_id}/workflow/draft"),
            ("GET", f"/apps/{wf_app_id}/workflow/published"),
            ("GET", f"/apps/{wf_app_id}/workflows"),
            ("GET", f"/apps/{wf_app_id}/workflows/draft"),
        ] if wf_app_id else []

        groups = [
            ("WORKFLOW", workflow_paths),
            ("WORKSPACE", CANDIDATES["workspace"]),
            ("MODEL_PROVIDERS", CANDIDATES["model_providers"]),
        ]

        for name, paths in groups:
            print(f"\n=== {name} ===")
            for method, path in paths:
                code, body = await probe(client, method, path)
                marker = "✓" if code == 200 else "✗"
                print(f"  {marker} [{code}] {method} {path}")
                if code == 200:
                    print(f"      body: {body}")


if __name__ == "__main__":
    asyncio.run(main())
