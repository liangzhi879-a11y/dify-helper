"""测试用 refresh_token 刷新 access_token（Dify 1.14+）。

Dify 1.14+ 实际端点：POST {BASE_URL}/console/api/refresh-token
- 需带 X-CSRF-Token 头（双提交 cookie 模式）
- Cookie 同时带 access_token / csrf_token / refresh_token
- Body: {"refresh_token": "..."}

为了让测试自包含（不依赖外部注入 token），脚本会先做一次邮箱密码登录
拿到最新 token，再用其测试 refresh 流程。
"""
from __future__ import annotations

import asyncio
import base64
import os

import httpx
from dotenv import load_dotenv

load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"),
    override=True,
)

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "").rstrip("/")
EMAIL = os.getenv("DIFY_EMAIL", "")
PASSWORD = os.getenv("DIFY_PASSWORD", "")

# Dify 1.14+ 实际可用的刷新端点
REFRESH_ENDPOINT = "/console/api/refresh-token"


async def login_and_get_tokens(client: httpx.AsyncClient) -> tuple[str, str, str]:
    """登录拿 access_token / csrf_token / refresh_token。"""
    r = await client.post(
        f"{BASE_URL}/console/api/login",
        json={
            "email": EMAIL,
            "password": base64.b64encode(PASSWORD.encode()).decode(),
        },
    )
    r.raise_for_status()
    body = r.json()
    data = body.get("data", {}) or {}

    # 优先从 Set-Cookie 取，其次从 body.data 取
    access = client.cookies.get("access_token") or data.get("access_token", "")
    refresh = client.cookies.get("refresh_token") or data.get("refresh_token", "")
    csrf = client.cookies.get("csrf_token") or data.get("csrf_token", "")
    return access, refresh, csrf


async def try_refresh_endpoint(
    client: httpx.AsyncClient,
    suffix: str,
    payload: dict,
    csrf_token: str,
    use_cookie: bool = True,
) -> tuple[int, str, dict | None]:
    url = f"{BASE_URL}{suffix}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token

    # httpx 的 cookie jar 已经在 client.cookies 里；如果用单独的 cookie 参数会覆盖
    if not use_cookie:
        # 临时清空 cookie（用一个新 client）
        tmp = httpx.AsyncClient(timeout=15, headers=headers)
        r = await tmp.post(url, json=payload)
        body = r.text[:200].replace("\n", " ")
        await tmp.aclose()
        return r.status_code, body, None

    r = await client.post(url, json=payload, headers=headers)
    body = r.text[:200].replace("\n", " ")
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    return r.status_code, body, data


async def main():
    print(f"BASE_URL: {BASE_URL}")
    print(f"EMAIL: {EMAIL}")
    print(f"REFRESH_ENDPOINT: {REFRESH_ENDPOINT}")
    print()

    if not BASE_URL or not EMAIL or not PASSWORD:
        print("ERROR: DIFY_CONSOLE_BASE_URL / DIFY_EMAIL / DIFY_PASSWORD 未设置")
        return

    async with httpx.AsyncClient(timeout=15) as client:
        # 1. 登录拿 token
        try:
            access, refresh, csrf = await login_and_get_tokens(client)
        except Exception as e:
            print(f"❌ 登录失败: {e}")
            return
        print(f"✓ 登录成功")
        print(f"  access_token:  {access[:40]}...")
        print(f"  refresh_token: {refresh[:40]}...")
        print(f"  csrf_token:    {csrf[:40]}...")
        print()

        # 2. 试刷新（先 Dify 1.14+ 的标准端点）
        status, body, data = await try_refresh_endpoint(
            client, REFRESH_ENDPOINT, {"refresh_token": refresh}, csrf, use_cookie=True
        )
        marker = "✓" if status == 200 else "✗"
        print(f"  {marker} [{status}] POST {REFRESH_ENDPOINT}  csrf=True  cookie=True")
        print(f"      body: {body}")
        if status == 200 and isinstance(data, dict) and data.get("result") == "success":
            # Dify 把新 token 写进了 Set-Cookie，看一下
            new_access = client.cookies.get("access_token", "")
            new_refresh = client.cookies.get("refresh_token", "")
            print(f"      NEW access_token:  {new_access[:50]}...")
            print(f"      NEW refresh_token: {new_refresh[:50]}...")

            # 3. 用新 token 调一个真实接口验证有效（用新的 httpx client 避免 cookie 缓存干扰）
            verify_client = httpx.AsyncClient(
                timeout=15,
                cookies={
                    "access_token": new_access,
                    "csrf_token": csrf,
                    "refresh_token": new_refresh,
                },
                headers={"X-CSRF-Token": csrf, "Accept": "application/json"},
            )
            r2 = await verify_client.get(f"{BASE_URL}/console/api/apps?limit=1")
            print(f"      用新 token 调 /apps: HTTP {r2.status_code}")
            if r2.status_code == 200:
                print(f"      ✓ refresh 流程完整可用（HTTP 200）")
            else:
                print(f"      ✗ 新 token 调接口失败: {r2.text[:100]}")
            await verify_client.aclose()
            return

        # 4. 标准端点失败，回退到老端点猜测
        print()
        print("--- 回退候选端点 ---")
        for suf in ["/refresh-token", "/auth/refresh-token", "/auth/refresh", "/api/refresh-token"]:
            status, body, _ = await try_refresh_endpoint(
                client, suf, {"refresh_token": refresh}, csrf, use_cookie=True
            )
            m = "✓" if status == 200 else "✗"
            print(f"  {m} [{status}] POST {suf}")

        print()
        print("=== 刷新失败：Dify 1.14+ 实际端点可能需要更新本测试 ===")


if __name__ == "__main__":
    asyncio.run(main())
