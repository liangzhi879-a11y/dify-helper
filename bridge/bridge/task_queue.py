"""In-memory async task queue (v0.3.0 per-user).

v0.3.0 Phase 2: 拆为 per-user 隔离空间
- (user_id, task_id) 联合 key
- submit(user_id, description) — caller 必须传 user_id
- get(user_id, task_id) — ownership 校验内置（用户 A 看不到用户 B 的 task）
- pick_pending() — worker 全局仍拉所有 user 的 pending（按 FIFO）
- update(task_id, **fields) — worker 全局更新（不限 user，但 task_id 仍唯一）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from .models import Task, TaskStatus


class TaskQueue:
    """线程安全（基于 asyncio.Lock）的内存任务队列。"""

    def __init__(self) -> None:
        # (user_id, task_id) → Task
        self._tasks: dict[tuple[str, str], Task] = {}
        # [(user_id, task_id)] 维持提交顺序（worker.pick_pending 用）
        self._order: list[tuple[str, str]] = []
        self._lock = asyncio.Lock()

    async def submit(self, user_id: str, description: str) -> Task:
        """创建任务并入队，返回新任务。"""
        async with self._lock:
            task = Task(id=str(uuid.uuid4()), user_id=user_id, description=description)
            key = (user_id, task.id)
            self._tasks[key] = task
            self._order.append(key)
            return task

    async def get(self, user_id: str, task_id: str) -> Task | None:
        """按 (user_id, task_id) 获取任务；不存在或越权返回 None。"""
        async with self._lock:
            return self._tasks.get((user_id, task_id))

    async def pick_pending(self) -> Task | None:
        """取出一个 pending 任务（worker 使用）。仅返回，不修改状态。"""
        async with self._lock:
            for key in self._order:
                task = self._tasks.get(key)
                if task is not None and task.status == TaskStatus.pending:
                    return task
            return None

    async def update(self, task_id: str, **fields) -> Task:
        """更新任务字段（worker 全局用，不限 user；task_id 全局唯一）。

        任务不存在抛出 KeyError。
        """
        async with self._lock:
            # O(N) 扫描：找到该 task_id 对应的 (user_id, task_id)
            target = None
            for key, t in self._tasks.items():
                if t.id == task_id:
                    target = t
                    break
            if target is None:
                raise KeyError(f"task {task_id} not found")
            for key, value in fields.items():
                setattr(target, key, value)
            target.updated_at = datetime.now()
            return target