"""探查 workflow run status 端点（Dify 1.14.2）。"""
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


async def probe(client, method, path):
    url = f"{BASE_URL}/console/api{path}"
    try:
        r = await client.request(method, url, headers=HEADERS, timeout=10)
        body = r.text[:100].replace("\n", " ")
        return r.status_code, body
    except Exception as e:
        return 0, f"ERR {e}"


async def main():
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/console/api/apps",
            params={"page": 1, "limit": 50},
            headers=HEADERS, timeout=10,
        )
        wf_app_id = None
        if r.status_code == 200:
            for a in r.json().get("data", []):
                if a.get("mode") == "workflow":
                    wf_app_id = a.get("id")
                    break
        print(f"workflow app_id = {wf_app_id}\n")

        # 用一个假 run_id '00000000-0000-0000-0000-000000000000' 探测路径
        rid = "00000000-0000-0000-0000-000000000000"
        paths = [
            ("GET", f"/apps/{wf_app_id}/workflow-runs/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflow_runs/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflow/runs/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflows/runs/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflows/draft/runs/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflows/draft/run/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflows/run/{rid}"),
            ("GET", f"/apps/{wf_app_id}/runs/{rid}"),
            ("GET", f"/apps/{wf_app_id}/workflows/{rid}"),
            # 也看下完成流式端点
            ("GET", f"/apps/{wf_app_id}/workflow-runs"),
            ("GET", f"/apps/{wf_app_id}/workflow_runs"),
            ("GET", f"/apps/{wf_app_id}/workflow/runs"),
            ("GET", f"/apps/{wf_app_id}/workflows/draft/runs"),
        ]
        for method, path in paths:
            code, body = await probe(client, method, path)
            marker = "✓" if code == 200 else ("·" if code in (404, 405) else "!")
            print(f"  {marker} [{code}] {method} {path}")
            if code not in (404, 405):
                print(f"      body: {body}")


if __name__ == "__main__":
    asyncio.run(main())
