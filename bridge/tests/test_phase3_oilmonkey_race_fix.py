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

    # 1) 版本号已 bump 到 0.3.9
    failures += assert_contains("local.version", src, "@version      0.3.9")

    # 2) v0.3.1 race condition 修复说明注释存在
    failures += assert_contains("local.changelog_v031", src, "★ 0.3.1 修复 v0.3.0 启动 race condition")

    # 3) v0.3.2 Firefox error overlay 修复说明
    failures += assert_contains("local.changelog_v032", src, "★ 0.3.2 修复 Firefox 上展开按钮闪退")

    # 4) v0.3.4 auto-update URL 配置
    failures += assert_contains("local.changelog_v034", src, "★ 0.3.4 加 GitHub auto-update URL")
    failures += assert_contains("local.updateURL", src, "@updateURL    https://raw.githubusercontent.com/liangzhi879-a11y/dify-helper/main/tampermonkey/dify-claude-floating-window.user.js")
    failures += assert_contains("local.downloadURL", src, "@downloadURL  https://raw.githubusercontent.com/liangzhi879-a11y/dify-helper/main/tampermonkey/dify-claude-floating-window.user.js")
    failures += assert_contains("local.homepageURL", src, "@homepageURL  https://github.com/liangzhi879-a11y/dify-helper")

    # 5) v0.3.5 UI 优化（titlebar 单行化 + 跳动动画）
    failures += assert_contains("local.changelog_v035", src, "★ 0.3.5 面板 titlebar 单行化 + FAB 机器人居中修复 + 跳动动画")
    failures += assert_regex("local.titlebar_nowrap", src, r"flex-wrap:\s*nowrap;")
    failures += assert_contains("local.robot_jump_keyframes", src, "@keyframes dcfw-robot-jump")
    failures += assert_contains("local.host_panel_open_class", src, 'hostEl.classList.add("dcfw-panel-open")')
    failures += assert_contains("local.host_class_set", src, 'hostEl.className = "dcfw-host"')

    # 6) v0.3.6 像素画重设计（半角 block 元素）+ 去除 "✕" 切换
    failures += assert_contains("local.changelog_v036", src, "★ 0.3.6 FAB 机器人像素画重设计 + 跳动动画修复")
    failures += assert_contains("local.no_close_icon", src, "// ★ 0.3.5: 不再切到 \"✕\" — 机器人保持显示")

    # 7) v0.3.7 标题栏拆两行 + 拟终端 prompt 链 statusbar + FAB 用 Claude Code 官方 banner
    failures += assert_contains("local.changelog_v037", src, "★ 0.3.7 标题栏拆两行 + FAB 用 Claude Code 官方 banner")
    failures += assert_contains("local.robot_official_banner", src, 'btn.innerHTML = \'<pre class="dcfw-fab-robot" aria-hidden="true"> ▐▛███▜▌\\n▝▜█████▛▘\\n  ▘▘ ▝▝</pre>\'')
    failures += assert_contains("local.robot_font_variant_emoji", src, "font-variant-emoji: text")
    # 8) v0.3.7 拟终端 prompt 链：▌ title prefix + ▸ statusbar prompt + │ separator（0.3.8 移除 tab ▎）
    failures += assert_contains("local.title_block_cursor", src, 'content: "▌"')   # ▌
    failures += assert_contains("local.statusbar_prompt_span", src, 'class="dcfw-statusbar-prompt"')
    failures += assert_contains("local.statusbar_prompt_symbol", src, "<span class=\"dcfw-statusbar-prompt\">▸</span>")
    failures += assert_contains("local.statusbar_separator", src, 'content: "│"')
    # 8b) v0.3.8: 移除 .dcfw-tab::before ▎ 前缀 + @match 宽化 + 占位符 bridge host
    failures += assert_regex("local.tab_prefix_removed", src, r"\.dcfw-tab::before", must_match=False)
    failures += assert_contains("local.match_wide_glob", src, "@match        http://*/*")
    failures += assert_contains("local.bridge_host_placeholder", src, "__REMOTE_BRIDGE_HOST__")
    failures += assert_contains("local.bridge_host_gm_key", src, "__bridge_remote_host__")
    # 8c) v0.3.9: gmFetch.onerror 包 Error —— 之前 reject(raw err) → 上游 String(err) === "[object Object]"
    failures += assert_contains("local.gmFetch_onerror_wrap_error", src, 'new Error("GM network error:')
    failures += assert_regex("local.no_e_message_or_e_pattern", src, r"\(e\.message \|\| e\)", must_match=False)
    # 9) statusbar 内部子元素（mode/badge/page）背景/边框/圆角都被覆盖为透明
    failures += assert_contains("local.mode_badge_in_statusbar_transparent", src, ".dcfw-statusbar-cell .dcfw-mode-badge {")
    failures += assert_contains("local.bridge_badge_in_statusbar_transparent", src, ".dcfw-statusbar-cell .dcfw-bridge-badge {")
    failures += assert_contains("local.statusbar_css", src, ".dcfw-statusbar {")
    failures += assert_contains("local.statusbar_html", src, '<div class="dcfw-statusbar">')
    failures += assert_contains("local.mode_cell", src, 'id="dcfw-mode-cell"')
    failures += assert_contains("local.agent_cell", src, 'id="dcfw-agent-cell"')
    failures += assert_contains("local.url_cell", src, 'id="dcfw-url-cell"')
    failures += assert_contains("local.statusbar_cell_grow", src, "dcfw-statusbar-cell-grow")
    failures += assert_contains("local.titlebar_title", src, 'class="dcfw-titlebar-title"')
    failures += assert_contains("local.titlebar_actions", src, 'class="dcfw-titlebar-actions"')
    failures += assert_contains("local.titlebar_right_removed", src, 'class="dcfw-titlebar-right"', must_exist=False)
    failures += assert_contains("local.titlebar_span_first_child_removed", src, ".dcfw-titlebar > span:first-child", must_exist=False)
    failures += assert_contains("local.statusbar_handler", src, "shadowRoot.getElementById(\"dcfw-mode-cell\")")
    failures += assert_contains("local.click_guard_statusbar", src, ".dcfw-statusbar-cell")

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

    failures += assert_contains("remote.version", src, "@version      0.3.9-remote")

    # v0.3.3-remote 修复 changelog
    failures += assert_contains("remote.changelog_v033", src, "★ 0.3.3-remote 修复 Firefox 上点 FAB 直接闪退的真根因")

    # v0.3.4-remote auto-update URL
    failures += assert_contains("remote.changelog_v034", src, "★ 0.3.4-remote 加 GitHub auto-update URL")
    failures += assert_contains("remote.updateURL", src, "@updateURL    https://raw.githubusercontent.com/liangzhi879-a11y/dify-helper/main/tampermonkey/dify-claude-floating-window-remote.user.js")

    # v0.3.5-remote UI 优化
    failures += assert_contains("remote.changelog_v035", src, "★ 0.3.5-remote 面板 titlebar 单行化 + FAB 机器人居中修复 + 跳动动画")
    failures += assert_regex("remote.titlebar_nowrap", src, r"flex-wrap:\s*nowrap;")
    failures += assert_contains("remote.host_panel_open_class", src, 'hostEl.classList.add("dcfw-panel-open")')

    # v0.3.6-remote 像素画重设计
    failures += assert_contains("remote.changelog_v036", src, "★ 0.3.6-remote FAB 像素画重设计 + 跳动动画")

    # v0.3.7-remote 标题栏拆两行 + FAB 用 Claude Code 官方 banner
    failures += assert_contains("remote.changelog_v037", src, "★ 0.3.7-remote 标题栏拆两行 + FAB 用 Claude Code 官方 banner")
    failures += assert_contains("remote.robot_official_banner", src, 'btn.innerHTML = \'<pre class="dcfw-fab-robot" aria-hidden="true"> ▐▛███▜▌\\n▝▜█████▛▘\\n  ▘▘ ▝▝</pre>\'')
    failures += assert_contains("remote.statusbar_html", src, '<div class="dcfw-statusbar">')
    failures += assert_contains("remote.titlebar_right_removed", src, 'class="dcfw-titlebar-right"', must_exist=False)
    # 拟终端 prompt 链（remote 与 local 同步；0.3.8 移除 tab ▎ 前缀）
    failures += assert_contains("remote.title_block_cursor", src, 'content: "▌"')
    failures += assert_contains("remote.statusbar_prompt_symbol", src, "<span class=\"dcfw-statusbar-prompt\">▸</span>")
    failures += assert_contains("remote.statusbar_separator", src, 'content: "│"')
    failures += assert_regex("remote.tab_prefix_removed", src, r"\.dcfw-tab::before", must_match=False)
    # v0.3.8: @match 宽化 + 占位符 bridge host
    failures += assert_contains("remote.match_wide_glob", src, "@match        http://*/*")
    failures += assert_contains("remote.bridge_host_placeholder", src, "__REMOTE_BRIDGE_HOST__")
    failures += assert_contains("remote.bridge_host_gm_key", src, "__bridge_remote_host__")
    failures += assert_contains("remote.gmFetch_onerror_wrap_error", src, 'new Error("GM network error:')
    failures += assert_regex("remote.no_e_message_or_e_pattern", src, r"\(e\.message \|\| e\)", must_match=False)

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