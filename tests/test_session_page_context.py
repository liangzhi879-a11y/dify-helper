"""★ 0.2.16: SendMessageRequest.page_context + _format_page_context_block 单元测试。

覆盖：
- pydantic round-trip（接受 page_context 字段）
- send_message 转发 page_context 到 _send_user_message（注入 stdin 内容）
- _format_page_context_block 防御性截断
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bridge.app import app, session_manager
from bridge.session import SendMessageRequest


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
    proc.stdout.readline = AsyncMock(return_value=b"")
    proc.stdout.at_eof = MagicMock(return_value=True)
    proc.stderr = MagicMock()
    proc.stderr.readline = AsyncMock(return_value=b"")
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    proc.returncode = 0
    return proc


# ==================== 单元测试 1: pydantic round-trip ====================


def test_send_message_request_accepts_page_context() -> None:
    """SendMessageRequest 应该接受可选 page_context dict，缺省时为 None。"""
    # 无 page_context
    req = SendMessageRequest(content="hello")
    assert req.page_context is None

    # 有 page_context
    ctx = {"url": "http://127.0.0.1/apps/abc", "title": "My App",
           "app_id": "abc", "capturedAt": "2026-07-04T00:00:00Z"}
    req2 = SendMessageRequest(content="hello", page_context=ctx)
    assert req2.page_context == ctx
    assert req2.content == "hello"


def test_send_message_request_extra_fields_ignored() -> None:
    """pydantic v2 默认 extra='ignore'，未知字段不报错（向后兼容旧 caller）。"""
    req = SendMessageRequest(content="hello", extra_unknown_field="ignored")
    assert req.content == "hello"
    assert not hasattr(req, "extra_unknown_field")


# ==================== 单元测试 2: send_message 转发 page_context ====================


@pytest.fixture
def running_session_manager():
    mock_proc = make_mock_proc()
    with patch(
        "bridge.session_manager.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        asyncio.run(session_manager.start())
        try:
            yield session_manager
        finally:
            try:
                asyncio.run(session_manager.stop())
            except Exception:
                pass


def _run_async(coro):
    return asyncio.run(coro)


def test_send_message_forwards_page_context_to_stdin(running_session_manager) -> None:
    """send_message 收到 page_context 后应作为 content block 前缀写入 stdin。

    同时验证 history 中只追加短标记 [page: TITLE]，避免历史膨胀。
    """

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            page_ctx = {
                "url": "http://127.0.0.1/apps/abc-uuid/workflow",
                "title": "Test App",
                "app_id": "abc-uuid",
                "capturedAt": "2026-07-04T00:00:00Z",
            }
            resp = await client.post(
                f"/sessions/{session_id}/messages",
                json={"content": "看看这个应用", "page_context": page_ctx},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["accepted"] is True

            # 验证 history 里最后一条 user message 包含 [page: Test App] 标记
            history_resp = await client.get(f"/sessions/{session_id}/history")
            messages = history_resp.json()["messages"]
            last = messages[-1]
            assert last["role"] == "user"
            assert "看看这个应用" in last["content"]
            assert "[page: Test App]" in last["content"]

            # 验证 stdin 写入的 JSON 包含 page context block + 用户原文
            session = session_manager._sessions[session_id]
            assert session.claude_proc is not None
            stdin_writes = session.claude_proc.stdin.write.call_args_list
            assert len(stdin_writes) >= 1
            stdin_payload = stdin_writes[-1].args[0]
            if isinstance(stdin_payload, bytes):
                stdin_payload = stdin_payload.decode("utf-8")
            parsed = json.loads(stdin_payload)
            content_blocks = parsed["message"]["content"]
            assert len(content_blocks) == 2
            assert "[Page context captured by Dify Helper / 0.2.16 plugin]" in content_blocks[0]["text"]
            assert "URL: http://127.0.0.1/apps/abc-uuid/workflow" in content_blocks[0]["text"]
            assert "Title: Test App" in content_blocks[0]["text"]
            assert "App ID: abc-uuid" in content_blocks[0]["text"]
            assert content_blocks[1]["text"] == "看看这个应用"

    _run_async(scenario())


def test_send_message_without_page_context_unchanged(running_session_manager) -> None:
    """没传 page_context 时，行为完全不变（单 block，content 仅用户原文）。"""

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            create_resp = await client.post("/sessions", json={})
            session_id = create_resp.json()["session_id"]

            resp = await client.post(
                f"/sessions/{session_id}/messages",
                json={"content": "纯文本消息"},
            )
            assert resp.status_code == 200

            # stdin 应该是单个 block
            session = session_manager._sessions[session_id]
            stdin_payload = session.claude_proc.stdin.write.call_args_list[-1].args[0]
            if isinstance(stdin_payload, bytes):
                stdin_payload = stdin_payload.decode("utf-8")
            parsed = json.loads(stdin_payload)
            content_blocks = parsed["message"]["content"]
            assert len(content_blocks) == 1
            assert content_blocks[0]["text"] == "纯文本消息"

            # history 也不应有 [page: ...] 标记
            history_resp = await client.get(f"/sessions/{session_id}/history")
            last = history_resp.json()["messages"][-1]
            assert "[page:" not in last["content"]

    _run_async(scenario())


# ==================== 单元测试 3: _format_page_context_block 截断 ====================


def test_format_page_context_block_truncates_long_fields() -> None:
    """_format_page_context_block 应截断超长字段（URL 200, title 120, app_id 64）。"""
    # URL 1000 字
    long_url = "http://example.com/" + ("x" * 1000)
    ctx = {"url": long_url, "title": "T" * 500, "app_id": "A" * 200}

    block = session_manager._format_page_context_block(ctx)

    # 截断后 URL 部分 ≤ 203 字符（含 "URL: " 前缀和 "…" 后缀）
    url_line = next(ln for ln in block.split("\n") if ln.startswith("URL: "))
    assert len(url_line) <= len("URL: ") + 200 + len("…")

    # title ≤ 120 + 前缀
    title_line = next(ln for ln in block.split("\n") if ln.startswith("Title: "))
    assert len(title_line) <= len("Title: ") + 120 + len("…")

    # app_id ≤ 64
    app_id_line = next(ln for ln in block.split("\n") if ln.startswith("App ID: "))
    assert len(app_id_line) <= len("App ID: ") + 64 + len("…")


def test_format_page_context_block_omits_missing_fields() -> None:
    """缺字段时整行 omit，不报 KeyError。"""
    ctx = {"url": "http://example.com"}  # 只有 url
    block = session_manager._format_page_context_block(ctx)
    assert "URL: http://example.com" in block
    assert "Title:" not in block
    assert "App ID:" not in block
    assert "Captured at:" not in block


def test_format_page_context_block_empty_dict() -> None:
    """空 dict 只生成 header 一行，不 crash。"""
    block = session_manager._format_page_context_block({})
    assert "[Page context captured by Dify Helper / 0.2.16 plugin]" in block
    # 只有 header 一行
    assert block.count("\n") == 0


def test_format_page_context_block_none_values_safe() -> None:
    """None 字段不 crash。"""
    ctx = {"url": None, "title": None, "app_id": None, "capturedAt": None}
    block = session_manager._format_page_context_block(ctx)
    assert "[Page context captured by Dify Helper / 0.2.16 plugin]" in block
    # 没有任何 "X: " 内容行
    assert "URL:" not in block
    assert "Title:" not in block


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))