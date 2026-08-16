"""WorkBuddy 用量采集（本地，读 workbuddy.db）。

WorkBuddy 把每次会话的累计用量存在自身运行库：
  ~/.workbuddy/workbuddy.db
其中：
  - session_usage.used       : 该会话累计消耗（token / 积分；size 字段恒为 192000，疑似配额上限）
  - session_usage.updated_at : 毫秒时间戳
  - sessions.model           : 模型名（如 "hy3"）
  - sessions.created_at      : 毫秒时间戳
  - sessions.id == session_usage.session_id

约束（来自 aggregate.py）：
  - 聚合只认 requests / input_tokens / output_tokens 三个数值字段，
    Record.to_dict() 不含 total_tokens 属性，因此必须把 used 落到 input/output 上。
  - 本库只有每会话累计 used，无 input/output 拆分、无 requests 计数：
    我们把 used 整体计入 input_tokens（total_tokens = used），requests 按每会话计 1。

健壮性：
  - db 为 WorkBuddy 运行时持有，用只读 URI 连接 + busy_timeout 规避文件锁。
  - 路径跨平台自动探测（~/.workbuddy / ~/WorkBuddy / %APPDATA%/WorkBuddy）。
  - date 维度取 sessions.created_at 的本地日期（会话归属创建日）。
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from . import Record


def _find_db(cfg: dict) -> str | None:
    if cfg.get("db_path"):
        return cfg["db_path"]
    home = Path.home()
    candidates = [
        home / ".workbuddy" / "workbuddy.db",
        home / "WorkBuddy" / "workbuddy.db",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "WorkBuddy" / "workbuddy.db")
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def collect(name: str, cfg: dict, date: str) -> list[Record]:
    db_path = _find_db(cfg)
    if not db_path:
        print(f"[warn] {name}: 未找到 WorkBuddy 数据库（~/.workbuddy/workbuddy.db），跳过")
        return []

    try:
        uri = Path(db_path).as_uri()
        con = sqlite3.connect(f"{uri}?mode=ro", uri=True)
        con.execute("PRAGMA busy_timeout=5000")
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute(
            """
            SELECT s.model      AS model,
                   s.created_at AS created_at,
                   COALESCE(u.used, 0) AS used
            FROM sessions s
            LEFT JOIN session_usage u ON u.session_id = s.id
            WHERE s.deleted_at IS NULL
            """
        ).fetchall()
        con.close()
    except Exception as e:
        print(f"[error] {name}: 读取 WorkBuddy 数据库失败: {e}")
        return []

    out = []
    for r in rows:
        created = r["created_at"]
        if not created:
            continue
        day = datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d")
        if day != date:
            continue
        used = int(r["used"] or 0)
        out.append(
            Record(
                source=name,
                model=r["model"] or "unknown",
                date=day,
                requests=1,  # 每会话计 1 次交互
                input_tokens=used,  # used 无法拆分 in/out，整体计入 input 作总量近似
                output_tokens=0,
            )
        )

    print(
        f"[ok] {name}: 当日 {len(out)} 个会话，累计 used="
        f"{sum(x.input_tokens for x in out)}"
    )
    return out
