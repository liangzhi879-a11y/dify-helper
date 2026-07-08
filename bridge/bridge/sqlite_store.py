"""SQLite 持久化层（Dify Helper Bridge v0.3.0 多用户隔离）。

设计要点：
- 使用 aiosqlite（同步 sqlite3 的 async 包装）+ WAL 模式
- 单一数据库文件：`<bridge_dir>/data/bridge.db`
- 所有用户、session、event、message、task、display_name 映射全在此处
- 启动时自动应用 v*.sql 迁移（通过 schema_migrations 表追踪）
- 不引入 ORM；手写 SQL 更可控、性能更好

API 分类：
- init_db(): 应用所有 pending migration
- Users: upsert_user / get_user / list_recent_users
- display_name: resolve_display_name / count_collisions / list_candidates
- Sessions: create / get / list / update / delete
- Messages: append / list（支持重连回放）
- Events: append / list_since（双写 + 重启恢复）
- Tasks: create / get / update / list

Phase 0 仅实现 CRUD 骨架；Phase 1+ 接入 SessionManager / EventStore。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from .migrations import list_migration_files


# DB 文件路径（与 .env / config 同级部署）
_DEFAULT_DB_PATH = str(
    Path(__file__).resolve().parent.parent / "data" / "bridge.db"
)


@dataclass
class SqliteStore:
    """SQLite 持久化层单例。"""

    db_path: str

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.environ.get(
            "BRIDGE_DB_PATH", _DEFAULT_DB_PATH
        )
        # 确保父目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    # ==================== 初始化 ====================

    async def init_db(self) -> None:
        """应用所有 pending migrations。幂等。"""
        async with self._init_lock:
            if self._initialized:
                return
            # 先确保 schema_migrations 表存在（v1_initial.sql 会创建）
            # 但 init_db 的首次调用要先建这张表
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "  version INTEGER PRIMARY KEY,"
                    "  applied_at REAL NOT NULL"
                    ")"
                )
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.commit()

            # 读已应用版本
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
                applied_rows = await cursor.fetchall()
                await cursor.close()
                applied = {row["version"] for row in applied_rows}

            # 应用新 migration
            for version, sql_file in list_migration_files():
                if version in applied:
                    continue
                sql = sql_file.read_text(encoding="utf-8")
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA foreign_keys=ON")
                    # executescript 自动 commit
                    await db.executescript(sql)
                    await db.execute(
                        "INSERT INTO schema_migrations (version, applied_at) "
                        "VALUES (?, ?)",
                        (version, time.time()),
                    )
                    await db.commit()
                print(f"[SqliteStore] applied migration v{version}: {sql_file.name}")

            self._initialized = True

    # ==================== 连接管理 ====================

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[aiosqlite.Connection]:
        """获取一个 aiosqlite 连接（自动应用 PRAGMA）。"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA foreign_keys=ON")
            db.row_factory = aiosqlite.Row
            yield db

    # ==================== Users ====================

    async def upsert_user(
        self,
        user_id: str,
        ip: str | None = None,
        user_agent: str | None = None,
        display_name: str | None = None,
        is_legacy: bool = False,
    ) -> None:
        """插入或更新用户记录。

        - 首次插入：记录 first_seen_at
        - 后续：只更新 last_seen_at + last_known 信息
        """
        now = time.time()
        async with self._conn() as db:
            await db.execute(
                """
                INSERT INTO users (
                    user_id, display_name, first_ip, first_user_agent,
                    first_seen_at, last_seen_at, is_legacy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    display_name = COALESCE(excluded.display_name, users.display_name),
                    is_legacy = excluded.is_legacy
                """,
                (
                    user_id, display_name, ip, user_agent,
                    now, now, 1 if is_legacy else 0,
                ),
            )
            await db.commit()

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        async with self._conn() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        return dict(row)

    async def list_recent_users(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._conn() as db:
            cursor = await db.execute(
                "SELECT * FROM users ORDER BY last_seen_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(r) for r in rows]

    # ==================== display_name 二次区分 ====================

    async def resolve_display_name(
        self, raw_user_id: str, display_name: str
    ) -> str:
        """返回 (raw_user_id, display_name) 对应的 canonical_user_id。

        逻辑（display_name_map 表 UNIQUE(display_name) 保证全局唯一）：
        - 已存在 (raw_user_id, display_name) 映射 → 返回其 canonical_user_id
        - display_name 已被其他 raw 占用（撞库） → **复用那个 canonical_user_id**
          （"alice" 已被 raw-A 占用 → raw-B 说自己叫 alice 也算 raw-A，不新建）
          这种情况下不插入新行，避免 UNIQUE 冲突
        - 全新 → 用 uuid5(raw|dn) 派生新 canonical_user_id（不同 raw 的
          不同 display_name 必须得到不同 user_id；同 raw 同 dn 必须稳定）
        """
        import uuid as _uuid
        now = time.time()
        async with self._conn() as db:
            # 1. 已有 raw+name 映射？
            cursor = await db.execute(
                "SELECT canonical_user_id FROM display_name_map "
                "WHERE raw_user_id = ? AND display_name = ?",
                (raw_user_id, display_name),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                await db.execute(
                    "UPDATE display_name_map SET last_used_at = ? "
                    "WHERE raw_user_id = ? AND display_name = ?",
                    (now, raw_user_id, display_name),
                )
                await db.commit()
                return row["canonical_user_id"]

            # 2. display_name 已被其他 raw 占用？
            cursor = await db.execute(
                "SELECT canonical_user_id FROM display_name_map WHERE display_name = ?",
                (display_name,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                # 撞库：不插入新行（UNIQUE 会冲突），返回已有 canonical
                canonical = row["canonical_user_id"]
                # 但要更新 last_used_at 让审计能看到这次访问
                await db.execute(
                    "UPDATE display_name_map SET last_used_at = ? "
                    "WHERE display_name = ?",
                    (now, display_name),
                )
                await db.commit()
                return canonical

            # 3. 全新：派生确定性新 canonical_user_id
            #    关键：同 raw + 同 dn → 同 canonical（重启稳定）
            #    关键：同 raw + 不同 dn → 不同 canonical（撞库细分）
            canonical = str(_uuid.uuid5(
                _uuid.NAMESPACE_OID,
                f"{raw_user_id}|{display_name}",
            ))
            await db.execute(
                """
                INSERT INTO display_name_map (
                    raw_user_id, display_name, canonical_user_id,
                    claimed_at, last_used_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (raw_user_id, display_name, canonical, now, now),
            )
            await db.commit()
            return canonical

    async def count_display_name_collisions(self, user_id: str) -> int:
        """返回与 user_id 共享 display_name 的不同 user 数（撞库数）。"""
        async with self._conn() as db:
            # 找该 user 的 display_name
            cursor = await db.execute(
                "SELECT display_name FROM display_name_map WHERE canonical_user_id = ?",
                (user_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            if not rows:
                return 0
            display_names = [r["display_name"] for r in rows]
            # 算这些 display_name 关联的不同 canonical 数
            placeholders = ",".join("?" for _ in display_names)
            cursor = await db.execute(
                f"SELECT COUNT(DISTINCT canonical_user_id) FROM display_name_map "
                f"WHERE display_name IN ({placeholders})",
                display_names,
            )
            row = await cursor.fetchone()
            await cursor.close()
            total = row[0] if row else 0
            # 减 1 表示自己不算撞库
            return max(0, total - 1)

    async def list_collision_candidates(self, user_id: str) -> list[str]:
        """返回该 user 的 display_name 关联的所有 canonical_user_id。"""
        async with self._conn() as db:
            cursor = await db.execute(
                """
                SELECT DISTINCT d2.canonical_user_id, u.display_name AS user_display_name
                FROM display_name_map d1
                JOIN display_name_map d2 ON d1.display_name = d2.display_name
                LEFT JOIN users u ON d2.canonical_user_id = u.user_id
                WHERE d1.canonical_user_id = ?
                ORDER BY d2.canonical_user_id
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        seen = set()
        result: list[str] = []
        for r in rows:
            cid = r["canonical_user_id"]
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
        return result

    # ==================== Sessions ====================

    async def create_session(
        self,
        user_id: str,
        session_id: str,
        mode: str = "bypass",
        claude_model: str | None = None,
    ) -> None:
        now = time.time()
        async with self._conn() as db:
            await db.execute(
                """
                INSERT INTO sessions (
                    user_id, session_id, mode, status,
                    created_at, last_active_at, claude_model
                )
                VALUES (?, ?, ?, 'idle', ?, ?, ?)
                """,
                (user_id, session_id, mode, now, now, claude_model),
            )
            await db.execute(
                "UPDATE users SET session_count = session_count + 1 "
                "WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

    async def get_session(
        self, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        async with self._conn() as db:
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return dict(row) if row else None

    async def list_user_sessions(
        self, user_id: str, include_closed: bool = False
    ) -> list[dict[str, Any]]:
        async with self._conn() as db:
            if include_closed:
                cursor = await db.execute(
                    "SELECT * FROM sessions WHERE user_id = ? "
                    "ORDER BY last_active_at DESC",
                    (user_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM sessions WHERE user_id = ? AND status != 'closed' "
                    "ORDER BY last_active_at DESC",
                    (user_id,),
                )
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(r) for r in rows]

    async def update_session(
        self, user_id: str, session_id: str, **fields: Any
    ) -> None:
        if not fields:
            return
        # 白名单字段
        allowed = {
            "name", "mode", "status", "last_active_at", "closed_at",
            "last_event_id", "message_count",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [user_id, session_id]
        async with self._conn() as db:
            await db.execute(
                f"UPDATE sessions SET {set_clause} "
                f"WHERE user_id = ? AND session_id = ?",
                values,
            )
            await db.commit()

    async def delete_session(self, user_id: str, session_id: str) -> None:
        async with self._conn() as db:
            await db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            await db.commit()

    # ==================== Messages ====================

    async def append_message(
        self,
        user_id: str,
        session_id: str,
        seq: int,
        role: str,
        content: str,
        page_context: dict | None = None,
        timestamp: float | None = None,
    ) -> None:
        ts = timestamp or time.time()
        page_ctx_json = json.dumps(page_context, ensure_ascii=False) if page_context else None
        async with self._conn() as db:
            await db.execute(
                """
                INSERT INTO messages (
                    user_id, session_id, seq, role, content,
                    page_context_json, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, session_id, seq) DO NOTHING
                """,
                (user_id, session_id, seq, role, content, page_ctx_json, ts),
            )
            await db.commit()

    async def list_messages(
        self, user_id: str, session_id: str
    ) -> list[dict[str, Any]]:
        async with self._conn() as db:
            cursor = await db.execute(
                "SELECT seq, role, content, page_context_json, timestamp "
                "FROM messages WHERE user_id = ? AND session_id = ? "
                "ORDER BY seq",
                (user_id, session_id),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("page_context_json"):
                try:
                    d["page_context"] = json.loads(d["page_context_json"])
                except json.JSONDecodeError:
                    d["page_context"] = None
            del d["page_context_json"]
            result.append(d)
        return result

    # ==================== Events ====================

    async def append_event(
        self,
        user_id: str,
        session_id: str,
        event_id: int,
        event_type: str,
        event: dict,
        timestamp: float | None = None,
    ) -> None:
        """追加一条事件（双写：内存 + SQLite）。"""
        ts = timestamp or time.time()
        event_json = json.dumps(event, ensure_ascii=False)
        async with self._conn() as db:
            await db.execute(
                """
                INSERT INTO events (
                    user_id, session_id, event_id, event_type,
                    event_json, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, session_id, event_id) DO NOTHING
                """,
                (user_id, session_id, event_id, event_type, event_json, ts),
            )
            await db.execute(
                "UPDATE users SET event_count = event_count + 1 WHERE user_id = ?",
                (user_id,),
            )
            # 同步 last_event_id 到 session
            await db.execute(
                "UPDATE sessions SET last_event_id = MAX(last_event_id, ?) "
                "WHERE user_id = ? AND session_id = ?",
                (event_id, user_id, session_id),
            )
            await db.commit()

    async def list_events_since(
        self,
        user_id: str,
        session_id: str,
        since_event_id: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """返回 since_event_id 之后的所有事件（含 since+1 到 max）。"""
        async with self._conn() as db:
            cursor = await db.execute(
                """
                SELECT event_id, event_type, event_json, timestamp
                FROM events
                WHERE user_id = ? AND session_id = ? AND event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (user_id, session_id, since_event_id, limit),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        result = []
        for r in rows:
            try:
                event = json.loads(r["event_json"])
            except json.JSONDecodeError:
                event = {"_corrupt": True}
            event["event_id"] = r["event_id"]
            result.append(event)
        return result

    # ==================== Tasks ====================

    async def create_task(
        self, user_id: str, task_id: str, description: str
    ) -> None:
        now = time.time()
        async with self._conn() as db:
            await db.execute(
                """
                INSERT INTO tasks (
                    user_id, task_id, description, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (user_id, task_id, description, now, now),
            )
            await db.commit()

    async def get_task(
        self, user_id: str, task_id: str
    ) -> dict[str, Any] | None:
        async with self._conn() as db:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE user_id = ? AND task_id = ?",
                (user_id, task_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return dict(row) if row else None

    async def update_task(
        self, user_id: str, task_id: str, **fields: Any
    ) -> None:
        if not fields:
            return
        allowed = {
            "status", "result", "error",
            "started_at", "finished_at",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [user_id, task_id]
        async with self._conn() as db:
            await db.execute(
                f"UPDATE tasks SET {set_clause} "
                f"WHERE user_id = ? AND task_id = ?",
                values,
            )
            await db.commit()

    async def list_user_tasks(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        async with self._conn() as db:
            if status:
                cursor = await db.execute(
                    "SELECT * FROM tasks WHERE user_id = ? AND status = ? "
                    "ORDER BY created_at DESC",
                    (user_id, status),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                )
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(r) for r in rows]


# ==================== FastAPI Dependency ====================

# 进程级单例（app.py lifespan 启动时 init）
_store: SqliteStore | None = None


def get_store() -> SqliteStore:
    """FastAPI dependency：返回全局 SqliteStore 单例。"""
    if _store is None:
        raise RuntimeError(
            "SqliteStore 未初始化！请确保 app.py lifespan 调过 init_db()"
        )
    return _store


def init_store(db_path: str | None = None) -> SqliteStore:
    """初始化全局 SqliteStore 单例。"""
    global _store
    _store = SqliteStore(db_path)
    return _store