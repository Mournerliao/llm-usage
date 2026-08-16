"""纯函数：把 stats.daily 归约成给定日期的「模型排行」展示模型。

这是 SVG 渲染器（render.py）与 React 组件（UsageWidget）共用的真实 seam：
两边都只做薄渲染，排行 / 占比计算集中在此，避免两份逻辑漂移、也便于单测。

deletion test：删掉本模块，render.py 与 UsageWidget 必须各自把这段排行逻辑
搬回去 —— 复杂度被「集中」而非「平移」，这正是我们要的 deepening。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def rank_models(
    daily: list[dict[str, Any]],
    date: str | None,
    limit: int = 8,
    group_by: str = "model",
) -> dict[str, Any]:
    """对 daily 记录按 `date` 过滤，按 `group_by` 维度合并 token，降序取前 `limit`。

    group_by="model"：按模型合并（忽略来源），与 SVG 渲染器口径一致；
    group_by="source"：按来源合并。两个维度都走同一纯函数，
    SVG 与 React 组件只是切换默认维度，不再各写一套分组逻辑。

    返回：
        {
          "date": str | None,
          "total_tokens": int,
          "total_requests": int,
          "rows": [{"label": str, "tokens": int, "pct": float}, ...],  # 已按 tokens 降序
        }
    rows 中的 pct 为该维度 token 占当日总 token 的百分比（0~100）。
    """
    if date is None:
        return {"date": None, "total_tokens": 0, "total_requests": 0, "rows": []}

    day_rows = [r for r in daily if r.get("date") == date]
    total_tokens = sum(r.get("total_tokens", 0) for r in day_rows)
    total_requests = sum(r.get("requests", 0) for r in day_rows)

    def key_of(r: dict[str, Any]) -> str:
        if group_by == "source":
            return r.get("source") or "unknown"
        return r.get("model") or "unknown"

    agg: dict[str, int] = defaultdict(int)
    for r in day_rows:
        agg[key_of(r)] += r.get("total_tokens", 0)

    ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    rows = [
        {
            "label": label,
            "tokens": toks,
            "pct": (toks / total_tokens * 100) if total_tokens else 0.0,
        }
        for label, toks in ranked
    ]
    return {
        "date": date,
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "rows": rows,
    }
