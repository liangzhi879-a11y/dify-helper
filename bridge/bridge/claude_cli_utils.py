"""Claude Code CLI 调用共享工具函数。

供 Worker（一次性 headless 任务）和 SessionManager（流式会话）共用：
- write_mcp_config: 生成临时 MCP JSON，透传 DIFY_* 环境变量
- build_claude_command: 一次性 -p 模式命令（Windows .cmd 兼容）
- build_stream_json_command: stream-json 持久进程模式命令
- kill_process: 强制终止子进程
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile


def _resolve_claude_exec(claude_path: str) -> str:
    """解析 claude 可执行文件路径，Windows 上自动选择 .cmd 变体。

    shutil.which("claude") 在 Windows 上返回无扩展名的 Unix shell 脚本，
    asyncio.create_subprocess_exec 无法直接执行（WinError 193），
    需改用同名 .cmd 文件。
    """
    resolved = shutil.which(claude_path)
    claude_exec = resolved or claude_path

    if sys.platform == "win32":
        lower_exec = claude_exec.lower()
        if not lower_exec.endswith((".exe", ".cmd", ".bat", ".ps1")):
            cmd_variant = claude_exec + ".cmd"
            if os.path.exists(cmd_variant):
                claude_exec = cmd_variant

    return claude_exec


def write_mcp_config(mcp_server_cmd: str) -> str:
    """生成临时 MCP 配置 JSON 文件，返回文件路径。

    env 中的 DIFY_CONSOLE_BASE_URL / DIFY_CONSOLE_TOKEN 等从桥接服务
    环境变量透传给 Claude Code 的 MCP server 子进程。
    """
    cmd_parts = mcp_server_cmd.split()
    command = cmd_parts[0] if cmd_parts else "python"
    args = cmd_parts[1:] if len(cmd_parts) > 1 else ["-m", "mcp_server"]

    env: dict[str, str] = {}
    # 透传 Dify 1.14+ 认证所需的全部环境变量
    for key in (
        "DIFY_CONSOLE_BASE_URL",
        "DIFY_CONSOLE_TOKEN",      # access_token
        "DIFY_CSRF_TOKEN",
        "DIFY_REFRESH_TOKEN",
        "DIFY_SESSION_ID",
        "DIFY_EMAIL",
        "DIFY_PASSWORD",
    ):
        val = os.environ.get(key)
        if val:
            env[key] = val

    config = {
        "mcpServers": {
            "dify": {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }

    fd, path = tempfile.mkstemp(suffix=".json", prefix="dify_mcp_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return path


# ★ 0.2.7: 模式 → CLI flag 映射
# bypass（auto）用 bypassPermissions + allow-dangerously-skip-permissions 组合，
# 自动批准所有工具调用；plan 只输出规划；default 每次工具调用都需确认（headless
# 不推荐，会卡死）；acceptEdits 仅自动批准 Edit/Write。
_MODE_PERMISSION_FLAGS = {
    "bypass":      ["--permission-mode", "bypassPermissions",
                    "--allow-dangerously-skip-permissions"],
    "plan":        ["--permission-mode", "plan"],
    "default":     ["--permission-mode", "default"],
    "acceptEdits": ["--permission-mode", "acceptEdits"],
}


def _permission_flags_for(mode: str) -> list[str]:
    """根据 mode 返回对应的 CLI flag。未知 mode 降级到 bypass。"""
    return _MODE_PERMISSION_FLAGS.get(mode, _MODE_PERMISSION_FLAGS["bypass"])


def build_claude_command(
    claude_path: str,
    description: str,
    config_path: str,
    output_format: str = "text",
    mode: str = "bypass",                       # ★ 0.2.7
) -> list[str]:
    """构建一次性 -p 调用命令（headless 模式）。

    Windows 兼容 .cmd/.bat；batch 文件在换行符处截断参数，
    因此把 description 的换行替换为空格，变成单行传入。
    """
    claude_exec = _resolve_claude_exec(claude_path)

    # batch 文件在换行符处截断参数，把多行描述压成单行（换行→空格）
    single_line_desc = " ".join(description.split())

    cmd = [
        claude_exec,
        "-p", single_line_desc,
        "--mcp-config", config_path,
        *_permission_flags_for(mode),            # ★ 0.2.7
        "--output-format", output_format,
    ]

    return cmd


def build_stream_json_command(
    claude_path: str,
    config_path: str,
    mode: str = "bypass",                       # ★ 0.2.7
) -> list[str]:
    """构建 stream-json 持久进程命令（用于 SessionManager）。

    stream-json 模式：
    - 输入：stdin 写入 JSON 行 `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"..."}]}}`
    - 输出：stdout 输出 JSON 行，含 stream_event/assistant/result/system 等类型
    - --include-partial-messages: 启用 text_delta 流式增量

    用 stdbuf -oL -eL 包裹：claude CLI 是 Node 二进制，默认 stdout 是全缓冲（4KB 阈值），
    不到 4KB 不 flush。stdbuf 强制 line-buffered，让 text_delta 增量立即到达，
    避免用户"问进度才看到输出"的延迟感。
    """
    claude_exec = _resolve_claude_exec(claude_path)

    cmd = [
        claude_exec,
        "--mcp-config", config_path,
        *_permission_flags_for(mode),            # ★ 0.2.7
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]

    # 用 stdbuf 包裹（如果系统有）强制行缓冲。找不到 stdbuf 就直接返回原命令
    # （Windows / 容器环境可能没装 stdbuf）。
    if shutil.which("stdbuf"):
        return ["stdbuf", "-oL", "-eL", *cmd]
    return cmd


async def kill_process(proc: asyncio.subprocess.Process) -> None:
    """强制终止子进程。"""
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    try:
        await proc.wait()
    except Exception:
        pass
