"""stats.json 契约校验（纯 stdlib，无第三方依赖）。

单一事实源是仓库根的 ``stats.schema.json``；本模块做等价的结构检查，供 aggregate
自测与 tests 使用，避免为这个项目引入 jsonschema 依赖。
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 2
UNITS = {"requests", "sessions", "tokens", "credits", "lines"}

_REQUIRED_TOP = ("schema_version", "latest_date", "total_dates", "units",
                 "machines", "daily")
_REQUIRED_ROW = ("date", "machine", "source", "model", "unit", "amount")
_INT_FIELDS = ("amount", "amount_in", "amount_out")


def validate_stats(stats: Any) -> list[str]:
    """返回错误列表；空列表表示通过。只做结构与类型检查，不判断业务合理性。"""
    if not isinstance(stats, dict):
        return ["stats 必须是对象"]

    errs: list[str] = []
    for key in _REQUIRED_TOP:
        if key not in stats:
            errs.append(f"缺少顶层字段 {key}")

    if stats.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version 应为 {SCHEMA_VERSION}，"
                    f"实际为 {stats.get('schema_version')!r}")

    daily = stats.get("daily")
    if not isinstance(daily, list):
        errs.append("daily 必须是数组")
        return errs

    for i, row in enumerate(daily):
        if not isinstance(row, dict):
            errs.append(f"daily[{i}] 不是对象")
            continue
        for key in _REQUIRED_ROW:
            if key not in row:
                errs.append(f"daily[{i}] 缺少字段 {key}")
        for key in _INT_FIELDS:
            if key in row and not isinstance(row[key], int):
                errs.append(f"daily[{i}].{key} 应为整数")
        unit = row.get("unit")
        if unit is not None and unit not in UNITS:
            errs.append(f"daily[{i}].unit 未知：{unit!r}")
        if "amount" in row and isinstance(row["amount"], int) and row["amount"] < 0:
            errs.append(f"daily[{i}].amount 不应为负")

    return errs
