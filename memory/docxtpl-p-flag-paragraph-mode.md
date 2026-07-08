---
name: poi-tl-p-flag-does-not-exist
description: DocHub 用 Poi-tl 1.12.2 (不是 docxtpl)，Poi-tl **全系列不支持** docxtpl 的 {{p var }} 段落标志；加了会让 placeholder 透传为字面文本
metadata:
  type: project
---

**症状**: 模板用 `{{p project_intro}}` 渲染 LLM 多段输出，结果**字面文本** `{{p project_intro}}` 原样输出到 docx（没有任何替换）。

**根因（实测 PATCH 47→51 验证）**:
- **DocHub 用 Poi-tl 1.12.2 (NOT docxtpl)** —— 参见 [[poi-tl-no-1-13-release]]
- Poi-tl 把整个 `{{ ... }}` 当 placeholder name lookup
- 看到 `{{p project_intro}}` → 在 dataJson 里找 key="p project_intro"（含空格）→ 找不到 → 透传 raw text
- docxtpl 的 `p` / `r` / `rp` 标志在 Poi-tl 0 识别 (字面 placeholder name 一部分)

**作者原 PATCH 47 翻车链**:
1. 想给多段 LLM 输出加 docxtpl paragraph mode (`{{p var }}`)
2. DocHub → Poi-tl → 把 `p project_intro` 当字面 placeholder 名字
3. 6 个字段输出 `{{p project_intro}}` 等字面文本
4. PATCH 51 revert: 把 6 个 `{{p var }}` 改回 `{{var }}` → 渲染正常

**当前 Poi-tl 处理 `\n` 的行为（无法在 template 层解决）**:
- `\n` → `<w:br w:type="textWrapping"/>` (软回车) —— **不是硬回车**
- 用户要求"硬回车去软回车"在 Poi-tl 1.12.2 + DocHub 当前实现下做不到

**Why**: Poi-tl 设计哲学是 simple text replacement；`\n → <w:br/>` 是 1.12.x 默认行为，没有 `\n → <w:p>` 边界 split 功能。需要等 Poi-tl 1.13+ 才可能有 paragraph mode（但 1.13 不存在，参见 [[poi-tl-no-1-13-release]]）。

**How to apply**:
1. **不要**给 DocHub 模板加 `{{p var }}` / `{{r var }}` / `{{rp var }}` 标志
2. 多段文本模板: **只写 `{{var }}`** (Poi-tl 兼容格式)
3. 接受 Poi-tl 默认 `\n → <w:br/>` 软回车；如需硬回车:
   - Option A: 改 DocHub 插件代码 (侵入性大)
   - Option B: LLM 输出预分段，每段独立 placeholder (`project_intro_p1`, `_p2`...)
   - Option C: post-process 用 python-docx 把 `<w:br/>` 拆段 (在 DocHub 容器后处理)
   - Option D: 让用户接受软回车
4. 改模板后必跑一次 DocHub generate，**检查字面 `{{` 透传**

**反查表**:
| 症状 | 根因 | 修复 |
|---|---|---|
| 字面 `{{p var }}` 出现在 docx | DocHub 用 Poi-tl, 不支持 p 标志 | 改回 `{{var }}` |
| 字面 `{{r var }}` 出现 | 同上 | 同上 |
| 字面 `{{var }}` 出现 (无 p/r 前缀) | dataJson 缺字段 / DocHub render 失败 | 检查 dataJson key 是否一致 |
| 多段文本挤一段 | Poi-tl `\n` 不拆段 | 接受软回车 / 用多 placeholder / post-process |

**关联**: [[poi-tl-no-1-13-release]] (Poi-tl 1.13 不存在, 1.12.2 是顶) + [[poi-tl-placeholder-spaces-and-runs]] (占位符跨 run + 空格双层 bug, PATCH 42) + [[dify-dochub-template-id-must-be-uuid]] (DocHub 基础) + PATCH 51 脚本 `backups/_tmp_scripts/_patch51_revert_p_flag_add_sectionbreak.py`
