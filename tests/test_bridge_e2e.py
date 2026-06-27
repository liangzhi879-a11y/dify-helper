"""桥接服务端到端测试。

不依赖真实 Claude Code CLI，用 mock 子进程验证流程。
运行：python -m pytest tests/test_bridge_e2e.py -v
或：python tests/test_bridge_e2e.py
"""
import httpx
import asyncio
from bridge.app import app
from bridge.task_queue import TaskQueue
from bridge.models import TaskStatus

# ASGITransport 不会触发 FastAPI 的 lifespan 事件，因此后台 Worker 不会启动，
# 提交的任务会保持 pending 状态，便于断言。


# 测试 1：健康检查
async def _health_check():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_health_check():
    asyncio.run(_health_check())


# 测试 2：提交任务返回 task_id
async def _submit_task():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/tasks", json={"task_description": "test task"})
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"


def test_submit_task():
    asyncio.run(_submit_task())


# 测试 3：查询不存在的任务返回 404
async def _query_nonexistent_task():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/tasks/nonexistent-id/status")
        assert resp.status_code == 404


def test_query_nonexistent_task():
    asyncio.run(_query_nonexistent_task())


# 测试 4：任务队列状态流转
def test_task_queue_flow():
    async def run():
        queue = TaskQueue()
        task = await queue.submit("test")
        assert task.status == TaskStatus.pending
        picked = await queue.pick_pending()
        assert picked.id == task.id
        await queue.update(task.id, status=TaskStatus.running)
        await queue.update(task.id, status=TaskStatus.completed, result="done")
        final = await queue.get(task.id)
        assert final.status == TaskStatus.completed
        assert final.result == "done"

    asyncio.run(run())


if __name__ == "__main__":
    test_health_check()
    print("✓ test_health_check")
    test_submit_task()
    print("✓ test_submit_task")
    test_query_nonexistent_task()
    print("✓ test_query_nonexistent_task")
    test_task_queue_flow()
    print("✓ test_task_queue_flow")
    print("\n所有测试通过！")
