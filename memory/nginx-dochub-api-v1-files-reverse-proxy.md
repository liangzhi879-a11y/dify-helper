---
name: nginx-dochub-api-v1-files-reverse-proxy
description: DocHub tool 返回 downloadUrl 是相对路径 /api/v1/files/download，浏览器拼当前 host 直接访问会 404 + 401；需在 nginx 加 /api/v1/files/ 反代（自动注入 X-API-Key）
metadata:
  type: reference
---

# DocHub 下载链接在公网/容器外不可访问的 nginx 修复 (PATCH 32)

## 症状
- DocHub tool 节点生成的 docx，task_summary 显示 downloadUrl=`/api/v1/files/download?path=<base64>`
- 用户在浏览器点击这个 URL → 拼当前 host (`http://<any-host>/api/v1/files/download?path=...`) → **404 或 401**
- 在 Dify 容器外的网络（公网 IP 9980 / LAN IP 80 / 不同端口）全部失败
- 之前 `/dochub-files/` 反代可下，但用户需要**手动**改 URL 前缀，不能直接点 task_summary 里的链接

## 根因
- DocHub 服务端 `/api/v1/generate` 返回 `downloadUrl` 时只给**相对路径**（参考 `dify-plugin/tools/generate_document.py:53` `data.get("downloadUrl", "")`）
- DocHub 服务端 `/api/v1/files/download` **强制要求 `X-API-Key` header**（参考 `doc-gen/src/main/java/com/dochub/api/filter/ApiKeyAuthFilter.java`）
- 浏览器直接 GET 没法带 X-API-Key → 401
- Dify nginx 之前只配了 `/dochub-files/` 反代，没有 `/api/v1/files/` 反代 → 直接 404
- 双重失败：404 (没反代) + 401 (即使有反代也要带 key)

## How to apply

### 修复方案（已应用 2026-07-06）
在 `/home/sutai/source_code/dify/docker/nginx/conf.d/default.conf` 加 1 个 location：

```nginx
# PATCH 32: 让 DocHub 返回的相对路径 /api/v1/files/download 直接通
location ^~ /api/v1/files/ {
    proxy_pass http://dochub-app:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-API-Key "dk_default_test_key";   # 自动注入, 绕过 auth
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 600s;
}
```

`^~` 修饰符确保这条规则优先于普通 `/api` 前缀匹配，不会污染 Dify API 路由。

### 执行步骤（无重启）
```bash
cd /home/sutai/source_code/dify/docker/nginx/conf.d
cp default.conf default.conf.bak.$(date +%s)   # 备份
# 编辑追加上面那段
docker exec docker-nginx-1 nginx -t              # 验证语法
docker exec docker-nginx-1 nginx -s reload       # 热加载, 不重启容器
```

### 验证清单
1. ✅ 内部 `http://127.0.0.1/api/v1/files/download?path=<b64>` → HTTP 200 + OOXML
2. ✅ LAN `http://192.168.x.x/api/v1/files/download?path=<b64>` → HTTP 200 (路由器 NAT 后)
3. ✅ 公网 `http://REDACTED_HOST:9980/api/v1/files/download?path=<b64>` → HTTP 200 (外部设备访问)
4. ✅ 字节级 SHA256 一致 (3 个反代路径拿到同一份 docx)
5. ✅ Dify UI `/apps` 不受影响 (HTTP 200, 391898 bytes)
6. ✅ Dify API `/api/setup` 不被劫持 (404 是 Dify 端点本身不存在, 不会走到 PATCH 32)

### 关联
- 触发词: "DocHub 下载失败 / 外部无法下载 / 401 / 404 docx"
- 相关: [[dify-dochub-container-dns-not-loopback]] (dochub-app:8080 DNS)
- 相关: [[dify-dochub-template-id-must-be-uuid]] (template_id)
- 备份: `/home/sutai/source_code/dify/docker/nginx/conf.d/default.conf.bak.1783302169`