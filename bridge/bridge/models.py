"""Task data models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Task(BaseModel):
    id: str
    description: str
    status: TaskStatus = TaskStatus.pending
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskSubmitRequest(BaseModel):
    task_description: str


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: TaskStatus


class TaskStatusResponse(BaseModel):
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskResultResponse(BaseModel):
    status: TaskStatus
    result: str | None = None
    error: str | None = None
