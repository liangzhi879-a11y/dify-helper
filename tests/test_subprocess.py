"""测试 asyncio.create_subprocess_exec 直接调用 claude CLI（跨平台）。
- Windows: claude.cmd（npm shim 在 PowerShell 路径下要加 .cmd）
- Linux/macOS: claude
"""
import asyncio
import os
import shutil
import sys


def resolve_claude() -> str:
    """跨平台解析 claude CLI 路径。"""
    if sys.platform == "win32":
        path = shutil.which("claude.cmd") or shutil.which("claude")
    else:
        path = shutil.which("claude")
    if not path:
        raise FileNotFoundError(
            "未找到 claude CLI，请先安装 Claude Code 并确保在 PATH 中"
        )
    return path


async def main():
    resolved = resolve_claude()
    print(f"resolved: {resolved}")
    print(f"exists: {os.path.exists(resolved)}")

    mcp_config = os.path.abspath(".mcp.json")
    print(f"mcp_config abs: {mcp_config}, exists: {os.path.exists(mcp_config)}")

    desc = "调用 dify_list_apps_summary 工具，告诉我应用总数。直接调用，无需请求权限。"
    cmd = [
        resolved,
        "-p", desc,
        "--mcp-config", mcp_config,
        "--permission-mode", "bypassPermissions",
        "--allow-dangerously-skip-permissions",
        "--output-format", "text",
        "--verbose",
    ]
    print(f"cmd: {cmd}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        print(f"returncode: {proc.returncode}")
        print(f"=== stdout (first 1500) ===")
        print(stdout.decode('utf-8', errors='replace')[:1500])
        print(f"=== stderr (first 2000) ===")
        print(stderr.decode('utf-8', errors='replace')[:2000])
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

asyncio.run(main())
