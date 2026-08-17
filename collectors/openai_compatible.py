"""OpenAI / DeepSeek / 任意 OpenAI 兼容中转站的用量采集器（共用一个实现）。

    GET {base_url}/v1/usage?start_time=&end_time=
    → data[].{model, input_tokens, output_tokens, num_requests}

这是目前唯一能给出**真实 token 口径**的源，所以它的事件同时填 ``amount_in`` /
``amount_out``；本地源（Cursor 记请求数）拆不开输入输出。

各家的 usage 接口字段略有差异，需要适配时改 ``_parse_item``，不要动 collect。
"""
from __future__ import annotations

import datetime as dt
import os

import requests

from . import CollectContext, Event


def _day_window(day: str, tz) -> tuple[int, int]:
    """某一天在配置时区下的 [起, 止] 时间戳（秒）。

    用配置时区而不是 UTC，是为了让这里的「一天」和本地源的归日口径一致；
    否则同一次调用在两种源里会落到不同日期。
    """
    y, m, d = map(int, day.split("-"))
    start = dt.datetime(y, m, d, tzinfo=tz)
    end = start + dt.timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp()) - 1


def _parse_item(item: dict) -> tuple[str, int, int, int]:
    model = item.get("model") or item.get("snapshot_id") or "unknown"
    return (
        model,
        int(item.get("num_requests", 0) or 0),
        int(item.get("input_tokens", 0) or 0),
        int(item.get("output_tokens", 0) or 0),
    )


def collect(ctx: CollectContext, cfg: dict) -> list[Event]:
    name = cfg.get("name", "openai")
    api_key = os.environ.get(cfg.get("api_key_env", ""), "")
    if not api_key:
        print(f"[warn] {name}: 缺少环境变量 {cfg.get('api_key_env')}，跳过")
        return []

    base_url = cfg["base_url"].rstrip("/")
    events: list[Event] = []
    for day in ctx.recent_days(ctx.lookback_days):
        start_ts, end_ts = _day_window(day, ctx.tz)
        try:
            resp = requests.get(
                f"{base_url}/v1/usage",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"start_time": start_ts, "end_time": end_ts},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"[error] {name}: 拉取 {day} 失败: {exc}")
            continue

        for item in payload.get("data", []):
            model, reqs, tok_in, tok_out = _parse_item(item)
            if tok_in or tok_out:
                events.append(Event(
                    date=day, machine=ctx.machine, source=name, model=model,
                    unit="tokens", amount=tok_in + tok_out,
                    amount_in=tok_in, amount_out=tok_out,
                ))
            if reqs:
                events.append(Event(
                    date=day, machine=ctx.machine, source=name, model=model,
                    unit="requests", amount=reqs,
                ))

    print(f"[ok] {name}: 取到 {len(events)} 条用量事件")
    return events


def collected_days(ctx: CollectContext) -> list[str]:
    return ctx.recent_days(ctx.lookback_days)
