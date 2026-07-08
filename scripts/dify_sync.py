#!/usr/bin/env python3
"""Dify 源码增量同步（★ 网络恢复后才跑）

P4 任务 #32：每周跑一次，自动 re-fetch langgenius/dify 仓库 + 检测 drift。
当 `curl raw.githubusercontent.com` + GitHub API + gh CLI + WebFetch 全数恢复时启用。

用法：
  python scripts/dify_sync.py                  # 增量 sync 默认 tag（1.14.2）
  python scripts/dify_sync.py --tag 1.15.0     # 切到新 tag（升级 Dify 后）
  python scripts/dify_sync.py --dry-run        # 只检查不写文件
  python scripts/dify_sync.py --cron           # 输出 cron 表达式

输出：
  - 更新 docs/dify-raw/ 下的 7 节点 entities.py + workflow engine + DSL service
  - 在 FETCH_LOG.md 追加抓取记录
  - 检测到 breaking change → 在 CLAUDE.md 顶部加 ⚠️ 警告条
  - 检测到 schema drift → 跑 scripts/dify_schema.py drift 对比
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_ROOT = SCRIPT_DIR.parent
DIFY_RAW = HELPER_ROOT / "docs" / "dify-raw"
FETCH_LOG = DIFY_RAW / "FETCH_LOG.md"
CLAUDE_MD = HELPER_ROOT / "CLAUDE.md"

DEFAULT_TAG = "1.14.2"

# 抓取清单（与 docs/dify-raw/README.md 第 3 节同步；B1 精简版）
NODES_7 = [
    "agent", "datasource", "knowledge_index", "knowledge_retrieval",
    "trigger_plugin", "trigger_schedule", "trigger_webhook",
]
# 可选扩展（--fetch-engine 时拉回；默认不抓，B1 决策 2026-07-04）
GRAPH_ENGINE = [
    "graph_topology", "node_factory", "node_runtime", "workflow_entry",
    "system_variables", "variable_pool_initializer", "template_rendering",
    "variable_prefixes", "human_input_adapter",
]
EXTRA_FILES = {
    "api_console/app_dsl_service.py": "api/services/app_dsl_service.py",
    "api_console/pyproject.toml": "api/pyproject.toml",
}


def curl_raw(tag: str, repo_path: str, dest: Path) -> tuple[bool, int, str]:
    """curl raw.githubusercontent.com 抓单个文件。返回 (success, size, error_msg)"""
    url = f"https://raw.githubusercontent.com/langgenius/dify/{tag}/{repo_path}"
    try:
        with urlopen(url, timeout=8) as r:
            data = r.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True, len(data), ""
    except (URLError, TimeoutError, OSError) as e:
        return False, 0, str(e)
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"


def fetch_all(tag: str, dry_run: bool = False, fetch_engine: bool = False) -> dict:
    """抓全部清单（B1 默认只抓 7 节点；--fetch-engine 时拉 graph_engine + api_console）

    返回 report dict
    """
    report = {
        "tag": tag,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "nodes": {},
        "engine": {},
        "extra": {},
        "failures": [],
    }

    # 7 官方节点（B1 默认必抓）
    for node in NODES_7:
        repo_path = f"api/core/workflow/nodes/{node}/entities.py"
        dest = DIFY_RAW / "nodes" / node / "entities.py"
        if dry_run:
            report["nodes"][node] = ("DRY_RUN", 0, "")
            continue
        ok, size, err = curl_raw(tag, repo_path, dest)
        report["nodes"][node] = ("OK" if ok else "FAIL", size, err)
        if not ok:
            report["failures"].append(f"nodes/{node}/entities.py: {err}")

    # 可选扩展（仅 --fetch-engine 时拉）
    if fetch_engine:
        for fname in GRAPH_ENGINE:
            repo_path = f"api/core/workflow/{fname}.py"
            dest = DIFY_RAW / "graph_engine" / f"{fname}.py"
            if dry_run:
                report["engine"][fname] = ("DRY_RUN", 0, "")
                continue
            ok, size, err = curl_raw(tag, repo_path, dest)
            report["engine"][fname] = ("OK" if ok else "FAIL", size, err)
            if not ok:
                report["failures"].append(f"graph_engine/{fname}.py: {err}")

        for dest_rel, repo_path in EXTRA_FILES.items():
            dest = DIFY_RAW / dest_rel
            if dry_run:
                report["extra"][dest_rel] = ("DRY_RUN", 0, "")
                continue
            ok, size, err = curl_raw(tag, repo_path, dest)
            report["extra"][dest_rel] = ("OK" if ok else "FAIL", size, err)
            if not ok:
                report["failures"].append(f"{dest_rel}: {err}")

    return report


def append_fetch_log(report: dict) -> None:
    """追加一行到 FETCH_LOG.md"""
    if not FETCH_LOG.exists():
        return
    n_total = len(report["nodes"]) + len(report["engine"]) + len(report["extra"])
    n_fail = len(report["failures"])
    line = (
        f"\n## {report['timestamp']} — re-fetch (tag={report['tag']})\n\n"
        f"- **tag**: {report['tag']}\n"
        f"- **触发**: dify_sync.py 自动 / 手动\n"
        f"- **抓取项**: {n_total}\n"
        f"- **失败**: {n_fail}\n"
    )
    if n_fail:
        line += f"- **失败清单**:\n"
        for f in report["failures"]:
            line += f"  - {f}\n"
    with FETCH_LOG.open("a", encoding="utf-8") as f:
        f.write(line)


def detect_drift() -> dict | None:
    """调用 scripts/dify_schema.py drift，返回解析结果"""
    cli = SCRIPT_DIR / "dify_schema.py"
    if not cli.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(cli), "drift"],
            capture_output=True, text=True, timeout=10,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Dify 源码增量同步")
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"Dify git tag（默认 {DEFAULT_TAG}）")
    parser.add_argument("--dry-run", action="store_true", help="只检查不写文件")
    parser.add_argument("--cron", action="store_true", help="输出 cron 表达式（每周一 9:00）")
    parser.add_argument("--fetch-engine", action="store_true",
                        help="同时抓回 graph_engine/ + api_console/（B1 默认不抓）")
    args = parser.parse_args()

    if args.cron:
        print("# 每周一上午 9:17 跑（避开整点高峰）")
        print("17 9 * * 1 cd /home/sutai/dify-helper && /opt/anaconda3/bin/python scripts/dify_sync.py >> /tmp/dify_sync.log 2>&1")
        return 0

    mode = "full (含 engine)" if args.fetch_engine else "B1 精简 (7 节点)"
    print(f"━━━ Dify 源码同步（tag={args.tag}, mode={mode}, dry_run={args.dry_run}）━━━\n")
    report = fetch_all(args.tag, dry_run=args.dry_run, fetch_engine=args.fetch_engine)

    n_total = len(report["nodes"]) + len(report["engine"]) + len(report["extra"])
    n_fail = len(report["failures"])
    print(f"抓取: {n_total} 文件，失败 {n_fail}")
    if n_fail:
        print("失败清单:")
        for f in report["failures"]:
            print(f"  - {f}")
        print("\n⚠️  全失败可能是网络问题。回退方案：AskUserQuestion 让用户协助。")
        return 1

    if not args.dry_run:
        append_fetch_log(report)
        print(f"✅ FETCH_LOG.md 已更新")

    # Drift 检测
    print("\n━━━ Schema Drift 检测 ━━━")
    drift = detect_drift()
    if drift is None:
        print("⚠️  dify_schema.py 不存在，跳过 drift 检测")
    elif drift["exit_code"] == 0:
        print("✅ 无 drift")
    elif drift["exit_code"] > 0:
        print("⚠️  发现 drift：")
        print(drift["stdout"])
        print("\n建议：修 _NODE_SCHEMAS 字典（mcp_server/server.py:155）+ scripts/dify_schema.py _NODE_REGISTRY")
        return 1
    else:
        print(f"⚠️  drift 检测失败: {drift['stderr']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())