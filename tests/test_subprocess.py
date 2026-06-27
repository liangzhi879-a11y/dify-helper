"""测试 asyncio.create_subprocess_exec 直接调用 claude.cmd（不用 cmd /c）。"""
import asyncio
import os
import shutil
import sys

async def main():
    resolved = shutil.which("claude")
    print(f"resolved: {resolved}")
    cmd_variant = resolved + ".cmd"
    print(f"cmd_variant exists: {os.path.exists(cmd_variant)}")

    mcp_config = os.path.abspath(".mcp.json")
    print(f"mcp_config abs: {mcp_config}, exists: {os.path.exists(mcp_config)}")

    desc = "调用 dify_list_apps_summary 工具，告诉我应用总数。直接调用，无需请求权限。"
    cmd = [
        cmd_variant,
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
