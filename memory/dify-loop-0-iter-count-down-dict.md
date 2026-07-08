---
name: dify-loop-0-iter-count-down-dict
description: Dify loop variable 在 0 iter 时被包成 dict {"count_down": 1} 输出, 外部 code 节点 int(count_down) 直接 TypeError; 必须 _to_int() 防御性封装
metadata:
  type: project
---

## 症状
env=1 (RD_TOTAL_COUNT=1) → workflow 整体 fail, exit 255:
```
TypeError: int() argument must be a string, a bytes-like object or a real number, not 'dict'
File "/var/sandbox/.../task_summary_001.py", line 8, in main
    rd_count = int(count_down) if count_down else 0
```
task_summary_001 node 整个 fail, RD_count=0, outputs={}.

## 根因 (loop 0 iter 的特殊语义)
Dify loop 的 break condition `count_down ≥ env` 在 loop 开始前就检查:
- initial count_down = 1 (PATCH 21 为跳过 RD00 设置)
- env=1: 1 ≥ 1 → break 立即触发 → 0 iter
- 0 iter 时, Dify 把 loop 变量输出包成 dict: `{"count_down": 1}` (而不是 scalar 1)
- 外部 code 节点 `int(count_down)` 期望 scalar, 收到 dict → TypeError

## env 实际语义 (PATCH 36 doc 写错!)
| env 值 | iter 数 | 处理 RD |
|---|---|---|
| 1 | 0 | (无) |
| 2 | 1 | RD01 |
| 3 | 2 | RD01, RD02 |
| N+1 | N | RD01..RDN |

(PATCH 36 CHANGELOG 说"默认 6 → 跑 6 次"实际是 5 iters, doc 错了)

## 修复 (PATCH 31 + 32)
```python
# task_summary_001 顶部注入 _to_int 辅助
def _to_int(v):
    if v is None or v == '':
        return 0
    if isinstance(v, dict):
        # Dify wraps loop vars as {"<label>": value} on 0-iter case
        for k in ('count_down', 'value', 'count'):
            if k in v:
                try:
                    return int(v[k])
                except (TypeError, ValueError):
                    continue
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

# main() 中应用
rd_count = _to_int(count_down)  # 防御性 dict/scalar/None → int
```

## PATCH 31 的 bug → PATCH 32 修复
**PATCH 31 脚本错在**: check logic 顺序
```python
new_code = old_code.replace('int(count_down)', '_to_int(count_down)')  # ← 加了 _to_int
if "_to_int(" not in new_code:  # ← False! 因为刚加进去 → 函数定义注入被 skip
    # inject _to_int function
```
**结果**: live code 调 `_to_int(count_down)` 但**没有函数定义**, 运行时 NameError。

**PATCH 32 修复**: 直接 replace `def main(...)` 前插入 `def _to_int(v):...`, 不依赖 check。

## Why (为什么 Dify 这样设计)
- 0 iter 情况下, loop variables 应该有"虚拟"输出值, Dify 选择 dict 包一层让消费者区分"未跑 vs 跑到 N"
- 这是 Dify 1.14+ loop 0-iter 的隐式行为, 不在 schema 里, 只能实测发现

## How to apply
1. **任何外部 code 节点消费 loop variable 时**, 永远用 `_to_int()` / `_to_str()` / `_to_list()` 防御性封装, 不要相信 scalar
2. **PATCH 脚本的"check-then-act"逻辑要小心**: replace 后再 check "新内容是否存在" 永远 False, 应在 replace 前 check 旧内容是否存在
3. **不要凭 CHANGELOG 信任 env 语义**: 跑实测验证 iter 数
4. **env=N 要得到 N iter, 设 N+1** (因为 initial=1 跳过 RD00 + break 用 ≥)

## 关联
- [[dify-dochub-empty-date-cn-date-to-iso]] — 同一 E2E run 暴露的两个不同 bug (env=1 → 0 iter → task_summary int(dict) fail)
- [[dify-rd-total-count-patch-chain]] — env var + publish 方案, 但 env 语义本身有坑
- PATCH 31 脚本: `backups/_tmp_scripts/_patch31_task_summary_defensive.py`
- PATCH 32 脚本: `backups/_tmp_scripts/_patch32_inject_to_int_def.py`