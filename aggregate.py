"""汇总：把 data/raw 下所有机器、所有源的事件 fold 成 data/stats.json。

这一层是纯粹的归约：读原始事件 → 归一模型名 → 按 (date, machine, source, model,
unit) 累加 → 写产物。不做采集、不访问网络、不读任何本机专属路径，所以 CI 拿着
仓库就能重新生成产物，不需要配置任何密钥。

重跑幂等：产物完全由 raw 决定，跑一次和跑十次结果一样。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import config
from collectors import read_all_events

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

SCHEMA_VERSION = 2


def fold_events(events: list[dict], aliases: dict[str, str] | None = None) -> list[dict]:
    """纯函数：把原始事件归约成日记录。

    按 (date, machine, source, 归一后的 model, unit) 累加 amount。``amount_in`` /
    ``amount_out`` 只在参与的事件都提供了拆分时才保留，任一为空则整体置空——
    半真半假的拆分比没有拆分更容易误导。

    deletion test：删掉本函数，aggregate() 就必须把归一与累加逻辑搬回编排流程，
    复杂度被集中而非平移。
    """
    aliases = {} if aliases is None else aliases
    buckets: dict[tuple, dict] = {}

    for e in events:
        model = config.normalize_model(e.get("model") or "unknown", aliases)
        key = (
            e.get("date"),
            e.get("machine") or "unknown",
            e.get("source") or "unknown",
            model,
            e.get("unit") or "requests",
        )
        row = buckets.setdefault(key, {"amount": 0, "amount_in": 0,
                                       "amount_out": 0, "splittable": True})
        row["amount"] += int(e.get("amount") or 0)
        if e.get("amount_in") is None and e.get("amount_out") is None:
            row["splittable"] = False
        else:
            row["amount_in"] += int(e.get("amount_in") or 0)
            row["amount_out"] += int(e.get("amount_out") or 0)

    daily = []
    for (date, machine, source, model, unit), row in buckets.items():
        entry = {
            "date": date,
            "machine": machine,
            "source": source,
            "model": model,
            "unit": unit,
            "amount": row["amount"],
        }
        if row["splittable"]:
            entry["amount_in"] = row["amount_in"]
            entry["amount_out"] = row["amount_out"]
        daily.append(entry)

    daily.sort(key=lambda r: (r["date"], r["unit"], r["source"],
                              r["machine"], r["model"]))
    return daily


def build_stats(daily: list[dict]) -> dict:
    """把日记录包装成 stats.json 的顶层结构。"""
    dates = sorted({r["date"] for r in daily})
    return {
        "schema_version": SCHEMA_VERSION,
        "latest_date": dates[-1] if dates else None,
        "total_dates": len(dates),
        "units": sorted({r["unit"] for r in daily}),
        "machines": sorted({r["machine"] for r in daily}),
        "daily": daily,
    }


def aggregate(root: Path = ROOT) -> dict:
    events = read_all_events(root)
    daily = fold_events(events, config.model_aliases())
    stats = build_stats(daily)

    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[ok] 汇总完成：{len(events)} 条事件 → {len(daily)} 条日记录，"
          f"覆盖 {stats['total_dates']} 天，单位 {stats['units']}")
    return stats


if __name__ == "__main__":
    aggregate()
