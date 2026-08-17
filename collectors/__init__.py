"""采集层：数据契约（``Event``）、原始数据读写、以及 SQLite 快照工具。

每个采集器暴露 ``collect(ctx, cfg) -> list[Event]``，只负责把某个源的用量翻译成
``Event``，不碰文件系统。落盘、聚合、渲染都在采集器之外，方便单独测试。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

# 允许的计量单位。不同源的口径天然不同，聚合时按 unit 分桶，绝不跨单位相加。
UNITS = ("requests", "sessions", "tokens", "credits", "lines")


@dataclass(frozen=True)
class Event:
    """一条用量记录：某台机器、某个源、某个模型，在某一天用掉了 ``amount`` 个 ``unit``。

    ``amount_in`` / ``amount_out`` 只在源能拆分输入输出时才有值（目前仅 OpenAI 兼容
    接口能给），拆不开的源留 ``None``，而不是把总量硬塞进 input 字段假装拆开过。
    """

    date: str                      # YYYY-MM-DD，按配置时区计算
    machine: str                   # 采集机器，如 work-mac / home-win
    source: str                    # ADE 名，如 cursor / openai
    model: str
    unit: str
    amount: int
    amount_in: int | None = None
    amount_out: int | None = None
    surface: str | None = None      # 源内部的细分入口，如 composer / cli / tab
    note: str | None = None         # 口径说明，供日后回看，不参与计算

    def __post_init__(self):
        if self.unit not in UNITS:
            raise ValueError(f"未知 unit: {self.unit}（允许 {UNITS}）")

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CollectContext:
    """采集器需要的环境信息，由 run.py 组装后传入。"""

    machine: str
    tz: tzinfo
    root: Path
    # 回看天数：对「可按日重新查询」的源（Cursor、云端 API），每次重采最近这些天，
    # 覆盖式写回，使采集幂等；对累计型源（差分）无意义。
    lookback_days: int = 30

    def day_of(self, ms: int) -> str:
        """毫秒时间戳 → 配置时区下的 YYYY-MM-DD。"""
        return datetime.fromtimestamp(ms / 1000, self.tz).strftime("%Y-%m-%d")

    def today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def recent_days(self, days: int) -> list[str]:
        """回看窗口内的日期列表，含今天，升序。"""
        end = datetime.now(self.tz).date()
        return [(end - timedelta(days=offset)).isoformat()
                for offset in range(days - 1, -1, -1)]

    def day_of_start_ms(self, days: int) -> int:
        """回看窗口第一天的零点，转成毫秒时间戳，供 SQL 过滤用。"""
        first = datetime.now(self.tz).date() - timedelta(days=days - 1)
        start = datetime(first.year, first.month, first.day, tzinfo=self.tz)
        return int(start.timestamp() * 1000)


# ---------------------------------------------------------------- 原始数据读写

def _raw_path(root: Path, machine: str, source: str, month: str) -> Path:
    return root / "data" / "raw" / machine / source / f"{month}.json"


def write_events(root: Path, machine: str, source: str, events: list[Event],
                 days: list[str]) -> None:
    """把 ``events`` 写入按月分片的原始文件，并覆盖 ``days`` 覆盖到的那些天。

    ``days`` 是本次采集「负责」的日期列表：这些天在文件里的旧内容会被整体替换，
    没被列出的天原样保留。这让采集可以重复运行而不产生重复记录，也不会因为
    某天恰好没有用量就把旧数据留成幽灵。

    文件路径含 ``machine``，所以两台机器永远写不同文件，git 层面不存在并发修改。
    """
    by_month: dict[str, dict[str, list[dict]]] = {}
    for day in days:
        by_month.setdefault(day[:7], {})[day] = []
    for e in events:
        by_month.setdefault(e.date[:7], {}).setdefault(e.date, []).append(e.to_dict())

    for month, fresh_days in by_month.items():
        path = _raw_path(root, machine, source, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"machine": machine, "source": source, "month": month, "days": {}}
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[warn] {path} 解析失败（{exc}），按空文件重建")
        doc.setdefault("days", {}).update(fresh_days)
        doc["days"] = {d: doc["days"][d] for d in sorted(doc["days"])}
        doc["machine"], doc["source"], doc["month"] = machine, source, month
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def read_all_events(root: Path) -> list[dict]:
    """读取 data/raw 下所有机器、所有源、所有月份的事件，供聚合使用。"""
    out: list[dict] = []
    raw = root / "data" / "raw"
    if not raw.exists():
        return out
    for path in sorted(raw.glob("*/*/*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[warn] 读取 {path} 失败: {exc}")
            continue
        for day, rows in (doc.get("days") or {}).items():
            for row in rows:
                row.setdefault("date", day)
                row.setdefault("machine", doc.get("machine", "unknown"))
                row.setdefault("source", doc.get("source", "unknown"))
                out.append(row)
    return out


# ------------------------------------------------------------- SQLite 快照工具

@contextmanager
def sqlite_snapshot(db_path: str | Path):
    """把 SQLite 库连同 -wal / -shm 复制到临时目录后再打开，读完即删。

    这类库（如 Cursor 的 ai-code-tracking.db）在采集时正被宿主程序持有并以 WAL 模式
    写入。直接以只读模式打开 WAL 库需要对 -wal/-shm 有写权限，容易失败或读到不完整
    数据；加 immutable=1 又会忽略 WAL 里尚未 checkpoint 的部分，漏掉最近的记录。
    复制一份再读可以同时避开这两个问题，也完全不干扰宿主。
    """
    src = Path(db_path)
    with tempfile.TemporaryDirectory(prefix="llm-usage-") as tmp:
        dst = Path(tmp) / src.name
        shutil.copy2(src, dst)
        for suffix in ("-wal", "-shm"):
            side = src.with_name(src.name + suffix)
            if side.exists():
                shutil.copy2(side, dst.with_name(dst.name + suffix))
        con = sqlite3.connect(str(dst))
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()


def find_db(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None
