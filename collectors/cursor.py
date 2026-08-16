"""Cursor 本地用量采集（需在本机运行）。

Cursor 把会话存进本地 SQLite：
  Windows: %APPDATA%/Cursor/User/workspaceStorage/*/state.vscdb
  macOS:   ~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb
其中 composer / 对话记录含 model 与 token 用量。

== 注意 == 具体表名/字段尚未在“细聊”阶段核实，下方为占位实现：
运行时会打印可用表结构，便于我们下一步补全字段映射。
"""
import glob
import os
import sqlite3
from . import Record


def _find_db(cfg: dict):
    pattern = os.path.expandvars(cfg.get("db_glob", ""))
    matches = sorted(glob.glob(pattern))
    return matches[0] if matches else None


def collect(name: str, cfg: dict, date: str) -> list[Record]:
    db_path = _find_db(cfg)
    if not db_path:
        print(f"[warn] {name}: 未找到 Cursor 数据库，跳过（需在本机运行）")
        return []

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        print(f"[debug] {name}: 数据库表 = {tables}")
        # TODO: 根据核实后的表结构，解析 model + promptTokens/completionTokens
        conn.close()
    except Exception as e:
        print(f"[error] {name}: 读取数据库失败: {e}")
        return []

    print(f"[todo] {name}: 字段映射待确认，暂返回空；下一步补全")
    return []
