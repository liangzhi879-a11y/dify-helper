"""测试用 refresh_token 刷新 access_token。"""
import asyncio
import httpx
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"), override=True)

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "").rstrip("/")
REFRESH_TOKEN = os.getenv("DIFY_REFRESH_TOKEN", "")
CSRF_TOKEN = os.getenv("DIFY_CSRF_TOKEN", "")
OLD_ACCESS_TOKEN = os.getenv("DIFY_CONSOLE_TOKEN", "")


async def try_refresh():
    """尝试多种刷新端点和 payload 组合。"""
    candidates = [
        # (url_suffix, json_payload, use_csrf_header, use_cookie)
        ("/refresh-token", {"refresh_token": REFRESH_TOKEN}, True, True),
        ("/refresh-token", {"refresh_token": REFRESH_TOKEN}, False, False),
        ("/refresh", {"refresh_token": REFRESH_TOKEN}, True, True),
        ("/auth/refresh-token", {"refresh_token": REFRESH_TOKEN}, True, True),
        ("/refresh-token", {"refresh_token": REFRESH_TOKEN, "access_token": OLD_ACCESS_TOKEN}, True, True),
    ]

    async with httpx.AsyncClient(timeout=15) as client:
        for suffix, payload, use_csrf, use_cookie in candidates:
            url = f"{BASE_URL}/console/api{suffix}"
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            if use_csrf and CSRF_TOKEN:
                headers["X-CSRF-Token"] = CSRF_TOKEN
            if use_cookie:
                headers["Cookie"] = f"access_token={OLD_ACCESS_TOKEN}; csrf_token={CSRF_TOKEN}; refresh_token={REFRESH_TOKEN}"

            try:
                r = await client.post(url, json=payload, headers=headers)
                body = r.text[:200].replace("\n", " ")
                marker = "✓" if r.status_code == 200 else "✗"
                print(f"  {marker} [{r.status_code}] POST {suffix}  csrf={use_csrf} cookie={use_cookie}")
                print(f"      body: {body}")
                if r.status_code == 200:
                    data = r.json()
                    print(f"      KEYS: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                    # 检查返回结构
                    if isinstance(data, dict):
                        at = data.get("access_token") or data.get("data", {}).get("access_token")
                        rt = data.get("refresh_token") or data.get("data", {}).get("refresh_token")
                        if at:
                            print(f"      NEW access_token: {at[:50]}...")
                            print(f"      NEW refresh_token: {rt[:50] if rt else 'N/A'}")
                            return at, rt
            except Exception as e:
                print(f"  ✗ ERR POST {suffix}: {e}")

    return None, None


async def main():
    print(f"BASE_URL: {BASE_URL}")
    print(f"OLD access_token: {OLD_ACCESS_TOKEN[:40]}...")
    print(f"refresh_token: {REFRESH_TOKEN[:40]}...")
    print()
    at, rt = await try_refresh()
    if at:
        print(f"\n=== 刷新成功 ===")
        print(f"NEW access_token = {at}")
        if rt:
            print(f"NEW refresh_token = {rt}")
    else:
        print(f"\n=== 所有刷新端点都失败 ===")


if __name__ == "__main__":
    asyncio.run(main())
