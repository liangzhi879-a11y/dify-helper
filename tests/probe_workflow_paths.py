"""探查 workflow 写操作端点的正确路径（Dify 1.14.2）。

已知 GET /apps/{app_id}/workflows/draft 工作，再验证：
- POST /apps/{app_id}/workflows/draft (update)
- POST /apps/{app_id}/workflows/publish (publish)
- POST /apps/{app_id}/workflows/run (run debug)
- GET /apps/{app_id}/workflows/runs/{run_id} (status)
- GET /apps/{app_id}/workflows/published (published version)

仅用 OPTIONS 或 GET 探测路径是否存在（不实际触发写操作）。
"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"), override=True)

import httpx

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


async def probe(client, method, path, **kwargs):
    url = f"{BASE_URL}/console/api{path}"
    try:
        r = await client.request(method, url, headers=HEADERS, timeout=10, **kwargs)
        body = r.text[:160].replace("\n", " ")
        return r.status_code, body
    except Exception as e:
        return 0, f"ERR {e}"


async def main():
    async with httpx.AsyncClient() as client:
        # 取一个 workflow app
        r = await client.get(
            f"{BASE_URL}/console/api/apps",
            params={"page": 1, "limit": 50},
            headers=HEADERS,
            timeout=10,
        )
        wf_app_id = None
        if r.status_code == 200:
            for a in r.json().get("data", []):
                if a.get("mode") == "workflow":
                    wf_app_id = a.get("id")
                    break
        print(f"workflow app_id = {wf_app_id}\n")

        # 各种候选路径
        paths = [
            # 已确认可用
            ("GET",    f"/apps/{wf_app_id}/workflows"),
            ("GET",    f"/apps/{wf_app_id}/workflows/draft"),
            # 待确认（GET 探测，不发数据）
            ("GET",    f"/apps/{wf_app_id}/workflows/published"),
            ("GET",    f"/apps/{wf_app_id}/workflows/publish"),
            ("GET",    f"/apps/{wf_app_id}/workflows/run"),
            ("GET",    f"/apps/{wf_app_id}/workflows/runs"),
            ("GET",    f"/apps/{wf_app_id}/workflows/runs/test"),
            # 旧路径（已知 404）
            ("GET",    f"/apps/{wf_app_id}/workflow"),
            ("GET",    f"/apps/{wf_app_id}/workflow/draft"),
        ]

        for method, path in paths:
            code, body = await probe(client, method, path)
            marker = "✓" if code == 200 else ("·" if code in (404, 405) else "!")
            print(f"  {marker} [{code}] {method} {path}")
            if code == 200:
                print(f"      body: {body}")

        # POST 路径用空 body 探测（会因参数缺失返回 400/422，但 400 比 404 说明路径存在）
        print("\n--- POST 路径探测（无 body，400=路径存在，404=路径不存在） ---")
        post_paths = [
            f"/apps/{wf_app_id}/workflows/draft",
            f"/apps/{wf_app_id}/workflows/publish",
            f"/apps/{wf_app_id}/workflows/run",
            f"/apps/{wf_app_id}/workflow",
            f"/apps/{wf_app_id}/workflow/publish",
            f"/apps/{wf_app_id}/workflow/run",
        ]
        for path in post_paths:
            code, body = await probe(client, "POST", path)
            marker = "·" if code in (400, 422) else ("✓" if code == 200 else "!")
            print(f"  {marker} [{code}] POST {path}")
            print(f"      body: {body[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
