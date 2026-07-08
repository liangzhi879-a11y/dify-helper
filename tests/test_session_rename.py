"""★ 0.2.15: PATCH /sessions/{id}/rename 端点单元测试。

覆盖：创建 → 重命名 → list 验证 / 重命名为 None / 不存在 ID 404 / 超长 name 拒绝
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bridge.app import app, session_manager


# ==================== Mock 工具 ====================


def make_mock_proc() -> MagicMock:
    """构造 mock Claude 子进程：EOF 立即返回。"""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.stdin.wait_closed = AsyncMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(return_value=b"")  # EOF
    proc.stdout.at_eof = MagicMock(return_value=True)
    proc.stderr = MagicMock()
    proc.stderr.readline = AsyncMock(return_value=b"")
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    proc.returncode = 0
    return proc


# ==================== 同步 fixture（沿用 test_session.py 风格） ====================


@pytest.fixture
def running_session_manager():
    """启动 session_manager（mock 子进程），测试后停止。"""
    mock_proc = make_mock_proc()
    with patch(
        "bridge.session_manager.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ) as _mock_exec:
        asyncio.run(session_manager.start())
        try:
            yield session_manager
        finally:
            try:
                asyncio.run(session_manager.stop())
            except Exception:
                pass


def _run_async(coro):
    """在同步测试函数内跑 async 协程。"""
    return asyncio.run(coro)


# ==================== 测试用例 ====================


def test_rename_session_success(running_session_manager) -> None:
    """创建 → PATCH rename → GET /sessions 验证 name 已更新。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            assert create_resp.status_code == 200, create_resp.text
            session_id = create_resp.json()["session_id"]

            new_name = "调试工作流"
            resp = await client.patch(
                f"/sessions/{session_id}/rename",
                json={"name": new_name},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert "sessions" in body
            assert len(body["sessions"]) == 1
            assert body["sessions"][0]["id"] == session_id
            assert body["sessions"][0]["name"] == new_name

            list_resp = await client.get("/sessions")
            assert list_resp.status_code == 200
            listed = list_resp.json()["sessions"]
            assert any(
                s["id"] == session_id and s["name"] == new_name for s in listed
            ), f"name not found: {listed}"

    _run_async(scenario())


def test_rename_to_none_clears(running_session_manager) -> None:
    """重命名为 None 会清空 name。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            await client.patch(
                f"/sessions/{session_id}/rename", json={"name": "临时名"}
            )
            # 再清空
            resp = await client.patch(
                f"/sessions/{session_id}/rename", json={"name": None}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["sessions"][0]["name"] is None

    _run_async(scenario())


def test_rename_to_empty_string_clears(running_session_manager) -> None:
    """空字符串 / 全空白视为清空。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            resp = await client.patch(
                f"/sessions/{session_id}/rename", json={"name": "   "}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["sessions"][0]["name"] is None

    _run_async(scenario())


def test_rename_too_long_returns_error(running_session_manager) -> None:
    """name > 100 字符应拒绝（endpoint 用 404 + 通用 message）。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            long_name = "x" * 200
            resp = await client.patch(
                f"/sessions/{session_id}/rename", json={"name": long_name}
            )
            # rename_session 在 name 超长时返 None → endpoint 返 404
            assert resp.status_code == 404, resp.text
            assert "not found" in resp.text or "invalid" in resp.text.lower()

    _run_async(scenario())


def test_rename_nonexistent_session_404(running_session_manager) -> None:
    """PATCH 不存在的 session_id → 404。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            fake_id = "00000000-0000-0000-0000-000000000000"
            resp = await client.patch(
                f"/sessions/{fake_id}/rename", json={"name": "test"}
            )
            assert resp.status_code == 404

    _run_async(scenario())


def test_first_message_preview(running_session_manager) -> None:
    """first_message_preview 来自 messages[0].content[:30]。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            # 直接改 session_manager 内部塞消息（绕过 send_message 真实流程）
            from bridge.session import ChatMessage
            session = session_manager._sessions[session_id]
            session.messages.append(
                ChatMessage(
                    role="user",
                    content="这是一条测试消息应该被截断到三十个字以内",
                )
            )

            list_resp = await client.get("/sessions")
            target = next(
                s for s in list_resp.json()["sessions"] if s["id"] == session_id
            )
            preview = target["first_message_preview"]
            assert len(preview) <= 30
            assert preview.startswith("这是一条测试消息")

    _run_async(scenario())


def test_list_includes_name_field(running_session_manager) -> None:
    """GET /sessions 返回的每个 session 都必须有 name 字段（默认 None）。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            list_resp = await client.get("/sessions")
            target = next(
                s for s in list_resp.json()["sessions"] if s["id"] == session_id
            )
            assert "name" in target
            assert target["name"] is None  # 默认未设置
            assert "first_message_preview" in target

    _run_async(scenario())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
