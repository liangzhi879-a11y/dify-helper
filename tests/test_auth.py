"""快速验证 DifyClient 能否调通 Dify API。"""
import os
import asyncio
from mcp_server.server import client, DIFY_CONSOLE_TOKEN, DIFY_CSRF_TOKEN

async def main():
    print("DIFY_CONSOLE_TOKEN:", repr(DIFY_CONSOLE_TOKEN[:30]) if DIFY_CONSOLE_TOKEN else "EMPTY")
    print("DIFY_CSRF_TOKEN:", repr(DIFY_CSRF_TOKEN[:30]) if DIFY_CSRF_TOKEN else "EMPTY")
    print("headers:", {k: v[:40] + "..." if len(v) > 40 else v for k, v in client._headers.items()})
    # 测试 apps
    try:
        r = await client.get("/apps", params={"limit": 3})
        print(f"\n[apps] type={type(r).__name__}")
        if isinstance(r, dict) and "data" in r:
            print(f"  total={r.get('total')}, returned={len(r['data'])}")
            for app in r["data"][:3]:
                print(f"  - {app.get('name')} ({app.get('mode')})")
        else:
            print(f"  {str(r)[:200]}")
    except Exception as e:
        print(f"\n[apps] ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
