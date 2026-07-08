---
name: dify-dochub-template-id-must-be-uuid
description: DocHub plugin tool 节点的 template_id 必须硬编码 UUID, 不能用文件名也不能用 {{#sys.env.X#}}; env var 在 tool 节点不解析, plugin daemon 收到字面字符串
metadata:
  type: project
---

**症状**: DocHub 节点报 `文档生成失败 (HTTP 404): 模板不存在: sys.env.RD_REPORT_TEMPLATE_ID`, rd_doc_urls 全是错误。

**根因 (双错位)**:
1. `tool_configurations.template_id.value = "RD_temp_test"` ← 用户填的是模板**文件名**, DocHub API 要的是 **UUID**
2. `tool_parameters.template_id.value = "{{#sys.env.RD_REPORT_TEMPLATE_ID#}}"` ← Dify 1.14+ tool 节点解析时把字面字符串直接透传给 plugin daemon, **不解析 env var** (不像 prompt_template 的 jinja2)

**修复**: 两处都硬编码 UUID `e2bb9951-05a4-498d-8c1f-ff9ef47f560b` (从 DocHub `/api/v1/templates/options` 端点取回):
- `tool_configurations.template_id.value = "e2bb9951-..."` 
- `tool_parameters.template_id.value = "e2bb9951-..."`

**验证模板存在的方法**:
```python
# 解密 tool_builtin_providers 里的 encrypted api_key
# tenant private.pem 在 /home/sutai/source_code/dify/docker/volumes/app/storage/privkeys/<tenant_id>/private.pem
# libs/rsa.py: decrypt_token_with_decoding(encrypted_bytes, private_key, cipher_rsa)
# 注意 cipher_rsa 用 libs/gmpy2_pkcs10aep_cipher.new(private_key), 不是直接 import "new"
```
```bash
# 必须从 docker network 内访问 (plugin_daemon 容器 → dochub-app:8080)
docker exec docker-plugin_daemon-1 curl -H "X-API-Key: <decrypted_key>" http://dochub-app:8080/api/v1/templates/e2bb9951-...
# 注意 header 是 X-API-Key, 不是 Authorization: Bearer
```

**Why**: template_id 是 DocHub API 路由主键, 文件名当主键返回 404; env var 在 tool node 不解析是 Dify 1.14+ 的设计, prompt_template 的 jinja2 解析不延伸到 tool parameters。

**How to apply**:
1. 任何 DocHub tool 节点 PATCH 前先 `GET /api/v1/templates/options` 拿真实 UUID 列表 (label 才是可读文件名)
2. tool_configurations 和 tool_parameters 都要写 UUID (前者控制 plugin UI 显示, 后者控制实际调用 payload)
3. 模板验证: docker network 内 curl + X-API-Key header (Authorization Bearer 返回 401 "缺少 X-API-Key 请求头")
4. trace 里查 template_id 是否是 UUID (不是 "RD_temp_test" 也不是 "{{...}}")

关联: [[dify-dochub-container-dns-not-loopback]] (plugin daemon 用容器 DNS, 不是 127.0.0.1) + [[dify-tool-node-data-required-fields]]