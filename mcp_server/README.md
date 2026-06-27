# Dify MCP Server

将 Dify Console API 封装为 MCP（Model Context Protocol）工具，供 Claude Code 调用，使 Claude Code 能直接在 Dify 中创建应用、编排工作流、管理知识库等。

## 功能

- 基于 `mcp` 官方 SDK（FastMCP）实现，通过 stdio 传输
- 封装 Dify Console API（`/console/api`），Bearer Token 认证
- HTTP 请求超时 30 秒，网络/服务端错误指数退避重试 3 次
- 统一错误处理：非 2xx 抛出 `DifyApiError(status_code, message, payload)`
- 工具组覆盖：App / Workflow / Dataset / Model / Workspace（Task 3 逐步补充）

## 安装

```bash
pip install -e ./mcp_server
```

## 配置

复制 `.env.example` 为 `.env`，填入 Dify 实例地址与 Personal Access Token：

```bash
cp mcp_server/.env.example mcp_server/.env
```

```env
DIFY_CONSOLE_BASE_URL=http://218.17.137.219:9980
DIFY_CONSOLE_TOKEN=your-personal-access-token-here
```

> Token 获取：登录 Dify → 个人设置 → Personal Access Token → 创建。

## 启动

```bash
python -m mcp_server
```

服务以 stdio 模式运行，等待 MCP 客户端连接，可按 `Ctrl+C` 退出。

## 在 Claude Code 中配置

### 方式一：命令行添加

```bash
claude mcp add dify -- python -m mcp_server
```

如需通过环境变量注入凭据：

```bash
claude mcp add dify \
  --env DIFY_CONSOLE_BASE_URL=http://218.17.137.219:9980 \
  --env DIFY_CONSOLE_TOKEN=<your-token> \
  -- python -m mcp_server
```

### 方式二：编辑配置文件

编辑 `~/.claude/claude_desktop_config.json`（或项目级 `.mcp.json`）：

```json
{
  "mcpServers": {
    "dify": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": {
        "DIFY_CONSOLE_BASE_URL": "http://218.17.137.219:9980",
        "DIFY_CONSOLE_TOKEN": "your-personal-access-token-here"
      }
    }
  }
}
```

配置后重启 Claude Code，使用 `claude mcp list` 即可查看已加载的 Dify 工具。
