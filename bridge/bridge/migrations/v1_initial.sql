-- v1_initial.sql — Dify Helper Bridge 多用户隔离 schema (v1, 2026-07-07)
-- 设计依据：plan §4
--
-- 联合主键 (user_id, *) 是核心隔离原则：
-- - session_id 单 unique 不够，必须 (user_id, session_id) 联合主键（防撞 UUID）
-- - 老 in-memory 时代所有 session 全归 LEGACY_GLOBAL_USER_ID 下，无感迁移
--
-- 索引策略：
-- - sessions 按 user_id + last_active_at 排（list user 的活跃 session）
-- - events 按 (user_id, session_id, event_id) 排（since N 拉新事件）
-- - tasks 按 user_id + status（worker 拉 pending）+ created_at（审计）

-- ==================== schema_migrations（迁移版本追踪）====================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

-- ==================== users ====================
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,                    -- uuid5
    display_name TEXT,                            -- 用户自命名（可选）
    first_ip TEXT,
    first_user_agent TEXT,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    is_legacy INTEGER NOT NULL DEFAULT 0,         -- 1 = 老油猴无 fingerprint
    session_count INTEGER NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_users_display_name ON users(display_name);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen_at);

-- ==================== display_name 映射（同 IP+UA 撞库二次细分）====================
-- 同一 (raw_user_id, display_name) → canonical_user_id
-- 首次 claim 创建映射；后续同名 display_name 复用
CREATE TABLE IF NOT EXISTS display_name_map (
    raw_user_id TEXT NOT NULL,                   -- compute_user_id(ip,ua,lang) 的原始结果
    display_name TEXT NOT NULL,
    canonical_user_id TEXT NOT NULL,              -- 实际 user_id（= raw_user_id 首次出现时）
    claimed_at REAL NOT NULL,
    last_used_at REAL NOT NULL,
    PRIMARY KEY (raw_user_id, display_name)
);
CREATE INDEX IF NOT EXISTS idx_display_name_canonical ON display_name_map(canonical_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_display_name_unique ON display_name_map(display_name);

-- ==================== sessions ====================
CREATE TABLE IF NOT EXISTS sessions (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    name TEXT,
    mode TEXT NOT NULL DEFAULT 'bypass',
    status TEXT NOT NULL,                         -- active/idle/closed
    created_at REAL NOT NULL,
    last_active_at REAL NOT NULL,
    closed_at REAL,
    last_event_id INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    claude_model TEXT,
    PRIMARY KEY (user_id, session_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON sessions(user_id, last_active_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status) WHERE status != 'closed';

-- ==================== messages（每条对话单独存，支持重连回放）====================
CREATE TABLE IF NOT EXISTS messages (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,                         -- session 内单调
    role TEXT NOT NULL,                           -- user/assistant/system
    content TEXT NOT NULL,
    page_context_json TEXT,                       -- 可选序列化 page_context
    timestamp REAL NOT NULL,
    PRIMARY KEY (user_id, session_id, seq),
    FOREIGN KEY (user_id, session_id) REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(user_id, session_id, seq);

-- ==================== events ====================
CREATE TABLE IF NOT EXISTS events (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,                    -- 单调递增
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,                     -- 完整事件 dict
    timestamp REAL NOT NULL,
    PRIMARY KEY (user_id, session_id, event_id),
    FOREIGN KEY (user_id, session_id) REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_session_time ON events(user_id, session_id, event_id);

-- ==================== tasks（一次性 headless 任务）====================
CREATE TABLE IF NOT EXISTS tasks (
    user_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,                         -- pending/running/completed/failed
    result TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    PRIMARY KEY (user_id, task_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);