"""端到端测试：通过 Bridge SSE 会话验证悬浮窗完整链路。

前置条件：
  1. Bridge 服务运行中（cd bridge && python -m bridge.app，监听 :8001）
  2. Claude Code CLI 已安装且模型已配置
  3. mcp_server/.env 配置真实 Dify 凭据
  4. Dify 实例可访问

运行：python tests/test_e2e_floating_window.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import httpx

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8001")


# ==================== 工具函数 ====================


def check_bridge_running() -> bool:
    """检查 bridge 服务是否运行。"""
    try:
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{BRIDGE_URL}/health")
            return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def create_session(client: httpx.Client, initial_prompt: str | None = None) -> str:
    """创建会话，返回 session_id。"""
    body = {"initial_prompt": initial_prompt} if initial_prompt else {}
    resp = client.post(f"{BRIDGE_URL}/sessions", json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()["session_id"]


def close_session(client: httpx.Client, session_id: str) -> None:
    """关闭会话（清理）。"""
    try:
        client.delete(f"{BRIDGE_URL}/sessions/{session_id}", timeout=10)
    except Exception:
        pass


def send_message(client: httpx.Client, session_id: str, content: str) -> dict:
    """发送消息，返回响应。"""
    resp = client.post(
        f"{BRIDGE_URL}/sessions/{session_id}/messages",
        json={"content": content},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def collect_sse_events(
    client: httpx.Client,
    session_id: str,
    timeout: int = 180,
) -> list[dict]:
    """收集 SSE 事件直到 result/error/session_closed。

    用 httpx 流式读取，按 \n\n 分割事件。
    """
    events: list[dict] = []
    try:
        with client.stream(
            "GET",
            f"{BRIDGE_URL}/sessions/{session_id}/events",
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        ) as resp:
            buffer = ""
            for chunk in resp.iter_text():
                buffer += chunk
                # 按 \n\n 分割事件
                while "\n\n" in buffer:
                    evt_str, buffer = buffer.split("\n\n", 1)
                    for line in evt_str.split("\n"):
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                events.append(data)
                                # 终止事件
                                if data.get("type") in (
                                    "result",
                                    "error",
                                    "session_closed",
                                ):
                                    return events
                            except json.JSONDecodeError:
                                continue
    except httpx.TimeoutException:
        pass
    except Exception as e:
        events.append({"type": "error", "message": f"SSE collection error: {e}"})
    return events


def send_and_collect(
    client: httpx.Client,
    session_id: str,
    content: str,
    timeout: int = 180,
) -> list[dict]:
    """并发发送消息并收集 SSE 事件。

    发送消息与读取 SSE 是两个并发请求：
    - 主线程发送 POST /messages
    - SSE 读取线程持续读流直到终止事件
    """
    events: list[dict] = []
    sse_done = threading.Event()
    sse_error: list[str] = []

    def read_sse():
        try:
            nonlocal events
            events = collect_sse_events(client, session_id, timeout=timeout)
        except Exception as e:
            sse_error.append(str(e))
        finally:
            sse_done.set()

    # 启动 SSE 读取线程（先于发送消息，避免丢失早期事件）
    sse_thread = threading.Thread(target=read_sse, daemon=True)
    sse_thread.start()

    # 等待一小段时间让 SSE 连接建立
    time.sleep(0.5)

    # 发送消息
    send_message(client, session_id, content)

    # 等待 SSE 完成
    sse_done.wait(timeout=timeout + 10)
    sse_thread.join(timeout=5)

    if sse_error:
        events.append({"type": "error", "message": "SSE thread error: " + "; ".join(sse_error)})

    return events


def find_event(events: list[dict], evt_type: str) -> dict | None:
    """在事件列表中查找指定类型的事件。"""
    for e in events:
        if e.get("type") == evt_type:
            return e
    return None


def find_tool_call(events: list[dict], tool_name_part: str) -> dict | None:
    """查找包含指定工具名的 tool_call 事件。"""
    for e in events:
        if e.get("type") == "tool_call":
            tool = e.get("tool", "") or ""
            if tool_name_part.lower() in tool.lower():
                return e
    return None


# ==================== 测试用例 ====================


def test_sse_simple_chat() -> bool:
    """测试 1：创建会话并发送简单消息，收集 SSE 流直到 result。"""
    print("\n[测试 1] SSE 简单对话")
    with httpx.Client(timeout=200) as client:
        session_id = create_session(client)
        print(f"  会话已创建: {session_id[:8]}...")
        try:
            events = send_and_collect(
                client,
                session_id,
                "你好，请用一句话介绍自己。不要调用任何工具。",
                timeout=120,
            )
            print(f"  收到 {len(events)} 个事件")
            print(f"  事件类型: {[e.get('type') for e in events]}")

            # 断言：收到至少一个 text_delta
            text_deltas = [e for e in events if e.get("type") == "text_delta"]
            if not text_deltas:
                print("  ✗ 未收到 text_delta 事件")
                return False
            print(f"  ✓ 收到 {len(text_deltas)} 个 text_delta")

            # 断言：收到 result 且 is_error=False
            result = find_event(events, "result")
            if result is None:
                print("  ✗ 未收到 result 事件")
                return False
            if result.get("is_error"):
                print(f"  ✗ result.is_error=True: {result.get('result', '')[:200]}")
                return False
            print(f"  ✓ result 收到，is_error=False")
            return True
        finally:
            close_session(client, session_id)


def test_local_command_help() -> bool:
    """测试 2：本地指令 /dify-help 通过 HTTP 返回。"""
    print("\n[测试 2] 本地指令 /dify-help")
    with httpx.Client(timeout=30) as client:
        session_id = create_session(client)
        print(f"  会话已创建: {session_id[:8]}...")
        try:
            resp = send_message(client, session_id, "/dify-help")
            print(f"  响应: accepted={resp.get('accepted')}, local_command={resp.get('local_command')}")

            if not resp.get("accepted"):
                print(f"  ✗ 指令未被接受: {resp.get('message')}")
                return False
            if not resp.get("local_command"):
                print("  ✗ 未识别为本地指令")
                return False
            msg = resp.get("message", "")
            if "Dify Helper" not in msg and "Skill" not in msg:
                print(f"  ✗ 帮助文本不含 Dify Helper/Skill: {msg[:200]}")
                return False
            print(f"  ✓ 帮助文本返回，含 Skill 关键字")
            return True
        finally:
            close_session(client, session_id)


def test_slash_reset() -> bool:
    """测试 3：斜杠指令 /reset 重置会话。"""
    print("\n[测试 3] /reset 重置会话")
    with httpx.Client(timeout=30) as client:
        session_id = create_session(client)
        print(f"  原会话: {session_id[:8]}...")
        try:
            resp = client.post(f"{BRIDGE_URL}/sessions/{session_id}/reset", timeout=30)
            resp.raise_for_status()
            new_session_id = resp.json()["session_id"]
            print(f"  新会话: {new_session_id[:8]}...")

            if new_session_id == session_id:
                print("  ✗ 新旧 session_id 相同")
                return False
            print(f"  ✓ 新 session_id 与原不同")
            # 清理新会话
            close_session(client, new_session_id)
            return True
        finally:
            # 原会话已被 reset 销毁，但仍尝试清理
            close_session(client, session_id)


def test_sse_create_app_via_mcp() -> bool:
    """测试 4：通过 SSE 会话调用 MCP 工具创建 Dify 应用。

    这是完整链路测试：悬浮窗 → Bridge SSE → Claude CLI → MCP → Dify。
    """
    print("\n[测试 4] SSE + MCP 创建 Dify 应用")
    app_name = f"E2E悬浮窗测试-{int(time.time())}"
    print(f"  目标应用名: {app_name}")

    with httpx.Client(timeout=300) as client:
        session_id = create_session(client)
        print(f"  会话已创建: {session_id[:8]}...")
        try:
            prompt = (
                f"请直接调用 dify_create_app 工具创建一个 chat 模式的应用，"
                f"名称为'{app_name}'，描述'E2E 测试'。不要询问，直接调用工具。"
            )
            events = send_and_collect(client, session_id, prompt, timeout=240)
            print(f"  收到 {len(events)} 个事件")
            print(f"  事件类型: {[e.get('type') for e in events]}")

            # 断言：收到 tool_call 且工具名含 dify_create_app
            tool_call = find_tool_call(events, "dify_create_app")
            if tool_call is None:
                # 也可能是 mcp__dify__dify_create_app
                tool_call = find_tool_call(events, "create_app")
            if tool_call is None:
                print("  ✗ 未收到 dify_create_app 工具调用事件")
                # 打印所有 tool_call 便于调试
                tool_calls = [e for e in events if e.get("type") == "tool_call"]
                for tc in tool_calls:
                    print(f"    tool_call: {tc.get('tool')}")
                return False
            print(f"  ✓ 收到 tool_call: {tool_call.get('tool')}")

            # 断言：收到 result 且 is_error=False
            result = find_event(events, "result")
            if result is None:
                print("  ✗ 未收到 result 事件")
                return False
            if result.get("is_error"):
                print(f"  ✗ result.is_error=True: {result.get('result', '')[:200]}")
                return False
            print(f"  ✓ result 收到，is_error=False")

            # 验证 Dify 应用列表是否含新应用（可选，需 Dify 可访问）
            try:
                apps_resp = client.get(f"{BRIDGE_URL}/dify/apps?limit=100", timeout=30)
                if apps_resp.status_code == 200:
                    apps_data = apps_resp.json()
                    if apps_data.get("ok") and apps_data.get("apps", {}).get("data"):
                        names = [a.get("name", "") for a in apps_data["apps"]["data"]]
                        if app_name in names:
                            print(f"  ✓ Dify 应用列表确认含 '{app_name}'")
                        else:
                            print(f"  ⚠ Dify 应用列表未找到 '{app_name}'（可能仍在创建中）")
            except Exception as e:
                print(f"  ⚠ 验证 Dify 应用列表失败: {e}")

            return True
        finally:
            close_session(client, session_id)


# ==================== 主入口 ====================


def main():
    print("=" * 60)
    print("悬浮窗 E2E 集成测试")
    print(f"Bridge URL: {BRIDGE_URL}")
    print("=" * 60)

    if not check_bridge_running():
        print(f"\n✗ Bridge 服务未运行，请先启动:")
        print(f"  cd bridge && python -m bridge.app")
        sys.exit(1)

    print("✓ Bridge 服务正常运行")

    results = []
    tests = [
        ("test_sse_simple_chat", test_sse_simple_chat),
        ("test_local_command_help", test_local_command_help),
        ("test_slash_reset", test_slash_reset),
        ("test_sse_create_app_via_mcp", test_sse_create_app_via_mcp),
    ]

    for name, func in tests:
        try:
            passed = func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n[异常] {name}: {type(e).__name__}: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passed_count = 0
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {name}")
        if passed:
            passed_count += 1
    print(f"\n{passed_count}/{len(results)} 通过")

    sys.exit(0 if passed_count == len(results) else 1)


if __name__ == "__main__":
    main()
