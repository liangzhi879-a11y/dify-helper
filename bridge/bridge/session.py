"""ChatSession 数据模型 + 请求/响应模型。

ChatSession 代表一个 Claude Code CLI stream-json 持久会话：
- claude_proc: 子进程引用（运行时，不序列化）
- event_queue: SSE 事件管道（运行时，不序列化）
- event_store: HTTP 轮询用的事件存储（运行时，不序列化）
- messages: 对话历史
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# EventStore 在独立模块 event_store 里，避免 session.py ↔ session_manager.py 循环 import
from .event_store import EventStore


class SessionStatus(str, Enum):
    active = "active"      # 子进程在跑，正在流式输出
    idle = "idle"          # 子进程在跑，等待下一条输入
    closed = "closed"      # 子进程已终止


class ChatMessage(BaseModel):
    """单条对话消息。"""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ChatSession(BaseModel):
    """Claude Code CLI stream-json 会话。

    运行时字段（claude_proc / event_queue / mcp_config_path）不参与序列化，
    通过 model_config = {"arbitrary_types_allowed": True} 允许任意类型。
    """
    id: str
    status: SessionStatus = SessionStatus.idle
    # ★ 0.2.7: Claude Code 模式（plan/bypass/default/acceptEdits）
    # 切换会重启子进程（保留 session_id + 历史消息）
    mode: str = "bypass"
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    last_active_at: datetime = Field(default_factory=datetime.now)
    # ★ 0.2.15: 用户友好名（rename 设置）。为 None 时 UI 退到 first_message_preview
    name: str | None = None

    # 运行时引用（不序列化）
    claude_proc: asyncio.subprocess.Process | None = None
    event_queue: asyncio.Queue | None = None
    mcp_config_path: str | None = None
    read_task: asyncio.Task | None = None
    # HTTP 轮询用的 EventStore（替代 SSE，给 Tampermonkey 等 SSE 不稳的客户端用）
    event_store: "EventStore | None" = None
    last_event_id: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def to_public_dict(self) -> dict:
        """返回可序列化的公开信息（剥离运行时字段）。"""
        # ★ 0.2.15: 首条消息预览（slice 前 30 字），给 UI 当会话标签
        first_msg_preview = ""
        if self.messages:
            first_content = self.messages[0].content or ""
            first_msg_preview = first_content[:30]
        return {
            "id": self.id,
            "status": self.status.value,
            "mode": self.mode,           # ★ 0.2.7
            "message_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            # ★ 0.2.15
            "name": self.name,
            "first_message_preview": first_msg_preview,
        }


# ==================== 请求/响应模型 ====================


class CreateSessionRequest(BaseModel):
    """创建会话请求。initial_prompt 可选，若提供则创建后立即发送。"""
    initial_prompt: str | None = None
    # ★ 0.2.7: 创建时指定 Claude 模式（不传则用默认 "bypass"）
    mode: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    status: SessionStatus
    mode: str                              # ★ 0.2.7: 回传生效的 mode


class SendMessageRequest(BaseModel):
    """发送消息请求。content 可以是普通文本或斜杠指令。

    ★ 0.2.16: 可选 page_context 字段（Dify 调试 plugin 注入当前页面元信息）。
    字段为 None 或缺失时保持原行为不变。
    """
    content: str
    page_context: dict | None = None


class SessionModeRequest(BaseModel):
    """★ 0.2.7: 切换 Claude 模式请求。mode ∈ {plan,bypass,default,acceptEdits}"""
    mode: str


class SendMessageResponse(BaseModel):
    """发送消息响应。local_command=True 表示是 bridge 本地指令，无需 SSE 流。"""
    accepted: bool
    local_command: bool = False
    message: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[dict]


class SessionExportResponse(BaseModel):
    """会话导出响应。"""
    session_id: str
    format: str
    content: str


# ★ 0.2.15: 重命名会话请求。None 表示清空恢复 UUID 预览
class RenameSessionRequest(BaseModel):
    """重命名会话请求。name 为 None 表示清空（UI 退到 first_message_preview）。"""
    name: str | None = None
