"""端到端测试：通过桥接服务让 Claude Code 创建知识库。

环境要求同 test_e2e_workflow.py
运行：python tests/test_e2e_dataset.py
"""
import httpx
import time
import sys
import os

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8001")
TASK_DESC = """你已经拥有所有 mcp__dify__* 工具的调用权限，无需请求授权，请直接调用工具完成以下任务：

在 Dify 中创建一个产品 FAQ 知识库：
1. 用 dify_create_dataset 创建数据集，名称为"E2E测试-产品FAQ"
2. 用 dify_add_document_by_text 添加一个文档，内容如下：
   Q: 产品支持哪些操作系统？
   A: 支持 Windows、macOS 和 Linux。
   Q: 如何获取技术支持？
   A: 可通过官网提交工单或发送邮件至 support@example.com。
3. 用 dify_get_indexing_status 查询索引状态，等待完成
4. 告诉我创建的 dataset_id 和 document_id"""

# submit_and_wait 函数同 test_e2e_workflow.py，复制过来
def submit_and_wait(description: str, timeout: int = 600) -> dict:
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{BRIDGE_URL}/tasks", json={"task_description": description})
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        print(f"任务已提交: {task_id}")
        start = time.time()
        while time.time() - start < timeout:
            resp = client.get(f"{BRIDGE_URL}/tasks/{task_id}/status")
            data = resp.json()
            status = data["status"]
            print(f"  状态: {status} (已用 {int(time.time()-start)}s)")
            if status in ("completed", "failed"):
                break
            time.sleep(5)
        resp = client.get(f"{BRIDGE_URL}/tasks/{task_id}/result")
        return resp.json()

if __name__ == "__main__":
    try:
        with httpx.Client(timeout=5) as c:
            c.get(f"{BRIDGE_URL}/health")
    except httpx.HTTPError:
        print(f"✗ 桥接服务未运行，请先启动")
        sys.exit(1)
    print("开始端到端测试：创建知识库")
    print("=" * 50)
    result = submit_and_wait(TASK_DESC)
    print("=" * 50)
    print(f"最终状态: {result['status']}")
    if result["status"] == "completed":
        print("✓ 任务完成，Claude Code 输出：")
        print(result.get("result", ""))
    else:
        print("✗ 任务失败：")
        print(result.get("error", "未知错误"))
