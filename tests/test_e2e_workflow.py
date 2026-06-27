"""端到端测试：通过桥接服务让 Claude Code 创建 Dify 工作流。

需要完整环境：
  1. 桥接服务运行中（python -m bridge 或 dify-bridge）
  2. mcp_server/.env 配置真实 Dify 凭据
  3. Claude Code CLI 已安装且模型已配置
  4. Dify 实例可访问

运行：python tests/test_e2e_workflow.py
"""
import httpx
import time
import sys
import os

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8001")
TASK_DESC = """你已经拥有所有 mcp__dify__* 工具的调用权限，无需请求授权，请直接调用工具完成以下任务：

在 Dify 中创建一个简单的客服工作流应用：
1. 用 dify_create_app 创建一个 workflow 模式的应用，名称为"E2E测试-客服工作流"
2. 用 dify_update_workflow 配置工作流图：start 节点（接收 query 变量）→ LLM 节点（用已配置的模型回复）→ end 节点
3. 用 dify_publish_workflow 发布工作流
4. 用 dify_run_workflow_debug 用输入 {"query":"你好"} 调试运行一次
完成后告诉我创建的应用 ID。"""

def submit_and_wait(description: str, timeout: int = 600) -> dict:
    """提交任务并轮询直到完成。"""
    with httpx.Client(timeout=30) as client:
        # 提交
        resp = client.post(f"{BRIDGE_URL}/tasks", json={"task_description": description})
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        print(f"任务已提交: {task_id}")

        # 轮询
        start = time.time()
        while time.time() - start < timeout:
            resp = client.get(f"{BRIDGE_URL}/tasks/{task_id}/status")
            data = resp.json()
            status = data["status"]
            print(f"  状态: {status} (已用 {int(time.time()-start)}s)")
            if status in ("completed", "failed"):
                break
            time.sleep(5)

        # 获取结果
        resp = client.get(f"{BRIDGE_URL}/tasks/{task_id}/result")
        return resp.json()

if __name__ == "__main__":
    # 检查桥接服务
    try:
        with httpx.Client(timeout=5) as c:
            c.get(f"{BRIDGE_URL}/health")
    except httpx.HTTPError:
        print(f"✗ 桥接服务未运行，请先启动: cd bridge && dify-bridge")
        sys.exit(1)

    print("开始端到端测试：创建客服工作流")
    print("=" * 50)
    result = submit_and_wait(TASK_DESC)
    print("=" * 50)
    print(f"最终状态: {result['status']}")
    if result["status"] == "completed":
        print("✓ 任务完成，Claude Code 输出：")
        print(result.get("result", ""))
        print("\n请到 Dify 控制台确认是否出现了'E2E测试-客服工作流'应用")
    else:
        print("✗ 任务失败：")
        print(result.get("error", "未知错误"))
