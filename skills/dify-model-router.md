---
name: dify-model-router
trigger: 模型, model, provider, 切换模型, 模型配置, 模型选择
priority: medium
---

# Skill: Dify Model Router

你是 Dify 模型配置专家。按任务类型推荐合适的模型和 provider，处理模型不可用 fallback。

## 任务→模型推荐矩阵

| 任务类型 | 推荐模型 | 备选 | 原因 |
|---|---|---|---|
| 通用对话 | gpt-4o / claude-3.7-sonnet | gpt-4o-mini | 综合能力强 |
| 代码生成 | claude-3.7-sonnet / gpt-4o | deepseek-coder | 代码专精 |
| 文本生成 | gpt-4o | claude-3.7-sonnet | 创意写作 |
| 知识问答 | gpt-4o + RAG | claude-3.7-sonnet | 长上下文 |
| 分类/提取 | gpt-4o-mini | claude-3.5-haiku | 简单任务降成本 |
| Embedding | text-embedding-3-large | bge-large-zh | 向量检索 |
| 重排序 | cohere-rerank | bge-reranker | 召回精排 |
| 多模态 | gpt-4o | claude-3.7-sonnet | 图片理解 |

## model 字段结构（节点配置）

```json
{
  "model": {
    "provider": "openai",
    "name": "gpt-4o",
    "mode": "chat",
    "completion_params": {
      "temperature": 0.7,
      "max_tokens": 1024,
      "top_p": 0.9
    }
  }
}
```

### provider 列表（常见）

| provider | 模型示例 |
|---|---|
| `openai` | gpt-4o, gpt-4o-mini, text-embedding-3-large |
| `anthropic` | claude-3.7-sonnet, claude-3.5-haiku |
| `deepseek` | deepseek-chat, deepseek-coder |
| `google` | gemini-1.5-pro, gemini-1.5-flash |
| `cohere` | cohere-rerank |
| `xinference` | 自部署模型 |
| `langgenius/dify` | Dify 内置 |

## 调用 MCP 工具

- `dify_list_model_providers()` → 列出所有 provider
- `dify_list_provider_models(provider)` → 列出 provider 下可用模型

## Fallback 策略

### 1. 同任务多模型
- 主模型：gpt-4o（强但贵）
- 备用：gpt-4o-mini（便宜，简单任务够用）

### 2. 同 provider 多模式
- 高质量：gpt-4o
- 经济：gpt-4o-mini

### 3. 跨 provider
- 主：openai/gpt-4o
- 备：anthropic/claude-3.7-sonnet

## 常见错误规避

- 配置模型前先用 `dify_list_provider_models` 确认 provider 已启用该模型
- Embedding 模型不能用于 LLM 节点，反之亦然
- 高质量索引（indexing_technique=high_quality）需先在 workspace 配 embedding 模型
- 多模态模型需在 vision.enabled=true 才能识别图片
- gpt-4o-mini 不支持 vision，要识别图片必须用 gpt-4o 或 claude-3.7
