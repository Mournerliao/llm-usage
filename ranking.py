"""纯函数：把 stats.daily 归约成某一天的展示视图。

这是 SVG 渲染器（render.py）与 React 组件（UsageWidget）共用的 seam：两边都只做薄
渲染，「取哪天、按哪个维度合并、怎么算占比」这些判断集中在此。

== 为什么要按 unit 分节 ==

不同源的计量单位天然不同：Cursor 只能给出请求数，OpenAI 兼容接口给的是真 token，
将来接入的源还可能是积分或代码行数。把它们相加得到的「总量」没有意义，占比也会被
量级最大的单位主导。所以视图按 unit 切成若干独立小节，每节内部各自算 100%。

deletion test：删掉本模块，render.py 与 UsageWidget 必须各自把分节、合并、占比
逻辑搬回去，两份实现会立刻开始漂移。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# 单位的展示顺序。排在前面的更「主要」，SVG 空间有限时优先渲染。
UNIT_ORDER = ("tokens", "requests", "sessions", "credits", "lines")

# 单位有两种中文写法：小节标题用名词（「请求」），汇总行要带量词（「14 次请求」）。
# 拆成两张表而不是拼字符串，因为中文量词位置不能靠拼接推出来。
UNIT_LABELS = {
    "tokens": "Tokens",
    "requests": "请求",
    "sessions": "会话",
    "credits": "积分",
    "lines": "代码行",
}
UNIT_COUNTED = {
    "tokens": "{n} tokens",
    "requests": "{n} 次请求",
    "sessions": "{n} 个会话",
    "credits": "{n} 积分",
    "lines": "{n} 行代码",
}

DIMENSION_LABELS = {
    "model": "模型",
    "source": "ADE",
    "machine": "机器",
}


def _unit_sort_key(unit: str) -> tuple[int, str]:
    return (UNIT_ORDER.index(unit) if unit in UNIT_ORDER else len(UNIT_ORDER), unit)


def unit_label(unit: str) -> str:
    """小节标题用的名词形式。"""
    return UNIT_LABELS.get(unit, unit)


def unit_counted(unit: str, amount: int) -> str:
    """汇总行用的带量词形式，如「14 次请求」。"""
    return UNIT_COUNTED.get(unit, "{n} " + unit).format(n=f"{amount:,}")


def dimension_label(group_by: str) -> str:
    return DIMENSION_LABELS.get(group_by, group_by)


def build_view(
    daily: list[dict[str, Any]],
    date: str | None,
    limit: int = 8,
    group_by: str = "model",
) -> dict[str, Any]:
    """构建某一天的展示视图。

    ``group_by`` 取 model / source / machine，三个维度走同一条路径，渲染层只切换
    默认维度，不再各写一套分组逻辑。

    返回::

        {
          "date": str | None,
          "group_by": str,
          "totals": [{"unit": str, "amount": int}, ...],   # 按单位分别汇总
          "sections": [                                     # 每个单位一节
            {
              "unit": str,
              "total": int,
              "rows": [{"label": str, "amount": int, "pct": float}, ...],
            },
          ],
        }

    ``pct`` 是该行在**所在小节**内的占比（0~100），不是全局占比。
    """
    if group_by not in DIMENSION_LABELS:
        group_by = "model"
    if date is None:
        return {"date": None, "group_by": group_by, "totals": [], "sections": []}

    day_rows = [r for r in daily if r.get("date") == date]

    per_unit: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in day_rows:
        unit = r.get("unit") or "requests"
        label = r.get(group_by) or "unknown"
        per_unit[unit][label] += int(r.get("amount") or 0)

    sections = []
    totals = []
    for unit in sorted(per_unit, key=_unit_sort_key):
        agg = per_unit[unit]
        total = sum(agg.values())
        totals.append({"unit": unit, "amount": total})
        ranked = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        sections.append({
            "unit": unit,
            "total": total,
            "rows": [
                {
                    "label": label,
                    "amount": amount,
                    "pct": (amount / total * 100) if total else 0.0,
                }
                for label, amount in ranked
            ],
        })

    return {"date": date, "group_by": group_by, "totals": totals, "sections": sections}
