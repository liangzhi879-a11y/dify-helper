# Dify-Claude Bridge

本地桥接服务，连接 Dify（通过插件）与本地 Claude Code CLI。Dify Agent 通过插件向桥接服务提交任务，桥接服务在后台以 headless 模式调用 `claude -p` 执行，并注入 Dify MCP Server 配置，使 Claude Code 能直接在 Dify 中搭建 Agent / 工作流 / 知识库。

## 工作流程

```
Dify Agent → 插件(submit_task/query_status/get_result) → Bridge HTTP API → Worker → claude -p (headless) --mcp-config → Dify MCP Server → Dify Console API
```

## 安装

```bash
pip install -e ./bridge
```

## 配置

复制示例配置并按需修改：

```bash
cp config.example.yaml config.yaml
```

`config.yaml` 字段：

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| `claude_path` | Claude Code CLI 可执行文件路径 | `claude` |
| `work_dir` | Claude Code 工作目录 | `.` |
| `timeout` | 单任务超时秒数 | `600` |
| `host` | 桥接服务监听地址 | `0.0.0.0` |
| `port` | 桥接服务监听端口 | `8000` |
| `mcp_server_cmd` | MCP server 启动命令 | `python -m mcp_server` |
| `max_concurrent` | 最大并发任务数 | `1` |

### 环境变量

桥接服务会读取以下环境变量并透传给 Claude Code 的 MCP server 子进程：

- `DIFY_CONSOLE_BASE_URL`：Dify Console 地址
- `DIFY_CONSOLE_TOKEN`：Dify Console Bearer Token

## 启动

```bash
# 方式一：入口脚本
dify-bridge

# 方式二：uvicorn
uvicorn bridge.app:app --host 0.0.0.0 --port 8000
```

## HTTP 接口

- `GET /health` — 健康检查，返回 `{"status": "ok"}`
- `POST /tasks` — 提交任务，body：`{"task_description": "..."}`，返回 `{"task_id": "...", "status": "pending"}`
- `GET /tasks/{task_id}/status` — 查询任务状态
- `GET /tasks/{task_id}/result` — 查询任务结果
