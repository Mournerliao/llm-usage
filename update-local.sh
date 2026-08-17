#!/usr/bin/env bash
# 本机用量更新脚本：采集 → 写原始数据 → 推送。
#
# 真实用量只存在于本机（如 ~/.cursor/ai-tracking/），云端 runner 读不到，
# 所以采集必须在本机跑。本脚本只推送「原始数据」，产物（stats.json 与 assets/*.svg）
# 交给 GitHub Actions 生成 —— 这样两台机器永远不会同时改同一个文件。
#
# 用法（仓库根目录）：
#   ./update-local.sh
#
# 前置：
#   - Python 3.12+，已装依赖（python3 -m venv .venv && .venv/bin/pip install -r requirements.txt）
#   - 已从 config/sources.example.yaml 复制出 sources.yaml，并填好 machine
#
# 建议每天跑一次（cron / 任务计划程序）。Cursor 的追踪库只保留最近约一个月，
# 长期不跑会让更早的数据滚出窗口后永久丢失。
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "错误：未找到 python3，也没有 .venv" >&2
  exit 1
fi

LOOKBACK="${LOOKBACK:-30}"

echo "==> 采集并汇总（回看 ${LOOKBACK} 天）"
"$PY" run.py --lookback "$LOOKBACK"

# 只提交原始数据。产物由 CI 生成，本机不碰，避免两台机器争同一个文件。
echo "==> 同步远端"
git pull --rebase --autostash origin main

echo "==> 提交原始数据"
git add data/raw
if git diff --cached --quiet; then
  echo "无变更，跳过提交。"
  exit 0
fi

MACHINE=$("$PY" -c "import config; print(config.load_sources_config()['machine'])")
git commit -m "chore(${MACHINE}): usage raw @ $(date +%F)"

# 推送失败几乎总是因为另一台机器刚推过，rebase 后重试一次即可。
# 原始数据按机器分片，两台机器改的是不同文件，rebase 不会有冲突要解。
if ! git push origin main; then
  echo "==> 推送被拒，重新 rebase 后再试"
  git pull --rebase --autostash origin main
  git push origin main
fi

echo "==> 已推送。GitHub Actions 会重新生成 stats.json 与 SVG，README 随之刷新。"
