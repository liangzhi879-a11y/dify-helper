# skills/ 目录迁移说明

## 状态

**已废弃** —— 本目录的 .md 文件**不再被 Claude Code 加载**。

## 新位置

Dify 调试专属 Skill 全部迁移到 `/home/sutai/dify-helper/.claude/skills/<name>/SKILL.md`（Claude Code 官方 Skill manifest 格式）。

## 为什么废弃

1. **格式不对**：Claude Code 扫描 `.claude/skills/<name>/SKILL.md`，本目录是 `<name>.md`，harness 找不到
2. **CLAUDE.md 误导**：旧 CLAUDE.md 声称 13 个 Skill 自动激活，实际是 0 个
3. **没有 description 字段**：旧文件有 `name` / `trigger` / `priority`，但**缺 `description`**——harness 靠 description 匹配用户意图

## 旧文件保留的原因

- **git 历史**：保留可回看，删除会丢 commit
- **参考价值**：旧文件的 trigger 关键词、frontmatter 字段定义是新 SKILL.md 的参考

## 新旧对应表

| 旧文件 | 新 Skill |
|---|---|
| `dify-app-architect.md` | `.claude/skills/dify-app-architect/SKILL.md` |
| `dify-workflow-builder.md` | **拆分**为 `dify-workflow-canvas-debugger` + `dify-loop-iteration-builder` |
| `dify-dataset-curator.md` | `.claude/skills/dify-dataset-curator/SKILL.md` |
| `dify-dsl-importer.md` | `.claude/skills/dify-dsl-importer/SKILL.md` + `dify-dsl-architect` |
| `dify-prompt-engineer.md` | `.claude/skills/dify-prompt-engineer/SKILL.md` |
| `dify-model-router.md` | `.claude/skills/dify-model-router/SKILL.md` + `dify-model-provider-checker` |
| `dify-debug-runner.md` | `.claude/skills/dify-debug-runner/SKILL.md` + `dify-render-error-debugger` |
| `systematic-thinking.md` | `.claude/skills/systematic-thinking/SKILL.md`（强化） |
| `bug-diagnostician.md` | `.claude/skills/bug-diagnostician/SKILL.md`（强化 + 翻车复盘） |
| `code-review-strict.md` | **不迁移**（与 DIFY 专精定位冲突） |
| `refactor-patterns.md` | **不迁移**（与 DIFY 专精定位冲突） |
| `security-mindset.md` | **不迁移**（与 DIFY 专精定位冲突） |
| `test-first-thinking.md` | **不迁移**（与 DIFY 专精定位冲突） |

**最终新 Skill 数：15 个**（13 旧 → 15 新，其中 2 拆分 + 2 拆分 + 4 不迁移 + 4 新增专项）。

详见 `.claude/skills/_EXCLUDED.md`。

## 如何清理（可选）

如果确定不再需要旧文件，可以删除整个 `skills/` 目录：

```bash
rm -rf /home/sutai/dify-helper/skills/
```

**注意**：删除前确认 git 已 commit 旧文件（`git log --follow skills/dify-app-architect.md`）。

## 验证新 Skill 生效

1. 重启 Claude Code 在 `/home/sutai/dify-helper/`
2. 输入 `/skills` 看是否能列出 DIFY 专属 skill
3. 输入"渲染此组件时发生了意外错误" → 应自动加载 `dify-render-error-debugger`

## 时间

迁移完成：2026-07-01
依据：`/home/sutai/.claude/plans/zany-snacking-liskov.md` 计划