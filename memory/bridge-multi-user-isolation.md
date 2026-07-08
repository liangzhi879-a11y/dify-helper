---
name: bridge-multi-user-isolation
description: Dify Helper Bridge 多用户隔离的核心架构决策（IP+UA fingerprint 而非密码、SQLite 联合主键、per-user worker pool、HMAC-SHA256+uuid5）；为什么这么设计 + 怎么改
metadata:
  type: project
---

Dify Helper Bridge 从单用户假设升级为多用户隔离（2026-07-07）。本文件记录**架构决策根因**，避免下次 session 重新发明。

## 核心架构决策（v0.3.0）

| 决策 | 选什么 | 不选什么 | 为什么 |
|---|---|---|---|
| 身份识别 | IP+UA+Accept-Language → HMAC-SHA256 → uuid5 | Dify cookie / 密码 / OAuth | 内部团队使用，无强威胁模型；fingerprint 足够区分 |
| 二次细分 | `display_name` UI 弹窗选择器 | 强制账号体系 | 同 NAT+同 UA 时手动区分，撞库合并为预期行为 |
| 持久化 | SQLite (WAL + synchronous=NORMAL) | 纯内存 / Postgres | 重启恢复 + 审计 + 零运维；不超 20 user 性能足够 |
| Worker 并发 | per-user `asyncio.Queue` + per-user Task | 全局串行 / 全局并行 | 同 user 内保 Claude session 上下文；不同 user 互不阻塞 |
| 旧端点改造 | `Depends(get_current_user)` 注入 | 中间件全局拦截 | FastAPI 依赖注入更显式；现有端点改动最小（仅加 1 行） |
| 老用户兼容 | `BRIDGE_LEGACY_USER_ID` 兜底 | 强制立即升级 | Phase 1-3 期间老油猴无 fingerprint → 全部归此 user，行为不变 |

## 关键 SQL 决策（schema 不可逆）

**`(user_id, session_id)` 必须联合主键**——session_id 是 uuid4，理论上不撞；但**当 user_id 也变 0.0.0.0 测试时 + display_name 撞库时**，联合主键是唯一隔离屏障。

`events` / `messages` / `tasks` 全部带 `user_id` 维度：
```sql
PRIMARY KEY (user_id, session_id, event_id)  -- events
PRIMARY KEY (user_id, task_id)              -- tasks
PRIMARY KEY (user_id, session_id, seq)      -- messages
```

`display_name_map` 表的 `UNIQUE(display_name)` 是撞库合并的**物理保证**：
- alice 被 raw-A 占用 → raw-B 也叫 alice → UNIQUE 阻止插入新行 → 必须复用 raw-A 的 canonical_user_id
- 这正是"撞库合并到同一 user"的设计意图

## 3 个易踩的坑（已修）

1. **`display_name` 撞库时的 UNIQUE 冲突**：`INSERT` 会失败。**解法**：先 `SELECT existing canonical`，撞库时只 `UPDATE last_used_at`，**不插入新行**。
2. **`resolve_display_name` 顺序：先查 (raw, name) 命中 → 再查 name 撞库 → 最后才 INSERT**。逻辑搞反会触发 UNIQUE。
3. **aiosqlite 的 `executescript` 自动 commit**，但 `execute` 后必须显式 `await db.commit()`（已写成 helper `_conn()` 包装）。

## Fingerprint 算法为什么这样选

```python
digest = hmac.new(SALT.encode(), f"{ip}|{ua[:256]}|{lang[:32]}".encode(), hashlib.sha256).hexdigest()
return uuid.uuid5(uuid.NAMESPACE_DNS, digest)
```

- **HMAC 而非纯 hash**：看不到 salt 外部无法暴力反推 ip/ua（256 bit salt 不可爆破）
- **uuid5 而非 uuid4**：确定性输入 → 确定性输出，重启后同一 user 拿同一 UUID
- **`ua[:256]` / `lang[:32]` 截断**：防恶意 client 传超长 header 拖死 hash
- **三字段组合（不是 IP+UA 两字段）**：Accept-Language 增加维度，碰撞概率 << 单字段

## How to apply（下次同类问题）

**任何**用户态隔离场景（不限于 Dify）按以下顺序决策：

1. **威胁模型**：内部团队（弱）vs 公网（强）。弱 = fingerprint + UUID5；强 = 必须 HTTPS + JWT + refresh token
2. **二次细分**：单一 fingerprint 字段撞库怎么办？display_name / 选择器 UI / 设备 allow-list 至少一个
3. **持久化**：要不要重启恢复？要不要审计？都要 → SQLite 起步；user 数 > 100 → Postgres
4. **并发**：同 user 内串行 / 不同 user 并行 = 黄金分割（除非 user 间共享 state）
5. **向后兼容**：用 `LEGACY_GLOBAL_USER_ID` 兜底，让老用户零感知升级

## 涉及文件（v0.3.0）

- `bridge/bridge/migrations/v1_initial.sql` — 完整 DDL（6 张表 + 7 索引 + 1 schema_migrations）
- `bridge/bridge/sqlite_store.py` — SqliteStore 单例 + 全部 CRUD
- `bridge/bridge/auth.py` — HMAC fingerprint + UserContext + get_current_user dependency
- `bridge/bridge/app.py` — lifespan `init_db()` + 16 个端点 owner check + `/auth/whoami` + bridge/.env 加载
- `bridge/bridge/session_manager.py` — Phase 2 改 dict key `(user_id, session_id)` + 所有 public method 加 user_id 参数
- `bridge/bridge/task_queue.py` — Phase 2 拆为 `(user_id, task_id)` 联合 key + ownership 校验内置
- `bridge/.env` — `BRIDGE_FINGERPRINT_SALT` / `LEGACY_USER_ID` / `MAX_USERS` / `IDLE_EVICT_SEC`
- `bridge/pyproject.toml` — `aiosqlite>=0.19`
- `tampermonkey/dify-claude-floating-window.user.js` — v0.3.0：bootstrap `/auth/whoami` + GM key 命名空间 `dcfw_<fp>_*` + 👤 display_name popover UI
- `tampermonkey/dify-claude-floating-window-remote.user.js` — v0.3.0-remote：与本地版同步所有改动

## 已完成 phase

- ✅ Phase 0：salt 生成 + SQLite schema + sqlite_store + auth + `/auth/whoami`
- ✅ Phase 1：EventStore 双写 + SessionManager 5 个 SQLite 落盘点
- ✅ Phase 2：16 端点 owner check + SessionManager per-user dict + TaskQueue per-user + 跨 user 404 验证
- ✅ Phase 3：油猴 v0.3.0（local + remote）— bootstrap + GM 命名空间 + header 注入 + 👤 UI
- ✅ Phase 3.1：v0.3.1 修复启动 race condition（start() 同步调 bootstrap 时 detectBridge 还在 async loop，bootstrap 读到全 pending 早退，fingerprint 永远 null）
- ✅ Phase 4：`BRIDGE_LEGACY_DISABLED` 开关 + 全员升级后 flip 强制 client 升级
- ⏳ Phase 5：监控（`/admin/stats`）+ 文档（CLAUDE.md「多用户隔离架构」章节）

## v0.3.0 实施时踩的 1 个关键 bug

**`resolve_display_name` step 3 错把 canonical 设成 raw_user_id**：
- 现象：同 IP+UA（Alice 跟 Bob 共享电脑）各自报名字"alice"/"bob"，本应 2 个 user，实际合并成 1 个
- 根因：原始代码 `canonical = raw_user_id`（步骤 3）—— 同 raw 任何 name 都映射回 raw
- 修复：`canonical = uuid5(NAMESPACE_OID, f"{raw_user_id}|{display_name}")`（同 raw + 同 dn 稳定，同 raw + 不同 dn 区分）
- 检测：E2E `[3] fp+alice` vs `[4] fp+bob` 之前给相同 user_id，发现后修复

**Why:** schema 里 `UNIQUE(display_name)` 已防「不同 raw 撞同一个 name」合并，但**没防**「同 raw 多个 name」合并
**How to apply:** 任何 multi-tenant schema 在「主键维度」（raw）+「细分维度」（name）组合时，**细分维度的每个新值必须派生独立 ID**，不能退化到主键

## v0.3.1 修复的关键 race condition

**用户报"前端油猴插件，显示无指纹，设置 display_name 点击闪退"**：
- 现象：badge 永远显示 👤?（"无 fingerprint"），调 /auth/whoami 永远不发生
- 根因：`start()` 在 IIFE 同步路径里调 `bootstrap()`，但 `bootstrap()` 第一行是：
  ```js
  const ok = (state.bridgeProbes || []).find((p) => p.status === "ok");
  if (!ok) { ... return; }  // ← 早退，永远不调 whoami
  ```
  而 `detectBridge()` 是 async（顶层 fire-and-forget 调用），还在 for 循环里 `await Promise.race(...)`，**state.bridgeProbes 全是 "pending"**。bootstrap 立即 early-return，fingerprint 永远 null。
- 旧注释（错的）："bootstrap 在 detectBridge 解析 ok 之后跑，时序安全" —— 实际时序根本不安全
- 修复：
  1. `start()` 改 `async`，内部 `await detectBridge()` → `await bootstrap()` 顺序执行
  2. 顶层 `detectBridge();` fire-and-forget 调用注释掉（避免双重探测）
  3. `setDisplayName` / `clearDisplayName` 用 try/catch 包 `addSystemMessage`（极端场景兜底防闪退）
- 验证：
  - jsdom 测试 `[LOG] [bridge] v0.3.0 bootstrap: user=b4fed778...` 之前从不出现，修复后稳定出现
  - `bridge/tests/test_phase3_oilmonkey_race_fix.py` 8 个静态断言全过（lock 住修复）

**Why:** "在 async setup 后立即读 async 阶段写入的 state" 是经典 race condition。JS 单线程让人误以为时序安全，但 await 让"另一段代码"先跑。
**How to apply:**
- **任何 setup chain 都用 await 串行**，不要 fire-and-forget 后立即读其结果
- 注释里写"时序安全"前，必须真在浏览器跑一遍验证（jsdom 抓 console 是最便宜的早期检测）
- 防"用户报 crash 但 jsdom 复现不出来"的尴尬 → 把高风险函数用 try/catch 包起来，让它"宁可什么都不做也别 throw"

## v0.3.3-remote 修复的 Firefox 闪退真根因

**用户报"Firefox 上点 FAB 直接闪退"**（v0.3.2 修了 race condition 之后，仍闪退）：

- 现象：FAB 一闪而过；不开 F12 看不到 console 报错
- v0.3.2-remote 第一次修复尝试：加 error overlay + togglePanel try/catch，但**没修到真根因**
- 真根因（v0.3.3-remote）：remote variant 的 `togglePanel()` 在 v0.3.2 改动时被错误写成了**两段重复定义**：
  ```js
  function togglePanel() {        // ← 第一段，try { 后只到 if (state.panelOpen) { 就结束
    try { state.panelOpen = !state.panelOpen; const panel = ...;
    if (!panel || !fab) { ... }
    if (state.panelOpen) {        // ← 这里结束
  function togglePanel() {        // ← 第二段，无 try/{}，缺 null-check guard
    state.panelOpen = !state.panelOpen;
    const panel = shadowRoot.getElementById("dcfw-panel");
    ...
  }
  ```
  整个 IIFE eval 抛 **SyntaxError** → 油猴静默吞掉 → 用户看到的就是 FAB "闪退"。
- **为什么 jsdom 第一次没测出来**：测试只 grep "try {" 出现没出现，对**结构性破坏**（重复函数定义）不敏感
- 修复：
  1. 把 remote `togglePanel()` 替换为单一定义（与 local 完全一致）
  2. 测试加 `len(re.findall(r"^  function togglePanel\s*\(", src)) == 1` 防复发
  3. bump 到 0.3.3-remote（**值得 bump 版本号**：这是真正的修复，不是装饰）
- 验证：jsdom eval 远程版 → IIFE 不抛 → FAB 注入 → 点击 → panel.open=true

**Why:** v0.3.2 改动 togglePanel 时，local + remote 分两次编辑，且工具对 IIFE eval 失败不报告（"闪退"被静默吞掉）。**用 grep 数函数定义数量**是检测此类污染的最便宜方法。
**How to apply:**
- 任何对油猴 IIFE 内部的函数体改动，**改完必须立刻 jsdom 跑一遍 eval**，catch 任何 SyntaxError
- 测试加 "该函数名应只出现 1 次" 的结构性断言，比语义断言更早发现问题
- local + remote 双版本同步改动时，**不能假设两边都对**——差异越大越要单独验证

## 相关

- [[tampermonkey-shadow-dom-color-inheritance]] — 油猴改 CSS 的另一类坑
- [[dify-bridge-deployment]] — 本机部署端口/路径/凭据
- `~/.claude/plans/typed-hatching-teacup.md` — 本次升级的完整 plan