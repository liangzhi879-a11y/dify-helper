# DocHub 文档局域网下载指南

> 适用对象：Dify workflow `WF_RDReport (v2 doc-ext 复刻)`（app_id `7ab3c5fd-306a-4180-a99a-693604bd5c69`）生成的 docx 文档。
>
> **本机（docker host）测试时间**：2026-07-05
> **Docker 反代实测时间**：2026-07-06（PATCH 29 / DOC-A 验证通过）

---

## 1. 3 条下载路径对比

| URL | 鉴权 | 适用场景 | 来源 |
|---|---|---|---|
| `http://127.0.0.1:8088/api/v1/files/download?path=<b64>` | Header `X-API-Key: dk_default_test_key` | 本机 / docker 内 curl | DocHub 容器 8088→8080 端口映射 |
| `http://192.168.x.x:8088/api/v1/files/download?path=<b64>` | Header `X-API-Key: dk_default_test_key` | LAN 设备直连 DocHub 容器 | 同上 |
| **`http://192.168.x.x/dochub-files/download?path=<b64>`** | **无需 Key**（nginx 自动注入） | **LAN 设备、移动设备、浏览器（推荐）** | docker-nginx-1 反代 `/dochub-files/` |

> 第 3 条是 LAN 内最常用的入口。无需 API key，浏览器直接打开就能下载 docx。

## 2. path 是什么？

Dify workflow 跑完后，`task_summary_001` 输出里有所有生成的 docx URL，形如：

```
/api/v1/files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA==
```

`path=` 后面的 `L2FwcC9kYXRh...` 是 base64 字符串，解码后是 DocHub 容器内路径：

```bash
$ echo 'L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRl90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA==' | base64 -d
/app/data/generated/tenant_default/RD_temp_test_20260705235122.docx
```

## 3. 4 种下载示例

### 3.1 浏览器（最简单）

直接在 LAN 设备的浏览器地址栏粘贴：

```
http://192.168.x.x/dochub-files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA==
```

→ 浏览器自动下载 `RD_temp_test_20260705235122.docx`。

### 3.2 curl（推荐 LAN 脚本/调试）

```bash
# LAN 反代（无需 Key）
curl -OJ "http://192.168.x.x/dochub-files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA=="

# 本机直连（需要 X-API-Key）
curl -OJ -H "X-API-Key: dk_default_test_key" \
  "http://127.0.0.1:8088/api/v1/files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA=="
```

`-OJ` 让 curl 用服务端指定的文件名。

### 3.3 Python（集成到自动化脚本）

```python
import requests

PATH_B64 = "L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA=="

# LAN 反代
resp = requests.get(
    f"http://192.168.x.x/dochub-files/download?path={PATH_B64}",
    timeout=60,
)
resp.raise_for_status()
with open("downloaded.docx", "wb") as f:
    f.write(resp.content)
print(f"Downloaded {len(resp.content)} bytes")
```

### 3.4 wget

```bash
wget "http://192.168.x.x/dochub-files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDUyMzUxMjIuZG9jeA=="
```

## 4. 如何从 workflow 输出里提取所有文档 URL

跑完 workflow 后，`task_summary` 字段会含全部文档 URL。例如：

```markdown
# 任务执行总结

- **生成时间**: 2026-07-06 14:23:11 UTC
- **RD 项目总数**: 6
- **DocHub 文档数**: 6
- **QC 通过**: 7
- **QC 失败**: 0

## 文档下载链接

1. **RD01**: /api/v1/files/download?path=L2FwcC9kYXRh...
2. **RD02**: /api/v1/files/download?path=L2FwcC9kYXRh...
...
```

把 path 抠出来，拼到 `http://192.168.x.x/dochub-files/download?path=` 后面就行。

### 批量下载（Python 模板）

```python
import requests
import re

TASK_SUMMARY = """  # 从 workflow 输出粘贴
1. **RD01**: /api/v1/files/download?path=L2FwcC9kYXRh...
2. **RD02**: /api/v1/files/download?path=L2FwcC9kYXRh...
"""

# 提取 (rd_code, path) 列表
urls = re.findall(r'\*\*(\w+)\*\*: /api/v1/files/download\?path=(\S+)', TASK_SUMMARY)

for rd_code, path_b64 in urls:
    resp = requests.get(
        f"http://192.168.x.x/dochub-files/download?path={path_b64}",
        timeout=60,
    )
    resp.raise_for_status()
    fname = f"{rd_code}.docx"
    with open(fname, "wb") as f:
        f.write(resp.content)
    print(f"✅ {fname}: {len(resp.content)} bytes")
```

## 5. 网络拓扑

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  LAN 客户端       │ ──────> │  docker-nginx-1  │ ──────> │  docker-dochub    │
│  (192.168.3.x)   │  :80    │  192.168.x.x   │  8080   │  (容器, 默认       │
│                  │         │  自动注入 X-API-Key│        │   0.0.0.0:8080)   │
└──────────────────┘         └──────────────────┘         └──────────────────┘
                                       │
                                       │ docker_default 网络
                                       ▼
                              ┌──────────────────┐
                              │  172.19.0.x      │  (容器内 IP, 不固定)
                              └──────────────────┘
```

- `docker-nginx-1` 在 `docker_default` 网络 → 能 DNS 解析 `dochub-app`
- `dochub-app` 端口 `0.0.0.0:8088→8080` 已映射到 host (`192.168.x.x:8088`)
- `docker-nginx-1` 端口 `0.0.0.0:80→80` + `0.0.0.0:443→443` 已映射到 host (`192.168.x.x:80/443`)

## 6. nginx 配置（已就绪，无需修改）

配置在 `docker-nginx-1 /etc/nginx/conf.d/default.conf`（2026-07-05 已加）：

```nginx
location /dochub-files/ {
    rewrite ^/dochub-files/(.*)$ /api/v1/files/$1 break;
    proxy_pass http://dochub-app:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-API-Key "dk_default_test_key";
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 600s;
}
```

备份：`default.conf.bak.1783262403`

## 7. 安全注意

- **默认 X-API-Key (`dk_default_test_key`) 是 DocHub docker-compose 的公开 key**，所以 LAN 内任何人只要拿到 path 都能下载 → **path 本身是唯一鉴权**（base64 容器内路径，UUID 难猜）
- 生产环境应改 `docker-compose env DOCHUB_API_KEY`，并同步修改 nginx 配置里的 `X-API-Key`
- **公网暴露前必须加**：HTTPS（Let's Encrypt）+ IP 白名单 或 Bearer token + 防火墙限制 source IP

## 8. 故障排查

| 症状 | 根因 | 修复 |
|---|---|---|
| `HTTP 404 文件不存在` | path 过期（docx 已被清理）或 URL 拼错 | 重跑 workflow 拿新 path；用 `xxd` 看 base64 是否完整 |
| `HTTP 502 Bad Gateway` | nginx 容器不通 DocHub 容器 | `docker exec docker-nginx-1 curl http://dochub-app:8080/` 验证 DNS |
| `HTTP 500 服务器内部错误`（调用 `/api/v1/files/list`） | DocHub 文件列表 API 本身坏 | 不影响 `/download`，忽略 |
| 反代下载字节数 != 直连 DocHub 下载字节数 | nginx 缓冲/proxy 配置 | 加 `proxy_buffering off`（已加） |
| docx 打开报"文件损坏" | 下载未完整（curl 被 timeout 截断） | 加 `-m 0` 关 timeout，或 `proxy_read_timeout 600s`（已加） |

## 9. 验证记录（2026-07-06 DOC-A）

| 路由 | HTTP | 字节数 | sha256 | magic bytes |
|---|---|---|---|---|
| `http://192.168.x.x:8088/api/v1/files/download?path=<b64>` (X-API-Key) | 200 | 38986 | `0aa727e4c947c0330290142299f879f1d9663a5b9cadbe4fb7640787c9bf21c7` | `504b0304` (ZIP/DOCX) |
| `http://192.168.x.x/dochub-files/download?path=<b64>` (无 Key) | 200 | 38986 | `0aa727e4c947c0330290142299f879f1d9663a5b9cadbe4fb7640787c9bf21c7` | `504b0304` (ZIP/DOCX) |

**两条路径下载到字节级一致的 docx → 反代正确工作**。

## 10. 关联文档

- `memory/dochub-file-download-lan-and-external.md` — 3 条路径 + 网络拓扑
- `memory/dify-dochub-container-dns-not-loopback.md` — 容器 DNS 不是 loopback
- `memory/dify-dochub-template-id-must-be-uuid.md` — template_id 必须 UUID 硬编码
- `docs/dify-debug-trace.log.md` PATCH 27 段 — template_id 修复
- `backups/wfrdreport_v2_doc_ext/draft_BEFORE_PATCH_27_*.json` — PATCH 27 备份