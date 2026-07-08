# Dify Helper 部署运维文档

> 本文档描述如何将 Dify Helper（Bridge + MCP Server + Tampermonkey 悬浮窗）部署到服务器，使 Dify 实例页面内可直接与 Claude Code 实时对话。

---

## 一、前置条件

### 服务器环境
- **操作系统**：Linux（推荐 Ubuntu 22.04+）或 Windows Server
- **Python**：3.10+（推荐 3.12）
- **Node.js**：18+（Dify 实例本身需要）
- **网络**：Dify 实例（http://REDACTED_HOST:9980）可达
- **端口**：8001（Bridge 服务）需对外开放

### Claude Code CLI
- **版本**：v2.1.187+
- **模型配置**：已通过 `claude` 命令登录并配置可用模型（如 Claude Sonnet 4.5）
- **验证**：`claude --version` 能正常输出

### Dify 实例
- **版本**：1.14.2+
- **访问**：http://REDACTED_HOST:9980 可达
- **凭据**：有效邮箱密码（REDACTED_EMAIL@example.com）
- **验证**：浏览器能登录并看到应用列表

### 浏览器侧
- **Tampermonkey 扩展**：Chrome/Edge/Firefox 已安装
- **版本**：Tampermonkey 4.x+

---

## 二、代码同步

### 方式 A：git clone（推荐）
```bash
# 假设项目已推送到 git 仓库
cd /opt
git clone <repo-url> dify-helper
cd dify-helper
```

### 方式 B：rsync 同步
```bash
# 从开发机同步到服务器
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  "d:/Dify Helper/" user@REDACTED_HOST:/opt/dify-helper/
```

### 方式 C：scp 打包传输
```bash
# 开发机打包
cd "d:/Dify Helper"
tar -czf dify-helper.tar.gz --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' .

# 传输
scp dify-helper.tar.gz user@REDACTED_HOST:/opt/

# 服务器解压
ssh user@REDACTED_HOST
cd /opt
mkdir -p dify-helper && cd dify-helper
tar -xzf /opt/dify-helper.tar.gz
```

---

## 三、依赖安装

### 3.1 创建虚拟环境
```bash
cd /opt/dify-helper
python3 -m venv .venv
source .venv/bin/activate  # Linux
# 或 .venv\Scripts\activate  # Windows
```

### 3.2 安装 Bridge 依赖
```bash
pip install -e bridge/
```

### 3.3 安装 MCP Server 依赖
```bash
pip install -e mcp_server/
```

### 3.4 验证安装
```bash
python -c "from bridge.app import app; print('bridge ok')"
python -c "from mcp_server.server import mcp; print('mcp ok')"
```

---

## 四、配置文件

### 4.1 mcp_server/.env
```ini
DIFY_CONSOLE_BASE_URL=http://REDACTED_HOST:9980
DIFY_EMAIL=REDACTED_EMAIL@example.com
DIFY_PASSWORD=<base64编码后的密码>
# 或直接用 token（可选）
# DIFY_CONSOLE_TOKEN=<access_token>
# DIFY_CSRF_TOKEN=<csrf_token>
# DIFY_REFRESH_TOKEN=<refresh_token>
```

> 密码需 base64 编码：`echo -n 'your_password' | base64`

### 4.2 bridge/config.yaml
```yaml
claude_path: claude          # Claude CLI 可执行文件路径
work_dir: /opt/dify-helper   # Claude Code 工作目录
timeout: 1200                # 单任务超时（秒），调试运行/索引较慢
host: 0.0.0.0                # 监听所有网卡（生产环境）
port: 8001                   # Bridge 端口
mcp_server_cmd: python -m mcp_server
max_concurrent: 1            # 一次性任务并发数（SSE 会话不受此限）
```

### 4.3 验证配置
```bash
# 验证 Dify 认证
python tests/test_auth.py

# 预期：返回 35+ 个应用
```

---

## 五、启动 Bridge 服务

### 5.1 前台调试
```bash
cd /opt/dify-helper/bridge
python -m bridge.app
```

预期输出：
```
[SessionManager] started, skills loaded: 5234 chars
[Worker] started
INFO:     Uvicorn running on http://0.0.0.0:8001
```

### 5.2 健康检查
```bash
curl http://localhost:8001/health
# 预期：{"status":"ok","version":"0.2.0"}
```

### 5.3 SSE 端点验证
```bash
# 创建会话
curl -X POST http://localhost:8001/sessions -H "Content-Type: application/json" -d '{}'
# 预期：{"session_id":"...","status":"idle"}

# 列出会话
curl http://localhost:8001/sessions
# 预期：{"sessions":[...]}
```

---

## 六、防火墙开放端口

### Ubuntu/Debian（ufw）
```bash
sudo ufw allow 8001/tcp
sudo ufw reload
```

### CentOS/RHEL（firewalld）
```bash
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --reload
```

### Windows
```powershell
netsh advfirewall firewall add rule name="Dify Bridge 8001" dir=in action=allow protocol=TCP localport=8001
```

### 云服务器安全组
- 在云控制台安全组规则中添加：入方向 TCP 8001，源 0.0.0.0/0（或限制为 Dify 实例内网 IP）

### 验证外部可达
```bash
# 从 Dify 服务器或本地浏览器访问
curl http://REDACTED_HOST:8001/health
```

---

## 七、Tampermonkey 脚本安装

### 7.1 获取脚本
- 文件位置：`tampermonkey/dify-claude-floating-window.user.js`
- 或从项目仓库下载

### 7.2 安装步骤
1. 浏览器打开 Tampermonkey 仪表盘（chrome://extensions/ → Tampermonkey → 仪表盘）
2. 点击"实用工具"标签
3. 在"从 URL 导入"或"新建脚本"中：
   - 方式 A：粘贴脚本全文 → 保存
   - 方式 B：若脚本已托管，填入 URL → 导入
4. 确认脚本已启用（绿色开关）

### 7.3 配置确认
脚本头部已硬编码：
```javascript
const CONFIG = {
  BRIDGE_URL: "http://REDACTED_HOST:8001",
  DIFY_URL: "http://REDACTED_HOST:9980",
  ...
};
```

若 Bridge 部署在其他地址，修改 `BRIDGE_URL` 后保存。

### 7.4 @connect 声明
脚本已声明 `@connect REDACTED_HOST`，Tampermonkey 会允许向该域名发起 `GM_xmlhttpRequest`。若 Bridge 部署在其他域名，需同步修改 `@connect`。

---

## 八、验证清单

### 8.1 服务端验证
```bash
# 1. Bridge 健康
curl http://REDACTED_HOST:8001/health
# 预期：{"status":"ok"}

# 2. Dify 认证
curl http://REDACTED_HOST:8001/dify/apps
# 预期：{"apps":{"data":[...]},"ok":true}

# 3. 会话创建
curl -X POST http://REDACTED_HOST:8001/sessions -H "Content-Type: application/json" -d '{}'
# 预期：{"session_id":"...","status":"idle"}
```

### 8.2 浏览器验证
1. 访问 http://REDACTED_HOST:9980/apps
2. 预期：右下角出现 💬 悬浮按钮
3. 点击展开 → 切换到"对话"Tab
4. 输入"你好" → 预期收到 Claude 流式回复
5. 输入 `/` → 预期弹出斜杠指令面板
6. 输入 `/dify-help` → 预期显示 Skill 列表
7. 输入 `/reset` → 预期会话重置
8. 切换到"资源"Tab → 预期看到 Dify 应用列表
9. 切换到"快捷"Tab → 预期看到快捷按钮

### 8.3 端到端验证
1. 在悬浮窗输入："用 dify_create_app 创建一个 chat 应用叫'测试'"
2. 预期：看到 tool_call 事件 → tool_result 事件 → result 事件
3. Dify 应用列表应 +1

### 8.4 自动化测试
```bash
# 单元测试（无需真实环境）
cd /opt/dify-helper
python -m pytest tests/test_session.py -v
# 预期：12 passed

# E2E 测试（需真实 bridge + Claude CLI）
python tests/test_e2e_floating_window.py
# 预期：4/4 通过
```

---

## 九、常见问题排查

### Q1: Bridge 启动失败，端口被占用
```bash
# 检查 8001 端口占用
sudo lsof -i :8001  # Linux
netstat -ano | findstr 8001  # Windows

# 解决：修改 bridge/config.yaml 的 port，或 kill 占用进程
```

### Q2: 悬浮窗显示"无法连接 bridge 服务"
1. 检查 Bridge 是否运行：`curl http://REDACTED_HOST:8001/health`
2. 检查防火墙是否开放 8001
3. 检查 Tampermonkey `@connect` 是否含 `REDACTED_HOST`
4. 检查脚本 `CONFIG.BRIDGE_URL` 是否正确

### Q3: SSE 流被 Nginx 超时切断
若 Bridge 前有 Nginx 反向代理，需配置：
```nginx
location /sessions/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_read_timeout 3600s;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
}
```

### Q4: Claude CLI 调用失败
1. 验证 CLI 可用：`claude --version`
2. 验证模型配置：`claude -p "hello"`
3. 检查 `bridge/config.yaml` 的 `claude_path` 是否指向正确的可执行文件
4. Windows 上确保 `claude.cmd` 存在（`shutil.which` 返回的路径需加 `.cmd`）

### Q5: MCP 工具调用返回认证错误
1. 检查 `mcp_server/.env` 的 `DIFY_EMAIL` / `DIFY_PASSWORD` 是否正确
2. 密码需 base64 编码：`echo -n 'pwd' | base64`
3. 运行 `python tests/test_auth.py` 验证认证
4. 检查 Dify 实例是否可访问：`curl http://REDACTED_HOST:9980`

### Q6: 悬浮窗 SPA 切页后消失
- 脚本已用 `MutationObserver` + `history.pushState` 劫持处理
- 若仍消失，检查浏览器控制台是否有 JS 错误
- 手动刷新页面应恢复

### Q7: 创建知识库文档失败
- Dify 1.14+ 需先 `/files/upload` 再 `/datasets/{id}/documents`
- 检查 `dify_add_document_by_text` 工具是否已修复（server.py 已含两步上传逻辑）

### Q8: 单元测试 ASGITransport 不触发 lifespan
- 已在 `tests/test_session.py` 用 `running_session_manager` fixture 手动 `start()`
- mock `asyncio.create_subprocess_exec` 避免启动真实 Claude CLI

---

## 十、进程守护方案

### 方案 A：systemd（Linux 推荐）
创建 `/etc/systemd/system/dify-bridge.service`：
```ini
[Unit]
Description=Dify Claude Bridge
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/dify-helper
Environment=PATH=/opt/dify-helper/.venv/bin:/usr/bin
ExecStart=/opt/dify-helper/.venv/bin/python -m bridge.app
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

启用：
```bash
sudo systemctl daemon-reload
sudo systemctl enable dify-bridge
sudo systemctl start dify-bridge
sudo systemctl status dify-bridge
# 查看日志
sudo journalctl -u dify-bridge -f
```

### 方案 B：pm2（跨平台）
```bash
npm install -g pm2
pm2 start "python -m bridge.app" --name dify-bridge --cwd /opt/dify-helper/bridge
pm2 save
pm2 startup  # 开机自启
```

### 方案 C：nohup（临时）
```bash
cd /opt/dify-helper/bridge
nohup python -m bridge.app > /var/log/dify-bridge.log 2>&1 &
echo $! > /var/run/dify-bridge.pid
```

### 方案 D：Windows 服务（Windows Server）
```powershell
# 用 nssm 创建服务
nssm install DifyBridge "D:\Python312\python.exe" "-m bridge.app"
nssm set DifyBridge AppDirectory "D:\dify-helper\bridge"
nssm set DifyBridge AppEnvironmentExtra "PATH=D:\dify-helper\.venv\Scripts;..."
nssm start DifyBridge
```

---

## 十一、监控与日志

### 日志位置
- **Bridge**：`journalctl -u dify-bridge -f`（systemd）或 `/var/log/dify-bridge.log`（nohup）
- **SessionManager**：`[SessionManager]` 前缀日志
- **Worker**：`[Worker]` 前缀日志

### 关键指标
- 活跃会话数：`curl http://localhost:8001/sessions | jq '.sessions | length'`
- 健康状态：`curl http://localhost:8001/health`
- Dify 连通性：`curl http://localhost:8001/dify/apps`

### 告警建议
- Bridge 进程宕机：systemd `Restart=on-failure` 自动重启
- Dify 认证失败：定期跑 `tests/test_auth.py`，失败发告警
- 8001 端口不可达：外部探针监控

---

## 十二、升级与回滚

### 升级
```bash
cd /opt/dify-helper
git pull origin main
pip install -e bridge/ -e mcp_server/  # 依赖更新
sudo systemctl restart dify-bridge
```

### 回滚
```bash
cd /opt/dify-helper
git checkout <previous-commit-hash>
pip install -e bridge/ -e mcp_server/
sudo systemctl restart dify-bridge
```

### Tampermonkey 脚本更新
- 浏览器 Tampermonkey 仪表盘 → 编辑脚本 → 粘贴新版本 → 保存
- 或用 `@updateURL` 自动更新（需脚本托管在可访问 URL）

---

## 十三、安全注意事项

1. **8001 端口暴露**：Bridge 无认证，任何能访问 8001 的人都能创建会话调用 Claude
   - 生产环境建议加 Nginx Basic Auth 或 IP 白名单
   - 或用 SSH 隧道：`ssh -L 8001:localhost:8001 user@REDACTED_HOST`

2. **Dify 凭据**：`mcp_server/.env` 含邮箱密码，文件权限设为 600
   ```bash
   chmod 600 /opt/dify-helper/mcp_server/.env
   ```

3. **Claude CLI 权限**：`bypassPermissions` 模式自动批准所有工具调用
   - 仅在受控服务器部署
   - 限制服务器 SSH 访问权限

4. **CORS**：Bridge 已配置允许 `http://REDACTED_HOST:9980`
   - 生产环境建议收紧为具体路径

5. **Tampermonkey 脚本来源**：仅安装来自可信来源的脚本
   - 本项目脚本不外传敏感信息，仅与 Bridge 通信

---

**部署文档结束。遇到问题请参考"九、常见问题排查"或查看服务日志。**
