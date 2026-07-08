---
name: dify-dochub-container-dns-not-loopback
description: Dify plugin_daemon 容器内调 DocHub 不能用 127.0.0.1:8088 — 容器自己的 loopback 没 DocHub；必须用容器 DNS http://dochub-app:8080（同 docker_default 网段可路由）
metadata:
  type: project
---

# DocHub 本地寻址 = 容器 DNS（不是 host loopback）

Dify plugin daemon 跑在 docker 容器 `docker-plugin_daemon-1`，DocHub 跑在 `dochub-app`。两者**只在 `docker_default` 网段共享路由**。容器内 `127.0.0.1` 是各自 loopback——**plugin daemon 自己的 127.0.0.1:8088 没起 DocHub，会 ECONNREFUSED**。

## 实测验证（2026-07-05）

| 路由（从 plugin daemon 容器） | 结果 | 延迟 |
|---|---|---|
| `http://127.0.0.1:8088/...` | ❌ Connection refused | 0 ms |
| `http://dochub-app:8080/...`（容器 DNS） | ✅ 200 OK | 27 ms |
| `http://172.19.0.12:8080/...`（容器 IP） | ✅ 200 OK | 3 ms |
| host 上 `http://127.0.0.1:8088/...` | ✅ 200 OK | — |

**用户视角**："我本机能调通 DocHub → 在 plugin 上配 `127.0.0.1:8088` 就行"，但 plugin daemon 是另一台 namespace 的"机器"，对它来说 `127.0.0.1` 不是 host。

## Why（具体翻车）

2026-07-05 调查 DocHub 本地模板 ID 时，原 cb154f61 app PATCH 17 后"跑得通"是 host 上手工 run；从 Dify plugin daemon 跑的 workflow 全部 `network error after 3 retries`。Plugin credentials `team_credentials.base_url` 之前填的如果是 `127.0.0.1:8088`，插件容器一调就 ECONNREFUSED。

## How to apply

### 排查"plugin 调下游服务 ECONNREFUSED" 步骤
```bash
# 1. 确认下游容器名 + 网络
docker ps --format '{{.Names}} {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'

# 2. 看 plugin daemon 在哪个网络
docker inspect docker-plugin_daemon-1 --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'

# 3. 进 plugin daemon 容器测连通
docker exec docker-plugin_daemon-1 sh -c 'curl -s -m 4 -w "%{http_code}" http://127.0.0.1:8088/ && echo LOCAL'   # → ECONNREFUSED
docker exec docker-plugin_daemon-1 sh -c 'curl -s -m 4 -w "%{http_code}" http://<CONTAINER_NAME>:<PORT>/ && echo DNS'   # → 200

# 4. 拉到 DocHub plugin 容器 network
docker network inspect docker_default | jq '.[] | .Containers[].Name'
```

### 配 plugin credentials 时 base_url 的正确写法

| 下游服务 | base_url |
|---|---|
| 同 host 进程 (host 上跑) | `http://127.0.0.1:<port>`（userland proxy 转 host 端口） |
| 同 `docker_default` 网段另一容器 | `http://<container_name>:<inner_port>`（容器 DNS） |
| 同 `docker_default` 网段另一容器（写死 IP） | `http://<container_ip>:<inner_port>`（不推荐，容器 IP 会变） |
| 跨 host | `http://<host_ip>:<port>`（防火墙/网络策略另算） |

### 本地 DocHub 当前正确配

```yaml
team_credentials:
  api_key: dk_default_test_key     # tenant_default 默认租户
  base_url: http://dochub-app:8080  # 容器 DNS（不是 127.0.0.1:8088！）
```

## 模板 ID 唯一性

DocHub 本地 (`tenant_default`) **只有一个模板**：
```
ID:   e2bb9951-05a4-498d-8c1f-ff9ef47f560b
NAME: RD_temp_test
TYPE: word
```

查询方法：进入 `dochub-app` 容器 → `java -cp /tmp/h2.jar org.h2.tools.Shell -url "jdbc:h2:file:/app/data/dochub;AUTO_SERVER=TRUE;IFEXISTS=TRUE" -user sa -password "" -sql 'SELECT * FROM "TEMPLATE_META"'`。注：表名单数 `"TEMPLATE_META"`，不是猜的 `templates`。

template schema 11 个 required 字段：`project_year / project_name / start_date_cn / leader / project_year_cn / count_no / budget / finish_date_cn / expenses / labor_costs / ip_count`。**额外字段默认允许**（draft-07 `additionalProperties: true` 默认），不会拒。

## 关联记忆

- [[dify-tool-node-data-required-fields]] — 同一 plugin 的 tool_parameters 三阶层必填
- [[dify-http-node-hardcode-localhost]] — 同 vector（不能用 127.0.0.1 写死）
