#!/usr/bin/env bash
# 本机用量更新脚本（替代原云端 GitHub Action）
#
# 为什么不用 GitHub Action：
#   真实用量来自本机 ~/.workbuddy/workbuddy.db 等本地数据源，
#   云端 runner 访问不到，且原 Action 只跑 cloud 模式、还漏提交了
#   线上端点真正读取的 data/stats.json，所以永远更新不了。
#
# 本脚本在本机做「采集 → 汇总 → 推送」，让 GitHub 主页的
# Vercel 动态组件（https://llm-usage.vercel.app/widget.svg）自动刷新。
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

# —— 提交清单 ——
# 跑完采集/汇总后，需要 commit 并 push 到仓库、供线上端点读取的文件：
#   data/stats.json  —— 线上 Vercel 端点【实际读取】的数据源（必须提交）
#   data/daily.json  —— 汇总后的每日明细（历史留档）
#   data/local/      —— 本地采集的原始记录（回流留档）
# 注意：不再提交 assets/widget.svg（端点动态生成，该静态文件已废弃）
#       也不再碰 README.md（已固定嵌入 Vercel 动态地址）
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
