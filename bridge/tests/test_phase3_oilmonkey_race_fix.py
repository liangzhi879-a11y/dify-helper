"""v0.3.1 oil monkey 启动 race condition 修复回归测试。

核心断言：
- v0.3.0: bootstrap() 同步读 state.bridgeProbes → find(ok) → undefined → early-return
  → /auth/whoami 永远不调 → fingerprint 永远 null（BUG）
- v0.3.1: start() 改 async，await detectBridge() 后再 await bootstrap() →
  /auth/whoami 正常调 → fingerprint 正确写入 state

测试方法：用静态分析 + 字符串匹配验证 user.js 关键改动。
不能跑真实油猴（需要 Tampermonkey + 浏览器），但能锁住代码层面的修复。
"""

import os
import re
import sys

LOCAL_JS = "/home/sutai/dify-helper/tampermonkey/dify-claude-floating-window.user.js"
REMOTE_JS = "/home/sutai/dify-helper/tampermonkey/dify-claude-floating-window-remote.user.js"


def read_js(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def assert_contains(label: str, src: str, needle: str, must_exist: bool = True) -> list[str]:
    """断言 src 含/不含 needle。"""
    exists = needle in src
    if must_exist and not exists:
        return [f"[{label}] 应含: {needle[:120]}"]
    if not must_exist and exists:
        return [f"[{label}] 不应含: {needle[:120]}"]
    return []


def assert_regex(label: str, src: str, pattern: str, must_match: bool = True) -> list[str]:
    """断言 src 是否匹配 pattern。"""
    matched = re.search(pattern, src, re.MULTILINE) is not None
    if must_match and not matched:
        return [f"[{label}] 应匹配: {pattern[:120]}"]
    if not must_match and matched:
        return [f"[{label}] 不应匹配: {pattern[:120]}"]
    return []


def test_local_fix() -> list[str]:
    """验证本地版 user.js 修复。"""
    failures = []
    src = read_js(LOCAL_JS)

    # 1) 版本号已 bump 到 0.3.2（含 v0.3.1 race condition fix + v0.3.2 Firefox error overlay）
    failures += assert_contains("local.version", src, "@version      0.3.2")

    # 2) v0.3.1 race condition 修复说明注释存在
    failures += assert_contains("local.changelog_v031", src, "★ 0.3.1 修复 v0.3.0 启动 race condition")

    # 3) v0.3.2 Firefox error overlay 修复说明
    failures += assert_contains("local.changelog_v032", src, "★ 0.3.2 修复 Firefox 上展开按钮闪退")

    # 3.5) togglePanel 必须只有 1 个定义（防 0.3.2 remote 翻车的"重复定义 + 缩进错乱"复发）
    #    只数代码中的定义，不数 changelog 注释里提到的字符串
    tp_count = len(re.findall(r"^  function togglePanel\s*\(", src, re.MULTILINE))
    if tp_count != 1:
        failures.append(f"[local.togglePanel_unique] 应只 1 个 togglePanel 定义，实际 {tp_count} 个")

    # 4) start() 必须是 async
    failures += assert_regex("local.start_async", src, r"async function start\(\)")

    # 5) start() 必须 await detectBridge 后再 await bootstrap
    #    注意顺序：detectBridge 在前，bootstrap 在后
    m = re.search(
        r"await detectBridge\(\);\s*\n\s*await bootstrap\(\);",
        src,
    )
    if not m:
        failures.append("[local.start_chain] 应包含顺序: await detectBridge() → await bootstrap()")

    # 5) 顶层 fire-and-forget detectBridge() 必须被注释掉（// detectBridge();）
    failures += assert_regex(
        "local.detectBridge_f2f_commented",
        src,
        r"//\s+detectBridge\(\);",
    )

    # 6) setDisplayName 用 try/catch 包 addSystemMessage
    failures += assert_regex(
        "local.setDisplayName_trycatch",
        src,
        r"async function setDisplayName\(name\)\s*\{\s*\n\s*try \{",
    )

    # 7) clearDisplayName 用 try/catch 包 addSystemMessage
    failures += assert_regex(
        "local.clearDisplayName_trycatch",
        src,
        r"async function clearDisplayName\(\)\s*\{\s*\n\s*try \{",
    )

    # 8) 旧 bootstrap.then() 写法已被替换
    failures += assert_regex(
        "local.no_legacy_bootstrap_then",
        src,
        r"bootstrap\(\)\.then\(",  # 这个模式不应再出现
        must_match=False,
    )

    # ★ v0.3.2 新增：Firefox error overlay 机制
    # 9) _recordFatal 函数存在
    failures += assert_contains("local.recordFatal", src, "function _recordFatal(")
    # 10) _showFatalOverlay 函数存在
    failures += assert_contains("local.showFatalOverlay", src, "function _showFatalOverlay(")
    # 11) window error listener 注册
    failures += assert_contains("local.error_listener", src, 'window.addEventListener("error"')
    # 12) unhandledrejection listener 注册
    failures += assert_contains("local.unhandledrejection_listener", src, 'window.addEventListener("unhandledrejection"')
    # 13) togglePanel 用 try/catch 防御（注释允许插在 { 后与 try 前）
    failures += assert_regex(
        "local.togglePanel_trycatch",
        src,
        r"function togglePanel\(\)\s*\{[\s\S]{0,200}?try \{",
    )

    return failures


def test_remote_fix() -> list[str]:
    """验证远程版 user.js 修复（与本地逻辑同步，仅 metadata 差）。"""
    failures = []
    src = read_js(REMOTE_JS)

    failures += assert_contains("remote.version", src, "@version      0.3.3-remote")

    # v0.3.3-remote 修复 changelog
    failures += assert_contains("remote.changelog_v033", src, "★ 0.3.3-remote 修复 Firefox 上点 FAB 直接闪退的真根因")
    failures += assert_regex("remote.start_async", src, r"async function start\(\)")
    m = re.search(r"await detectBridge\(\);\s*\n\s*await bootstrap\(\);", src)
    if not m:
        failures.append("[remote.start_chain] 应包含顺序: await detectBridge() → await bootstrap()")
    failures += assert_regex("remote.detectBridge_f2f_commented", src, r"//\s+detectBridge\(\);")
    failures += assert_regex("remote.setDisplayName_trycatch", src, r"async function setDisplayName\(name\)\s*\{\s*\n\s*try \{")
    failures += assert_regex("remote.clearDisplayName_trycatch", src, r"async function clearDisplayName\(\)\s*\{\s*\n\s*try \{")
    # v0.3.2 sync
    failures += assert_contains("remote.recordFatal", src, "function _recordFatal(")
    failures += assert_contains("remote.error_listener", src, 'window.addEventListener("error"')
    failures += assert_regex("remote.togglePanel_trycatch", src, r"function togglePanel\(\)\s*\{[\s\S]{0,200}?try \{")
    # v0.3.3: 远程版 togglePanel 必须只有 1 个（修复"重复定义"导致 SyntaxError）
    tp_count = len(re.findall(r"^  function togglePanel\s*\(", src, re.MULTILINE))
    if tp_count != 1:
        failures.append(f"[remote.togglePanel_unique] 应只 1 个 togglePanel 定义，实际 {tp_count} 个")

    return failures


def test_local_remote_logic_aligned() -> list[str]:
    """验证本地版和远程版逻辑一致（仅 metadata 差）。"""
    failures = []
    local = read_js(LOCAL_JS)
    remote = read_js(REMOTE_JS)

    # 抽掉 metadata 头（前 30 行）+ 远程特有 @match/@connect 后，对比
    # 简化：只比对关键代码段
    local_keys = re.findall(r"await (?:detectBridge|bootstrap|refreshUserBadge)\(\);", local)
    remote_keys = re.findall(r"await (?:detectBridge|bootstrap|refreshUserBadge)\(\);", remote)
    if local_keys != remote_keys:
        failures.append(f"[sync] await 调用序列不一致:\n  local:  {local_keys}\n  remote: {remote_keys}")

    # try/catch 块数量应一致
    local_try = len(re.findall(r"async function (set|clear)DisplayName", local))
    remote_try = len(re.findall(r"async function (set|clear)DisplayName", remote))
    if local_try != remote_try:
        failures.append(f"[sync] setDisplayName/clearDisplayName 数量不一致: local={local_try} remote={remote_try}")

    return failures


def main() -> int:
    all_failures = []
    print("=" * 60)
    print("Phase 3 oil monkey v0.3.1 + v0.3.2 修复回归")
    print("=" * 60)

    print("\n[Test 1] 本地版 user.js 修复")
    print("-" * 40)
    failures = test_local_fix()
    all_failures.extend(failures)
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
    else:
        print("  ✅ 所有断言通过")

    print("\n[Test 2] 远程版 user.js 修复")
    print("-" * 40)
    failures = test_remote_fix()
    all_failures.extend(failures)
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
    else:
        print("  ✅ 所有断言通过")

    print("\n[Test 3] 本地/远程逻辑一致性")
    print("-" * 40)
    failures = test_local_remote_logic_aligned()
    all_failures.extend(failures)
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
    else:
        print("  ✅ 逻辑同步")

    print("\n" + "=" * 60)
    if all_failures:
        print(f"❌ {len(all_failures)} 个失败")
        return 1
    print("✅ v0.3.1 race condition + v0.3.2 Firefox error overlay 修复回归全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())