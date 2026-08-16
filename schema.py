"""stats.json 契约校验（纯 stdlib，无第三方依赖）。

单一事实源是仓库根的 ``stats.schema.json``；本模块做等价的结构检查，
供 ``aggregate`` 自测与 ``tests`` 使用，避免为项目引入 ``jsonschema`` 依赖。
"""
from __future__ import annotations

from typing import Any

_REQUIRED_TOP = ("latest_date", "total_dates", "daily")
_REQUIRED_ROW = (
    "source",
    "model",
    "date",
    "requests",
    "input_tokens",
    "output_tokens",
    "total_tokens",
)
_INT_FIELDS = ("requests", "input_tokens", "output_tokens", "total_tokens")


def validate_stats(stats: Any) -> list[str]:
    """返回错误列表；空列表表示通过。

    仅做结构性校验（字段存在 + 数值类型），不强制业务合理性。
    """
    if not isinstance(stats, dict):
        return ["stats 必须是对象"]
    errs: list[str] = []
    for k in _REQUIRED_TOP:
        if k not in stats:
            errs.append(f"缺少顶层字段 {k}")
    daily = stats.get("daily")
    if not isinstance(daily, list):
        errs.append("daily 必须是数组")
        return errs
    for i, r in enumerate(daily):
        if not isinstance(r, dict):
            errs.append(f"daily[{i}] 不是对象")
            continue
        for k in _REQUIRED_ROW:
            if k not in r:
                errs.append(f"daily[{i}] 缺少字段 {k}")
        for k in _INT_FIELDS:
            if k in r and not isinstance(r[k], int):
                errs.append(f"daily[{i}].{k} 应为整数")
    return errs
