---
name: tampermonkey-shadow-dom-color-inheritance
description: Tampermonkey + Shadow DOM v1 中 color 修复必须区分「普通元素走继承」和「form 元素（textarea/input）被 UA 拦截」；`*` 直写 color 会破坏继承链
metadata:
  type: project
---

Tampermonkey 脚本注入到外部网站，用 Shadow DOM v1 隔离样式。当目标网站有暗色主题时，宿主 `<div>` 上设置的 `color: white` 会通过 **color 继承属性** 串到 shadow tree 里所有没显式声明 color 的元素，导致浅底白字看不见。修过 3 次才彻底对（0.2.19 → 0.2.20 → 0.2.21）。

## CSS 推理核心

| 选择器写法 | 命中范围 | 特异性 | 影响 |
|---|---|---|---|
| `:host { color: ... }` | 仅 host 元素本身 | 0,0,1,0 | descendants 通过**继承**拿默认；子元素的 class 显式 color 继续胜出 |
| `:host, * { color: ... }` | host + 所有 descendants | 命中 `*` 时 0,0,0,0 | **直写覆盖**：所有元素被强制写死，**继承链被截断**——子元素不再继承祖先的 `#fff` / `#f3f4f6`，全变成 `#1F1E1B` 黑字 |
| `#id { color: ... }` | 匹配该 id 元素 | 0,1,0,0 | 永远胜 UA/继承；**必加给 form 元素（textarea / input / select）** |

## 3 个版本各自的根因

- **0.2.18 之前**：完全没设 color，宿主页面暗色 → 全部继承白字 → 米色/白底看不见
- **0.2.19**: 在 `:host, * { color: #1F1E1B }` 设默认。`*` 直写破坏继承：**「Dify Claude 助手」标题、状态图标、bridge 徽章、调试面板子项** 全部变黑字，导致橙底白字（标题栏设计意图）失效 + 调试面板深灰底完全看不见
- **0.2.20**: 把 color 从 `*` 收回 `:host` 上，descendants 走继承。修复普通元素，**但 textarea 仍有问题**
- **0.2.21**: `<textarea>` 是 form 元素，UA 样式表显式设 `color: CanvasText` / `field-text`，叠加暗色页面 `<meta name="color-scheme">` 时**拦截从 `:host` 的继承**。必须 ID 选择器 `#dcfw-chat-input { color: ... }`（特异 0,1,0,0）直接覆盖

## Why: 跨 3 个 patch 才彻底对（2026-07-04 这次体感最深）

- 之前 0.2.18 修了 thinking 折叠 + 横向滚动条，让用户终于觉得好用 → 立刻报下一个视觉问题
- 0.2.19 一开始我自信满满 —— `*` 特异性最低、子元素 class 更高肯定胜出，**漏算了 `*` 仍然在子元素身上直写了 color 这一事实**（低特异性 ≠ 不生效，是直接生效压过继承）
- 0.2.20 用户报回归才意识到这个
- 0.2.21 又因为 form 元素特殊 UA 再补一刀

## How to apply

下次任何人（自己或同事）写 **Tampermonkey / 用户脚本 + Shadow DOM** 主题适配，**默认三件套一起写**：

```css
:host {
  color: #1F1E1B;  /* 默认深字，descendants 继承 */
}
:host, * {
  font-family: ...;  /* 字体可放这里无害 */
}
#script-input,
#script-textarea,
#script-select {
  color: #1F1E1B;          /* form 元素直写，覆盖 UA + color-scheme */
  caret-color: #1F1E1B;    /* 光标同步 */
}
#script-other-input {     /* 其他 form 元素同理 */
  color: #1F1E1B;
}
```

**调试清单**（用户报"暗色网站下面板看不清"时）：

1. 先 F12 看 Computed → color 实际值，确认是 inherit 自外部还是真被某个样式改写
2. 普通元素（div/span）走继承路径：检查 `:host` 是否设 color
3. form 元素（input/textarea/select）默认不继承：必须 ID 选择器直写
4. **绝不在用户脚本 CSS 里写 `:host, * { color: ... }` 这种全星模式**，宁可多写几条

## 涉及文件

- `tampermonkey/dify-claude-floating-window.user.js` (0.2.21)
- `tampermonkey/dify-claude-floating-window-remote.user.js` (0.2.21-remote)
- 双脚本 `:host` 规则在该文件的 STYLES 字符串顶部
- `#dcfw-chat-input` 规则在后半段

## 相关

- [[dify-patch-first-compare-normal-node]] —— PATCH 类的调试协议（"对比正常节点" SOP）
- [[dify-code-node-outputs-require-value-type]] —— 字段缺失类 bug 沉淀范例
