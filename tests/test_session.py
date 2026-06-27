"""SessionManager + SSE 端点单元测试。

不依赖真实 Claude Code CLI，用 mock 子进程验证流程。
ASGITransport 不触发 FastAPI lifespan，需手动启动 session_manager。

运行：python -m pytest tests/test_session.py -v
或：python tests/test_session.py
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bridge.app import app, session_manager


# ==================== Mock 工具 ====================


def make_mock_proc() -> MagicMock:
    """构造 mock Claude 子进程：stdin 可写、stdout 立即 EOF、kill/wait 为 noop。"""
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


@pytest.fixture
def mock_subprocess():
    """patch asyncio.create_subprocess_exec，避免启动真实 Claude CLI。"""
    mock_proc = make_mock_proc()
    with patch(
        "bridge.session_manager.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ) as mock_exec:
        yield mock_exec, mock_proc


@pytest.fixture
def running_session_manager(mock_subprocess):
    """启动 session_manager（已 mock 子进程），测试后停止。"""
    asyncio.run(session_manager.start())

    yield session_manager

    # 清理：停止管理器并清空所有会话
    try:
        asyncio.run(session_manager.stop())
    except Exception:
        pass


def async_test(coro_func):
    """简化异步测试包装。"""
    return asyncio.run(coro_func())


# ==================== 测试用例 ====================


def test_health_check():
    """1. 健康检查端点可用。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"

    asyncio.run(run())


def test_list_sessions_empty(running_session_manager):
    """2. 列出会话（初始为空或仅清理后）。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/sessions")
            assert resp.status_code == 200
            data = resp.json()
            assert "sessions" in data
            assert isinstance(data["sessions"], list)

    asyncio.run(run())


def test_create_session(running_session_manager):
    """3. 创建会话返回 session_id 和 status=idle。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/sessions", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert "session_id" in data
            assert data["status"] == "idle"
            assert len(data["session_id"]) > 0

    asyncio.run(run())


def test_send_message_nonexistent_session(running_session_manager):
    """4. 向不存在的会话发送消息返回 accepted=false。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/sessions/nonexistent-id/messages",
                json={"content": "hello"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["accepted"] is False
            assert data["local_command"] is False
            assert "not found" in data["message"].lower()

    asyncio.run(run())


def test_local_command_dify_help(running_session_manager):
    """5. 本地指令 /dify-help 返回帮助文本。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 先创建会话
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            # 发送 /dify-help
            resp = await client.post(
                f"/sessions/{session_id}/messages",
                json={"content": "/dify-help"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["accepted"] is True
            assert data["local_command"] is True
            assert data["message"] is not None
            # 帮助文本应含 Skill 关键字
            assert "Dify Helper" in data["message"] or "Skill" in data["message"]

    asyncio.run(run())


def test_tui_disabled_command(running_session_manager):
    """6. TUI 禁用指令 /rewind 返回提示。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            resp = await client.post(
                f"/sessions/{session_id}/messages",
                json={"content": "/rewind"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["accepted"] is False
            assert data["local_command"] is True
            assert "rewind" in data["message"]
            assert "交互式终端" in data["message"] or "terminal" in data["message"].lower()

    asyncio.run(run())


def test_export_nonexistent_session(running_session_manager):
    """7. 导出不存在的会话返回 404。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/sessions/nonexistent/export")
            assert resp.status_code == 404

    asyncio.run(run())


def test_close_nonexistent_session(running_session_manager):
    """8. 关闭不存在的会话返回 404。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/sessions/nonexistent")
            assert resp.status_code == 404

    asyncio.run(run())


def test_list_sessions_after_create(running_session_manager):
    """9. 创建会话后列出，能在列表中看到。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            list_resp = await client.get("/sessions")
            sessions = list_resp.json()["sessions"]
            ids = [s["id"] for s in sessions]
            assert session_id in ids

    asyncio.run(run())


def test_local_command_history(running_session_manager):
    """10. 本地指令 /history 返回消息历史（初始可能为空或含 system prompt）。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            resp = await client.post(
                f"/sessions/{session_id}/messages",
                json={"content": "/history"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["accepted"] is True
            assert data["local_command"] is True
            # /history 返回 JSON 数组字符串
            assert data["message"] is not None

    asyncio.run(run())


def test_dify_apps_endpoint(running_session_manager):
    """11. Dify 资源端点 /dify/apps 可达（可能返回 ok=false 因无凭据，但不应 500）。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/dify/apps")
            assert resp.status_code == 200
            data = resp.json()
            assert "ok" in data

    asyncio.run(run())


def test_close_session_after_create(running_session_manager):
    """12. 创建后关闭会话，再查应 404。"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            # 关闭
            del_resp = await client.delete(f"/sessions/{session_id}")
            assert del_resp.status_code == 200
            assert del_resp.json()["closed"] is True

            # 再次关闭应 404
            del_resp2 = await client.delete(f"/sessions/{session_id}")
            assert del_resp2.status_code == 404

    asyncio.run(run())


# ==================== 主入口 ====================


if __name__ == "__main__":
    # 手动运行：python tests/test_session.py
    import sys

    print("=" * 60)
    print("SessionManager 单元测试")
    print("=" * 60)

    # 测试 1：健康检查（不需要 session_manager）
    test_health_check()
    print("✓ test_health_check")

    # 需要手动管理 fixture
    with patch(
        "bridge.session_manager.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=make_mock_proc(),
    ):
        asyncio.run(session_manager.start())
        try:
            test_list_sessions_empty(running_session_manager=None)
            print("✓ test_list_sessions_empty")
        except Exception as e:
            print(f"✗ test_list_sessions_empty: {e}")

        try:
            test_create_session(running_session_manager=None)
            print("✓ test_create_session")
        except Exception as e:
            print(f"✗ test_create_session: {e}")

        try:
            test_send_message_nonexistent_session(running_session_manager=None)
            print("✓ test_send_message_nonexistent_session")
        except Exception as e:
            print(f"✗ test_send_message_nonexistent_session: {e}")

        try:
            test_local_command_dify_help(running_session_manager=None)
            print("✓ test_local_command_dify_help")
        except Exception as e:
            print(f"✗ test_local_command_dify_help: {e}")

        try:
            test_tui_disabled_command(running_session_manager=None)
            print("✓ test_tui_disabled_command")
        except Exception as e:
            print(f"✗ test_tui_disabled_command: {e}")

        try:
            test_export_nonexistent_session(running_session_manager=None)
            print("✓ test_export_nonexistent_session")
        except Exception as e:
            print(f"✗ test_export_nonexistent_session: {e}")

        try:
            test_close_nonexistent_session(running_session_manager=None)
            print("✓ test_close_nonexistent_session")
        except Exception as e:
            print(f"✗ test_close_nonexistent_session: {e}")

        try:
            test_list_sessions_after_create(running_session_manager=None)
            print("✓ test_list_sessions_after_create")
        except Exception as e:
            print(f"✗ test_list_sessions_after_create: {e}")

        try:
            test_local_command_history(running_session_manager=None)
            print("✓ test_local_command_history")
        except Exception as e:
            print(f"✗ test_local_command_history: {e}")

        try:
            test_dify_apps_endpoint(running_session_manager=None)
            print("✓ test_dify_apps_endpoint")
        except Exception as e:
            print(f"✗ test_dify_apps_endpoint: {e}")

        try:
            test_close_session_after_create(running_session_manager=None)
            print("✓ test_close_session_after_create")
        except Exception as e:
            print(f"✗ test_close_session_after_create: {e}")

        asyncio.run(session_manager.stop())

    print("=" * 60)
    print("单元测试完成")
    sys.exit(0)
