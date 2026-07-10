"""Background worker that executes tasks via Claude Code CLI (headless)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

from .claude_cli_utils import (
    build_claude_command,
    kill_process,
    write_mcp_config,
)
from .config import BridgeConfig
from .models import Task, TaskStatus
from .task_queue import TaskQueue


class Worker:
    """后台 asyncio 任务：循环从队列取 pending 任务执行。"""

    def __init__(self, queue: TaskQueue, config: BridgeConfig) -> None:
        self._queue = queue
        self._config = config
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """启动 worker 循环。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """停止 worker 循环。"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                task = await self._queue.pick_pending()
                if task is None:
                    await asyncio.sleep(0.5)
                    continue
                await self._run_task(task)
            except asyncio.CancelledError:
                break
            except Exception:
                # 防止循环因意外异常退出
                await asyncio.sleep(0.5)

    async def _run_task(self, task: Task) -> None:
        # 1. 标记 running、started_at
        await self._queue.update(
            task.id,
            status=TaskStatus.running,
            started_at=datetime.now(),
        )

        config_path: str | None = None
        try:
            # 2. 生成临时 MCP 配置 JSON（复用共享函数）
            config_path = write_mcp_config(self._config.mcp_server_cmd)

            # 3. 构建 claude 命令（复用共享函数）
            cmd = build_claude_command(
                self._config.claude_path,
                task.description,
                config_path,
            )

            # 4. 启动子进程，工作目录设为 config.work_dir
            # 【模型锁定】强制注入 claude_env 环境变量
            proc_env = os.environ.copy()
            if self._config.claude_model:
                proc_env["ANTHROPIC_MODEL"] = self._config.claude_model
            for k, v in self._config.claude_env.items():
                proc_env[k] = v

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._config.work_dir,
                env=proc_env,
            )

            # 4. 用 asyncio.wait_for 包裹，超时则 kill 进程
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._config.timeout,
                )
            except asyncio.TimeoutError:
                await kill_process(proc)
                await self._queue.update(
                    task.id,
                    status=TaskStatus.failed,
                    error=f"task timed out after {self._config.timeout}s",
                    finished_at=datetime.now(),
                )
                return

            result_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            err_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            # 5. 成功：捕获 stdout 作为 result，标记 completed
            if proc.returncode == 0:
                await self._queue.update(
                    task.id,
                    status=TaskStatus.completed,
                    result=result_text,
                    finished_at=datetime.now(),
                )
            else:
                # 6. 失败：记录 error
                await self._queue.update(
                    task.id,
                    status=TaskStatus.failed,
                    error=err_text or f"claude exited with code {proc.returncode}",
                    result=result_text or None,
                    finished_at=datetime.now(),
                )
        except Exception as e:
            # 6. 异常标记 failed，记录 error
            await self._queue.update(
                task.id,
                status=TaskStatus.failed,
                error=f"{type(e).__name__}: {e}",
                finished_at=datetime.now(),
            )
        finally:
            # 清理临时 MCP 配置文件
            if config_path is not None:
                try:
                    os.unlink(config_path)
                except OSError:
                    pass
