#!/usr/bin/env bash
# 本机用量更新脚本：采集 → 写原始数据 → 推送。
#
# 采集必须在本机跑：认证要用本机 Cursor 的登录态（state.vscdb 里的 access token），
# 云端 runner 读不到。本脚本只推送「原始数据」，产物（stats.json 与 assets/*.svg）
# 交给 GitHub Actions 生成。
#
# 用法（仓库根目录）：
#   ./update-local.sh
#   SINCE=2026-07-01 ./update-local.sh     # 临时改采集起点
#
# 前置：
#   - Python 3.12+，已装依赖（python3 -m venv .venv && .venv/bin/pip install -r requirements.txt）
#   - 已从 config/sources.example.yaml 复制出 sources.yaml
#   - 本机登录着 Cursor（或设置了 CURSOR_SESSION_TOKEN）
#
# 每次都重采 [起点, 今天] 全量并覆盖写回，所以采集幂等：漏跑几天补跑一次即可，
# 不会产生重复记录，也不会因为漏跑而永久丢数据（用量历史在 Cursor 账号侧）。
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

echo "==> 采集并汇总"
if [ -n "${SINCE:-}" ]; then
  "$PY" run.py --since "$SINCE"
else
  "$PY" run.py
fi

# 只提交原始数据。产物由 CI 生成，本机不碰，避免两台机器争同一个文件。
echo "==> 同步远端"
git pull --rebase --autostash origin main

echo "==> 提交原始数据"
git add data/raw
if git diff --cached --quiet; then
  echo "无变更，跳过提交。"
  exit 0
fi

git commit -m "chore(data): usage raw @ $(date +%F)"

# 推送失败几乎总是因为另一台机器刚推过，rebase 后重试一次即可。
#
# Cursor 的用量来自账号级接口，两台机器采到的是同一份数据、写同一个文件，所以这里
# 确实可能撞上冲突（不像按机器分片那样天然无冲突）。但两边的内容是同一份数据的快照，
# 取任意一边都对，之后任何一次采集都会把它重写成最新的完整状态。
if ! git push origin main; then
  echo "==> 推送被拒，重新 rebase 后再试"
  git pull --rebase --autostash origin main
  git push origin main
fi

echo "==> 已推送。GitHub Actions 会重新生成 stats.json 与 SVG，README 随之刷新。"
