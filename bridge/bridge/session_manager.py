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
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from .claude_cli_utils import (
    build_stream_json_command,
    kill_process,
    write_mcp_config,
)
from .config import BridgeConfig
from .session import ChatMessage, ChatSession, SessionStatus


# bridge 本地斜杠指令（不转发给 Claude）
LOCAL_COMMANDS = {
    "/reset", "/history", "/list-sessions", "/switch",
    "/export", "/dify-help",
}

# TUI 专属指令（headless 模式不可用，前端拦截提示）
TUI_DISABLED_COMMANDS = {
    "/rewind", "/branch", "/btw", "/chrome",
    "/install-github-app", "/remote-control", "/exit", "/quit",
}

# 心跳间隔
SSE_HEARTBEAT_INTERVAL = 30.0
# idle 会话超时清理（秒）
IDLE_TIMEOUT = 1800.0  # 30 分钟


class SessionManager:
    """管理多个 ChatSession 的并发管理器。"""

    def __init__(self, config: BridgeConfig) -> None:
        self._config = config
        self._sessions: dict[str, ChatSession] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._cleanup_task: asyncio.Task | None = None
        self._skills_prompt: str = ""
        self._active_session_id: str | None = None  # 当前活跃会话（/switch 用）

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
            for session in list(self._sessions.values()):
                await self._close_session_internal(session)

    # ==================== 公开方法 ====================

    async def create_session(self, initial_prompt: str | None = None) -> ChatSession:
        """创建新会话：启动 Claude CLI stream-json 子进程。"""
        async with self._lock:
            session = ChatSession(id=str(uuid.uuid4()))
            session.event_queue = asyncio.Queue()

            # 1. 写临时 MCP config
            session.mcp_config_path = write_mcp_config(self._config.mcp_server_cmd)

            # 2. 构建 stream-json 命令
            cmd = build_stream_json_command(
                self._config.claude_path,
                session.mcp_config_path,
            )

            # 3. 启动子进程
            try:
                session.claude_proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._config.work_dir,
                    # 避免 Windows 弹窗
                    env=os.environ.copy(),
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
            self._sessions[session.id] = session
            self._active_session_id = session.id

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
        self, session_id: str, content: str
    ) -> dict:
        """发送消息。返回 {"accepted": bool, "local_command": bool, "message": str}。

        - 本地指令（/reset /history 等）→ bridge 本地处理，返回 local_command=True
        - TUI 禁用指令 → 返回 accepted=False, message=提示
        - 其他（含 Claude 原生 /xxx）→ 写入 stream-json stdin
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {"accepted": False, "local_command": False, "message": "session not found"}
            if session.status == SessionStatus.closed:
                return {"accepted": False, "local_command": False, "message": "session closed"}

        # 处理本地指令
        if content in LOCAL_COMMANDS or content.startswith("/switch"):
            return await self._handle_local_command(session, content)

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
            await self._send_user_message(session, content)
        return {"accepted": True, "local_command": False, "message": None}

    async def get_events(self, session_id: str) -> AsyncGenerator[dict, None]:
        """SSE 事件生成器。每 SSE_HEARTBEAT_INTERVAL 秒发心跳。"""
        async with self._lock:
            session = self._sessions.get(session_id)
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

    async def close_session(self, session_id: str) -> bool:
        """关闭会话。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            await self._close_session_internal(session)
            return True

    async def list_sessions(self) -> list[dict]:
        """列出所有会话公开信息。"""
        async with self._lock:
            return [s.to_public_dict() for s in self._sessions.values()]

    async def reset_session(self, session_id: str) -> ChatSession | None:
        """重置会话：销毁旧子进程，新建空白会话。"""
        # 关闭旧会话
        await self.close_session(session_id)
        # 创建新会话
        return await self.create_session()

    async def get_history(self, session_id: str) -> list[dict] | None:
        """获取会话消息历史。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()}
                for m in session.messages
            ]

    async def export_session(self, session_id: str, fmt: str = "md") -> str | None:
        """导出会话为 Markdown。"""
        history = await self.get_history(session_id)
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

    async def get_active_session_id(self) -> str | None:
        """获取当前活跃会话 ID。"""
        async with self._lock:
            return self._active_session_id

    async def switch_active_session(self, session_id: str) -> bool:
        """切换活跃会话。"""
        async with self._lock:
            if session_id not in self._sessions:
                return False
            self._active_session_id = session_id
            return True

    # ==================== 内部方法 ====================

    async def _send_user_message(self, session: ChatSession, content: str) -> None:
        """向会话 stdin 写入 user 消息。"""
        session.messages.append(ChatMessage(role="user", content=content))
        session.last_active_at = datetime.now()
        session.status = SessionStatus.active
        await self._write_to_stdin(session, {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": content}],
            },
        })

    async def _write_to_stdin(self, session: ChatSession, payload: dict) -> None:
        """向子进程 stdin 写入 JSON 行。"""
        if session.claude_proc is None or session.claude_proc.stdin is None:
            return
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            session.claude_proc.stdin.write(line.encode("utf-8"))
            await session.claude_proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            await session.event_queue.put({
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
                    await session.event_queue.put({
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
                    elif parsed.get("type") == "result":
                        # result 是 Claude 输出的最终结果
                        result_text = parsed.get("result", "")
                        if result_text:
                            session.messages.append(ChatMessage(
                                role="assistant",
                                content=result_text,
                            ))
                        session.status = SessionStatus.idle

                    await session.event_queue.put(parsed)

                    # result 后结束当前事件流（前端会关闭 SSE）
                    if parsed.get("type") == "result":
                        # 不直接 return，让后续 result 后状态保持 idle 等下一条消息
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await session.event_queue.put({
                "type": "error",
                "message": f"read_loop error: {type(e).__name__}: {e}",
            })
        finally:
            # 推送会话结束事件
            if session.status != SessionStatus.closed:
                await session.event_queue.put({
                    "type": "session_closed",
                    "message": "claude process exited",
                })
                session.status = SessionStatus.closed

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
                return {
                    "type": "tool_result",
                    "tool_use_id": inner.get("tool_use_id"),
                    "content": inner.get("content"),
                }
            # 其他 stream_event 子类型
            return {"type": "stream_event", "subtype": inner_type, "raw": inner}

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
            # 系统信息（thinking_tokens 等）
            return {"type": "system", "raw": event}

        # 未知类型：原样转发
        return {"type": "unknown", "raw": event}

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

    async def _handle_local_command(self, session: ChatSession, content: str) -> dict:
        """处理 bridge 本地斜杠指令。"""
        cmd = content.split()[0] if content.split() else ""

        if cmd == "/reset":
            new_session = await self.reset_session(session.id)
            return {
                "accepted": True,
                "local_command": True,
                "message": f"session reset, new session_id: {new_session.id}",
            }

        if cmd == "/history":
            history = await self.get_history(session.id)
            return {
                "accepted": True,
                "local_command": True,
                "message": json.dumps(history or [], ensure_ascii=False),
            }

        if cmd == "/list-sessions":
            sessions = await self.list_sessions()
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
            ok = await self.switch_active_session(target)
            return {
                "accepted": ok,
                "local_command": True,
                "message": "switched" if ok else "session not found",
            }

        if cmd == "/export":
            md = await self.export_session(session.id, "md")
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

    async def _close_session_internal(self, session: ChatSession) -> None:
        """内部关闭会话（不持锁）。"""
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
        # 推送关闭事件
        if session.event_queue is not None:
            try:
                session.event_queue.put_nowait({
                    "type": "session_closed",
                    "message": "session closed by manager",
                })
            except asyncio.QueueFull:
                pass
        # 清理临时 MCP config
        if session.mcp_config_path:
            try:
                os.unlink(session.mcp_config_path)
            except OSError:
                pass
            session.mcp_config_path = None
        # 从字典移除
        self._sessions.pop(session.id, None)
        # 若是活跃会话，清空
        if self._active_session_id == session.id:
            self._active_session_id = None

    async def _cleanup_loop(self) -> None:
        """定期清理超时 idle 会话。"""
        while self._running:
            try:
                await asyncio.sleep(60.0)  # 每分钟检查一次
                now = datetime.now()
                async with self._lock:
                    expired = [
                        sid for sid, s in self._sessions.items()
                        if s.status == SessionStatus.idle
                        and (now - s.last_active_at).total_seconds() > IDLE_TIMEOUT
                    ]
                for sid in expired:
                    print(f"[SessionManager] cleaning up idle session {sid}")
                    await self.close_session(sid)
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
