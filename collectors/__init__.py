"""采集层：数据契约（``Event``）与原始数据读写。

每个采集器暴露 ``collect(ctx, cfg) -> list[Event]``，只负责把某个源的用量翻译成
``Event``，不碰文件系统。落盘、聚合、渲染都在采集器之外，方便单独测试。

== 为什么没有 unit 字段 ==

早先的契约有个 ``unit`` 字段（tokens / requests / sessions / credits），聚合时按它
分桶，防止把 token 和请求数加到一起。现在改成具名字段：token 的四个分类各占一个
字段，请求数和成本各占一个。这样「不同口径不能相加」变成了类型层面的事实——
``tokens_in`` 和 ``requests`` 是两个字段，根本没有把它们加起来的路径，不需要一层
分桶逻辑去拦。

拿不到 token 的源把四个 token 字段留 ``None``（不是 0）：``None`` 是「这个源不报
token」，0 是「报了，但确实是零」。展示层据此决定显示数字还是横线。

== 为什么没有 machine 字段 ==

Cursor 的用量来自账号级接口，两台机器采到的是同一份数据，按机器分片会导致重复
计数。所以原始数据只按源和月份分片，采集在哪台机器上跑不影响结果。将来若接入
只能在本机采到的源，再给它自己的分片键，不要把 machine 加回公共契约。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

# token 的四个分类。缓存读写的单价与输入输出差一个量级，合成一个总数会掩盖真相，
# 所以始终分开存，展示时再决定要不要合。
TOKEN_KINDS = ("tokens_in", "tokens_out", "cache_write", "cache_read")


@dataclass(frozen=True)
class Event:
    """某一天、某个源、某个模型上的用量。

    ``requests`` 是这一格里的调用次数，任何源都该能给出。四个 token 字段与
    ``cost_cents`` 只有能拿到真实明细的源才填。
    """

    date: str                        # YYYY-MM-DD，按配置时区计算
    source: str                      # 源名，如 cursor / openai
    model: str
    requests: int = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_write: int | None = None
    cache_read: int | None = None
    # token 按各模型单价折算出的成本，单位为「分」。刻意用浮点：单次调用的成本常
    # 在一分以下，取整会让求和系统性偏小。展示时才四舍五入到分。
    cost_cents: float | None = None
    note: str | None = None          # 口径说明，供日后回看，不参与计算

    @property
    def tokens_total(self) -> int | None:
        """四类 token 之和。四个字段全为 None 时返回 None，表示该源不报 token。"""
        parts = [getattr(self, k) for k in TOKEN_KINDS]
        if all(p is None for p in parts):
            return None
        return sum(p or 0 for p in parts)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CollectContext:
    """采集器需要的环境信息，由 run.py 组装后传入。"""

    tz: tzinfo
    root: Path
    # 采集起点。接口型源每次重采 [since, 今天] 的全部数据并覆盖写回，所以采集幂等：
    # 跑一次和跑十次结果相同，漏跑补跑都能自愈。
    since: str = "2026-01-01"

    def day_of(self, ms: int) -> str:
        """毫秒时间戳 → 配置时区下的 YYYY-MM-DD。"""
        return datetime.fromtimestamp(ms / 1000, self.tz).strftime("%Y-%m-%d")

    def today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def since_ms(self) -> int:
        """采集起点零点的毫秒时间戳，供接口的区间参数使用。"""
        d = datetime.strptime(self.since, "%Y-%m-%d")
        return int(datetime(d.year, d.month, d.day, tzinfo=self.tz).timestamp() * 1000)

    def days_between(self, start: str, end: str) -> list[str]:
        """[start, end] 的日期列表，升序。"""
        first = datetime.strptime(start, "%Y-%m-%d").date()
        last = datetime.strptime(end, "%Y-%m-%d").date()
        if last < first:
            return []
        return [(first + timedelta(days=i)).isoformat()
                for i in range((last - first).days + 1)]

    def days_since(self) -> list[str]:
        """[since, 今天] 的日期列表，升序。"""
        return self.days_between(self.since, self.today())


# ---------------------------------------------------------------- 原始数据读写

def _raw_path(root: Path, source: str, month: str) -> Path:
    return root / "data" / "raw" / source / f"{month}.json"


def write_events(root: Path, source: str, events: list[Event],
                 days: list[str]) -> None:
    """把 ``events`` 写入按月分片的原始文件，并覆盖 ``days`` 覆盖到的那些天。

    ``days`` 是本次采集「负责」的日期列表：这些天在文件里的旧内容会被整体替换，
    没被列出的天原样保留。这让采集可以重复运行而不产生重复记录，也不会因为某天
    恰好没有用量就把旧数据留成幽灵——负责范围内没有用量的那天会留一个空数组。
    """
    by_month: dict[str, dict[str, list[dict]]] = {}
    for day in days:
        by_month.setdefault(day[:7], {})[day] = []
    for e in events:
        by_month.setdefault(e.date[:7], {}).setdefault(e.date, []).append(e.to_dict())

    for month, fresh_days in by_month.items():
        path = _raw_path(root, source, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc: dict = {"source": source, "month": month, "days": {}}
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[warn] {path} 解析失败（{exc}），按空文件重建")
                doc = {"source": source, "month": month, "days": {}}
        doc.setdefault("days", {}).update(fresh_days)
        doc["days"] = {d: doc["days"][d] for d in sorted(doc["days"])}
        doc["source"], doc["month"] = source, month
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def read_all_events(root: Path) -> list[dict]:
    """读取 data/raw 下所有源、所有月份的事件，供聚合使用。"""
    out: list[dict] = []
    raw = root / "data" / "raw"
    if not raw.exists():
        return out
    for path in sorted(raw.glob("*/*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[warn] 读取 {path} 失败: {exc}")
            continue
        for day, rows in (doc.get("days") or {}).items():
            for row in rows:
                row.setdefault("date", day)
                row.setdefault("source", doc.get("source", "unknown"))
                out.append(row)
    return out
