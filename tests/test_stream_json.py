"""测试 Claude Code CLI 的 stream-json 模式，了解输入输出格式。

stream-json 模式：
- 输入：从 stdin 读 JSON 行（每行一个 JSON 对象）
- 输出：向 stdout 写 JSON 行（流式消息）
"""
import asyncio
import json
import os
import shutil

async def main():
    claude_exec = shutil.which("claude") + ".cmd"
    mcp_config = os.path.abspath(".mcp.json")

    cmd = [
        claude_exec,
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--mcp-config", mcp_config,
        "--permission-mode", "bypassPermissions",
        "--allow-dangerously-skip-permissions",
        "--verbose",
    ]
    print(f"cmd: {cmd[:3]}...")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.getcwd(),
    )

    # 发送一条用户消息
    user_msg = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "调用 dify_list_apps_summary 工具，告诉我应用总数。直接调用无需请求权限。"}]
        }
    }
    proc.stdin.write((json.dumps(user_msg) + "\n").encode())
    await proc.stdin.drain()

    # 读取流式输出（限时 60 秒）
    lines = []
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=60)
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                lines.append(decoded)
                # 尝试解析 JSON 并打印 type
                try:
                    obj = json.loads(decoded)
                    msg_type = obj.get("type", "?")
                    # 截取部分内容显示
                    preview = json.dumps(obj, ensure_ascii=False)[:300]
                    print(f"[{msg_type}] {preview}")
                except json.JSONDecodeError:
                    print(f"[raw] {decoded[:200]}")
            # 收到 result 类型表示结束
            try:
                obj = json.loads(decoded)
                if obj.get("type") == "result":
                    break
            except Exception:
                pass
    except asyncio.TimeoutError:
        print("(60s timeout)")

    # 关闭 stdin 结束进程
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()

    print(f"\n=== 共收到 {len(lines)} 行 ===")
    # 打印 stderr
    stderr = await proc.stderr.read()
    if stderr:
        print(f"stderr: {stderr.decode('utf-8', errors='replace')[:500]}")

asyncio.run(main())
