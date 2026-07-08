"""Phase 3 E2E: 油猴 v0.3.0 行为模拟。

模拟油猴发出的请求（带 X-Bridge-* headers），验证：
1. 无 header → LEGACY
2. 有 fp 无 dn → fingerprint 决定 user_id
3. 同 fp + 不同 dn → 不同 user_id（撞库细分）
4. 同 fp + 同 dn → 合并为同一 user（HMAC 稳定）
5. 不同 user 的 session 物理隔离
6. /auth/whoami 返回 collisions 字段
"""
import asyncio
import sys
import httpx

BASE = "http://127.0.0.1:8002"


async def whoami_with_headers(fp, dn):
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(
            f"{BASE}/auth/whoami",
            headers={
                "X-Bridge-Fingerprint": fp or "",
                "X-Bridge-Display-Name": dn or "",
                "User-Agent": "TampermonkeyTest/1.0",
            },
        )
        return r.json()


async def main() -> int:
    failures = []

    # 场景 1: 无 header → legacy
    r = await whoami_with_headers("", "")
    if not r["is_legacy"]:
        failures.append(f"[1] 期望 legacy 实际 {r}")
    print(f"[1] 无 header → {r['user_id'][:12]}... is_legacy={r['is_legacy']} ✅")

    # 场景 2: 有 fp 无 dn → fingerprint 决定 user_id
    r = await whoami_with_headers("fp_alice_laptop", "")
    if r["is_legacy"]:
        failures.append(f"[2] 不应 legacy: {r}")
    if r["display_name"] is not None:
        failures.append(f"[2] display_name 应 None: {r}")
    alice_user_id = r["user_id"]
    print(f"[2] fp_alice_laptop → {alice_user_id[:12]}... ✅")

    # 场景 3: 同 fp + display_name 'alice' → 撞库细分
    r = await whoami_with_headers("fp_alice_laptop", "alice")
    if r["display_name"] != "alice":
        failures.append(f"[3] display_name 应 alice: {r}")
    alice_dn_user_id = r["user_id"]
    if alice_dn_user_id == alice_user_id:
        failures.append("[3] display_name 撞库细分应产生不同 user_id")
    print(f"[3] fp+alice → {alice_dn_user_id[:12]}... (≠ fp-only {alice_user_id[:12]}...) ✅")

    # 场景 4: 同 fp + display_name 'bob' → 又一个不同 user
    r = await whoami_with_headers("fp_alice_laptop", "bob")
    if r["display_name"] != "bob":
        failures.append(f"[4] display_name 应 bob: {r}")
    bob_user_id = r["user_id"]
    if bob_user_id == alice_dn_user_id:
        failures.append("[4] bob 应与 alice 不同 user_id")
    print(f"[4] fp+bob → {bob_user_id[:12]}... (≠ alice {alice_dn_user_id[:12]}...) ✅")

    # 场景 5: HMAC 稳定
    r = await whoami_with_headers("fp_alice_laptop", "alice")
    if r["user_id"] != alice_dn_user_id:
        failures.append(f"[5] HMAC 不稳定: {r['user_id']} vs {alice_dn_user_id}")
    print(f"[5] alice 二次稳定: {r['user_id'][:12]}... ✅")

    # 场景 6: alice 创建 session → bob 看不到
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.post(
            f"{BASE}/sessions",
            json={"initial_prompt": None, "mode": "bypass"},
            headers={
                "X-Bridge-Fingerprint": "fp_alice_laptop",
                "X-Bridge-Display-Name": "alice",
            },
        )
        alice_sid = r.json()["session_id"]

        r = await c.get(
            f"{BASE}/sessions",
            headers={
                "X-Bridge-Fingerprint": "fp_alice_laptop",
                "X-Bridge-Display-Name": "bob",
            },
        )
        bob_sids = [s["id"] for s in r.json()["sessions"]]
        if alice_sid in bob_sids:
            failures.append("[6] bob 看到了 alice 的 session")
        else:
            print(f"[6] alice sid={alice_sid[:8]}... bob list 看不到 ✅")

    # 场景 7: 撞库合并 — 同 (fp, dn) 两次 → 同一 user
    r1 = await whoami_with_headers("fp_collide_test", "shared_name")
    r2 = await whoami_with_headers("fp_collide_test", "shared_name")
    if r1["user_id"] != r2["user_id"]:
        failures.append(f"[7] 同 (fp,dn) 两次应合并: {r1['user_id']} vs {r2['user_id']}")
    else:
        print(f"[7] 同 (fp,dn) 两次合并: {r1['user_id'][:12]}... ✅")

    # 场景 8: /auth/whoami 响应字段完整
    r = await whoami_with_headers("fp_test_fields", "")
    required = ["user_id", "fingerprint", "display_name", "is_legacy", "ip", "user_agent_preview", "accept_language", "collisions", "candidates"]
    missing = [f for f in required if f not in r]
    if missing:
        failures.append(f"[8] whoami 缺字段: {missing}")
    else:
        print(f"[8] whoami 字段完整: {len(required)} 个 ✅")

    # 场景 9: 旧 user 用 X-Bridge-Fingerprint 但无 display_name → 不算 legacy
    r = await whoami_with_headers("fp_some_user", "")
    if r["is_legacy"]:
        failures.append("[9] 有 fp 不应 legacy")
    else:
        print(f"[9] 有 fp 无 dn → fingerprint user ({r['user_id'][:12]}...) ✅")

    print()
    if failures:
        print(f"❌ {len(failures)} 个失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("✅ 所有油猴 v0.3.0 行为场景通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
