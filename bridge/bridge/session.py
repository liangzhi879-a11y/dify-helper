"""ChatSession 数据模型 + 请求/响应模型。

ChatSession 代表一个 Claude Code CLI stream-json 持久会话：
- claude_proc: 子进程引用（运行时，不序列化）
- event_queue: SSE 事件管道（运行时，不序列化）
- messages: 对话历史
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    last_active_at: datetime = Field(default_factory=datetime.now)

    # 运行时引用（不序列化）
    claude_proc: asyncio.subprocess.Process | None = None
    event_queue: asyncio.Queue | None = None
    mcp_config_path: str | None = None
    read_task: asyncio.Task | None = None

    model_config = {"arbitrary_types_allowed": True}

    def to_public_dict(self) -> dict:
        """返回可序列化的公开信息（剥离运行时字段）。"""
        return {
            "id": self.id,
            "status": self.status.value,
            "message_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
        }


# ==================== 请求/响应模型 ====================


class CreateSessionRequest(BaseModel):
    """创建会话请求。initial_prompt 可选，若提供则创建后立即发送。"""
    initial_prompt: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    status: SessionStatus


class SendMessageRequest(BaseModel):
    """发送消息请求。content 可以是普通文本或斜杠指令。"""
    content: str


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
