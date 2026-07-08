"""Bridge configuration loading."""

from __future__ import annotations

import os

from pydantic import BaseModel, field_validator


class BridgeConfig(BaseModel):
    claude_path: str = "claude"          # Claude Code CLI 可执行文件路径
    work_dir: str = "."                  # Claude Code 工作目录
    timeout: int = 600                   # 单任务超时秒数
    host: str = "0.0.0.0"
    port: int = 8000
    mcp_server_cmd: str = "python -m mcp_server"  # MCP server 启动命令
    max_concurrent: int = 1              # 最大并发任务数
    # 【模型锁定】只能使用授权模型；空字符串表示跟随调用方环境变量
    claude_model: str = "MiniMax-M3"

    @field_validator("claude_model")
    @classmethod
    def _check_model_authorized(cls, v: str) -> str:
        """白名单校验：只允许已授权的模型。

        如需新增模型，先在此白名单登记并确认有对应 API 凭据。
        """
        if v == "":
            # 空字符串 = 不强制，透传 ANTHROPIC_MODEL 环境变量
            return v
        ALLOWED = {"MiniMax-M3"}
        if v not in ALLOWED:
            raise ValueError(
                f"模型 {v!r} 未授权！仅允许: {sorted(ALLOWED)}。"
                "新增模型需先确认 API 凭据可用，再修改此白名单。"
            )
        return v


def load_config(path: str = "config.yaml") -> BridgeConfig:
    """从 yaml 加载配置，文件不存在则返回默认值。"""
    if not os.path.exists(path):
        return BridgeConfig()

    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return BridgeConfig(**data)
