"""Phase 4 E2E: BRIDGE_LEGACY_DISABLED 行为验证。

默认 (false) 行为：保留 LEGACY 兜底（向后兼容）
开启 (true) 行为：无 X-Bridge-* header → 401
匿名路径（/dify/* 等）仍 200（不受影响）
"""
import asyncio
import os
import sys
import time

import httpx

BASE = "http://127.0.0.1:8002"


def hdr_legacy():
    return {"User-Agent": "CurlTest/1.0"}


def hdr_new(fp="fp_test_user"):
    return {
        "X-Bridge-Fingerprint": fp,
        "User-Agent": "CurlTest/1.0",
    }


async def test_default_mode() -> list[str]:
    """默认 (BRIDGE_LEGACY_DISABLED=false) 行为。"""
    failures = []
    async with httpx.AsyncClient(timeout=5.0) as c:
        # 无 header → LEGACY 200
        r = await c.get(f"{BASE}/auth/whoami", headers=hdr_legacy())
        if r.status_code != 200 or not r.json().get("is_legacy"):
            failures.append(f"[默认] legacy 应 200+is_legacy，实际 {r.status_code} {r.json()}")
        else:
            print(f"[默认] 无 header → 200 (LEGACY 兜底) ✅")

        # 有 header → 200
        r = await c.get(f"{BASE}/auth/whoami", headers=hdr_new())
        if r.status_code != 200 or r.json().get("is_legacy"):
            failures.append(f"[默认] fp 应 200+非 legacy，实际 {r.status_code} {r.json()}")
        else:
            print(f"[默认] 有 fp header → 200 (正常) ✅")

    return failures


async def test_disabled_mode() -> list[str]:
    """开启 (BRIDGE_LEGACY_DISABLED=true) 行为。

    需要重启 bridge 时设置此环境变量；这里通过子进程启停。
    """
    failures = []
    # 停 bridge
    os.system("pkill -f 'python -m bridge.app' 2>/dev/null")
    await asyncio.sleep(2)

    # 用 BRIDGE_LEGACY_DISABLED=true 重启
    env = os.environ.copy()
    env["BRIDGE_LEGACY_DISABLED"] = "true"
    import subprocess
    proc = subprocess.Popen(
        ["/home/sutai/dify-helper/.venv/bin/python", "-m", "bridge.app"],
        cwd="/home/sutai/dify-helper/bridge",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 等启动
    for _ in range(20):
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{BASE}/health")
                if r.status_code == 200:
                    break
        except Exception:
            pass
        await asyncio.sleep(0.5)
    else:
        failures.append("bridge 启动超时")
        return failures

    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            # 无 header → 401
            r = await c.get(f"{BASE}/auth/whoami", headers=hdr_legacy())
            if r.status_code != 401:
                failures.append(f"[开启] 无 header 应 401，实际 {r.status_code} {r.json()}")
            else:
                print(f"[开启] 无 header → 401 ✅ ({r.json().get('detail', '')[:60]})")

            # 有 fp header → 200
            r = await c.get(f"{BASE}/auth/whoami", headers=hdr_new("fp_v030_user"))
            if r.status_code != 200 or r.json().get("is_legacy"):
                failures.append(f"[开启] 有 fp 应 200+非 legacy，实际 {r.status_code}")
            else:
                print(f"[开启] 有 fp header → 200 ✅")

            # 有 dn header → 200
            r = await c.get(f"{BASE}/auth/whoami",
                            headers={"X-Bridge-Display-Name": "alice", "User-Agent": "CurlTest/1.0"})
            if r.status_code != 200 or r.json().get("is_legacy"):
                failures.append(f"[开启] 有 dn 应 200+非 legacy，实际 {r.status_code}")
            else:
                print(f"[开启] 有 dn header → 200 ✅")

            # 16 个 session/task 端点：无 header → 401
            legacy_risky = [
                ("POST", "/sessions", {}),
                ("GET", "/sessions", None),
                ("GET", "/tasks/abc/status", None),
                ("DELETE", "/sessions/abc", None),
                ("POST", "/sessions/abc/messages", {"content": "hi"}),
            ]
            for method, path, body in legacy_risky:
                if method == "GET":
                    r = await c.get(f"{BASE}{path}", headers=hdr_legacy())
                elif method == "POST":
                    r = await c.post(f"{BASE}{path}", json=body, headers=hdr_legacy())
                elif method == "DELETE":
                    r = await c.delete(f"{BASE}{path}", headers=hdr_legacy())
                if r.status_code != 401:
                    failures.append(f"[开启] {method} {path} 无 header 应 401，实际 {r.status_code}")
                else:
                    print(f"[开启] {method} {path} 无 header → 401 ✅")

            # 匿名路径：/dify/* 不受影响（仍 200 或 500 但**不是 401**）
            r = await c.get(f"{BASE}/dify/apps", headers=hdr_legacy())
            if r.status_code == 401:
                failures.append(f"[开启] /dify/apps 不应 401（匿名路径），实际 {r.status_code}")
            else:
                print(f"[开启] /dify/apps 匿名 → {r.status_code} ✅ (无 401)")

            # /validate-dsl 是 POST
            r = await c.post(f"{BASE}/validate-dsl",
                             json={"workflow": {}}, headers=hdr_legacy())
            if r.status_code == 401:
                failures.append(f"[开启] /validate-dsl 不应 401，实际 {r.status_code}")
            else:
                print(f"[开启] /validate-dsl 匿名 → {r.status_code} ✅ (无 401)")

            # /health 永远 200
            r = await c.get(f"{BASE}/health", headers=hdr_legacy())
            if r.status_code != 200:
                failures.append(f"[开启] /health 应 200，实际 {r.status_code}")
            else:
                print(f"[开启] /health → 200 ✅")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        await asyncio.sleep(1)

    return failures


async def main() -> int:
    all_failures = []

    # Part 1: 默认模式（LEGACY_ENABLED）
    print("=" * 60)
    print("Part 1: 默认模式 (BRIDGE_LEGACY_DISABLED=false)")
    print("=" * 60)
    all_failures.extend(await test_default_mode())

    # Part 2: 开启模式
    print()
    print("=" * 60)
    print("Part 2: 开启模式 (BRIDGE_LEGACY_DISABLED=true)")
    print("=" * 60)
    # 重启 bridge 为默认模式供后续用
    import subprocess
    subprocess.Popen(
        ["/home/sutai/dify-helper/.venv/bin/python", "-m", "bridge.app"],
        cwd="/home/sutai/dify-helper/bridge",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(3)
    all_failures.extend(await test_disabled_mode())

    print()
    if all_failures:
        print(f"❌ {len(all_failures)} 个失败：")
        for f in all_failures:
            print(f"  - {f}")
        return 1
    print("✅ Phase 4 双模式行为全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
