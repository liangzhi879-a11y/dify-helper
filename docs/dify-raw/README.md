# Dify 官方源码本地化（langgenius/dify → 项目仓库）

> **目的**：把 Dify 官方仓库的权威 schema/spec 物理拉到本项目内，PATCH 决策**优先查此目录**，不靠记忆或外网搜索。

## 1. 抓取策略

按可达性分层（**全失败则停下来问用户**）：

| # | 方式 | 命令 | 适用 |
|---|------|------|------|
| ① | `curl raw.githubusercontent.com` | `curl -fsSL https://raw.githubusercontent.com/langgenius/dify/<tag>/<path>` | 无需认证，最快 |
| ② | GitHub API | `curl "https://api.github.com/repos/langgenius/dify/contents/<path>?ref=<tag>"` | 拿目录列表 + 文件元信息 |
| ③ | `gh api` | `gh api repos/langgenius/dify/contents/<path>` | gh CLI 已登录时 |
| ④ | WebFetch | harness 自带 | 一次性抓 |
| ⑤ | **用户协助** | AskUserQuestion 弹 4 选项 | ①②③④ 全失败时（最坏情况） |

**实测结论**（2026-07-04 本 session）：
- ✅ `curl raw.githubusercontent.com` 可用（HTTP 200，14KB/s 速率）
- ✅ GitHub Contents API 可用
- ❌ `gh` CLI 未安装
- ⚠️ WebFetch 挡外网（验证过 `docs.dify.ai` 不可达）

## 2. tag 选择（关键发现）

**用户的 Dify 实例是 1.14.2**（见 `CLAUDE.md` 第 "Dify 实例信息" 节）。

Dify 在 **1.13.0** 与 **1.12.1** 之间做了大规模重构：

| tag | `api/core/workflow/nodes/` 子目录 |
|-----|-----------------------------------|
| 1.10.1, 1.11.4, 1.12.1 | `agent / answer / base / code / datasource / document_extractor / end / http_request / human_input / if_else / iteration / knowledge_index / knowledge_retrieval / list_operator / llm / loop / parameter_extractor / question_classifier / start / template_transform / tool / trigger_plugin / trigger_schedule / trigger_webhook / variable_aggregator / variable_assigner`（27 个，含旧 18 节点） |
| **1.13.3, 1.14.2（用户）** | `agent / datasource / knowledge_index / knowledge_retrieval / trigger_plugin / trigger_schedule / trigger_webhook`（**仅 7 个**） |

**CLAUDE.md 列出的"18 个 workflow 节点类型"实际上仍存在，但被重构到了独立的 PyPI 包 `graphon~=0.4.0`**：

```
api/core/workflow/node_factory.py:
    _import_node_package("graphon.nodes")        # ← 旧 18 节点（外部 PyPI 包）
    _import_node_package("core.workflow.nodes")  # ← 新 7 节点（dify 仓库内）
```

所以 `from graphon.nodes.code.entities import CodeNodeData` 等语句**指向外部 PyPI 包**，**不在 dify 仓库内**。

**结论**：本目录抓的是 1.14.2 tag 的 7 节点 + node_factory 等注册逻辑。`graphon` 包的源码若需要请走 PyPI（`pip download graphon==0.4.0` 后 `tar -xzf` 解压看 `graphon/nodes/`）。

## 3. 目录结构（B1 瘦身版）

```
docs/dify-raw/                      总 ≈80KB
├── README.md                      # 本文件（抓取策略 + 维护协议）
├── FETCH_LOG.md                   # 每次抓取记录（URL / 时间 / size / tag）
└── nodes/                          # api/core/workflow/nodes/<7 节点>/entities.py ≈16KB
    ├── agent/entities.py            # 1.4KB
    ├── datasource/entities.py       # 1.9KB
    ├── knowledge_index/entities.py  # 2.6KB
    ├── knowledge_retrieval/entities.py # 1.9KB
    ├── trigger_plugin/entities.py   # 3.1KB
    ├── trigger_schedule/entities.py # 1.9KB
    └── trigger_webhook/entities.py  # 4.2KB
```

**已删除**（B1 决策 2026-07-04）：
- ~~`graph_engine/`~~ — workflow 引擎 9 文件（≈130KB）
- ~~`api_console/`~~ — DSL 服务 + pyproject（≈45KB）

**理由**：graphon 节点真值需走 PyPI `graphon~=0.4.0` 单独抓；engine / DSL 真值在 PATCH 决策中**第一查证频次低**（节点 schema 才是高频）。如需 engine / DSL 重新抓，跑：

```bash
cd /home/sutai/dify-helper
python scripts/dify_sync.py --fetch-engine    # 重新拉 graph_engine/ + api_console/
```

详见 `scripts/dify_sync.py --help`。

## 4. 维护协议

### 抓取命令（idempotent — 当前 B1 精简版只抓 7 节点）

```bash
cd /home/sutai/dify-helper/docs/dify-raw
TAG=1.14.2

# 7 官方节点（当前默认）
for node in agent datasource knowledge_index knowledge_retrieval trigger_plugin trigger_schedule trigger_webhook; do
  mkdir -p "nodes/${node}"
  curl -fsSL --max-time 5 -o "nodes/${node}/entities.py" \
    "https://raw.githubusercontent.com/langgenius/dify/${TAG}/api/core/workflow/nodes/${node}/entities.py"
done
```

### 可选扩展（按需补抓 graphon 节点真值）

```bash
# graphon 包（旧 18 节点真值）— 不在 dify 仓库，需 PyPI
pip download graphon==0.4.0 -d /tmp/graphon --no-deps
mkdir -p /home/sutai/dify-helper/docs/dify-raw/graphon_src
tar -xzf /tmp/graphon/graphon-0.4.0*.tar.gz -C /home/sutai/dify-helper/docs/dify-raw/graphon_src/
```

### 可选扩展（按需补抓 engine + DSL）

```bash
# workflow engine + DSL service（如 B1 后需要）
python /home/sutai/dify-helper/scripts/dify_sync.py --fetch-engine
```

### 刷新频率
- **每 30 天** re-fetch（CLAUDE.md Playbook 加提醒）
- Dify 发布新 minor version 后**立即** re-fetch + diff
- 改 `_NODE_SCHEMAS` 字典时**必须**先 diff `nodes/*/entities.py` 看是否一致

### 不要做的事
- ❌ 不要改 `docs/dify-raw/` 下任何文件的**内容**（只抓不改），改的话等于失去权威源
- ❌ 不要把 `graphon` 包源码也抓来（PyPI 外部依赖，体积大且独立 release）
- ❌ 不要把运行时行为代码（`<node>.py` 而非 `entities.py`）抓来，会膨胀仓库

## 5. Fallback（关键）

当 `curl raw.githubusercontent.com` + GitHub API + gh CLI + WebFetch **全数不可达**时（本实例整体挡外网），**不要**：
- ❌ 凭记忆或经验写 PATCH 脚本
- ❌ 重复 PATCH 1-9 的 5 次翻车

**应该**：
1. 立即 `AskUserQuestion`，给 4 选项：
   - A. 用户从浏览器复制 raw 文件粘贴
   - B. 用户上传离线 tgz / zip
   - C. 用户用另一台机器 `git clone langgenius/dify` 后 rsync 过来
   - D. 暂停 PATCH 等网络恢复
2. 收到后按选择执行，**不能**继续盲 PATCH

## 6. 引用约定

代码评审 / 反查时引用本目录用相对路径：
- `★ 权威源 docs/dify-raw/nodes/<type>/entities.py:N`（本目录仅 7 个 dify 自带节点）
- `★ 权威源（外部 PyPI）graphon~=0.4.0/nodes/<type>/entities.py:N`（旧 18 节点，需 pip download 后用）

PATCH 决策时**第一查证**就查这些文件，不靠模型记忆。