"""FastAPI application: HTTP endpoints + worker lifespan management.

包含两套服务：
1. 一次性 headless 任务（POST /tasks + 轮询）：通过 Worker + TaskQueue
2. SSE 实时会话（POST /sessions + SSE 流）：通过 SessionManager
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# 启动时加载 mcp_server/.env，让 worker.py 能透传 DIFY_* 环境变量给 MCP server 子进程
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mcp_server", ".env")
    load_dotenv(_env_path, override=True)
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
    SessionListResponse,
)
from .session_manager import SessionManager
from .task_queue import TaskQueue
from .worker import Worker

# 单例：配置、任务队列、worker、session_manager
config = load_config("config.yaml")
task_queue = TaskQueue()
worker = Worker(task_queue, config)
session_manager = SessionManager(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时启动 worker + session_manager
    await worker.start()
    await session_manager.start()
    yield
    # 关闭时反向停止
    await session_manager.stop()
    await worker.stop()


app = FastAPI(title="Dify-Claude Bridge", version="0.2.0", lifespan=lifespan)

# CORS：允许 Dify 页面直接访问（Tampermonkey 用 GM_xmlhttpRequest 本可绕，加 CORS 更稳健）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://218.17.137.219:9980",
        "http://localhost:9980",
        "http://127.0.0.1:9980",
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


# ==================== 一次性任务端点（保留，Dify 插件用） ====================


@app.post("/tasks", response_model=TaskSubmitResponse)
async def submit_task(req: TaskSubmitRequest) -> TaskSubmitResponse:
    task = await task_queue.submit(req.task_description)
    return TaskSubmitResponse(task_id=task.id, status=task.status)


@app.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    task = await task_queue.get(task_id)
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
async def get_task_result(task_id: str) -> TaskResultResponse:
    task = await task_queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskResultResponse(
        status=task.status,
        result=task.result,
        error=task.error,
    )


# ==================== SSE 会话端点（新增，悬浮窗用） ====================


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """创建新会话，可选传入 initial_prompt 立即发送。"""
    try:
        session = await session_manager.create_session(req.initial_prompt)
        return CreateSessionResponse(session_id=session.id, status=session.status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to create session: {e}")


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    """列出所有活跃会话。"""
    sessions = await session_manager.list_sessions()
    return SessionListResponse(sessions=sessions)


@app.get("/sessions/{session_id}/events")
async def session_events(session_id: str):
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
    """
    async def event_generator():
        async for event in session_manager.get_events(session_id):
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


@app.post("/sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_message(session_id: str, req: SendMessageRequest) -> SendMessageResponse:
    """向会话发送消息。content 可以是普通文本或斜杠指令。

    返回 local_command=True 时表示是 bridge 本地指令（/reset /history 等），
    结果在 message 字段，无需监听 SSE 流。
    """
    result = await session_manager.send_message(session_id, req.content)
    return SendMessageResponse(
        accepted=result["accepted"],
        local_command=result["local_command"],
        message=result.get("message"),
    )


@app.delete("/sessions/{session_id}")
async def close_session(session_id: str) -> dict:
    """关闭会话。"""
    ok = await session_manager.close_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"closed": True, "session_id": session_id}


@app.post("/sessions/{session_id}/reset", response_model=CreateSessionResponse)
async def reset_session(session_id: str) -> CreateSessionResponse:
    """重置会话：销毁旧子进程，新建空白会话。"""
    new_session = await session_manager.reset_session(session_id)
    if new_session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return CreateSessionResponse(session_id=new_session.id, status=new_session.status)


@app.get("/sessions/{session_id}/export", response_model=SessionExportResponse)
async def export_session(session_id: str, format: str = "md") -> SessionExportResponse:
    """导出会话为 Markdown 或 JSON。"""
    content = await session_manager.export_session(session_id, format)
    if content is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionExportResponse(session_id=session_id, format=format, content=content)


@app.get("/sessions/{session_id}/history")
async def get_history(session_id: str) -> dict:
    """获取会话消息历史。"""
    history = await session_manager.get_history(session_id)
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


# ==================== 入口 ====================


def main() -> None:
    """入口：用 uvicorn 启动，从 config.yaml 读取配置。"""
    import uvicorn

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
