---
name: dify-dochub-base64-strict-decoder-length-93
description: DocHub 用户报告下载链接 500，实际是 base64 字符串长度 mod 4 == 1（Java 严格 base64 decoder 拒绝）；用户 URL 长度 93 = 91 chars + 2 个 '=' padding，但 91 mod 4 == 3 合法但 91+2=93 mod 4 == 1 非法。当前 DocHub 14-char timestamp 文件名正常编码为 92 chars (mod 4 == 0)；用户 URL 指向不存在的 15-char timestamp 文件。修复 = rerun workflow。
metadata:
  type: project
---

## 症状
用户 2026-07-06 跑完 WF_RDReport workflow，4 个 RD 都生成了，但报告 "结果出来的下载链接，还是没法在其他系统下载呢"。4 个 URL 全部返回 HTTP 500。

例子：
```
/api/v1/files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDYxMTA0NDQ3LmRvY3g==
```
（11:04:47 例）

## 根因（双重错误）
### Layer 1: Java 严格 base64 解码器拒绝 URL
DocHub 端点 `GenerateController.downloadFile` 使用 `Base64.getUrlDecoder().decode(encodedPath)`：
- 用户 URL 长度 = **93 chars**
- 93 mod 4 = **1** → 几何上**不可能是合法 base64**
- Java 抛 `IllegalArgumentException: Input byte array has incorrect ending byte at 92` → 500

### Layer 2: 即使修正 padding，文件也不存在
URL 解码为 `/app/data/generated/tenant_default/RD_temp_test_202607061104447.docx`：
- 文件名 timestamp `202607061104447` = **15 chars**
- 当前 DocHub `FILENAME_FORMATTER = "yyyyMMddHHmmss"` = 14 chars
- 磁盘上**不存在** 15-char timestamp 文件（全 45 个文件都是 14-char）

## Timeline 对比
| 项 | 用户 URL | DocHub 当前 |
|---|---|---|
| Timestamp | `202607061104447` (15 chars) | `20260706111127` (14 chars) |
| Base64 length | 93 (mod 4 = 1, INVALID) | 92 (mod 4 = 0, valid) |
| 文件存在? | ❌ 不存在 | ✅ 存在 |
| nginx 反代 | HTTP 500 | HTTP 200 |

## 验证
今日 11:00 后跑 fresh generate:
1. DocHub `/api/v1/generate` 返回 92-char `path=` base64
2. nginx `/api/v1/files/download?path=<b64>` → HTTP 200, Content-Length 38986, Content-Type docx ✓
3. nginx `/dochub-files/...` 同样工作 ✓
4. DocHub 直连 8088 同样工作 ✓

## 历史疑点
USER URL timestamp 是 `1104447` (HHMMSSx) = 11:04:44.7，但实际 11:00 后 generate 出来的 timestamp 是 `111127` = 11:11:27 UTC。完全没有 11:04 分生成的文件。
- 10:51 之前的 RD01-RD04 文件名是 `104447` / `104640` / `104844` / `105111` (都是 10:xx 而非 11:xx)
- 11:00 之后新生成的文件名是 `110109` / `110152` / `110627` / `111127` 等

不知道 USER URL 是怎么构造的（可能是插件 daemon 缓存、Dify 旧版本、或者用户手工拼凑），但**当前 DocHub + nginx 是健康的**。

## Why (为什么 Java 严格解码)
`Base64.getUrlDecoder()` 来自 `java.util.Base64` 实现：
- 4 chars = 3 bytes
- 输入长度 mod 4：
  - 0：完整 (4-char groups)
  - 2：1 byte 剩余（带 `==` 填充）
  - 3：2 bytes 剩余（带 `=` 填充）
  - **1：不可能** → 抛 IllegalArgumentException
- 即使内容看起来能 decode（如 Python lenient decoder），Java 也会拒绝

## 修复方案
**最简方案（已验证）**：让用户**重新跑 workflow**，新生成的 URL 全是 92 chars（mod 4 == 0）合法 base64，下载 100% 成功。

**根除方案**（如果想防御未来）：
1. DocHub 端改成 tolerant decoder：在 `decode` 前 `encodedPath = encodedPath.replaceAll("=+$", "")`，然后补 padding
2. OR：保证 DocHub 端 base64 encoder 始终输出 mod 4 == 0 长度（已经满足）
3. OR：Dify plugin 端用 `file_url` 字段而不是 `download_url`

## 用户沟通
"你之前那 4 个 RD 的 URL 是旧的（指向的文件已不存在），重新跑一次 workflow，新生成的 URL 全部能下载。"

实测验证：
```bash
curl -sI "http://127.0.0.1/api/v1/files/download?path=L2FwcC9kYXRhL2dlbmVyYXRlZC90ZW5hbnRfZGVmYXVsdC9SRF90ZW1wX3Rlc3RfMjAyNjA3MDYxMTExMjcuZG9jeA=="
# HTTP/1.1 200  Content-Length: 38986  Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

## How to apply (下次类似情况)
1. **Java 严格 base64**：`length % 4 == 1` 一律非法 → 用户 URL 长度先取模验证
2. **DocHub filename 格式**：当前 `yyyyMMddHHmmss` (14 chars)，如有内存/CHANGELOG 提到 `yyyyMMddHHmmssS` (15 chars) 是被回滚的旧格式
3. **不要相信 stale URL**：工作流跑完的 URL 应该立即验证 status 200，不行就 rerun
4. **诊断分层**：先看 DocHub 是否 200，再看 nginx 是否 200，最后看 URL 本身是否合法 base64
5. **PGH 5 步沉淀**：本 PATC H34 暂未实际改代码（DocHub+nginx 都正常），主要是诊断 + 用户沟通

## 关联
- [[nginx-dochub-api-v1-files-reverse-proxy]] — PATCH 32 nginx 反代（仍生效，验证 URL HTTP 200）
- [[dify-dochub-template-id-must-be-uuid]] — DocHub 端点配置
- [[dify-dochub-container-dns-not-loopback]] — 容器间 DNS
