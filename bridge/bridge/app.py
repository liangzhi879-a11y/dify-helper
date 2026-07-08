"""FastAPI application: HTTP endpoints + worker lifespan management.

包含两套服务：
1. 一次性 headless 任务（POST /tasks + 轮询）：通过 Worker + TaskQueue
2. SSE 实时会话（POST /sessions + SSE 流）：通过 SessionManager
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import os
import re
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

# 启动时加载 mcp_server/.env，让 worker.py 能透传 DIFY_* 环境变量给 MCP server 子进程
# override=False（12-factor）：系统 env 优先（生产部署用），.env 仅作 dev 默认值
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mcp_server", ".env")
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

# v0.3.0: 加载 bridge/.env（BRIDGE_FINGERPRINT_SALT 等多用户隔离配置）
# bridge/.env 不与 mcp_server/.env 混用，保持职责清晰
# override=False：系统 env 优先（生产部署用 export BRIDGE_LEGACY_DISABLED=true 可覆盖 .env 默认 false）
try:
    from dotenv import load_dotenv as _load_bridge_env
    _bridge_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(_bridge_env):
        _load_bridge_env(_bridge_env, override=False)
except ImportError:
    pass

from .config import load_config
from .models import (
    TaskResultResponse,
    TaskStatusResponse,
    TaskSubmitRequest,
    TaskSubmitResponse,
)
from .session import (
    CreateSessionRequest,
    CreateSessionResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionExportResponse,
    SessionModeRequest,                    # ★ 0.2.7
    SessionListResponse,
    SessionStatus,
    RenameSessionRequest,                  # ★ 0.2.15
)
from .session_manager import SessionManager
from .sqlite_store import SqliteStore, init_store
from .task_queue import TaskQueue
from .worker import Worker

# 单例：配置、任务队列、worker、session_manager
config = load_config("config.yaml")
task_queue = TaskQueue()
worker = Worker(task_queue, config)
# v0.3.0 Phase 1: SessionManager 持有 store 引用，所有持久化操作走双写
# current_user_id Phase 1 暂用 LEGACY，Phase 2 改为从 Depends 注入
session_manager = SessionManager(
    config,
    store=None,  # 启动时 lifespan 调 init_store() 后再注入；此处为 None 是安全的（双写变 no-op）
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # v0.3.0: SQLite 持久化（多用户隔离 + 重启恢复）
    store = init_store()
    await store.init_db()
    print(f"[bridge] sqlite store ready: {store.db_path}")
    # v0.3.0 Phase 1: 把 store 注入 SessionManager 启用双写
    session_manager.set_store(store)
    # 启动时启动 worker + session_manager
    await worker.start()
    await session_manager.start()
    yield
    # 关闭时反向停止
    await session_manager.stop()
    await worker.stop()


app = FastAPI(title="Dify-Claude Bridge", version="0.2.0", lifespan=lifespan)

# CORS：允许 Dify 页面直接访问（Tampermonkey 用 GM_xmlhttpRequest 本可绕，加 CORS 更稳健）
# 注意：Dify 实际监听 nginx 80 端口，9980 是部署文档里的旧值
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # 本机 loopback
        "http://127.0.0.1",
        "http://localhost",
        # LAN IP（同网段其他电脑访问 Dify）
        "http://192.168.x.x",
        # 公网 IP（外网访问，需路由器配端口转发）
        "http://REDACTED_HOST",
        # 开发环境常见端口
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 健康检查 ====================


@app.get("/health")
async def health() -> dict:
    """健康检查，供插件校验凭据。"""
    return {"status": "ok", "version": "0.2.0"}


# ==================== v0.3.0 多用户隔离 ====================
# Phase 0 仅新增 /auth/whoami 端点，不改动任何业务端点；
# 老油猴（无 X-Bridge-* header）行为完全不变。

from .auth import get_current_user  # noqa: E402  (import after app def for Depends to work)
from .auth import UserContext as _UserContext  # noqa: E402
from .sqlite_store import SqliteStore as _SqliteStore  # noqa: E402
from .sqlite_store import get_store as _get_store  # noqa: E402


@app.get("/auth/whoami")
async def auth_whoami(
    request: Request,
    user: _UserContext = Depends(get_current_user),
    store: _SqliteStore = Depends(_get_store),
) -> dict:
    """返回当前 user 的身份信息 + 撞库候选。

    v0.3.0 新增：油猴启动时调一次，缓存 fingerprint + 检查 display_name 撞库。
    """
    collisions = await store.count_display_name_collisions(str(user.user_id))
    candidates = await store.list_collision_candidates(str(user.user_id))
    return {
        "user_id": str(user.user_id),
        "fingerprint": user.fingerprint,
        "display_name": user.display_name,
        "is_legacy": user.is_legacy,
        "ip": user.ip,
        "user_agent_preview": user.user_agent[:80],
        "accept_language": user.accept_language,
        "collisions": collisions,
        "candidates": candidates[:20],  # 至多返回 20 个候选避免响应过大
    }


# ==================== 一次性任务端点（保留，Dify 插件用） ====================


@app.post("/tasks", response_model=TaskSubmitResponse)
async def submit_task(
    req: TaskSubmitRequest,
    user: _UserContext = Depends(get_current_user),
) -> TaskSubmitResponse:
    """v0.3.0: 任务按 user 隔离，A 的 task B 看不到。"""
    task = await task_queue.submit(str(user.user_id), req.task_description)
    return TaskSubmitResponse(task_id=task.id, status=task.status)


@app.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    user: _UserContext = Depends(get_current_user),
) -> TaskStatusResponse:
    """v0.3.0: ownership 校验内置；越权返 404（不泄露存在性）。"""
    task = await task_queue.get(str(user.user_id), task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskStatusResponse(
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@app.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
async def get_task_result(
    task_id: str,
    user: _UserContext = Depends(get_current_user),
) -> TaskResultResponse:
    """v0.3.0: ownership 校验内置。"""
    task = await task_queue.get(str(user.user_id), task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskResultResponse(
        status=task.status,
        result=task.result,
        error=task.error,
    )


# ==================== SSE 会话端点（新增，悬浮窗用） ====================


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    req: CreateSessionRequest,
    user: _UserContext = Depends(get_current_user),
) -> CreateSessionResponse:
    """创建新会话，可选传入 initial_prompt 立即发送。

    ★ 0.2.7: 可选 req.mode 指定初始模式（不传则默认 "bypass"）。
    v0.3.0: 会话按 user 隔离，每 user 独立 dict namespace。
    """
    try:
        session = await session_manager.create_session(
            str(user.user_id),
            req.initial_prompt,
            mode=req.mode,
        )
        return CreateSessionResponse(
            session_id=session.id,
            status=session.status,
            mode=session.mode,                       # ★ 0.2.7
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to create session: {e}")


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user: _UserContext = Depends(get_current_user),
) -> SessionListResponse:
    """v0.3.0: 只列当前 user 的活跃会话（不再返回全 user）。"""
    sessions = await session_manager.list_sessions(str(user.user_id))
    return SessionListResponse(sessions=sessions)


@app.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
):
    """SSE 事件流。前端通过 EventSource 或 GM_xmlhttpRequest 订阅。

    事件类型：
    - text_delta: Claude 流式文本增量
    - thinking_delta: Claude 思考过程增量
    - assistant_complete: 完整 assistant 消息
    - tool_call: 工具调用开始
    - tool_result: 工具调用结果
    - result: 一次输入处理完成（前端可关闭流）
    - system: 系统信息
    - error: 错误
    - session_closed: 会话关闭
    - heartbeat: 心跳
    - raw: 未识别的原始输出

    v0.3.0: session 跨 user 不可见；越权时 generator 立即 yield 错误 + 关闭。
    """
    user_id = str(user.user_id)
    # 越权前置检查：避免 EventStore 内部 None 推断为「该 user 无 event」
    session = session_manager._sessions.get((user_id, session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    async def event_generator():
        async for event in session_manager.get_events(user_id, session_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx: 禁用缓冲
        },
    )


@app.get("/sessions/{session_id}/events/poll")
async def session_events_poll(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
    since: int = 0,
    max_wait: float = 1.0,
) -> dict:
    """HTTP 轮询端点（替代 SSE 给 Tampermonkey 等 SSE 不稳的客户端用）。

    Args:
        since: 客户端已收到的最大 event_id（0 = 取全部）
        max_wait: 没有新事件时最多等多少秒（避免空轮询压垮 server）

    Returns:
        {"events": [...], "last_event_id": N}
        每个 event 自带 "event_id" 字段（单调递增），客户端据此推进 since。

    v0.3.0: 越权返 404（不泄露存在性）。
    """
    # 越权前置检查：get_events_poll 对"session 不存在"和"无新事件"都返 []，
    # 必须显式校验 dict 存在性才能区分 404 vs 200-空列表
    user_id = str(user.user_id)
    if (user_id, session_id) not in session_manager._sessions:
        raise HTTPException(status_code=404, detail="session not found")
    events = await session_manager.get_events_poll(
        user_id, session_id, since_event_id=since, max_wait=max_wait
    )
    # 计算 last_event_id（取 events 中最大 event_id，若空则用 since）
    last_event_id = since
    for evt in events:
        eid = evt.get("event_id")
        if isinstance(eid, int) and eid > last_event_id:
            last_event_id = eid
    return {"events": events, "last_event_id": last_event_id}


@app.get("/sessions/{session_id}/status")
async def session_status(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
) -> dict:
    """只读状态端点：返回 session 实时状态，**不修改任何内部状态**。

    与 /events/poll 的区别：
    - /events/poll 通过 EventStore 返回事件流，会推进 last_event_id
    - /status 直接读 ChatSession 字段 + EventStore 最后一条，**只读**

    给客户端 UI 主动 progress 显示用（解决"用户不输入就看不到反馈"）。
    也给脚本端元指令拦截（"进度"/"?"）提供本地查询通道，**避免把元指令
    当 user prompt 发给 claude 导致复读**。

    Returns:
        session_id, status, is_processing, message_count,
        last_event_id, last_event (类型+preview), elapsed_seconds, claude_running

    v0.3.0: 越权返 404（dict key 改 (user_id, session_id)，跨 user 不可见）。
    """
    user_id = str(user.user_id)
    session = session_manager._sessions.get((user_id, session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # 取最近一条 event（只读，不推进 last_event_id）
    last_evt_dict: dict | None = None
    store = session.event_store
    if store is not None and store._events:
        eid, evt = store._events[-1]
        last_evt_dict = {
            "event_id": eid,
            "type": evt.get("type"),
            "tool": evt.get("tool"),
        }
        # 只在 text/thinking 类事件给 text preview（前 60 字）
        text_val = evt.get("text")
        if isinstance(text_val, str):
            last_evt_dict["text_preview"] = (
                text_val[:60] + ("..." if len(text_val) > 60 else "")
            )

    # claude 子进程是否还活着
    proc = session.claude_proc
    claude_running = (
        proc is not None and proc.returncode is None
    )

    return {
        "session_id": session.id,
        "status": session.status.value,
        "mode": session.mode,            # ★ 0.2.7
        "is_processing": session.status == SessionStatus.active,
        "message_count": len(session.messages),
        "last_event_id": session.last_event_id,
        "last_event": last_evt_dict,
        "elapsed_seconds": (
            datetime.now() - session.last_active_at
        ).total_seconds(),
        "claude_running": claude_running,
    }


@app.post("/sessions/{session_id}/mode")
async def set_session_mode(
    session_id: str,
    req: SessionModeRequest,
    user: _UserContext = Depends(get_current_user),
) -> dict:
    """★ 0.2.7: 切换 Claude 权限模式。

    mode ∈ {"plan", "bypass", "default", "acceptEdits"}
    切换会重启 Claude 子进程（保留 session_id + 历史消息）。

    v0.3.0: 越权返 404。
    """
    valid_modes = {"plan", "bypass", "default", "acceptEdits"}
    if req.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"unknown mode: {req.mode!r}, must be one of {sorted(valid_modes)}",
        )
    result = await session_manager.set_mode(str(user.user_id), session_id, req.mode)
    if not result.get("ok"):
        # 区分 404 (session not found) vs 500 (restart failed)
        if result.get("error") == "session not found":
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=500, detail=result.get("error", "unknown error"))
    return result


@app.post("/sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    user: _UserContext = Depends(get_current_user),
) -> SendMessageResponse:
    """向会话发送消息。content 可以是普通文本或斜杠指令。

    返回 local_command=True 时表示是 bridge 本地指令（/reset /history 等），
    结果在 message 字段，无需监听 SSE 流。

    v0.3.0: 越权返 404；per-user 队列保证 user 内串行、user 间并行。
    """
    result = await session_manager.send_message(
        str(user.user_id), session_id, req.content, req.page_context
    )
    if not result.get("accepted") and result.get("message") == "session not found":
        raise HTTPException(status_code=404, detail="session not found")
    return SendMessageResponse(
        accepted=result["accepted"],
        local_command=result["local_command"],
        message=result.get("message"),
    )


@app.post("/sessions/{session_id}/abort")
async def abort_session_endpoint(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
    timeout: float = 1.0,
) -> dict:
    """中断当前正在运行的 turn，但保留 session（不销毁）。

    流程：取消 read_loop → SIGINT graceful（默认 1 秒） → 超时则 SIGKILL
    → 状态切回 idle，partial text 入库。后续 send_message 会 lazy restart 子进程。

    Args:
        session_id: 会话 ID
        timeout: graceful 窗口（秒），超时则 SIGKILL hardkill

    Returns:
        {"aborted": bool, "method": "graceful"|"hardkill"|"none",
         "partial_text": str, "reason": str}

    v0.3.0: 越权返 404。
    """
    result = await session_manager.abort_session(str(user.user_id), session_id, timeout=timeout)
    return result


@app.delete("/sessions/{session_id}")
async def close_session(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
) -> dict:
    """关闭会话。v0.3.0: 越权返 404。"""
    ok = await session_manager.close_session(str(user.user_id), session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"closed": True, "session_id": session_id}


@app.post("/sessions/{session_id}/reset", response_model=CreateSessionResponse)
async def reset_session(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
) -> CreateSessionResponse:
    """重置会话：销毁旧子进程，新建空白会话（保留原 mode）。

    v0.3.0: 越权返 404。
    """
    new_session = await session_manager.reset_session(str(user.user_id), session_id)
    if new_session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return CreateSessionResponse(
        session_id=new_session.id,
        status=new_session.status,
        mode=new_session.mode,                  # ★ 0.2.7
    )


# ★ 0.2.15: PATCH /sessions/{id}/rename 重命名会话
# body: {"name": "..."} or {"name": null}（清空）
# 限长 100，超长返 400
@app.patch("/sessions/{session_id}/rename", response_model=SessionListResponse)
async def rename_session_endpoint(
    session_id: str,
    req: RenameSessionRequest,
    user: _UserContext = Depends(get_current_user),
) -> SessionListResponse:
    """重命名会话。None/空表示清空（UI 退到 first_message_preview）。

    v0.3.0: 越权返 404。
    """
    session = await session_manager.rename_session(
        str(user.user_id), session_id, req.name
    )
    if session is None:
        # 区分 404（会话不存在）和 400（name 超长）
        # rename_session 只在「会话存在但 name 非法」或「会话不存在」时返 None
        # 这里保守返 404 + 通用 message（前端通过 /sessions 列表兜底）
        raise HTTPException(status_code=404, detail="session not found or name invalid (max 100 chars)")
    return SessionListResponse(sessions=[session.to_public_dict()])


@app.get("/sessions/{session_id}/export", response_model=SessionExportResponse)
async def export_session(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
    format: str = "md",
) -> SessionExportResponse:
    """导出会话为 Markdown 或 JSON。v0.3.0: 越权返 404。"""
    content = await session_manager.export_session(str(user.user_id), session_id, format)
    if content is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionExportResponse(session_id=session_id, format=format, content=content)


@app.get("/sessions/{session_id}/history")
async def get_history(
    session_id: str,
    user: _UserContext = Depends(get_current_user),
) -> dict:
    """获取会话消息历史。v0.3.0: 越权返 404。"""
    history = await session_manager.get_history(str(user.user_id), session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": history}


# ==================== Dify 资源面板端点（透传 MCP 调用） ====================


@app.get("/dify/apps")
async def dify_list_apps(limit: int = 50) -> dict:
    """列出 Dify 应用，供资源面板展示。

    直接调用 Dify Console API（复用 mcp_server 的 DifyClient）。
    """
    try:
        from mcp_server.dify_client import DifyApiError, DifyClient
        # 复用 mcp_server/.env 的凭据
        client = DifyClient(
            base_url=os.environ.get("DIFY_CONSOLE_BASE_URL", ""),
            email=os.environ.get("DIFY_EMAIL") or None,
            password=os.environ.get("DIFY_PASSWORD") or None,
            csrf_token=os.environ.get("DIFY_CSRF_TOKEN") or None,
            refresh_token=os.environ.get("DIFY_REFRESH_TOKEN") or None,
            token=os.environ.get("DIFY_CONSOLE_TOKEN") or None,
        )
        result = await client.get("/apps", params={"page": 1, "limit": limit})
        return {"apps": result, "ok": True}
    except DifyApiError as e:
        return {"ok": False, "error": {"status": e.status_code, "message": e.message}}
    except Exception as e:
        return {"ok": False, "error": {"status": 500, "message": f"{type(e).__name__}: {e}"}}


@app.get("/dify/datasets")
async def dify_list_datasets(limit: int = 50) -> dict:
    """列出 Dify 知识库，供资源面板展示。"""
    try:
        from mcp_server.dify_client import DifyApiError, DifyClient
        client = DifyClient(
            base_url=os.environ.get("DIFY_CONSOLE_BASE_URL", ""),
            email=os.environ.get("DIFY_EMAIL") or None,
            password=os.environ.get("DIFY_PASSWORD") or None,
            csrf_token=os.environ.get("DIFY_CSRF_TOKEN") or None,
            refresh_token=os.environ.get("DIFY_REFRESH_TOKEN") or None,
            token=os.environ.get("DIFY_CONSOLE_TOKEN") or None,
        )
        result = await client.get("/datasets", params={"page": 1, "limit": limit})
        return {"datasets": result, "ok": True}
    except DifyApiError as e:
        return {"ok": False, "error": {"status": e.status_code, "message": e.message}}
    except Exception as e:
        return {"ok": False, "error": {"status": 500, "message": f"{type(e).__name__}: {e}"}}


# ==================== Phase C 诊断端点（4 个新增）====================
#
# 设计原则：
# 1. **/validate-dsl** 完全本地：纯 JSON schema 校验，不调 Dify 后端
# 2. **/diagnose/render-error** 调 Dify 拿 draft + 本地分析根因，列 hypothesis
# 3. **/diagnose/compare** 拿两个 app 的 draft 做结构 diff，定位差异节点
# 4. **/diagnose/node-schema** 离线 schema 缓存（与 MCP 的 dify_get_node_schema 同步）
#
# 跳过：POST /dify/screenshot（需要 puppeteer + Chromium，单独排期）

import re as _re

_UUID_V4_RE_BRIDGE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_NODE_SCHEMAS_BRIDGE: dict[str, dict] = {
    "start":               {"data_required": []},
    "end":                 {"data_required": []},
    "answer":              {"data_required": ["answer"]},
    "llm":                 {"data_required": ["model.provider", "model.name", "model.mode", "prompt_template"]},
    "knowledge-retrieval": {"data_required": ["dataset_ids", "query_variable_selector", "retrieval_mode"]},
    "loop":                {"data_required": ["start_node_id", "output_selector", "loop_variable"]},
    "iteration":           {"data_required": ["iterator_selector", "output_selector", "start_node_id"]},
    "if-else":             {"data_required": ["cases"]},
    "code":                {"data_required": ["code", "variables"]},
    "http-request":        {"data_required": ["url", "method"]},
}


def _validate_dsl_local(workflow: dict) -> dict:
    """本地工作流 JSON schema 校验（纯 Python，无 Dify 后端调用）。

    返回结构：
    {
      "valid": bool,
      "node_count": int, "edge_count": int,
      "error_count": int, "warning_count": int,
      "errors": [{"severity": "error"|"warning", "type": ..., "message": ..., ...}]
    }

    Dify 1.14+ 关键 quirk：
    - 顶层 node.type 永远是 "custom"，真实类型在 node.data.type
    - loop/iteration 的 children 是 dict {"nodes": [...]}，不是直接的 list
    """
    errors: list[dict] = []
    graph = workflow.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    def _real_type(node: dict) -> str:
        """从 node 提取真实类型（data.type > type > ''）。"""
        if not isinstance(node, dict):
            return ""
        data = node.get("data") or {}
        return (data.get("type") or node.get("type") or "").strip()

    # A：节点 ID 唯一性
    node_ids: list[str] = [n.get("id") for n in nodes if isinstance(n, dict)]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for nid in node_ids:
        if nid in seen:
            duplicates.add(nid)
        seen.add(nid)
    if duplicates:
        errors.append({
            "severity": "error",
            "type": "duplicate_node_id",
            "message": f"节点 ID 重复: {sorted(duplicates)}",
        })

    # B：边引用完整性
    node_id_set = set(node_ids)
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        eid = edge.get("id")
        if src and src not in node_id_set:
            errors.append({
                "severity": "error",
                "type": "edge_source_missing",
                "message": f"边 source={src!r} 指向不存在的节点",
                "edge_id": eid,
            })
        if tgt and tgt not in node_id_set:
            errors.append({
                "severity": "error",
                "type": "edge_target_missing",
                "message": f"边 target={tgt!r} 指向不存在的节点",
                "edge_id": eid,
            })

    # C：start 节点唯一（用 _real_type 查 data.type）
    start_nodes = [n for n in nodes if isinstance(n, dict) and _real_type(n) == "start"]
    if len(start_nodes) != 1:
        errors.append({
            "severity": "error",
            "type": "start_node_count",
            "message": f"start 节点应有且仅有 1 个，实际 {len(start_nodes)} 个",
        })

    # D：UUID 合法性（warning）
    conv_vars = workflow.get("conversation_variables") or []
    for var in conv_vars:
        if isinstance(var, dict):
            var_id = var.get("id", "")
            if not _UUID_V4_RE_BRIDGE.match(var_id):
                errors.append({
                    "severity": "warning",
                    "type": "invalid_uuid",
                    "message": f"conversation_variables.id 不是合法 UUID v4: {var_id!r}",
                    "var_name": var.get("name"),
                    "hint": "前端常容错，可能不是渲染错误的根因。建议先看 console 报错再决定是否改 UUID",
                })

    # E：节点必填字段（用 _real_type）
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = _real_type(node)
        schema = _NODE_SCHEMAS_BRIDGE.get(ntype)
        if not schema:
            continue
        data = node.get("data") or {}
        for path in schema.get("data_required", []):
            keys = path.split(".")
            current = data
            missing = False
            for k in keys:
                if not isinstance(current, dict) or k not in current:
                    missing = True
                    break
                v = current[k]
                if v is None or v == "" or v == []:
                    missing = True
                    break
                current = v
            if missing:
                errors.append({
                    "severity": "error",
                    "type": "missing_required_field",
                    "message": f"节点 {node.get('id')!r} ({ntype}) 缺少必填字段: {path}",
                    "node_id": node.get("id"),
                    "field": path,
                })

    # F：loop children 缺 positionAbsolute（Dify 1.14+ children 是 {"nodes":[...]}）
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _real_type(node) in ("loop", "iteration"):
            children_container = node.get("children") or {}
            if isinstance(children_container, dict):
                children = children_container.get("nodes") or []
            elif isinstance(children_container, list):
                children = children_container
            else:
                children = []
            for child in children:
                if isinstance(child, dict) and "positionAbsolute" not in child:
                    errors.append({
                        "severity": "warning",
                        "type": "loop_child_missing_position",
                        "message": f"loop/iteration 子节点缺 positionAbsolute 字段，可能导致渲染异常",
                        "parent_id": node.get("id"),
                        "child_id": child.get("id"),
                    })

    error_count = sum(1 for e in errors if e.get("severity") == "error")
    warning_count = sum(1 for e in errors if e.get("severity") == "warning")
    return {
        "valid": error_count == 0,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "error_count": error_count,
        "warning_count": warning_count,
        "errors": errors,
    }


def _build_dify_client():
    """构造 DifyClient，复用 mcp_server/.env 凭据（与其他 /dify/* 端点一致）。"""
    from mcp_server.dify_client import DifyClient
    return DifyClient(
        base_url=os.environ.get("DIFY_CONSOLE_BASE_URL", ""),
        email=os.environ.get("DIFY_EMAIL") or None,
        password=os.environ.get("DIFY_PASSWORD") or None,
        csrf_token=os.environ.get("DIFY_CSRF_TOKEN") or None,
        refresh_token=os.environ.get("DIFY_REFRESH_TOKEN") or None,
        token=os.environ.get("DIFY_CONSOLE_TOKEN") or None,
    )


@app.post("/validate-dsl")
async def validate_dsl_endpoint(payload: dict) -> dict:
    """本地 DSL 校验（不调 Dify 后端，可离线用）。

    Body:
        {
          "workflow": {...},   # 工作流 draft dict（直接从 dify_get_workflow 拿的）
          # 或
          "dsl_yaml": "..."   # YAML/JSON 字符串
        }

    Returns:
        {
          "valid": bool,
          "node_count": int, "edge_count": int,
          "error_count": int, "warning_count": int,
          "errors": [...],
          "source": "workflow_dict" | "yaml_string"
        }
    """
    try:
        if isinstance(payload, dict) and isinstance(payload.get("workflow"), dict):
            wf = payload["workflow"]
            source = "workflow_dict"
        elif isinstance(payload, dict) and isinstance(payload.get("dsl_yaml"), str):
            dsl_str = payload["dsl_yaml"]
            # 优先用 PyYAML；不可用则尝试 JSON
            try:
                import yaml  # type: ignore
                wf = yaml.safe_load(dsl_str)
            except ImportError:
                try:
                    wf = json.loads(dsl_str)
                except json.JSONDecodeError as e:
                    return {"ok": False, "error": {"status": 400, "message": f"无法解析 dsl_yaml（PyYAML 未装且 JSON 解析失败）: {e}"}}
            # DSL 标准格式可能有 app.workflow 嵌套；解开它
            if isinstance(wf, dict) and isinstance(wf.get("app"), dict):
                wf = wf["app"].get("workflow") or wf
            source = "yaml_string"
        else:
            return {"ok": False, "error": {"status": 400, "message": "payload 必须含 'workflow' (dict) 或 'dsl_yaml' (str)"}}
    except Exception as e:
        return {"ok": False, "error": {"status": 400, "message": f"{type(e).__name__}: {e}"}}

    result = _validate_dsl_local(wf)
    result["source"] = source
    result["ok"] = True
    return result


@app.get("/diagnose/render-error")
async def diagnose_render_error(app_id: str) -> dict:
    """自动化诊断 workflow canvas 渲染错误。

    工作流：
    1. 拿 app 元数据确认 mode（必须是 workflow / advanced-chat）
    2. 拿 draft workflow
    3. 本地校验（_validate_dsl_local）
    4. 列 ≥3 个根因假设（基于本地校验结果 + 历史经验）

    Args:
        app_id: Dify app ID

    Returns:
        {
          "ok": bool,
          "app_id": str,
          "mode": str,
          "validation": {...},
          "hypotheses": [
            {
              "rank": 1, "likelihood": "high"|"medium"|"low",
              "type": "...",
              "description": "...",
              "evidence": ["..."],
              "next_step": "<mcp__dify__XXX> ..."
            }
          ],
          "recommendation": "..."
        }
    """
    try:
        client = _build_dify_client()
        # 1. 拿 app 元数据
        try:
            app = await client.get(f"/apps/{app_id}")
        except Exception as e:
            return {"ok": False, "error": {"status": 500, "message": f"无法拿 app 元数据: {e}"}}

        mode = app.get("mode", "") if isinstance(app, dict) else ""
        if mode not in ("workflow", "advanced-chat"):
            return {
                "ok": False,
                "error": {
                    "status": 400,
                    "message": f"app mode={mode!r} 不是 workflow/advanced-chat，渲染错误不适用",
                },
            }

        # 2. 拿 draft workflow
        try:
            draft = await client.get(f"/apps/{app_id}/workflows/draft")
        except Exception as e:
            return {"ok": False, "error": {"status": 500, "message": f"无法拿 draft workflow: {e}"}}

        # 3. 本地校验
        validation = _validate_dsl_local(draft if isinstance(draft, dict) else {})

        # 4. 基于校验结果 + 历史经验列假设
        hypotheses: list[dict] = []

        # 假设 1：loop/iteration 字段缺失（最高频翻车）
        loop_errs = [e for e in validation["errors"] if e.get("type") == "missing_required_field" and "loop" in str(e.get("message", "")).lower()]
        if loop_errs:
            hypotheses.append({
                "rank": 1,
                "likelihood": "high",
                "type": "loop_iteration_missing_field",
                "description": f"loop/iteration 节点缺必填字段（{len(loop_errs)} 个错误）",
                "evidence": [e["message"] for e in loop_errs[:3]],
                "next_step": f"mcp__dify__dify_get_app_node(app_id='{app_id}', node_id='<err_node_id>') 看实际 data 字段，然后 mcp__dify__dify_update_workflow 1 个 1 个补",
            })

        # 假设 2：UUID 非法
        uuid_errs = [e for e in validation["errors"] if e.get("type") == "invalid_uuid"]
        if uuid_errs:
            hypotheses.append({
                "rank": 2,
                "likelihood": "medium",
                "type": "invalid_uuid",
                "description": f"conversation_variables.id 不是合法 UUID v4（{len(uuid_errs)} 个）",
                "evidence": [e["message"] for e in uuid_errs[:3]],
                "next_step": "先看 F12 console 报错：UUID 非法前端常容错，不是渲染错误的根因。如 console 报 UUID 相关才改。",
            })

        # 假设 3：边引用断裂
        edge_errs = [e for e in validation["errors"] if e.get("type") in ("edge_source_missing", "edge_target_missing")]
        if edge_errs:
            hypotheses.append({
                "rank": 3,
                "likelihood": "high",
                "type": "edge_reference_broken",
                "description": f"边的 source/target 指向不存在的节点（{len(edge_errs)} 个）",
                "evidence": [e["message"] for e in edge_errs[:3]],
                "next_step": f"用 dify_get_app_node 查 source/target 节点，看是被删除还是 ID 写错",
            })

        # 假设 4：start 节点异常
        if any(e.get("type") == "start_node_count" for e in validation["errors"]):
            hypotheses.append({
                "rank": 4,
                "likelihood": "high",
                "type": "start_node_abnormal",
                "description": "start 节点不是 1 个（缺失或重复）",
                "evidence": ["workflow 必须有且仅有 1 个 start 节点"],
                "next_step": "用 dify_get_workflow(detail='full') 看 nodes 列表，确认 start 节点数",
            })

        # 假设 5（兜底）：本地校验通过但仍渲染错 → 后端数据或前端 bug
        if validation["valid"]:
            hypotheses.append({
                "rank": 5,
                "likelihood": "medium",
                "type": "frontend_or_backend_render_bug",
                "description": "本地 JSON schema 校验通过但 canvas 仍渲染错 → 不是数据问题",
                "evidence": [f"error_count={validation['error_count']}, warning_count={validation['warning_count']}"],
                "next_step": "拿 F12 console 报错贴给 Claude；检查 Dify 后端版本（升级后渲染逻辑变化）；尝试硬刷新（Ctrl+Shift+R）",
            })

        # 推荐下一步
        if not hypotheses:
            recommendation = "本地校验完全通过且未发现常见根因。请用户从 F12 console 复制红字报错后再分析。"
        elif hypotheses[0]["likelihood"] == "high":
            recommendation = f"优先排查假设 #{hypotheses[0]['rank']}：{hypotheses[0]['description']}"
        else:
            recommendation = "本地校验无 fatal error。建议拿 F12 console 报错后再分析。"

        return {
            "ok": True,
            "app_id": app_id,
            "mode": mode,
            "validation": validation,
            "hypotheses": hypotheses,
            "recommendation": recommendation,
        }
    except Exception as e:
        return {"ok": False, "error": {"status": 500, "message": f"{type(e).__name__}: {e}"}}


@app.post("/diagnose/compare")
async def diagnose_compare(payload: dict) -> dict:
    """对比两个 app 的 workflow 结构，定位差异节点（用于复刻工作流或定位差异 bug）。

    Body:
        { "app_id_a": "...", "app_id_b": "..." }

    Returns:
        {
          "ok": bool,
          "diff": {
            "only_in_a": {"node_ids": [...], "edge_ids": [...]},
            "only_in_b": {"node_ids": [...], "edge_ids": [...]},
            "common_node_ids": [...],
            "diff_summary": "...",
          },
          "validation_a": {...},
          "validation_b": {...}
        }
    """
    try:
        app_id_a = payload.get("app_id_a") if isinstance(payload, dict) else None
        app_id_b = payload.get("app_id_b") if isinstance(payload, dict) else None
        if not app_id_a or not app_id_b:
            return {"ok": False, "error": {"status": 400, "message": "payload 必须含 app_id_a 和 app_id_b"}}

        client = _build_dify_client()
        try:
            wf_a = await client.get(f"/apps/{app_id_a}/workflows/draft")
            wf_b = await client.get(f"/apps/{app_id_b}/workflows/draft")
        except Exception as e:
            return {"ok": False, "error": {"status": 500, "message": f"无法拿 draft workflow: {e}"}}

        # 提取 nodes/edges
        graph_a = (wf_a.get("graph") if isinstance(wf_a, dict) else None) or {}
        graph_b = (wf_b.get("graph") if isinstance(wf_b, dict) else None) or {}
        nodes_a = graph_a.get("nodes") or []
        nodes_b = graph_b.get("nodes") or []
        edges_a = graph_a.get("edges") or []
        edges_b = graph_b.get("edges") or []

        ids_a = {n.get("id") for n in nodes_a if isinstance(n, dict) and n.get("id")}
        ids_b = {n.get("id") for n in nodes_b if isinstance(n, dict) and n.get("id")}
        edge_ids_a = {e.get("id") for e in edges_a if isinstance(e, dict) and e.get("id")}
        edge_ids_b = {e.get("id") for e in edges_b if isinstance(e, dict) and e.get("id")}

        only_a = ids_a - ids_b
        only_b = ids_b - ids_a
        common = ids_a & ids_b

        # 对 common 节点做字段 diff
        node_diff: list[dict] = []
        nodes_a_map = {n.get("id"): n for n in nodes_a if isinstance(n, dict)}
        nodes_b_map = {n.get("id"): n for n in nodes_b if isinstance(n, dict)}
        for nid in common:
            na = nodes_a_map[nid]
            nb = nodes_b_map[nid]
            if na != nb:
                # 简化：只记关键字段差异（type / data 内的字符串字段）
                data_a = na.get("data") or {}
                data_b = nb.get("data") or {}
                if data_a != data_b:
                    node_diff.append({
                        "node_id": nid,
                        "type": na.get("type"),
                        "diff_keys": list(
                            (set(data_a.keys()) | set(data_b.keys())) -
                            (set(data_a.keys()) & set(data_b.keys()))
                        )[:20],
                        "data_size_a": len(json.dumps(data_a, ensure_ascii=False)),
                        "data_size_b": len(json.dumps(data_b, ensure_ascii=False)),
                    })

        diff_summary = (
            f"A 有 {len(nodes_a)} 节点 / {len(edges_a)} 边，"
            f"B 有 {len(nodes_b)} 节点 / {len(edges_b)} 边。"
            f"差异：{len(only_a)} 节点仅在 A，{len(only_b)} 节点仅在 B，"
            f"{len(node_diff)} 共同节点 data 字段有差异。"
        )

        # 顺便校验两边
        validation_a = _validate_dsl_local(wf_a if isinstance(wf_a, dict) else {})
        validation_b = _validate_dsl_local(wf_b if isinstance(wf_b, dict) else {})

        return {
            "ok": True,
            "diff": {
                "only_in_a": {"node_ids": sorted(only_a), "edge_ids": sorted(edge_ids_a - edge_ids_b)},
                "only_in_b": {"node_ids": sorted(only_b), "edge_ids": sorted(edge_ids_b - edge_ids_a)},
                "common_node_ids": sorted(common),
                "common_node_data_diff": node_diff,
                "diff_summary": diff_summary,
            },
            "validation_a": validation_a,
            "validation_b": validation_b,
        }
    except Exception as e:
        return {"ok": False, "error": {"status": 500, "message": f"{type(e).__name__}: {e}"}}


@app.get("/diagnose/node-schema")
async def diagnose_node_schema(type: str = "") -> dict:
    """离线节点类型必填字段查询（与 MCP 的 dify_get_node_schema 同步）。

    Args:
        type: 节点类型（llm/loop/iteration/if-else 等），空=列出所有支持类型

    Returns:
        { "ok": bool, "node_type": str, "supported": bool, "schema": {...}, "supported_types": [...] }
    """
    if not type:
        return {
            "ok": True,
            "node_type": "",
            "supported": False,
            "supported_types": list(_NODE_SCHEMAS_BRIDGE.keys()),
            "hint": "传 ?type=loop 查 loop 节点的必填字段",
        }

    schema = _NODE_SCHEMAS_BRIDGE.get(type)
    if not schema:
        return {
            "ok": True,
            "node_type": type,
            "supported": False,
            "supported_types": list(_NODE_SCHEMAS_BRIDGE.keys()),
            "suggestion": f"类型 {type!r} 未在本地缓存。建议 mcp__dify__dify_get_app_node(app_id, node_id) 看实际节点的 data 字段。",
        }

    return {
        "ok": True,
        "node_type": type,
        "supported": True,
        "schema": schema,
        "note": "本地缓存，Dify 实际后端可能略有差异。",
    }


# ==================== DocHub 文档下载 Portal ====================
# 复用 bridge 服务（port 8002）提供友好的文档浏览/下载界面。
# 移动设备浏览器：打开 http://<host-ip>:8002/dochub/portal 即可看到所有生成的 docx 列表 + 下载按钮。
# 实现：用 docker exec 列 DocHub 容器 /app/data/generated/tenant_default/；
#      下载用 httpx 流式转发，39MB 文件不读入内存。
# 关联：memory/dochub-file-download-lan-and-external.md

DOCHUB_CONTAINER = "dochub-app"
DOCHUB_API_BASE = "http://127.0.0.1:8088"  # host 端口映射 8088→container 8080
DOCHUB_API_KEY = "dk_default_test_key"     # docker-compose 默认 key
DOCHUB_INTERNAL_DIR = "/app/data/generated/tenant_default"


async def _dochub_list_files_raw() -> list[dict]:
    """列 DocHub 容器 /app/data/generated/tenant_default/ 下的 docx 文件。"""
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", DOCHUB_CONTAINER, "ls", "-la", DOCHUB_INTERNAL_DIR + "/",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        return []
    if proc.returncode != 0:
        return []
    files: list[dict] = []
    for line in stdout.decode().splitlines()[3:]:  # 跳过 total / . / ..
        parts = line.split(None, 8)
        if len(parts) < 9 or not parts[8].endswith(".docx"):
            continue
        size = int(parts[4])
        # parts[5..7] = 月 日 时:分 (当年省略)
        files.append(
            {
                "filename": parts[8],
                "size_kb": round(size / 1024, 1),
                "mtime": f"{parts[5]} {parts[6]} {parts[7]}",
            }
        )
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files


@app.get("/dochub/portal", response_class=HTMLResponse)
async def dochub_portal() -> HTMLResponse:
    """移动设备友好的 HTML 列表页面，点文件名直接下载。"""
    files = await _dochub_list_files_raw()
    rows = "\n".join(
        f'<tr><td><a href="/dochub/files/{urllib.parse.quote(f["filename"])}" download>'
        f'{html.escape(f["filename"])}</a></td>'
        f'<td class="num">{f["size_kb"]:.1f} KB</td>'
        f'<td>{html.escape(f["mtime"])}</td></tr>'
        for f in files
    )
    if not rows:
        rows = '<tr><td colspan="3" style="text-align:center;color:#999">暂无文档</td></tr>'
    body = f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DocHub 文档下载</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;margin:0;padding:16px;background:#f5f5f7;color:#1c1c1e}}
h1{{font-size:18px;margin:0 0 4px}}
.meta{{color:#8e8e93;font-size:12px;margin-bottom:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #f0f0f0;font-size:14px}}
th{{background:#fafafa;font-weight:600;color:#6e6e73;font-size:12px}}
tr:last-child td{{border-bottom:none}}
td.num{{color:#6e6e73;white-space:nowrap}}
a{{color:#007aff;text-decoration:none}}
a:hover{{text-decoration:underline}}
.footer{{margin-top:16px;font-size:11px;color:#b0b0b5;text-align:center}}
</style>
</head>
<body>
<h1>📑 DocHub 文档下载</h1>
<div class="meta">{len(files)} 个文档 · 按时间倒序 · 点文件名下载</div>
<table>
<thead><tr><th>文件名</th><th>大小</th><th>生成时间</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<div class="footer">bridge service · /dochub/portal</div>
</body>
</html>"""
    return HTMLResponse(body)


@app.get("/dochub/files")
async def dochub_list_files_json() -> dict:
    """JSON 文件列表。"""
    files = await _dochub_list_files_raw()
    return {"count": len(files), "files": files}


@app.get("/dochub/files/{filename}")
async def dochub_download_file(filename: str) -> StreamingResponse:
    """代理下载指定 docx 文件（流式转发，不读入内存）。"""
    # 安全检查：filename 只允许字母数字 + ._- 且必须 .docx 后缀，防止路径穿越
    if not re.match(r"^[A-Za-z0-9_\-\.]+\.docx$", filename):
        raise HTTPException(status_code=400, detail="filename 非法（仅允许字母数字下划线点和 .docx 后缀）")
    internal_path = f"{DOCHUB_INTERNAL_DIR}/{filename}"
    encoded = base64.b64encode(internal_path.encode()).decode()

    async def stream():
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream(
                "GET",
                f"{DOCHUB_API_BASE}/api/v1/files/download",
                params={"path": encoded},
                headers={"X-API-Key": DOCHUB_API_KEY},
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(64 * 1024):
                    yield chunk

    return StreamingResponse(
        stream(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==================== 入口 ====================


def main() -> None:
    """入口：用 uvicorn 启动，从 config.yaml 读取配置。"""
    import uvicorn

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
