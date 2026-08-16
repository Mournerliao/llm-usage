"""汇总：把 cloud/ 与 local/ 两侧采集结果合并为统一 daily.json / stats.json。"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def load_side(side: str) -> list[dict]:
    out = []
    d = DATA / side
    if not d.exists():
        return out
    for f in d.glob("*.json"):
        try:
            out.extend(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[warn] 读取 {f} 失败: {e}")
    return out


def compute_daily(records: list[dict]) -> list[dict]:
    """纯函数：把原始采集记录按 (source, model, date) 聚合为日记录。

    不含任何文件 IO，可直接单测（deletion test：删掉它，aggregate()
    就必须把合并/累加逻辑搬回编排函数，复杂度被集中而非平移）。
    """
    agg = defaultdict(lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0})
    for r in records:
        k = (r["source"], r["model"], r["date"])
        a = agg[k]
        a["requests"] += r["requests"]
        a["input_tokens"] += r["input_tokens"]
        a["output_tokens"] += r["output_tokens"]

    daily = []
    for (source, model, date), a in agg.items():
        daily.append({
            "source": source,
            "model": model,
            "date": date,
            "requests": a["requests"],
            "input_tokens": a["input_tokens"],
            "output_tokens": a["output_tokens"],
            "total_tokens": a["input_tokens"] + a["output_tokens"],
        })

    daily.sort(key=lambda x: (x["date"], x["source"], x["model"]))
    return daily


def aggregate() -> dict:
    records = load_side("cloud") + load_side("local")
    daily = compute_daily(records)
    DATA.mkdir(exist_ok=True)
    (DATA / "daily.json").write_text(
        json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8")

    dates = sorted({d["date"] for d in daily}) if daily else []
    stats = {
        "latest_date": dates[-1] if dates else None,
        "total_dates": len(dates),
        "daily": daily,
    }
    (DATA / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 汇总完成：{len(daily)} 条日记录，覆盖 {len(dates)} 天")
    return stats


if __name__ == "__main__":
    aggregate()
