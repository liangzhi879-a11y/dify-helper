"""测试从登录响应的 cookies 提取 token。"""
import asyncio
import base64
import httpx
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"), override=True)

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "").rstrip("/")
EMAIL = os.getenv("DIFY_EMAIL", "")
PASSWORD = os.getenv("DIFY_PASSWORD", "")


async def main():
    encoded_pw = base64.b64encode(PASSWORD.encode()).decode()
    payload = {
        "email": EMAIL,
        "password": encoded_pw,
        "language": "zh-Hans",
        "remember_me": True,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{BASE_URL}/console/api/login", json=payload)

    print(f"status: {resp.status_code}")
    print(f"body: {resp.text}")
    print(f"\n--- 所有 Set-Cookie 头 ---")
    # httpx 的 resp.headers 可能合并多个 set-cookie，用 resp.cookies 更可靠
    print(f"resp.cookies 类型: {type(resp.cookies)}")
    for name, value in resp.cookies.items():
        print(f"  {name} = {value[:80]}{'...' if len(value) > 80 else ''}")

    # 也检查 raw headers
    print(f"\n--- raw set-cookie headers ---")
    for k, v in resp.headers.multi_items():
        if k.lower() == "set-cookie":
            print(f"  {v[:120]}")

    # 提取 token
    access_token = resp.cookies.get("access_token")
    csrf_token = resp.cookies.get("csrf_token")
    refresh_token = resp.cookies.get("refresh_token")
    print(f"\n--- 提取的 token ---")
    print(f"access_token: {access_token[:60] if access_token else 'N/A'}...")
    print(f"csrf_token: {csrf_token[:60] if csrf_token else 'N/A'}...")
    print(f"refresh_token: {refresh_token[:60] if refresh_token else 'N/A'}...")

    # 验证新 token 可用
    if access_token:
        print(f"\n--- 用新 token 测试 /apps ---")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token
        cookie_parts = [f"access_token={access_token}"]
        if csrf_token:
            cookie_parts.append(f"csrf_token={csrf_token}")
        if refresh_token:
            cookie_parts.append(f"refresh_token={refresh_token}")
        headers["Cookie"] = "; ".join(cookie_parts)

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/console/api/apps",
                params={"limit": 3},
                headers=headers,
            )
        print(f"status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  total={data.get('total')}, returned={len(data.get('data', []))}")
        else:
            print(f"  body: {r.text[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
