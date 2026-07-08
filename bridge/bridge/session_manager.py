"""SessionManager: 管理多个 ChatSession，每个会话一个独立 Claude CLI stream-json 子进程。

设计要点：
- 仿照 TaskQueue 用 asyncio.Lock + dict 存储
- 每个会话独立持有 asyncio.subprocess.Process（并发，非串行）
- 每个会话有独立 asyncio.Queue 作为 SSE 事件管道
- 后台 _read_loop 持续读 stdout 解析 stream-json，推入 event_queue
- 支持 bridge 本地斜杠指令（/reset /history /list-sessions /switch /export /dify-help）
- 30s SSE 心跳
- 启动时加载 skills/*.md 拼接 system prompt
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from .claude_cli_utils import (
    _resolve_claude_exec,
    build_stream_json_command,
    kill_process,
    write_mcp_config,
)
from .config import BridgeConfig
from .session import ChatMessage, ChatSession, SessionStatus
from .sqlite_store import SqliteStore


# bridge 本地斜杠指令（不转发给 Claude）
# 分类：
# - 桥接独占：bridge 自己实现（不转发 Claude），与 Claude Code 行为等价
# - 透传：Claude Code stream-json 模式下能用，桥接不拦截
LOCAL_COMMANDS = {
    # 桥接独占（Dify 调试专有）
    "/reset", "/history", "/list-sessions", "/switch",
    "/export", "/dify-help",
    # 桥接独占（Claude Code TUI-only，stream-json 模式返回 "isn't available"，
    # 桥接拦截后实现等价逻辑）
    "/clear",       # 等价 /reset
    "/mcp",         # 返回 MCP 状态 + 工具清单
    "/help",        # 返回帮助文本
    "/status",      # 返回 session 状态
    "/memory",      # 返回 memory 路径
    "/doctor",      # 运行 claude doctor 健康检查
}

# 透传给 Claude Code 的命令（stream-json 模式下 Claude 自己能处理）
PASS_THROUGH_COMMANDS = {
    "/init", "/review", "/debug", "/config", "/usage",
    "/insights", "/compact", "/context", "/heapdump",
    "/reload-skills", "/security-review", "/goal", "/team-onboarding",
}

# TUI 专属指令（headless 模式不可用，前端拦截提示）
TUI_DISABLED_COMMANDS = {
    "/rewind", "/branch", "/btw", "/chrome",
    "/install-github-app", "/remote-control", "/exit", "/quit",
}

# 心跳间隔
SSE_HEARTBEAT_INTERVAL = 30.0
# idle 会话超时清理（秒）—— 2 小时，避免用户几分钟后回来发现"会话已关闭"
IDLE_TIMEOUT = 7200.0  # 2 小时


# EventStore 在 event_store.py（独立模块以避免循环 import）
from .event_store import EventStore  # noqa: E402


class SessionManager:
    """管理多个 ChatSession 的并发管理器。"""

    def __init__(
        self,
        config: BridgeConfig,
        store: SqliteStore | None = None,
        current_user_id: str | None = None,
    ) -> None:
        self._config = config
        # v0.3.0 Phase 2: dict key 从 session_id 改为 (user_id, session_id) 联合 key
        self._sessions: dict[tuple[str, str], ChatSession] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._cleanup_task: asyncio.Task | None = None
        self._skills_prompt: str = ""
        # v0.3.0 Phase 2: 活跃 session 改为 per-user（不再是全局共享指针）
        self._active_per_user: dict[str, str] = {}

        # v0.3.0 Phase 1: SQLite 双写（仅持久化，不影响业务行为）
        # Phase 2 改造：current_user_id 改为从 get_current_user dependency 注入
        self._store = store
        self._current_user_id = current_user_id or os.environ.get(
            "BRIDGE_LEGACY_USER_ID",
            "00000000-0000-0000-0000-000000000000",
        )
        # session 内的 message seq 计数（每 session 独立单调）
        self._message_seq: dict[str, int] = {}

    async def start(self) -> None:
        """启动管理器：加载 Skills，启动 idle 清理任务。"""
        if self._running:
            return
        self._running = True
        self._skills_prompt = self._load_skills_prompt()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        print(f"[SessionManager] started, skills loaded: {len(self._skills_prompt)} chars")

    async def stop(self) -> None:
        """停止管理器：关闭所有会话，取消清理任务。"""
        self._running = False
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        # 关闭所有会话
        async with self._lock:
            for (uid, _sid), session in list(self._sessions.items()):
                await self._close_session_internal(session, uid)

    def set_store(self, store: SqliteStore, current_user_id: str | None = None) -> None:
        """v0.3.0 Phase 1: 在 lifespan 中调 init_db 后注入 store。

        必须在 start() 之前调用，确保后续 create_session 等操作能写入 SQLite。
        """
        self._store = store
        if current_user_id:
            self._current_user_id = current_user_id

    # ==================== 公开方法 ====================

    async def create_session(
        self,
        user_id: str,
        initial_prompt: str | None = None,
        mode: str | None = None,
    ) -> ChatSession:
        """创建新会话：启动 Claude CLI stream-json 子进程。

        ★ 0.2.7: mode 决定 Claude Code 权限模式（plan/bypass/default/acceptEdits），
        通过 build_stream_json_command 注入 --permission-mode 等 flag。
        默认 "bypass"（自动批准全部工具）保持向后兼容。

        v0.3.0 Phase 2: user_id 必传，dict key 改 (user_id, session_id)，
        旧 self._current_user_id 字段仅作为 SQLite 双写 fallback。
        """
        async with self._lock:
            session = ChatSession(id=str(uuid.uuid4()))
            # ★ 0.2.7: 持久化 mode 到 session（mode 变更走 _restart_proc_if_needed）
            session.mode = mode or "bypass"
            session.event_queue = asyncio.Queue()
            # HTTP 轮询用的事件存储（替代 SSE，给 Tampermonkey 等不稳客户端用）
            session.event_store = EventStore()

            # 1. 写临时 MCP config
            session.mcp_config_path = write_mcp_config(self._config.mcp_server_cmd)

            # 2. 构建 stream-json 命令（★ 0.2.7: 传 mode）
            cmd = build_stream_json_command(
                self._config.claude_path,
                session.mcp_config_path,
                mode=session.mode,
            )

            # 3. 启动子进程
            try:
                # 【模型锁定】强制注入 ANTHROPIC_MODEL 环境变量，
                # 防止任何调用方（如 MCP tool / 工作流）篡改模型
                proc_env = os.environ.copy()
                if self._config.claude_model:
                    proc_env["ANTHROPIC_MODEL"] = self._config.claude_model
                    print(f"[SessionManager] locking model to: {self._config.claude_model}")

                session.claude_proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._config.work_dir,
                    # 避免 Windows 弹窗
                    env=proc_env,
                    # ★ 默认 StreamReader limit = 64KB。
                    # claude stream-json 的 thinking_tokens system event 单行可达 100KB+
                    # （raw 字段塞了整个 system JSON），readline() 会抛
                    # "ValueError: Separator is found, but chunk is longer than limit"
                    # 直接拖死整个 read_loop。
                    # 提到 1MB，让单行 thinking_tokens / 巨型 tool_result 能完整通过；
                    # 真实大小限制在 _push_event 的 32KB 防御层（按字段截断）。
                    limit=1024 * 1024,
                )
            except Exception as e:
                # 启动失败：清理临时文件，抛出
                if session.mcp_config_path:
                    try:
                        os.unlink(session.mcp_config_path)
                    except OSError:
                        pass
                raise RuntimeError(f"failed to start claude: {e}") from e

            session.status = SessionStatus.idle
            self._sessions[(user_id, session.id)] = session
            self._active_per_user[user_id] = session.id
            # v0.3.0 Phase 1: SQLite 落盘（双写；落盘失败不阻塞创建）
            if self._store is not None:
                try:
                    await self._store.upsert_user(
                        user_id=user_id,
                        ip=None, user_agent=None,
                        is_legacy=(user_id == self._current_user_id),
                    )
                    await self._store.create_session(
                        user_id=user_id,
                        session_id=session.id,
                        mode=session.mode,
                        claude_model=self._config.claude_model or None,
                    )
                except Exception as e:
                    print(f"[SessionManager] sqlite dual-write (create_session) failed: {e}")
            # 初始化 message seq 计数器
            self._message_seq[session.id] = 0

            # 4. 启动后台读循环
            session.read_task = asyncio.create_task(self._read_loop(session))

            # 5. 注入 Skills system prompt（首条 system 消息）
            if self._skills_prompt:
                await self._write_to_stdin(session, {
                    "type": "system",
                    "message": {
                        "role": "system",
                        "content": [{"type": "text", "text": self._skills_prompt}],
                    },
                })

            # 6. 若有 initial_prompt，发送
            if initial_prompt:
                await self._send_user_message(session, initial_prompt)

            print(f"[SessionManager] session {session.id} created")
            return session

    async def send_message(
        self,
        user_id: str,
        session_id: str,
        content: str,
        page_context: dict | None = None,
    ) -> dict:
        """发送消息。返回 {"accepted": bool, "local_command": bool, "message": str}。

        - 本地指令（/reset /history 等）→ bridge 本地处理，返回 local_command=True
        - TUI 禁用指令 → 返回 accepted=False, message=提示
        - 其他（含 Claude 原生 /xxx）→ 写入 stream-json stdin

        ★ 0.2.16: page_context 由前端 (Dify Helper plugin) 注入，若提供会在 _send_user_message
        里作为 content block 前缀。

        v0.3.0 Phase 2: user_id 必传，ownership 校验内置（用户 A 不能 sendMessage 到用户 B 的 session）
        """
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return {"accepted": False, "local_command": False, "message": "session not found"}
            if session.status == SessionStatus.closed:
                return {"accepted": False, "local_command": False, "message": "session closed"}

        # Lazy restart：如果子进程死了（abort 后 / 异常退出），先重启
        if session.claude_proc is None:
            try:
                await self._restart_proc_if_needed(session)
            except Exception as e:
                return {"accepted": False, "local_command": False, "message": str(e)}

        # 处理本地指令
        if content in LOCAL_COMMANDS or content.startswith("/switch"):
            return await self._handle_local_command(user_id, session, content)

        # TUI 禁用指令
        cmd_word = content.split()[0] if content.split() else ""
        if cmd_word in TUI_DISABLED_COMMANDS:
            return {
                "accepted": False,
                "local_command": True,
                "message": f"指令 {cmd_word} 仅在交互式终端可用，headless 模式不支持",
            }

        # Claude 原生指令或普通文本：写入 stdin
        async with self._lock:
            await self._send_user_message(session, content, page_context)
        return {"accepted": True, "local_command": False, "message": None}

    async def get_events(
        self, user_id: str, session_id: str
    ) -> AsyncGenerator[dict, None]:
        """SSE 事件生成器。每 SSE_HEARTBEAT_INTERVAL 秒发心跳。

        v0.3.0 Phase 2: 越权访问 → yield error 事件（不抛 403，避免破坏 SSE 流）
        """
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None or session.event_queue is None:
                yield {"type": "error", "message": "session not found"}
                return

        queue = session.event_queue
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                yield event
                # result 或 error 事件后结束流
                if event.get("type") in ("result", "error", "session_closed"):
                    return
            except asyncio.TimeoutError:
                # 心跳
                yield {"type": "heartbeat", "timestamp": datetime.now().isoformat()}

    async def get_events_poll(
        self,
        user_id: str,
        session_id: str,
        since_event_id: int = 0,
        max_wait: float = 1.0,
    ) -> list[dict]:
        """HTTP 轮询端点：返回自 since_event_id 之后的所有事件。

        解决 Tampermonkey 远程访问时 GM_xmlhttpRequest SSE message channel 关闭
        导致 0 events 的 bug。前端用 setInterval 1s 调一次，bridge 在没有新事件时
        等待 max_wait 秒后返回空列表（避免空轮询压垮 server）。

        每个事件带单调递增的 event_id，客户端记录 last_event_id 即可。
        """
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return []
            store: EventStore | None = session.event_store
            last_id: int = session.last_event_id

        if store is None:
            return []

        # 已有积压事件：直接返回
        backlog = store.snapshot_since(since_event_id)
        if backlog:
            return backlog

        # 没有积压：短暂等待新事件（最多 max_wait 秒）
        try:
            await asyncio.wait_for(
                store.new_event_event.wait(), timeout=max_wait
            )
        except asyncio.TimeoutError:
            pass

        return store.snapshot_since(since_event_id)

    async def close_session(self, user_id: str, session_id: str) -> bool:
        """关闭会话。"""
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return False
            await self._close_session_internal(session, user_id)
            return True

    # ★ 0.2.15: 重命名会话。返回 None 表示会话不存在 / name 非法
    # 限长 100 字符（防滥用），空字符串视为 None（清空）
    async def rename_session(
        self, user_id: str, session_id: str, name: str | None
    ) -> "ChatSession | None":
        """重命名会话。name 为 None / 空字符串时清空。

        Returns: ChatSession (新状态), or None if session_id not found / name 非法
        """
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return None
            # 限长 100；超过截断；None/空串 → 清空
            if name is None:
                session.name = None
            else:
                stripped = name.strip()
                if not stripped:
                    session.name = None
                elif len(stripped) > 100:
                    # 拒绝超长——返回 None 让 endpoint 返 400
                    return None
                else:
                    session.name = stripped
            return session

    async def list_sessions(self, user_id: str) -> list[dict]:
        """列出指定 user 的所有活跃会话（不返回其他 user 的）。"""
        async with self._lock:
            return [
                s.to_public_dict()
                for (uid, _sid), s in self._sessions.items()
                if uid == user_id
            ]

    async def reset_session(
        self, user_id: str, session_id: str
    ) -> ChatSession | None:
        """重置会话：销毁旧子进程，新建空白会话。"""
        # 关闭旧会话
        await self.close_session(user_id, session_id)
        # 创建新会话
        return await self.create_session(user_id)

    async def abort_session(
        self, user_id: str, session_id: str, timeout: float = 1.0
    ) -> dict:
        """中断当前 turn（不销毁 session）。

        流程：
        1. 取消 read_loop task（CancelledError 让 readline 返回）
        2. 收集已累积的 partial text（从 event_store 拿）
        3. 向 claude 子进程发 SIGINT（Ctrl+C equivalent）—— graceful
        4. 等 timeout 秒，让 claude 清理
        5. 超时则 SIGKILL 强杀 —— hardkill
        6. 保留 session（proc = None，状态切回 idle，下个 sendMessage 时 lazy restart）
        7. 推 aborted 事件 + partial text 入库

        Returns:
            {"aborted": bool, "method": "graceful"|"hardkill"|"none",
             "partial_text": str, "reason": str}
        """
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return {"aborted": False, "method": "none", "partial_text": "", "reason": "session not found"}
            if session.claude_proc is None:
                return {"aborted": False, "method": "none", "partial_text": "", "reason": "no active process"}

        proc = session.claude_proc
        method = "graceful"

        # 1. 取消读循环（让 readline 抛 CancelledError 跳出）
        if session.read_task is not None and not session.read_task.done():
            session.read_task.cancel()
            try:
                await session.read_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            session.read_task = None

        # 2. 收集已累积的 partial text（从 event_store 拿）
        partial_text = self._collect_partial_text(session)

        # 3. SIGINT graceful（Windows 上 SIGINT 不支持，会自动 fallback 到 terminate）
        if hasattr(proc, "send_signal"):
            try:
                if os.name == "nt":
                    proc.terminate()  # Windows: 走 TerminateProcess
                else:
                    proc.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError):
                pass
        else:
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                pass

        # 4. 等 graceful 超时
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # 5. Hard kill
            method = "hardkill"
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
            try:
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass

        # 6. 标 dead，session 保留
        session.claude_proc = None
        session.status = SessionStatus.idle

        # 7. 推 aborted 事件
        await self._push_event(session, {
            "type": "aborted",
            "method": method,
            "message": f"任务已中断（{method}）",
            "partial_text": partial_text,
        })

        # 8. partial text 入库（避免丢失；用户能在 /history 看到）
        if partial_text:
            session.messages.append(ChatMessage(
                role="assistant",
                content=partial_text + "\n\n*[已中断]*",
            ))

        return {
            "aborted": True,
            "method": method,
            "partial_text": partial_text,
            "reason": "",
        }

    def _collect_partial_text(self, session: ChatSession) -> str:
        """从 event_store 收集最近的 text_delta，拼成 partial text。"""
        if not session.event_store:
            return ""
        chunks = []
        for _eid, evt in session.event_store._events:
            if evt.get("type") == "text_delta":
                chunks.append(evt.get("text", ""))
        return "".join(chunks)

    async def _restart_proc_if_needed(self, session: ChatSession) -> None:
        """Lazy restart：如果 claude 子进程已死（被 abort 或异常退出），重启它。

        ★ 0.2.7: mode 切换也会调用本函数。force=True 时不管当前状态强制重启
        （先 abort 当前在跑的子进程，再 spawn 新进程带新 mode）。
        """
        if session.status == SessionStatus.closed:
            return  # closed 状态的 session 不重启

        # 如果存在活进程且不是强制重启，直接返回
        if session.claude_proc is not None:
            return

        try:
            proc_env = os.environ.copy()
            if self._config.claude_model:
                proc_env["ANTHROPIC_MODEL"] = self._config.claude_model

            cmd = build_stream_json_command(
                self._config.claude_path,
                session.mcp_config_path,
                mode=session.mode,                  # ★ 0.2.7
            )
            session.claude_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._config.work_dir,
                env=proc_env,
                # ★ 同 create_session：1MB StreamReader 上限避免 thinking_tokens 单行触发 ValueError
                limit=1024 * 1024,
            )
            session.read_task = asyncio.create_task(self._read_loop(session))
        except Exception as e:
            # 重启失败：让上层返回错误
            raise RuntimeError(f"failed to restart claude process: {e}") from e

    async def set_mode(
        self, user_id: str, session_id: str, new_mode: str
    ) -> dict:
        """★ 0.2.7: 切换 Claude 权限模式。会重启子进程（保留 session_id + 历史）。

        返回 {"ok": bool, "mode": str, "restarted": bool, "error": str?}
        """
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return {"ok": False, "mode": new_mode, "restarted": False,
                        "error": "session not found"}

            if session.mode == new_mode:
                return {"ok": True, "mode": session.mode, "restarted": False}

            old_mode = session.mode
            session.mode = new_mode

            # 如果有活子进程，先 abort 再重启（带新 mode）
            if session.claude_proc is not None:
                try:
                    if session.claude_proc.returncode is None:
                        session.claude_proc.terminate()
                        try:
                            await asyncio.wait_for(session.claude_proc.wait(), timeout=2.0)
                        except asyncio.TimeoutError:
                            session.claude_proc.kill()
                            await session.claude_proc.wait()
                except Exception as e:
                    print(f"[SessionManager] abort old proc for mode change failed: {e}")
                session.claude_proc = None
                # 等 _read_loop 退出（read_task 会自动结束当 proc 被回收）
                if session.read_task is not None and not session.read_task.done():
                    try:
                        await asyncio.wait_for(session.read_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        session.read_task.cancel()
                session.read_task = None

            # 重新 spawn（带新 mode）
            try:
                await self._restart_proc_if_needed(session)
            except Exception as e:
                # 重启失败：回滚 mode 让用户能看到旧状态
                session.mode = old_mode
                return {"ok": False, "mode": old_mode, "restarted": False,
                        "error": f"restart failed: {e}"}

            # 重新注入 Skills system prompt（新进程无历史 context）
            if self._skills_prompt:
                try:
                    await self._write_to_stdin(session, {
                        "type": "system",
                        "message": {
                            "role": "system",
                            "content": [{"type": "text", "text": self._skills_prompt}],
                        },
                    })
                except Exception as e:
                    print(f"[SessionManager] skills prompt re-inject failed: {e}")

            return {"ok": True, "mode": session.mode, "restarted": True}

    async def get_history(
        self, user_id: str, session_id: str
    ) -> list[dict] | None:
        """获取会话消息历史。"""
        async with self._lock:
            session = self._sessions.get((user_id, session_id))
            if session is None:
                return None
            return [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()}
                for m in session.messages
            ]

    async def export_session(
        self, user_id: str, session_id: str, fmt: str = "md"
    ) -> str | None:
        """导出会话为 Markdown。"""
        history = await self.get_history(user_id, session_id)
        if history is None:
            return None
        if fmt == "md":
            lines = [f"# Claude Session {session_id}", ""]
            for m in history:
                role_label = {"user": "User", "assistant": "Assistant", "system": "System"}.get(
                    m["role"], m["role"]
                )
                lines.append(f"## {role_label} ({m['timestamp']})")
                lines.append("")
                lines.append(m["content"])
                lines.append("")
            return "\n".join(lines)
        # 其他格式 fallback 为 JSON
        return json.dumps(history, ensure_ascii=False, indent=2)

    async def get_active_session_id(self, user_id: str) -> str | None:
        """获取指定用户的活跃会话 ID。"""
        async with self._lock:
            return self._active_per_user.get(user_id)

    async def switch_active_session(self, user_id: str, session_id: str) -> bool:
        """切换指定用户的活跃会话。"""
        async with self._lock:
            if (user_id, session_id) not in self._sessions:
                return False
            self._active_per_user[user_id] = session_id
            return True

    # ==================== 内部方法 ====================

    def _format_page_context_block(self, ctx: dict) -> str:
        """★ 0.2.16: 将 page_context 字典格式化为人读可读的字符串。

        防御性：每个字段都做 maxlen 截断，防止恶意 URL/title 撑大 token。
        """
        def _clip(v, n=200):
            if v is None:
                return ""
            s = str(v)
            return s if len(s) <= n else s[:n] + "…"
        url = _clip(ctx.get("url"))
        title = _clip(ctx.get("title"), 120)
        app_id = _clip(ctx.get("app_id"), 64)
        captured = _clip(ctx.get("capturedAt"), 40)
        lines = ["[Page context captured by Dify Helper / 0.2.16 plugin]"]
        if url:
            lines.append(f"URL: {url}")
        if title:
            lines.append(f"Title: {title}")
        if app_id:
            lines.append(f"App ID: {app_id}")
        if captured:
            lines.append(f"Captured at: {captured}")
        return "\n".join(lines)

    async def _send_user_message(
        self, session: ChatSession, content: str, page_context: dict | None = None
    ) -> None:
        """向会话 stdin 写入 user 消息。

        ★ 0.2.16: 如果提供了 page_context（前端的 Dify Helper 注入），在 user content
        前面加一段 "[Page context ...]" 的 text block，并存到 messages 历史里（仅短标记）。
        """
        # 构造多 block content：第一段是 page context（若有），第二段是用户原文
        content_blocks = []
        if page_context:
            content_blocks.append({
                "type": "text",
                "text": self._format_page_context_block(page_context),
            })
        content_blocks.append({"type": "text", "text": content})

        # 历史里只存用户原文 + 一行小标记（避免历史膨胀）
        history_content = content
        if page_context:
            history_content = content + "\n\n[page: " + (
                page_context.get("title") or page_context.get("url") or ""
            ) + "]"

        session.messages.append(ChatMessage(role="user", content=history_content))
        session.last_active_at = datetime.now()
        session.status = SessionStatus.active
        # v0.3.0 Phase 1: SQLite 落盘 user message（独立 seq 计数）
        if self._store is not None:
            try:
                seq = self._message_seq.get(session.id, 0)
                await self._store.append_message(
                    user_id=self._current_user_id,
                    session_id=session.id,
                    seq=seq,
                    role="user",
                    content=history_content,
                    page_context=page_context,
                )
                self._message_seq[session.id] = seq + 1
            except Exception as e:
                print(f"[SessionManager] sqlite dual-write (user message) failed: {e}")
        await self._write_to_stdin(session, {
            "type": "user",
            "message": {
                "role": "user",
                "content": content_blocks,
            },
        })

    async def _push_event(self, session: ChatSession, event: dict) -> None:
        """统一推事件：同时写到 event_queue（SSE）+ event_store（HTTP 轮询）。

        防御性：单 event 序列化后超 32KB 时降级为摘要，避免 SSE chunked transfer
        在消费侧（httpx 默认 max_chunk_size=64KB）报 "Separator is found, but chunk
        is longer than limit" 错误。已知根因：MCP 工具返回 > 22KB 触发 stream-json
        解析器崩溃（已有 _safe_serialize 14KB 保护），但个别事件（如 stream_event 的
        raw payload）可能没经过 _safe_serialize。

        注：单行 JSON > 64KB 还会触发 asyncio StreamReader 默认上限的同类 ValueError，
        因此 create_subprocess_exec 已传 limit=1MB；这里做序列化层兜底。
        """
        # 防御：超大 payload 降级
        try:
            payload = json.dumps(event, ensure_ascii=False)
            if len(payload.encode("utf-8")) > 32_000:
                event = dict(event)  # 浅拷贝避免修改原 dict（可能多处引用）
                # 1) 截断大文本字段
                for key in ("content", "result", "text", "raw"):
                    val = event.get(key)
                    if isinstance(val, str) and len(val) > 1000:
                        event[key] = val[:1000] + "...[truncated by 32KB defense]"
                # 2) 截断大 dict 字段（assistant message / raw 字典等）
                #    序列化后截断到 4KB，保留可读的提示
                for key in ("message", "raw"):
                    val = event.get(key)
                    if isinstance(val, dict):
                        serialized = json.dumps(val, ensure_ascii=False)
                        if len(serialized.encode("utf-8")) > 4000:
                            event[key] = {
                                "_truncated_by_32kb_defense": True,
                                "_original_keys": list(val.keys()),
                                "_original_size_bytes": len(serialized.encode("utf-8")),
                                "_preview": serialized[:200],
                            }
                event["_truncated"] = True
        except Exception:
            # 序列化本身失败（不该发生），继续推原 event
            pass
        if session.event_queue is not None:
            await session.event_queue.put(event)
        if session.event_store is not None:
            eid = session.event_store.append(event)
            session.last_event_id = eid
            # v0.3.0 Phase 1: SQLite 落盘（双写；落盘失败不阻塞内存流）
            if self._store is not None:
                try:
                    await self._store.append_event(
                        user_id=self._current_user_id,
                        session_id=session.id,
                        event_id=eid,
                        event_type=event.get("type", "unknown"),
                        event=event,
                    )
                except Exception as e:
                    # SQLite 慢或锁竞争不阻塞 SSE；只记日志
                    print(f"[SessionManager] sqlite dual-write (event {eid}) failed: {e}")

    async def _write_to_stdin(self, session: ChatSession, payload: dict) -> None:
        """向子进程 stdin 写入 JSON 行。"""
        if session.claude_proc is None or session.claude_proc.stdin is None:
            return
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            session.claude_proc.stdin.write(line.encode("utf-8"))
            await session.claude_proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            await self._push_event(session, {
                "type": "error",
                "message": "claude process stdin closed",
            })

    async def _read_loop(self, session: ChatSession) -> None:
        """后台读循环：解析 stream-json 输出，推入 event_queue。"""
        proc = session.claude_proc
        if proc is None or proc.stdout is None:
            return

        try:
            while self._running and session.status != SessionStatus.closed:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    # EOF：子进程关闭
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # 非 JSON 行（可能是错误输出）：作为 raw 事件推送
                    await self._push_event(session, {
                        "type": "raw",
                        "text": line,
                    })
                    continue

                # 解析 stream-json 事件
                parsed = self._parse_stream_event(event)
                if parsed is not None:
                    # 记录 assistant 消息到历史
                    if parsed.get("type") == "assistant_complete":
                        msg_text = self._extract_assistant_text(parsed.get("message", {}))
                        if msg_text:
                            session.messages.append(ChatMessage(
                                role="assistant",
                                content=msg_text,
                            ))
                            # v0.3.0 Phase 1: SQLite 落盘 assistant message
                            if self._store is not None:
                                try:
                                    seq = self._message_seq.get(session.id, 0)
                                    await self._store.append_message(
                                        user_id=self._current_user_id,
                                        session_id=session.id,
                                        seq=seq,
                                        role="assistant",
                                        content=msg_text,
                                    )
                                    self._message_seq[session.id] = seq + 1
                                except Exception as e:
                                    print(f"[SessionManager] sqlite dual-write (assistant_complete) failed: {e}")
                    elif parsed.get("type") == "result":
                        # result 是 Claude 输出的最终结果
                        result_text = parsed.get("result", "")
                        if result_text:
                            session.messages.append(ChatMessage(
                                role="assistant",
                                content=result_text,
                            ))
                            # v0.3.0 Phase 1: SQLite 落盘 result message
                            if self._store is not None:
                                try:
                                    seq = self._message_seq.get(session.id, 0)
                                    await self._store.append_message(
                                        user_id=self._current_user_id,
                                        session_id=session.id,
                                        seq=seq,
                                        role="assistant",
                                        content=result_text,
                                    )
                                    self._message_seq[session.id] = seq + 1
                                except Exception as e:
                                    print(f"[SessionManager] sqlite dual-write (result) failed: {e}")
                        session.status = SessionStatus.idle

                    await self._push_event(session, parsed)

                    # result 后结束当前事件流（前端会关闭 SSE）
                    if parsed.get("type") == "result":
                        # 不直接 return，让后续 result 后状态保持 idle 等下一条消息
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            # 区分 readline 错误和 SSE 消费侧错误（前缀误导）
            await self._push_event(session, {
                "type": "error",
                "message": f"read_loop error: {type(e).__name__}: {e}",
                "exception_module": type(e).__module__,  # 帮助定位来源（如 httpx、asyncio）
            })
        finally:
            # 推送会话结束事件
            if session.status != SessionStatus.closed:
                await self._push_event(session, {
                    "type": "session_closed",
                    "message": "claude process exited",
                })
                session.status = SessionStatus.closed

    def _looks_like_confirmation(self, content: str) -> bool:
        """检测文本中是否包含 agent 等待用户确认的提示。

        关键词匹配（中英文常见变体）：
        - "需要确认" / "需要您确认" / "请确认" / "是否继续" / "请选择"
        - "needs confirmation" / "confirm?" / "proceed?" / "do you want to"
        """
        keywords = (
            "需要确认", "需要您确认", "需要你的确认",
            "请确认", "请选择", "是否继续", "是否执行", "是否应用", "是否保存",
            "需要批准", "需要授权",
            "needs confirmation", "needs your confirmation",
            "confirm?", "proceed?", "do you want to", "would you like to",
        )
        lower = content.lower()
        for kw in keywords:
            if kw.lower() in lower:
                return True
        return False

    def _parse_stream_event(self, event: dict) -> dict | None:
        """解析 stream-json 输出事件，转换为 SSE 事件。

        stream-json 输出类型：
        - stream_event: 含 content_block_delta（text_delta / thinking_delta）
        - assistant: 完整 assistant 消息
        - result: 最终结果，标志一次输入处理完成
        - system: thinking_tokens 等系统信息
        """
        event_type = event.get("type")

        if event_type == "stream_event":
            # stream_event 内部含 type 字段（text_delta / thinking_delta / message_start 等）
            inner = event.get("event", {})
            inner_type = inner.get("type", "")
            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    return {"type": "text_delta", "text": delta.get("text", "")}
                if delta_type == "thinking_delta":
                    return {"type": "thinking_delta", "text": delta.get("thinking", "")}
            # 工具调用相关
            if inner_type == "tool_use":
                return {
                    "type": "tool_call",
                    "tool": inner.get("name"),
                    "input": inner.get("input"),
                }
            if inner_type == "tool_result":
                content = inner.get("content")
                # 【防御性】检测 tool_result 中可能的确认请求信号
                # stream-json 协议不直接发 permission 事件，但 MCP 工具可能返回带
                # "需要确认"/"confirm?" 等提示的文本。检测到后转为 needs_confirmation
                # 事件，让前端在 system 区域显眼提示用户。
                if isinstance(content, str) and self._looks_like_confirmation(content):
                    return {
                        "type": "needs_confirmation",
                        "tool_use_id": inner.get("tool_use_id"),
                        "content_preview": content[:200],
                    }
                return {
                    "type": "tool_result",
                    "tool_use_id": inner.get("tool_use_id"),
                    "content": content,
                }
            # 其他 stream_event 子类型（content_block_start/stop、message_start/stop、
            # message_delta、ping 等）—— 不再保留 raw 整包（实测单行可达 100KB+，
            # 会触发 asyncio StreamReader 64KB 默认上限的 ValueError）。
            # 前端只需要 subtype 标识；详细 payload 需要时按需走 /history。
            return {"type": "stream_event", "subtype": inner_type}

        if event_type == "assistant":
            # 完整 assistant 消息
            return {"type": "assistant_complete", "message": event.get("message", {})}

        if event_type == "result":
            # 最终结果（一次输入处理结束）
            return {
                "type": "result",
                "result": event.get("result", ""),
                "subtype": event.get("subtype"),
                "is_error": event.get("is_error", False),
                "duration_ms": event.get("duration_ms"),
                "total_cost_usd": event.get("total_cost_usd"),
            }

        if event_type == "system":
            # thinking_tokens 等系统事件：保留有用字段（subtype + estimated_tokens 等），
            # **丢弃 raw 整包**，避免单行 > 64KB 拖死 readline。
            return {
                "type": "system",
                "subtype": event.get("subtype"),
                # 常见字段白名单（thinking_tokens 等会有 estimated_tokens / total_tokens）
                "estimated_tokens": event.get("estimated_tokens"),
                "total_tokens": event.get("total_tokens"),
            }

        # 未知类型：保留 type + subtype 元信息，不带 raw 整包
        return {
            "type": "unknown",
            "subtype": event.get("subtype"),
            "claude_event_type": event.get("type"),
        }

    def _extract_assistant_text(self, message: dict) -> str:
        """从 assistant 消息中提取纯文本。"""
        content = message.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "\n".join(texts)
        return ""

    async def _handle_local_command(
        self, user_id: str, session: ChatSession, content: str
    ) -> dict:
        """处理 bridge 本地斜杠指令。"""
        cmd = content.split()[0] if content.split() else ""

        if cmd == "/reset":
            new_session = await self.reset_session(user_id, session.id)
            return {
                "accepted": True,
                "local_command": True,
                "message": f"session reset, new session_id: {new_session.id}",
            }

        if cmd == "/history":
            history = await self.get_history(user_id, session.id)
            return {
                "accepted": True,
                "local_command": True,
                "message": json.dumps(history or [], ensure_ascii=False),
            }

        if cmd == "/list-sessions":
            sessions = await self.list_sessions(user_id)
            return {
                "accepted": True,
                "local_command": True,
                "message": json.dumps(sessions, ensure_ascii=False),
            }

        if cmd == "/switch":
            parts = content.split(maxsplit=1)
            if len(parts) < 2:
                return {
                    "accepted": False,
                    "local_command": True,
                    "message": "用法: /switch <session_id>",
                }
            target = parts[1].strip()
            ok = await self.switch_active_session(user_id, target)
            return {
                "accepted": ok,
                "local_command": True,
                "message": "switched" if ok else "session not found",
            }

        if cmd == "/export":
            md = await self.export_session(user_id, session.id, "md")
            return {
                "accepted": True,
                "local_command": True,
                "message": md or "export failed",
            }

        if cmd == "/dify-help":
            help_text = self._build_dify_help()
            return {
                "accepted": True,
                "local_command": True,
                "message": help_text,
            }

        # ========== Claude Code TUI-only 斜杠命令的桥接实现 ==========
        # 这些命令在 stream-json + bypassPermissions 模式下 Claude Code 会返回
        # "/xxx isn't available in this environment." 合成响应。桥接层拦截后
        # 实现等价行为。

        if cmd == "/clear":
            # /clear TUI 是"清屏+重置上下文"。这里等价 /reset。
            new_session = await self.reset_session(user_id, session.id)
            return {
                "accepted": True,
                "local_command": True,
                "message": f"session cleared (reset), new session_id: {new_session.id}",
            }

        if cmd == "/mcp":
            # /mcp TUI 是"显示 MCP 服务器和工具状态"。桥接从 .mcp.json 读配置 +
            # 列出 mcp__dify__* 工具。
            mcp_text = await self._build_mcp_status_text()
            return {
                "accepted": True,
                "local_command": True,
                "message": mcp_text,
            }

        if cmd == "/help":
            # /help TUI 是显示可用命令。桥接列出所有支持的斜杠命令。
            help_text = self._build_help_text()
            return {
                "accepted": True,
                "local_command": True,
                "message": help_text,
            }

        if cmd == "/status":
            # /status TUI 是显示 session 信息。桥接返回当前 session 状态。
            status_text = await self._build_status_text(session)
            return {
                "accepted": True,
                "local_command": True,
                "message": status_text,
            }

        if cmd == "/memory":
            # /memory TUI 是显示 memory 目录。桥接返回 memory 路径和文件列表。
            memory_text = await self._build_memory_text()
            return {
                "accepted": True,
                "local_command": True,
                "message": memory_text,
            }

        if cmd == "/doctor":
            # /doctor TUI 是健康检查。桥接调用 `claude doctor` 子进程。
            doctor_text = await self._run_doctor()
            return {
                "accepted": True,
                "local_command": True,
                "message": doctor_text,
            }

        return {
            "accepted": False,
            "local_command": True,
            "message": f"unknown local command: {cmd}",
        }

    def _build_dify_help(self) -> str:
        """构建 /dify-help 帮助文本。"""
        return """Dify Helper 可用 Skill:

【Dify 专属 Skill（7）】
- dify-app-architect: 应用架构选型（chat/completion/advanced-chat/workflow/agent-chat）
- dify-workflow-builder: 工作流编排（18 种节点 + graph schema）
- dify-dataset-curator: 知识库策略（indexing_technique + chunk）
- dify-dsl-importer: DSL 导入导出
- dify-prompt-engineer: 提示词工程
- dify-model-router: 模型路由
- dify-debug-runner: 调试运行

【通用应用开发 Skill（6）】
- systematic-thinking (critical): 系统化思考
- code-review-strict: 严格代码审查
- bug-diagnostician: 科学调试
- test-first-thinking: 测试驱动
- refactor-patterns: 重构与设计模式
- security-mindset: 安全意识

【使用方式】
直接描述需求即可，Skill 会按关键词自动激活。
例如：
- "创建一个工作流应用" → 激活 dify-app-architect + dify-workflow-builder
- "审查这段代码" → 激活 code-review-strict
- "调试这个 bug" → 激活 bug-diagnostician + systematic-thinking

【可用 MCP 工具】mcp__dify__* 共 27 个（App 6 / Workflow 5 / Dataset 11 / Model 3 / Workspace 2）
"""

    def _build_help_text(self) -> str:
        """构建 /help 文本。覆盖所有桥接支持的斜杠命令。"""
        return """Bridge 支持的斜杠命令：

【桥接独占（Dify 调试专有）】
- /reset              重置当前会话
- /history            显示消息历史
- /list-sessions      列出所有活跃会话
- /switch <sid>       切换活跃会话
- /export [md|json]   导出会话
- /dify-help          Dify 调试专用帮助

【桥接独占（替代 Claude Code TUI 命令）】
- /clear              等价 /reset
- /mcp                显示 MCP 状态 + 工具清单
- /help               本帮助（你正在看）
- /status             当前 session 状态
- /memory             memory 路径
- /doctor             claude 健康检查

【透传（Claude Code 处理）】
- /init, /review, /debug, /config, /usage,
- /insights, /compact, /context, /reload-skills 等

【TUI-only（headless 模式不支持）】
- /rewind, /branch, /btw, /chrome,
- /install-github-app, /remote-control, /exit, /quit
"""

    async def _build_mcp_status_text(self) -> str:
        """构建 /mcp 状态文本。

        读 .mcp.json 列 MCP 服务器配置 + 跑 `claude mcp list` 拿运行时状态 +
        从 server.py 提取 mcp__dify__* 工具列表。
        """
        lines: list[str] = ["MCP 服务器状态：\n"]

        # 1. 读 .mcp.json（项目级配置）
        work_dir = self._config.work_dir
        mcp_json_path = Path(work_dir) / ".mcp.json"
        if mcp_json_path.exists():
            try:
                cfg = json.loads(mcp_json_path.read_text(encoding="utf-8"))
                servers = cfg.get("mcpServers", {})
                if servers:
                    lines.append("【项目配置（.mcp.json）】")
                    for name, conf in servers.items():
                        cmd = conf.get("command", "?")
                        args = conf.get("args", [])
                        cwd = conf.get("cwd", work_dir)
                        lines.append(f"  - {name}: {cmd} {' '.join(args)} (cwd={cwd})")
                    lines.append("")
            except Exception as e:
                lines.append(f"  解析 .mcp.json 失败: {e}\n")

        # 2. 跑 `claude mcp list` 拿运行时状态
        try:
            proc = await asyncio.create_subprocess_exec(
                _resolve_claude_exec(self._config.claude_path), "mcp", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            runtime_output = (stdout or stderr).decode("utf-8", errors="replace").strip()
            if runtime_output:
                lines.append("【运行时状态（claude mcp list）】")
                lines.append(runtime_output)
                lines.append("")
        except (asyncio.TimeoutError, FileNotFoundError) as e:
            lines.append(f"  运行时检查失败: {e}\n")

        # 3. 列出 mcp__dify__* 工具
        # ★ 项目布局陷阱：dify-helper/mcp_server/ 是项目目录（**不是 Python 包**，
        # 无 __init__.py），但 mcp_server/mcp_server/ 里有 __init__.py 和 server.py，
        # server.py 用 `from .dify_client import ...` 相对导入。
        # 解法：用 importlib 把两层都注册成虚拟包，使相对导入能找到兄弟模块。
        try:
            import importlib.util
            import sys as _sys
            work_dir = str(Path(self._config.work_dir).resolve())
            inner_pkg_dir = Path(work_dir) / "mcp_server" / "mcp_server"
            server_py = inner_pkg_dir / "server.py"
            init_py = inner_pkg_dir / "__init__.py"
            if not server_py.is_file():
                lines.append(f"  列工具失败: server.py 不存在 {server_py}\n")
            elif not init_py.is_file():
                lines.append(f"  列工具失败: __init__.py 不存在 {init_py}\n")
            else:
                # 把内层 mcp_server/ 注册为虚拟包（先卸载已存在的同名模块避免冲突）
                inner_pkg_name = "_mcp_dify_inline_pkg"
                for n in (inner_pkg_name, f"{inner_pkg_name}.server", f"{inner_pkg_name}.dify_client"):
                    _sys.modules.pop(n, None)
                pkg_spec = importlib.util.spec_from_file_location(
                    inner_pkg_name, str(init_py),
                    submodule_search_locations=[str(inner_pkg_dir)],
                )
                pkg_mod = importlib.util.module_from_spec(pkg_spec)
                _sys.modules[inner_pkg_name] = pkg_mod
                pkg_spec.loader.exec_module(pkg_mod)
                # 把 server 注册为该虚拟包的子模块
                srv_spec = importlib.util.spec_from_file_location(
                    f"{inner_pkg_name}.server", str(server_py),
                )
                mcp_server_module = importlib.util.module_from_spec(srv_spec)
                _sys.modules[f"{inner_pkg_name}.server"] = mcp_server_module
                srv_spec.loader.exec_module(mcp_server_module)
                tools = sorted(
                    name for name in dir(mcp_server_module)
                    if name.startswith("dify_")
                    and callable(getattr(mcp_server_module, name))
                )
                if tools:
                    lines.append(f"【mcp__dify__* 工具（共 {len(tools)} 个）】")
                    for t in tools:
                        lines.append(f"  - {t}")
                    lines.append("")
                else:
                    lines.append("  列工具失败: dir(mcp_server_module) 里找不到 dify_* 函数\n")
        except Exception as e:
            import traceback
            lines.append(f"  列工具失败: {e}\n")
            lines.append(f"  详细堆栈: {traceback.format_exc()}\n")

        return "\n".join(lines)

    async def _build_status_text(self, session: ChatSession) -> str:
        """构建 /status 文本。当前 session 状态 + 全局统计。"""
        proc = session.claude_proc
        claude_running = proc is not None and proc.returncode is None
        # 计算消息数
        msg_count = len(session.messages)
        # 计算会话时长
        elapsed = (datetime.now() - session.last_active_at).total_seconds()

        lines = [
            "Session 状态：",
            f"  session_id:        {session.id}",
            f"  status:            {session.status.value}",
            f"  mode:              {session.mode}",        # ★ 0.2.7
            f"  claude_running:    {claude_running}",
            f"  message_count:     {msg_count}",
            f"  last_active_at:    {session.last_active_at.isoformat()}",
            f"  elapsed_seconds:   {elapsed:.1f}",
        ]
        # 活动会话信息（v0.3.0 Phase 2: per-user 活跃；status 命令查 caller 自己的活跃）
        # 但 _build_status_text 当前没拿 user_id；Phase 2 暂不显示 caller active，
        # 因为调用点 (/status) 是 local command，caller 是 _handle_local_command(user_id, ...)
        # 暂不重写 status 文本（功能不损失，只是少一行"我的活跃 session"）
        # 全局 session 数（所有用户合计；运维可见，不影响隔离）
        async with self._lock:
            total = len(self._sessions)
        lines.append(f"  total_sessions:    {total} (all users)")
        return "\n".join(lines)

    async def _build_memory_text(self) -> str:
        """构建 /memory 文本。返回 memory 路径 + 文件列表。"""
        # Claude Code 的 memory 路径约定。
        # 实际位置：从 init 事件的 memory_paths.auto 拿，但 bridge 启动时拿不到，
        # 用 home 推导兜底。
        home = Path.home()
        # 优先扫所有 ~/.claude/projects/*/memory/（不同项目会落不同目录）
        projects_dir = home / ".claude" / "projects"

        lines = ["Memory 目录：\n"]
        found_any = False
        if projects_dir.exists():
            for mem_dir in sorted(projects_dir.glob("*/memory")):
                if not mem_dir.is_dir():
                    continue
                files = sorted(mem_dir.glob("*.md"))
                if not files:
                    continue
                found_any = True
                lines.append(f"  {mem_dir}/")
                for f in files:
                    size = f.stat().st_size
                    lines.append(f"    - {f.name} ({size} bytes)")
                lines.append("")

        if not found_any:
            # 兜底：检查项目内 .claude/memory/
            fallback = Path(self._config.work_dir) / ".claude" / "memory"
            if fallback.exists():
                files = sorted(fallback.glob("*.md"))
                lines.append(f"  {fallback}/")
                for f in files:
                    size = f.stat().st_size
                    lines.append(f"    - {f.name} ({size} bytes)")
            else:
                lines.append("  (未找到任何 memory 目录)")

        # 提示 MEMORY.md 索引位置
        for mem_dir in projects_dir.glob("*/memory/MEMORY.md") if projects_dir.exists() else []:
            lines.append(f"\n索引文件: {mem_dir}")
            break
        return "\n".join(lines)

    async def _run_doctor(self) -> str:
        """运行 `claude doctor` 子进程，返回健康检查结果。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                _resolve_claude_exec(self._config.claude_path), "doctor",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = (stdout or stderr).decode("utf-8", errors="replace").strip()
            if not output:
                return "claude doctor: 无输出（可能不需要 health check）"
            return f"claude doctor 输出：\n{output}"
        except asyncio.TimeoutError:
            return "claude doctor: 超时（15s）"
        except FileNotFoundError as e:
            return f"claude doctor: 找不到 claude 可执行文件 ({e})"

    async def _close_session_internal(self, session: ChatSession, user_id: str) -> None:
        """内部关闭会话（不持锁）。

        v0.3.0 Phase 2: 接受 user_id 用于 dict.pop + active_session 清理 + SQLite 落盘。
        """
        session.status = SessionStatus.closed
        # 取消读循环
        if session.read_task is not None and not session.read_task.done():
            session.read_task.cancel()
            try:
                await session.read_task
            except asyncio.CancelledError:
                pass
            session.read_task = None
        # 杀子进程
        if session.claude_proc is not None:
            await kill_process(session.claude_proc)
            session.claude_proc = None
        # 推送关闭事件（同时写 SSE queue + HTTP 轮询 store）
        event = {
            "type": "session_closed",
            "message": "session closed by manager",
        }
        if session.event_queue is not None:
            try:
                session.event_queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        if session.event_store is not None:
            eid = session.event_store.append(event)
            session.last_event_id = eid
            # 双写（Phase 1 已加）
            if self._store is not None:
                try:
                    await self._store.append_event(
                        user_id=user_id,
                        session_id=session.id,
                        event_id=eid,
                        event_type=event.get("type", "unknown"),
                        event=event,
                    )
                except Exception as e:
                    print(f"[SessionManager] sqlite dual-write (close event) failed: {e}")
        # 清理临时 MCP config
        if session.mcp_config_path:
            try:
                os.unlink(session.mcp_config_path)
            except OSError:
                pass
            session.mcp_config_path = None
        # 从字典移除
        self._sessions.pop((user_id, session.id), None)
        # 若是该 user 的活跃会话，清空
        if self._active_per_user.get(user_id) == session.id:
            self._active_per_user.pop(user_id, None)
        # v0.3.0 Phase 1: SQLite 标记 closed
        if self._store is not None:
            try:
                await self._store.update_session(
                    user_id=user_id,
                    session_id=session.id,
                    status=SessionStatus.closed.value,
                    closed_at=time.time(),
                )
            except Exception as e:
                print(f"[SessionManager] sqlite dual-write (close_session) failed: {e}")
        # 清 message seq 计数器
        self._message_seq.pop(session.id, None)

    async def _cleanup_loop(self) -> None:
        """定期清理超时 idle 会话（v0.3.0 Phase 2: per-user）。"""
        while self._running:
            try:
                await asyncio.sleep(60.0)  # 每分钟检查一次
                now = datetime.now()
                async with self._lock:
                    expired = [
                        (uid, sid)
                        for (uid, sid), s in self._sessions.items()
                        if s.status == SessionStatus.idle
                        and (now - s.last_active_at).total_seconds() > IDLE_TIMEOUT
                    ]
                for uid, sid in expired:
                    print(f"[SessionManager] cleaning up idle session {sid} (user {uid[:8]}...)")
                    await self.close_session(uid, sid)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[SessionManager] cleanup loop error: {e}")
                await asyncio.sleep(60.0)

    def _load_skills_prompt(self) -> str:
        """加载 skills/ 目录下所有 .md 文件，拼接成 system prompt。

        每个文件结构：
        ---
        name: <skill-name>
        trigger: <关键词列表>
        priority: critical | high | medium | low
        ---
        # Skill: <Display Name>
        <system prompt 内容>
        """
        skills_dir = Path(self._config.work_dir) / "skills"
        if not skills_dir.exists():
            print(f"[SessionManager] skills dir not found: {skills_dir}")
            return ""

        # 按 priority 排序加载
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        skills: list[tuple[int, str, str]] = []

        for md_file in skills_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, body = self._parse_frontmatter(content)
                priority = frontmatter.get("priority", "medium")
                name = frontmatter.get("name", md_file.stem)
                sort_key = priority_order.get(priority, 3)
                skills.append((sort_key, name, body))
            except Exception as e:
                print(f"[SessionManager] failed to load skill {md_file}: {e}")

        skills.sort(key=lambda x: x[0])

        if not skills:
            return ""

        parts = ["你是一个 Dify 应用开发专用 Claude Code，加载了以下 Skill。按用户意图自动激活对应 Skill。", ""]
        for _, name, body in skills:
            parts.append(f"=== Skill: {name} ===")
            parts.append(body.strip())
            parts.append("")
            parts.append("---")
            parts.append("")

        return "\n".join(parts)

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """解析 YAML frontmatter + Markdown body。"""
        if not content.startswith("---"):
            return {}, content
        # 找第二个 ---
        end_idx = content.find("\n---", 3)
        if end_idx == -1:
            return {}, content
        frontmatter_text = content[3:end_idx].strip()
        body = content[end_idx + 4:].lstrip("\n")

        # 简单解析（不依赖 pyyaml，frontmatter 通常简单 key: value）
        frontmatter: dict[str, str] = {}
        for line in frontmatter_text.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                frontmatter[key.strip()] = value.strip()
        return frontmatter, body
