"""测试 Dify 邮箱密码登录。

尝试多种方式：
1. 明文密码
2. base64 编码密码
3. 查找 RSA 公钥端点（若需要加密）

打印完整响应（状态码、headers、body）便于分析。
"""
import asyncio
import base64
import json
import httpx
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server", ".env"), override=True)

BASE_URL = os.getenv("DIFY_CONSOLE_BASE_URL", "").rstrip("/")
EMAIL = os.getenv("DIFY_EMAIL", "")
PASSWORD = os.getenv("DIFY_PASSWORD", "")


async def try_login(label: str, payload: dict) -> dict | None:
    """尝试登录并打印完整响应。"""
    url = f"{BASE_URL}/console/api/login"
    print(f"\n--- {label} ---")
    print(f"POST {url}")
    print(f"payload keys: {list(payload.keys())}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
        print(f"status: {resp.status_code}")
        print(f"resp headers (set-cookie 等):")
        for k, v in resp.headers.items():
            if k.lower() in ("set-cookie", "content-type", "x-csrf-token"):
                print(f"  {k}: {v[:120]}")
        body = resp.text[:500]
        print(f"body: {body}")
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                pass
    except Exception as e:
        print(f"ERR: {e}")
    return None


async def check_system_features() -> dict | None:
    """检查 /console/api/system/features 端点是否返回 RSA 公钥或登录配置。"""
    url = f"{BASE_URL}/console/api/system/features"
    print(f"\n--- 检查系统配置 ---")
    print(f"GET {url}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        print(f"status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            # 查找 login / rsa / encrypt 相关配置
            for key in ("login", "rsa", "encrypt", "password", "public_key", "enable_password_login"):
                if key in data:
                    print(f"  {key}: {data[key]}")
                elif isinstance(data, dict):
                    for k, v in data.items():
                        if any(s in k.lower() for s in ("login", "rsa", "encrypt", "password", "public_key")):
                            print(f"  {k}: {v}")
                            break
            return data
        else:
            print(f"body: {resp.text[:200]}")
    except Exception as e:
        print(f"ERR: {e}")
    return None


async def check_bezel_endpoints() -> None:
    """检查其他可能的 RSA 公钥端点。"""
    candidates = [
        "/console/api/login/public-key",
        "/console/api/auth/public-key",
        "/console/api/system/public-key",
        "/console/api/login/rsa",
        "/console/api/bezel-public-key",
    ]
    print(f"\n--- 探查 RSA 公钥端点 ---")
    async with httpx.AsyncClient(timeout=5) as client:
        for path in candidates:
            url = f"{BASE_URL}{path}"
            try:
                r = await client.get(url)
                marker = "✓" if r.status_code == 200 else "·"
                print(f"  {marker} [{r.status_code}] GET {path}")
                if r.status_code == 200:
                    print(f"      body: {r.text[:200]}")
            except Exception:
                print(f"  ✗ ERR GET {path}")


async def main():
    print(f"BASE_URL: {BASE_URL}")
    print(f"EMAIL: {EMAIL}")
    print(f"PASSWORD: {'*' * len(PASSWORD)}")

    # 1. 检查系统配置
    await check_system_features()

    # 2. 探查 RSA 公钥端点
    await check_bezel_endpoints()

    # 3. 尝试明文登录
    result = await try_login("明文密码", {
        "email": EMAIL,
        "password": PASSWORD,
        "language": "zh-Hans",
        "remember_me": True,
    })

    # 4. 尝试 base64 编码
    if not result:
        encoded = base64.b64encode(PASSWORD.encode()).decode()
        result = await try_login("base64 密码", {
            "email": EMAIL,
            "password": encoded,
            "language": "zh-Hans",
            "remember_me": True,
        })

    # 5. 如果登录成功，打印 token
    if result:
        print(f"\n=== 登录成功 ===")
        print(f"keys: {list(result.keys())}")
        for k in ("access_token", "refresh_token", "csrf_token"):
            if k in result:
                v = result[k]
                print(f"{k}: {v[:60]}..." if len(v) > 60 else f"{k}: {v}")
        # 也检查 data 嵌套
        if "data" in result and isinstance(result["data"], dict):
            print(f"data keys: {list(result['data'].keys())}")


if __name__ == "__main__":
    asyncio.run(main())
