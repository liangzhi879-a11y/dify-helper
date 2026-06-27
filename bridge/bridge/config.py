"""Bridge configuration loading."""

from __future__ import annotations

import os

from pydantic import BaseModel


class BridgeConfig(BaseModel):
    claude_path: str = "claude"          # Claude Code CLI 可执行文件路径
    work_dir: str = "."                  # Claude Code 工作目录
    timeout: int = 600                   # 单任务超时秒数
    host: str = "0.0.0.0"
    port: int = 8000
    mcp_server_cmd: str = "python -m mcp_server"  # MCP server 启动命令
    max_concurrent: int = 1              # 最大并发任务数


def load_config(path: str = "config.yaml") -> BridgeConfig:
    """从 yaml 加载配置，文件不存在则返回默认值。"""
    if not os.path.exists(path):
        return BridgeConfig()

    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return BridgeConfig(**data)
