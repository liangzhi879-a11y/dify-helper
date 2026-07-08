---
name: tampermonkey-iife-let-tdz-floating-window
description: Tampermonkey IIFE 内 let/const 必须在所有同步调用前声明（detectBridge/start），否则在 TDZ 抛 ReferenceError "Cannot access 'X' before initialization"；state/shadowRoot/hostEl/_DIFY_PATH_PREFIXES 都要集中在 IIFE 顶部
metadata:
  type: feedback
---

Tampermonkey userscript 写在 IIFE `(function () { ... })()` 里时，所有 `let`/`const` 声明必须在 IIFE 内任何**同步调用**（如 `detectBridge();` `start();`）之前完成。

**Why**: 2026-07-04 修复 dify-claude-floating-window-remote.user.js TDZ bug。原脚本作者 v0.2.15 已经发现 `state` 必须在 `detectBridge()` 前声明（顶部有注释 `[重要] state 必须在 detectBridge() 调用之前声明，否则 detectBridge 内部访问 state.bridgeProbes 会抛 ReferenceError（const 不 hoist，TDZ）`），但漏掉了 3 个同样的 TDZ 问题：
- `let shadowRoot = null; let hostEl = null;` 原 line 600 — 但 `detectBridge()` 在 line 297 同步调用 `updateBridgeBadge()` / `renderProbeResults()`，访问 `shadowRoot` 还在 TDZ → ReferenceError
- `const _DIFY_PATH_PREFIXES = [...]` 原 line 3364 — 但 `start()` 在 line 3351 调用 `_isDifyPage()` 访问它 → ReferenceError

**症状**：油猴控制台报 3 个红字：
```
[bridge] updateBridgeBadge 失败 ReferenceError: Cannot access 'shadowRoot' before initialization
[bridge] renderProbeResults 失败 ReferenceError: Cannot access 'shadowRoot' before initialization
Cannot access '_DIFY_PATH_PREFIXES' before initialization
```
另外会附带 Dify 401 cascade（fetch 失败 → SPA 渲染崩溃 → `Cannot read 'enabled' of undefined`），看起来像整个 Dify 坏了，但其实只是油猴脚本崩了导致 fetch 失败被记到 console。

**How to apply**：
1. 油猴脚本里看到 "Cannot access 'X' before initialization" + 行号 + 同步函数名 → 99% 是 TDZ
2. 用 `grep -n "let X = \|const X = \|detectBridge();\|start();"` 排顺序：X 必须在 detectBridge/start 之前
3. 修复 = 把声明上移到 IIFE 顶部 `state` 之后集中区，加注释说明
4. 改完跑 `node --check userscript` 验语法
5. 关联 [[dify-render-error-debugger]] — TDZ 报的堆栈像是渲染错误，但根因不在 Dify 而在油猴脚本

**PATCH 18（油猴版）落地**：
- `tampermonkey/dify-claude-floating-window-remote.user.js` v0.2.18
- 移 2 个声明到 line 209/214（state 之后，detectBridge 之前）
- 原位置留注释指向上移
- `node --check` 通过；顺序验证：shadowRoot@209 < detectBridge@314 < start@3369

**PATCH 23（油猴版）二次防御 — 用户已装 0.2.22-remote 仍报 TDZ**：
2026-07-05 用户反馈：装的就是仓库 HEAD（v0.2.22-remote，TDZ 修复已在 209/214 行），但浏览器里 `[bridge] updateBridgeBadge 失败 ReferenceError: Cannot access 'shadowRoot' before initialization` 仍然出现。报错行号 `:2753:5 / :2796:5 / :3373:21` 与本地 HEAD 的 `:2775:5 / :2820:5 / :3398:21` 偏移约 16 行。

**根因（额外一层）**：用户 Tampermonkey 缓存命中了**旧的 pre-0.2.18 副本**，没有因为 @version 自增而真正刷新（Tampermonkey 自动更新依赖 metadata 严格递增 + 浏览器缓存同时失效，但用户场景下两者之一失效即跳过）。所以你"修了" ≠ "他拿到了"。

**判断方法**：取两条栈行 line offset，对比仓库 HEAD line number，相差等于 0.2.18 fix block 行数（~14-17 行）就是缓存了旧版。

**补救 = 双管齐下**：
1. `@version` bump（0.2.22 → 0.2.23-remote，强制缓存 miss）
2. **加防御性 `typeof X !== "undefined"` 守卫**，即便缓存还是旧版、声明未上移，照样不会抛错。具体补丁：
   ```js
   function updateBridgeBadge() {
     if (typeof shadowRoot === "undefined" || !shadowRoot) return;  // ★ 0.2.23-remote
     // ...
   }
   function _isDifyPage() {
     const prefixes = (typeof _DIFY_PATH_PREFIXES !== "undefined" && _DIFY_PATH_PREFIXES) || [
       "/apps", "/datasets", "/chat", "/tools", "/workflow",
       "/explore", "/install", "/signin", "/signup", "/forgot-password",
       "/finish", "/education",
     ];
     // ...用 prefixes 替代原 _DIFY_PATH_PREFIXES 引用
   }
   ```

**How to apply next time**：
1. 修 TDZ 时先 bump @version（强制 cache miss）
2. **永远加 typeof guard** ——成本 ~20 字符，换任何缓存策略下零报错
3. 守卫只是"兜底"，主体修复仍是上移声明（守卫无法替代 hoist 性的根本修正）

关联 [[dify-render-error-debugger]]（TDZ 错误常被误判为 Dify 渲染错）。