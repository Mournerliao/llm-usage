"""纯函数：把 stats.daily 归约成某一周的展示视图。

这是 SVG 渲染器（render.py）与 React 组件（UsageWidget）共用的 seam：两边都只做薄
渲染，「取哪一周、按什么排序、怎么算占比、数字怎么写」这些判断集中在此。

== 为什么格式化也在这里 ==

视图里带 ``*_display`` 字符串，而不是让两个渲染器各自把数字转成文本。因为
「479.0M」这种写法涉及量级选择与舍入方向，两边各写一遍必然漂移，而
``tests/test_parity.py`` 逐字段比对 Python 与 TS 的输出，把格式化收进视图，格式
本身就被这个测试锁住了。

舍入不用各语言内建的格式化：Python 的 ``f"{x:.1f}"`` 用银行家舍入，JS 的
``toFixed`` 用四舍五入，恰好落在半分位上的值会给出不同结果。所以两边都手写
``floor(|x| * 10^n + 0.5)``，在 IEEE754 双精度下逐位相同。

deletion test：删掉本模块，render.py 与 UsageWidget 必须各自把取周、排序、占比、
格式化逻辑搬回去，两份实现会立刻开始漂移。
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date as Date
from datetime import timedelta
from typing import Any

TOKEN_KINDS = ("tokens_in", "tokens_out", "cache_write", "cache_read")

TOKEN_LABELS = {
    "tokens_in": "输入",
    "tokens_out": "输出",
    "cache_write": "缓存写入",
    "cache_read": "缓存读取",
}

# 排序与占比的口径。成本是稀缺资源，有成本就按成本排；拿不到成本的源退到 token，
# 再退到请求数。视图里带 basis 字段，渲染层据此写对应的表头。
BASIS_LABELS = {
    "cost": "成本",
    "tokens": "Tokens",
    "requests": "请求",
}

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")


# ------------------------------------------------------------------ 数字格式化

def _fixed(value: float, digits: int) -> str:
    """定点格式化，四舍五入远离零。与 TS 侧实现逐位一致。"""
    factor = 10 ** digits
    scaled = math.floor(abs(value) * factor + 0.5)
    sign = "-" if value < 0 and scaled != 0 else ""
    text = str(int(scaled))
    if digits == 0:
        return sign + text
    text = text.rjust(digits + 1, "0")
    return f"{sign}{text[:-digits]}.{text[-digits:]}"


def _group(intpart: str) -> str:
    """千分位分隔。"""
    out = []
    for offset, ch in enumerate(reversed(intpart)):
        if offset and offset % 3 == 0:
            out.append(",")
        out.append(ch)
    return "".join(reversed(out))


def format_tokens(value: int | None) -> str:
    """token 量的紧凑写法：4,047 → 4.0K，479,000,000 → 479.0M。"""
    if value is None:
        return "—"
    n = abs(value)
    if n >= 1_000_000_000:
        return _fixed(value / 1_000_000_000, 2) + "B"
    if n >= 1_000_000:
        return _fixed(value / 1_000_000, 1) + "M"
    if n >= 1_000:
        return _fixed(value / 1_000, 1) + "K"
    return str(int(value))


def format_cost(cents: float | None) -> str:
    """分 → 美元，带千分位与两位小数。"""
    if cents is None:
        return "—"
    text = _fixed(cents / 100, 2)
    neg = text.startswith("-")
    if neg:
        text = text[1:]
    intpart, _, frac = text.partition(".")
    return f"{'-' if neg else ''}${_group(intpart)}.{frac}"


def format_count(value: int | None) -> str:
    if value is None:
        return "—"
    return _group(str(int(abs(value)))) if value >= 0 else "-" + _group(str(-int(value)))


def format_day(day: str) -> str:
    """2026-08-17 → 8月17日。"""
    _, month, dom = day.split("-")
    return f"{int(month)}月{int(dom)}日"


def format_range(start: str, end: str) -> str:
    return f"{format_day(start)} – {format_day(end)}"


# ---------------------------------------------------------------------- 视图

def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """按字段求和。全都没报的字段保持 ``None``，不塞 0。

    成本刻意**不做中途取整**：两端按同一顺序累加同一批双精度浮点，结果逐位相同，
    而 Python 的 ``round`` 是银行家舍入、JS 没有等价内建，中途取整反而会制造出
    parity 测试要抓的那种漂移。对外显示的位数由 ``format_cost`` 统一决定。
    """
    out: dict[str, Any] = {
        "requests": sum(int(r.get("requests") or 0) for r in rows),
    }
    for field in TOKEN_KINDS:
        values = [r[field] for r in rows if r.get(field) is not None]
        out[field] = sum(values) if values else None
    costs = [r["cost_cents"] for r in rows if r.get("cost_cents") is not None]
    out["cost_cents"] = sum(costs) if costs else None
    present = [out[f] for f in TOKEN_KINDS if out[f] is not None]
    out["tokens_total"] = sum(present) if present else None
    return out


def _basis_of(totals: dict[str, Any]) -> str:
    if totals.get("cost_cents"):
        return "cost"
    if totals.get("tokens_total"):
        return "tokens"
    return "requests"


def _basis_value(row: dict[str, Any], basis: str) -> float:
    if basis == "cost":
        return float(row.get("cost_cents") or 0)
    if basis == "tokens":
        return float(row.get("tokens_total") or 0)
    return float(row.get("requests") or 0)


def build_week_view(
    daily: list[dict[str, Any]],
    week: dict[str, str] | None,
    limit: int = 6,
) -> dict[str, Any]:
    """构建某一周的展示视图。

    ``week`` 形如 ``{"week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23"}``，
    直接取自 stats.json 的 ``weeks``。

    ``models`` 按 ``basis`` 降序，``pct`` 是该行在本周内的占比（0~100）。
    ``days`` 恒为 7 项（周一到周日），没有用量的那天补零，让日条形图的横轴稳定。
    """
    if not week:
        return {"week": None, "start": None, "end": None, "range_display": "",
                "basis": "requests", "requests": 0, "tokens_total": None,
                "cost_cents": None, "tokens_display": "—", "cost_display": "—",
                "requests_display": "0", "breakdown": [], "models": [], "days": []}

    start, end = week["start"], week["end"]
    rows = [r for r in daily if start <= r.get("date", "") <= end]

    totals = _totals(rows)
    basis = _basis_of(totals)

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r.get("model") or "unknown"].append(r)

    model_rows = []
    for name, group in by_model.items():
        agg = _totals(group)
        model_rows.append({
            "label": name,
            "requests": agg["requests"],
            "tokens_total": agg["tokens_total"],
            "cost_cents": agg["cost_cents"],
            "tokens_display": format_tokens(agg["tokens_total"]),
            "cost_display": format_cost(agg["cost_cents"]),
            "requests_display": format_count(agg["requests"]),
        })

    basis_total = sum(_basis_value(r, basis) for r in model_rows)
    for row in model_rows:
        row["pct"] = (_basis_value(row, basis) / basis_total * 100) if basis_total else 0.0
    model_rows.sort(key=lambda r: (-_basis_value(r, basis), r["label"]))

    # token 四分类的构成，按固定顺序而非大小排，让配色在各周之间稳定。
    breakdown = []
    if totals["tokens_total"]:
        for field in TOKEN_KINDS:
            value = totals[field]
            if value is None:
                continue
            breakdown.append({
                "kind": field,
                "label": TOKEN_LABELS[field],
                "amount": value,
                "display": format_tokens(value),
                "pct": value / totals["tokens_total"] * 100,
            })

    day_index: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        day_index[r["date"]].append(r)
    first = Date.fromisoformat(start)
    days = []
    for offset in range(7):
        day = (first + timedelta(days=offset)).isoformat()
        agg = _totals(day_index.get(day, []))
        days.append({
            "date": day,
            "weekday": WEEKDAY_LABELS[offset],
            "requests": agg["requests"],
            "tokens_total": agg["tokens_total"],
            "cost_cents": agg["cost_cents"],
        })

    return {
        "week": week["week"],
        "start": start,
        "end": end,
        "range_display": format_range(start, end),
        "basis": basis,
        "requests": totals["requests"],
        "tokens_total": totals["tokens_total"],
        "cost_cents": totals["cost_cents"],
        "tokens_display": format_tokens(totals["tokens_total"]),
        "cost_display": format_cost(totals["cost_cents"]),
        "requests_display": format_count(totals["requests"]),
        "breakdown": breakdown,
        "models": model_rows[:limit],
        "days": days,
    }
