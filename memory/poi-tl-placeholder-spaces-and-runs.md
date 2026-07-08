---
name: poi-tl-placeholder-spaces-and-runs
description: DocHub/Poi-tl 1.12.2 模板 docx 占位符 0 MetaTemplates 的双层 bug：跨 run 切碎 + 占位符内空格
metadata:
  type: feedback
---

# DocHub (Poi-tl 1.12.2) 模板解析"0 MetaTemplates"双层 bug

**症状**：DocHub /api/v1/generate 返回成功 HTTP 200 + 200KB docx，但 docx 里 28+ 个 `{{ xxx }}` 占位符**完全没替换**。DocHub-app 日志显示：

```
Resolve the document end, resolve and create 0 MetaTemplates.
Render template start...
Successfully Render template in 0 millis
```

**根因（双层，独立修复都无效）**：

1. **Bug A — 跨 run 切碎**：Word 自动拼写检查把 `{{ project_year }}` 切成 4-6 个独立 `<w:r>`：
   ```
   <w:r><w:t>{{ </w:t></w:r>
   <w:r><w:t>project_</w:t></w:r>
   <w:r><w:t>year</w:t></w:r>
   <w:r><w:t> }}</w:t></w:r>
   ```
   Poi-tl 1.12.2 `TemplateResolver` **不跨 run 拼接**，每个 run 单独匹配 → 0 MetaTemplates。

2. **Bug B — 占位符内空格（更隐蔽！）**：Poi-tl 1.12.2 默认 `DEFAULT_GRAMER_REGEX` 不识别 `{{ var }}`（含空格），只识别 `{{var}}`（无空格）。`{{ name }}` 测试 100% 失败，`{{name}}` 100% 成功。schema 提取（上传时）和 generate 渲染（TemplateResolver）用不同 parser，所以 schema 完整但渲染失败。

**修复方法（两步都做）**：

```python
# Step 1: 合并 {{ 到 }} 之间所有 run，删中间 w:proofErr
def merge_one(p, max_passes=30):
    for _ in range(max_passes):
        children = list(p._p)
        n_open = n_close = -1
        for i, c in enumerate(children):
            if c.tag != qn('w:r'):
                continue
            text = ''.join(t.text or '' for t in c.findall(qn('w:t')))
            if n_open == -1:
                if '{{' in text and '}}' not in text:
                    n_open = i
            else:
                if '}}' in text and '{{' not in text:
                    n_close = i; break
        if n_open == -1 or n_close == -1:
            break
        runs_in_range = [c for c in children[n_open:n_close+1] if c.tag == qn('w:r')]
        merged = ''.join(''.join(t.text or '' for t in r.findall(qn('w:t'))) for r in runs_in_range)
        first = runs_in_range[0]
        for t in first.findall(qn('w:t')): first.remove(t)
        new_t = etree.SubElement(first, qn('w:t'))
        new_t.text = merged
        new_t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        for r in runs_in_range[1:]: p._p.remove(r)
        for c in list(p._p)[n_open:n_close+1]:
            if c.tag == qn('w:proofErr'): p._p.remove(c)

# Step 2: 去占位符内边界空格（保留 {{r 和 name 之间的空格）
def smart_strip(p):
    for t in p._p.findall('.//' + qn('w:t')):
        if not t.text or '{{' not in t.text: continue
        new = t.text
        new = re.sub(r'\{\{ +([^{}][^{}]*?) +\}\}', r'{{\1}}', new)        # {{ xxx }} → {{xxx}}
        new = re.sub(r'\{\{r +([^{}][^{}]*?) +\}\}', r'{{r \1}}', new)    # {{r xxx }} → {{r xxx}}
        if new != t.text: t.text = new
```

**Why**：单跑 Step 1 (跨 run 合并) 仍 0 MetaTemplates → 必须 Step 2 (去空格)。单跑 Step 2 也不行（仍跨 run）。两个独立 bug 叠加。

**已知限制**：
- Poi-tl 1.12.2 不支持 `{{r xxx}}` 富文本（需 1.13+）。模板里 `project_intro` / `tech_innovation` / `project_deliverables` / `project_achievements` / `comprehensive_profits` 这 5 个富文本字段，docx 里仍残留 `{{r xxx}}`，需要升级 DocHub 内 Poi-tl 到 1.13+ 才能渲染。

**How to apply**：
- DocHub 模板生成失败、docx 占位符不替换时 → 第一查 `Resolve the document end, resolve and create X MetaTemplates` 日志，X = 0 → 跑 Step 1+2 修模板 docx。
- 对应本仓库 `_patch42_docx_template_normalize.py`（已写入 backups/_tmp_scripts/）。
- DocHub 容器里的模板文件路径：`/app/data/templates/tenant_default/word/{templateId}.docx`，可用 `docker cp` 覆盖（**注意权限，要先 chown 到容器内 uid=1000**）。
- 关联：[[dify-plugin-tool-node-outputs-no-json-key]]（PATCH 41 教训）— plugin 层问题；本条是 DocHub/Poi-tl 层问题。