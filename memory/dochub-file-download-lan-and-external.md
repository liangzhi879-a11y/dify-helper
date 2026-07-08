---
name: dochub-file-download-lan-and-external
description: DocHub 生成的 docx 文件通过 3 条路径可下载，nginx 反代 /dochub-files/ 让外部客户端无需 X-API-Key
metadata:
  type: reference
---

# DocHub 文档下载 3 条路径

DocHub tool 节点 (Dify workflow) 生成 docx 后，输出 `text` 字段含 DocHub 返回的 download 链接，形如：
```
/api/v1/files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRl90ZW1wX3Rlc3RfMjAyNjA3MDUxNDM1MDQuZG9jeA==
```
base64 解码后是容器内路径：`/app/data/generated/tenant_default/RD_temp_test_20260705143504.docx`

## 3 条访问路径

| URL | 鉴权 | 何时用 |
|---|---|---|
| `http://127.0.0.1:8088/api/v1/files/download?path=<b64>` | Header `X-API-Key: dk_default_test_key` | 本机调试 / docker 内 curl |
| `http://192.168.x.x:8088/api/v1/files/download?path=<b64>` | Header `X-API-Key: dk_default_test_key` | LAN 直连 DocHub 容器 8088→8080 映射 |
| `http://192.168.x.x/dochub-files/download?path=<b64>` | **无需 Key**（Dify nginx 自动注入） | LAN 外部客户端 / 移动设备 / 浏览器 |

第 3 条路径配置在 `docker-nginx-1 /etc/nginx/conf.d/default.conf`（2026-07-05 加）：
```nginx
location /dochub-files/ {
    rewrite ^/dochub-files/(.*)$ /api/v1/files/$1 break;
    proxy_pass http://dochub-app:8080;
    proxy_set_header X-API-Key "dk_default_test_key";
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 600s;
}
```

## 网络拓扑
- `docker-nginx-1` 在 `docker_default` 网络 → 能 DNS 解析 `dochub-app` (172.19.0.12)
- `dochub-app` 端口 `0.0.0.0:8088→8080` 已映射到 host (LAN 已通)
- `docker-nginx-1` 端口 `0.0.0.0:80→80` + `0.0.0.0:443→443` 已映射到 host

## 公网暴露方案（未实施）

如需外部互联网访问，按以下顺序选择：

1. **Cloudflare Tunnel（推荐）**：免费、自动 HTTPS、不开防火墙端口
   ```bash
   cloudflared tunnel --url http://localhost:80
   ```
2. **frp / ngrok**：临时内网穿透
3. **路由器端口转发 + DDNS**：开放 80/443 + 花生壳 / dyndns
4. **直接 IP+端口**：联系 ISP 拿公网 IP + 路由器开端口

**安全注意**：公网暴露前必须加：
- HTTPS（Let's Encrypt + certbot）
- IP 白名单 或 Bearer token 鉴权（参考现有 `/llm/` 和 `/embed/` location block 用 `if ($http_authorization != "Bearer XXX") return 403;`）
- 防火墙限制 source IP

## 默认 X-API-Key
`dk_default_test_key` 是 DocHub docker-compose 的默认 key，公开文件不需要 per-user 鉴权。生产环境应改 docker-compose env `DOCHUB_API_KEY`。

## 关联
- `backups/wfrdreport_v2_doc_ext/` 备份的 draft JSON
- `docs/dify-debug-trace.log.md` PATCH 27 段（template_id UUID）
- `memory/dify-dochub-template-id-must-be-uuid.md`