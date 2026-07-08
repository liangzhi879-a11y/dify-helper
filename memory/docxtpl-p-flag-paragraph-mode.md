---
name: docxtpl-p-flag-paragraph-mode
description: docxtpl 模板的 {{p var }} 标志必须加在多段落富文本字段上，否则 LLM 输出的 \n\n 会被丢成软回车或空格，整段挤在一个 w:p 里
metadata:
  type: project
---

**症状**: 模板用 `{{ project_intro }}` 渲染 LLM 输出的多段文本，结果输出的 docx 里整段是一坨（300+ 字挤一个 `<w:p>`），没有段落分隔；用户报告"软回车"。

**根因**: docxtpl 默认 `{{ var }}` 不保留 `\n`：
- 无标志：换行被丢，变空格或软回车
- `{{p var }}`：paragraph mode，`\n` 转 `<w:p>` 边界，`\n\n` 转 2 个段落（**推荐多段文本**）
- `{{r var }}`：rich text（保留 XML 转义）
- `{{rp var }}`：rich + paragraph（要 XML 内嵌时才需要）

**Why**: docxtpl 内部把 placeholder 当 Jinja2 表达式处理；默认渲染只把变量值塞当前 `<w:r><w:t>`，跨 `<w:p>` 边界要 `p` 标志触发"split by newline"。

**How to apply**:
1. 改模板时搜 `{{ var }}`，如果 var 装的是 LLM 多段输出（项目简介/技术内容/验收总结等），加 `p` 标志
2. 修改流程：unzip docx → 改 `word/document.xml` 字符串 → 重 zip → `docker cp` 覆盖
3. 备份原 docx（`cp ... .bak.<日期>`）再覆盖
4. 验证：跑 workflow，解包输出的 docx，统计 `<w:p>` 数（应该 30+ 而不是 5）

**反查表**:
| 症状 | 根因 | 修复 |
|---|---|---|
| 整段挤一个段落 | 缺 `p` 标志 | 改模板加 `{{p var }}` |
| 出现字面 `{{ var }}` 文本 | 模板被 raw 透传 / DocHub 渲染失败 | 看 DocHub run trace + 检查 tool_parameters.data_json |
| 出现 `<br/>` 软回车 | 模板用 `{{r }}` 但 docxtpl 渲染时 newline 行为 | 改 `{{rp var }}` 或 `{{p var }}` |

**关联**: [[dify-dochub-template-id-must-be-uuid]]（模板层 DocHub 基础）+ PATCH 47 脚本 `backups/_tmp_scripts/_patch47_docxtpl_p_flag.py`
