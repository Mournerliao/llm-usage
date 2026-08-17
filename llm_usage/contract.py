"""stats.json 契约：常量与校验。

单一事实源是仓库根的 ``stats.schema.json``。本模块从那里读出版本号与 token
四元组，并做等价的结构检查，避免为这个项目引入 jsonschema 依赖。
"""
from __future__ import annotations

import json
import re
from typing import Any

from llm_usage import REPO_ROOT

_SCHEMA = json.loads(
    (REPO_ROOT / "stats.schema.json").read_text(encoding="utf-8"))

SCHEMA_VERSION = int(_SCHEMA["properties"]["schema_version"]["const"])

_TOKEN_ORDER = ("tokens_in", "tokens_out", "cache_write", "cache_read")
TOKEN_KINDS = tuple(
    kind for kind in _TOKEN_ORDER
    if kind in _SCHEMA["properties"]["daily"]["items"]["properties"])

_REQUIRED_TOP = ("schema_version", "timezone", "latest_date", "weeks",
                 "sources", "daily", "year")
_REQUIRED_ROW = ("date", "source", "model", "requests")
_REQUIRED_VIEW = ("week", "start", "end", "range_display", "basis", "requests",
                  "tokens_display", "cost_display", "requests_display",
                  "breakdown", "models", "days")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


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

    errs += _check_weeks(stats.get("weeks"))
    errs += _check_daily(stats.get("daily"))
    return errs


def _check_weeks(weeks: Any) -> list[str]:
    if not isinstance(weeks, list):
        return ["weeks 必须是数组"]
    errs: list[str] = []
    for i, week in enumerate(weeks):
        if not isinstance(week, dict):
            errs.append(f"weeks[{i}] 不是对象")
            continue
        if not _WEEK_RE.match(str(week.get("week", ""))):
            errs.append(f"weeks[{i}].week 不是 YYYY-Www：{week.get('week')!r}")
        for key in ("start", "end"):
            if not _DATE_RE.match(str(week.get(key, ""))):
                errs.append(f"weeks[{i}].{key} 不是 YYYY-MM-DD：{week.get(key)!r}")
        start, end = week.get("start"), week.get("end")
        if isinstance(start, str) and isinstance(end, str) and start > end:
            errs.append(f"weeks[{i}] 的 start 晚于 end")
        errs += _check_view(week.get("view"), i)
    return errs


def _check_view(view: Any, week_index: int) -> list[str]:
    prefix = f"weeks[{week_index}].view"
    if not isinstance(view, dict):
        return [f"{prefix} 必须是对象"]
    errs: list[str] = []
    for key in _REQUIRED_VIEW:
        if key not in view:
            errs.append(f"{prefix} 缺少字段 {key}")
    if "days" in view:
        days = view["days"]
        if not isinstance(days, list):
            errs.append(f"{prefix}.days 必须是数组")
        elif days and not all(isinstance(d, dict) and "tokens_display" in d
                              for d in days):
            errs.append(f"{prefix}.days 每项必须带 tokens_display")
    return errs


def _check_daily(daily: Any) -> list[str]:
    if not isinstance(daily, list):
        return ["daily 必须是数组"]

    errs: list[str] = []
    for i, row in enumerate(daily):
        if not isinstance(row, dict):
            errs.append(f"daily[{i}] 不是对象")
            continue
        for key in _REQUIRED_ROW:
            if key not in row:
                errs.append(f"daily[{i}] 缺少字段 {key}")
        if not _DATE_RE.match(str(row.get("date", ""))):
            errs.append(f"daily[{i}].date 不是 YYYY-MM-DD：{row.get('date')!r}")

        # token 类字段必须是非负整数；缺失是合法的（表示该源不报此口径），
        # 但出现了就不能是 null 或浮点——那意味着上游把「没有」和「零」搞混了。
        for key in ("requests",) + TOKEN_KINDS:
            if key not in row:
                continue
            value = row[key]
            if not isinstance(value, int) or isinstance(value, bool):
                errs.append(f"daily[{i}].{key} 应为整数，实际 {value!r}")
            elif value < 0:
                errs.append(f"daily[{i}].{key} 不应为负")

        if "cost_cents" in row:
            cost = row["cost_cents"]
            if not isinstance(cost, (int, float)) or isinstance(cost, bool):
                errs.append(f"daily[{i}].cost_cents 应为数字，实际 {cost!r}")
            elif cost < 0:
                errs.append(f"daily[{i}].cost_cents 不应为负")

    return errs
