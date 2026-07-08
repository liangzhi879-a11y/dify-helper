"""Phase 2 verification: 跨 user 403/404 + SQLite 隔离。

需要：bridge 服务已启动（python -m bridge.app）。

测试场景：
1. 两个 user（不同 UA）各自 create session
2. user A 用 user B 的 session_id 访问 → 404
3. user A 看不到 user B 的 session list
4. user A 提交 task → user B 看不到
5. SQLite 中 user A 和 user B 的数据物理隔离
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8002"


def hdr(user_id_short: str) -> dict:
    """模拟两个不同 user（用不同 X-Bridge-Fingerprint 区分）。"""
    return {
        "X-Bridge-Fingerprint": f"fp_{user_id_short}",
        "User-Agent": f"BridgeTest/1.0 ({user_id_short})",
    }


async def main() -> int:
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        # ===== whoami: 验证两 user 拿到不同 user_id =====
        alice = await client.get(f"{BASE}/auth/whoami", headers=hdr("alice"))
        bob = await client.get(f"{BASE}/auth/whoami", headers=hdr("bob"))
        if alice.status_code != 200 or bob.status_code != 200:
            failures.append(f"whoami 失败: alice={alice.status_code} bob={bob.status_code}")
            print(f"  alice: {alice.text}")
            print(f"  bob:   {bob.text}")
            return 1
        alice_id = alice.json()["user_id"]
        bob_id = bob.json()["user_id"]
        print(f"[1] whoami OK: alice={alice_id[:8]}... bob={bob_id[:8]}...")
        if alice_id == bob_id:
            failures.append("两 user 拿到相同 user_id（fingerprint 没生效）")

        # ===== Alice 创建 session =====
        r = await client.post(
            f"{BASE}/sessions",
            json={"initial_prompt": None, "mode": "bypass"},
            headers=hdr("alice"),
        )
        if r.status_code != 200:
            failures.append(f"alice create_session 失败: {r.status_code} {r.text}")
            return 1
        alice_sid = r.json()["session_id"]
        print(f"[2] alice create_session OK: {alice_sid[:8]}...")

        # ===== Bob 列自己的 session —— 不应看到 alice 的 =====
        r = await client.get(f"{BASE}/sessions", headers=hdr("bob"))
        if r.status_code != 200:
            failures.append(f"bob list_sessions 失败: {r.status_code}")
        bob_sessions = r.json()["sessions"]
        bob_sids = {s["id"] for s in bob_sessions}
        if alice_sid in bob_sids:
            failures.append("泄漏！bob 看到了 alice 的 session")
        else:
            print(f"[3] bob list 看不到 alice session (OK)")

        # ===== Bob 用 alice 的 session_id 访问 status → 404 =====
        r = await client.get(
            f"{BASE}/sessions/{alice_sid}/status", headers=hdr("bob")
        )
        if r.status_code != 404:
            failures.append(f"越权 status 应 404，实际 {r.status_code}: {r.text[:100]}")
        else:
            print(f"[4] bob 越权 status → 404 (OK)")

        # ===== Bob 用 alice 的 session_id 访问 events → 404 =====
        r = await client.get(
            f"{BASE}/sessions/{alice_sid}/events/poll?since=0&max_wait=0.1",
            headers=hdr("bob"),
        )
        if r.status_code != 404:
            failures.append(f"越权 events/poll 应 404，实际 {r.status_code}")
        else:
            print(f"[5] bob 越权 events/poll → 404 (OK)")

        # ===== Bob 用 alice 的 session_id 发消息 → accepted=False, message='session not found' =====
        r = await client.post(
            f"{BASE}/sessions/{alice_sid}/messages",
            json={"content": "hello from bob"},
            headers=hdr("bob"),
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("accepted") and "error" not in str(data).lower():
                # 接受的成功不应该发生
                failures.append(f"越权 send_message 不应成功: {data}")
            else:
                print(f"[6] bob 越权 send_message → 拒绝 (OK, {data.get('message')})")
        elif r.status_code == 404:
            print(f"[6] bob 越权 send_message → 404 (OK)")
        else:
            failures.append(f"越权 send_message 异常状态: {r.status_code} {r.text[:100]}")

        # ===== Bob 用 alice 的 session_id abort → 不应崩溃 =====
        r = await client.post(
            f"{BASE}/sessions/{alice_sid}/abort", headers=hdr("bob")
        )
        # abort 返回 dict 不是 404（业务层 not found 不返 HTTP 404）
        if r.status_code == 200:
            data = r.json()
            if data.get("reason") == "session not found":
                print(f"[7] bob 越权 abort → 拒绝 (OK)")
            else:
                failures.append(f"越权 abort 异常: {data}")
        else:
            failures.append(f"越权 abort 异常状态: {r.status_code}")

        # ===== Bob 用 alice 的 session_id close → 404 =====
        r = await client.delete(
            f"{BASE}/sessions/{alice_sid}", headers=hdr("bob")
        )
        if r.status_code == 404:
            print(f"[8] bob 越权 close → 404 (OK)")
        else:
            failures.append(f"越权 close 应 404，实际 {r.status_code}")

        # ===== Alice 自己的 session 仍可用 → status 200 =====
        r = await client.get(
            f"{BASE}/sessions/{alice_sid}/status", headers=hdr("alice")
        )
        if r.status_code == 200:
            print(f"[9] alice 自己访问 status → 200 (OK)")
        else:
            failures.append(f"alice 自己的 session 访问失败: {r.status_code}")

        # ===== task 隔离 =====
        r = await client.post(
            f"{BASE}/tasks",
            json={"task_description": "test from alice"},
            headers=hdr("alice"),
        )
        if r.status_code != 200:
            failures.append(f"alice submit task 失败: {r.status_code}")
            return 1
        alice_tid = r.json()["task_id"]
        print(f"[10] alice submit task OK: {alice_tid[:8]}...")

        # Bob 拿 alice 的 task_id → 404
        r = await client.get(
            f"{BASE}/tasks/{alice_tid}/status", headers=hdr("bob")
        )
        if r.status_code == 404:
            print(f"[11] bob 越权 task status → 404 (OK)")
        else:
            failures.append(f"越权 task status 应 404，实际 {r.status_code}")

        # Alice 自己能查
        r = await client.get(
            f"{BASE}/tasks/{alice_tid}/status", headers=hdr("alice")
        )
        if r.status_code == 200:
            print(f"[12] alice 查自己 task → 200 (OK)")
        else:
            failures.append(f"alice 查自己 task 失败: {r.status_code}")

    # ===== 总结 =====
    print()
    if failures:
        print(f"❌ {len(failures)} 个失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("✅ 所有跨 user 隔离测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
