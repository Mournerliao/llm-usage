#!/usr/bin/env bash
# 本机用量更新脚本
#
# 真实用量来自本机数据源（如 ~/.workbuddy/workbuddy.db），云端 runner 无法访问，
# 因此在本机运行本脚本完成「采集 → 汇总 → 推送」，让 GitHub 主页与博客组件自动刷新。
#
# 用法（仓库根目录，Git Bash 中运行）：
#   ./update-local.sh
#
# 前置：
#   - Python 3.11+，且已 `pip install -r requirements.txt`
#   - 本机存在数据源（如 ~/.workbuddy/workbuddy.db）
#   - git remote 已指向 Mournerliao/llm-usage，且能 push
#
set -euo pipefail
cd "$(dirname "$0")"

# 选取可用的 python 解释器
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "错误：未找到 python / python3，请先安装 Python 3.11+" >&2
  exit 1
fi

DATE="$(date -u +%Y-%m-%d)"

echo "==> 采集本地用量并汇总（date=$DATE）"
"$PY" run.py --mode local --date "$DATE"

# 提交清单：本次需推送到仓库、供线上端点读取的文件
#   data/stats.json  —— 线上 Vercel 端点实际读取的数据源（必须提交）
#   data/daily.json  —— 汇总后的每日明细（历史留档）
#   data/local/      —— 本地采集的原始记录（回流留档）
COMMIT_LIST="data/stats.json data/daily.json data/local/"

echo "==> 提交变更"
git add $COMMIT_LIST
if git diff --cached --quiet; then
  echo "无变更，跳过提交。"
else
  git commit -m "chore: update usage stats ($DATE)"
  git push origin main
  echo "==> 已推送，线上组件将在数分钟内刷新（GitHub camo 缓存约 5~10 分钟）。"
fi
