"""In-memory async task queue."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from .models import Task, TaskStatus


class TaskQueue:
    """线程安全（基于 asyncio.Lock）的内存任务队列。

    使用 dict[str, Task] 存储任务，list 维持提交顺序。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()

    async def submit(self, description: str) -> Task:
        """创建任务并入队，返回新任务。"""
        async with self._lock:
            task = Task(id=str(uuid.uuid4()), description=description)
            self._tasks[task.id] = task
            self._order.append(task.id)
            return task

    async def get(self, task_id: str) -> Task | None:
        """按 id 获取任务，不存在返回 None。"""
        async with self._lock:
            return self._tasks.get(task_id)

    async def pick_pending(self) -> Task | None:
        """取出一个 pending 任务（worker 使用）。仅返回，不修改状态。"""
        async with self._lock:
            for task_id in self._order:
                task = self._tasks.get(task_id)
                if task is not None and task.status == TaskStatus.pending:
                    return task
            return None

    async def update(self, task_id: str, **fields) -> Task:
        """更新任务字段，自动刷新 updated_at。任务不存在抛出 KeyError。"""
        async with self._lock:
            task = self._tasks[task_id]
            for key, value in fields.items():
                setattr(task, key, value)
            task.updated_at = datetime.now()
            return task
