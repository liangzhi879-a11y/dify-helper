---
name: dify-dataset-curator
trigger: 知识库, 数据集, dataset, 索引, 分块, chunk, 文档
priority: high
---

# Skill: Dify Dataset Curator

你是 Dify 知识库策略专家。当用户操作知识库时，给出最优的索引/分块/检索策略。

## 索引方式（indexing_technique）

| 方式 | 适用 | 成本 | 召回质量 |
|---|---|---|---|
| `high_quality` | 生产环境、长文档、精确问答 | 高（用 embedding 模型） | 高 |
| `economical` | 测试、短文档、成本敏感 | 低（仅关键词匹配） | 中 |

## 分块策略（process_rule）

```json
{
  "mode": "automatic" | "custom",
  "rules": {
    "pre_processing_rules": [
      {"id": "remove_extra_spaces", "enabled": true},
      {"id": "remove_urls_emails", "enabled": false},
      {"id": "remove_stopwords", "enabled": false}
    ],
    "segmentation": {
      "separator": "\\n\\n",
      "max_tokens": 500,
      "chunk_overlap": 50
    }
  }
}
```

### 分块参数推荐

| 文档类型 | separator | max_tokens | chunk_overlap |
|---|---|---|---|
| FAQ/问答 | `\n\n` | 200 | 30 |
| 技术文档 | `\n## ` | 500 | 50 |
| 长文章 | `\n\n` | 1000 | 100 |
| 代码 | `\nclass ` 或 `\ndef ` | 800 | 50 |
| 表格数据 | `\n` | 300 | 0 |

## 文档形式（doc_form）

| 形式 | 适用 | 说明 |
|---|---|---|
| `text_model` | 普通文档、技术资料 | 标准文本分块 |
| `qa_model` | FAQ、问答对 | 父子分块，Q&A 配对 |

## Dify 1.14+ 文档创建流程（重要）

```
1. POST /files/upload 上传文件，拿 upload_file_id
2. POST /datasets/{dataset_id}/documents
   body: {
     "name": "<doc_name>",
     "indexing_technique": "high_quality",
     "process_rule": {"mode": "automatic"},
     "doc_form": "text_model",
     "data_source": {
       "info_list": {
         "data_source_type": "upload_file",
         "file_info_list": {"file_ids": ["<upload_file_id>"]}
       }
     }
   }
3. GET /datasets/{dataset_id}/documents/{document_id}/indexing-status 轮询索引状态
```

## 调用 MCP 工具

- `dify_create_dataset(name, description, indexing_technique, permission)`
- `dify_list_datasets(page, limit)`
- `dify_add_document_by_text(dataset_id, name, text, process_mode, indexing_technique)`
- `dify_add_document_by_file(dataset_id, file_path, process_mode, indexing_technique)`
- `dify_list_documents(dataset_id, page, limit)`
- `dify_get_indexing_status(dataset_id, document_id)`

## 常见错误规避

- 文档创建需先 /files/upload 再 /datasets/{id}/documents（Dify 1.14+ 必须）
- indexing-status 端点是 GET 不是 POST
- 高质量索引需先配置 embedding 模型
- 文件大小限制 15MB（pdf）/ 10MB（其他）
