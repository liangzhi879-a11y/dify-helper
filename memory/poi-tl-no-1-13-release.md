---
name: poi-tl-no-1-13-release
description: Poi-tl 1.13+ 不存在 — 项目在 v1.12.2 (2024-01-25) 之后基本停止活跃开发；任何"升级 Poi-tl 1.13+ 让富文本 {{r xxx}} 渲染"的设想都是基于错误信息
metadata:
  type: reference
---

# Poi-tl 1.13+ 不存在 — 升级路径不存在

**结论**：Poi-tl 没有 1.13+ 版本。WebSearch / 网络传言提到的 "Poi-tl 1.13.0" 是 AI 幻觉或基于过期信息。

**权威信号源**（2026-07-08 验证）：

| 信号源 | 验证方式 | 结果 |
|---|---|---|
| GitHub releases | `https://api.github.com/repos/Sayi/poi-tl/releases` | 最新 = **v1.12.2 (2024-01-25)** |
| GitHub tags | `https://api.github.com/repos/Sayi/poi-tl/tags` | 最高 = **v1.12.2** |
| Tencent Maven mirror | `https://mirrors.tencent.com/nexus/repository/maven-public/com/deepoove/poi-tl/maven-metadata.xml` | latest = `1.12.3-beta1` (2024-03-13) — **但 GitHub 无 tag 无 release，非正式构建** |
| 1.12.3-beta1 vs 1.12.2 类 diff | 仅 3 个文件不同：`StyleUtils.class` / `NiceXWPFDocument.class` / `MANIFEST` / `pom`；无新 class | bug fix only，无功能新增 |
| 1.13.0 在所有可达镜像 | Tencent / Aliyun / Maven Central 全 404 | **不存在** |

**关键事实**：
- **Poi-tl 项目在 v1.12.2 之后基本停止活跃开发**（最后 release 2024-01-25）
- **`{{r xxx}}` 富文本语法 Poi-tl 全系列不支持**（不是 1.12.2 的限制，是项目根本没实现）
- 1.12.3-beta1 是 Maven mirror 上的 beta build，未发布到 GitHub；只有 bug fix，无新功能

**Why**：避免反复触发"升级 Poi-tl 解决富文本问题"的无效 PATCH。

**How to apply**：
- 看到 "Poi-tl 1.13+ 升级" / "升级 poi-tl 让富文本生效" 等需求时 → **第一查本文件**，确认升级路径不存在
- DocHub 模板的 5 个富文本字段（`project_intro` / `tech_innovation` / `project_deliverables` / `project_achievements` / `comprehensive_profits`）的实际可行方案：
  - **A. 模板降级**：去掉 `r` 前缀 `{{r xxx}}` → `{{xxx}}`，丢富文本格式
  - **B. 接受残留**：docx 里残留 `{{r xxx}}` 字面量
  - **C. Fork DocHub**：高风险，需重打包 app.jar
- 关联：[[poi-tl-placeholder-spaces-and-runs]]（PATCH 42 修复 11/16 字段，5 字段富文本限制即本条）