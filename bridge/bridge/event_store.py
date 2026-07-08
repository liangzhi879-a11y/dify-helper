"""EventStore：HTTP 轮询用的事件存储（替代 SSE 给 Tampermonkey 等不稳客户端用）。

每个事件带单调递增的 event_id，客户端用 ?since=N 拉取新事件。
通过 asyncio.Event 在没有新事件时让轮询端点短暂等待（避免空轮询压垮 server）。

单独成模块以避免 session.py ↔ session_manager.py 的循环 import。
"""

from __future__ import annotations

import asyncio


class EventStore:
    def __init__(self) -> None:
        self._events: list[tuple[int, dict]] = []  # (event_id, event_dict)
        self._next_id: int = 0
        self._lock = asyncio.Lock()
        self.new_event_event = asyncio.Event()

    def append(self, event: dict) -> int:
        """追加事件，返回分配的 event_id。同时唤醒等待中的轮询请求。"""
        self._events.append((self._next_id, event))
        eid = self._next_id
        self._next_id += 1
        # 唤醒等待中的轮询请求
        self.new_event_event.set()
        self.new_event_event = asyncio.Event()  # 重置，给下一个 wait 用
        return eid

    def snapshot_since(self, since_id: int) -> list[dict]:
        """返回 since_id 之后的所有事件（不含 since_id 本身）。"""
        return [
            {"event_id": eid, **evt}
            for eid, evt in self._events
            if eid > since_id
        ]

    def __len__(self) -> int:
        return len(self._events)
