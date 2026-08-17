"""OpenAI / DeepSeek / 任意 OpenAI 兼容中转站的用量采集器（共用一个实现）。

    GET {base_url}/v1/usage?start_time=&end_time=
    → data[].{model, input_tokens, output_tokens, num_requests}

各家的 usage 接口字段略有差异，需要适配时改 ``_parse_item``，不要动 collect。

这类接口给的是输入输出两类 token，没有缓存读写的拆分，也不带成本，所以
``cache_write`` / ``cache_read`` / ``cost_cents`` 留 ``None``——表示「这个源不报」，
和「报了但是零」不是一回事。要算成本得自己维护一张单价表，那是估算不是实测，
本项目不做。
"""
from __future__ import annotations

import datetime as dt
import os

import requests

from . import CollectContext, Event


def _day_window(day: str, tz) -> tuple[int, int]:
    """某一天在配置时区下的 [起, 止] 时间戳（秒）。

    用配置时区而不是 UTC，是为了让这里的「一天」和其他源的归日口径一致；
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


def collect(ctx: CollectContext, cfg: dict) -> tuple[list[Event], list[str]]:
    name = cfg.get("name", "openai")
    api_key = os.environ.get(cfg.get("api_key_env", ""), "")
    if not api_key:
        print(f"[warn] {name}: 缺少环境变量 {cfg.get('api_key_env')}，跳过")
        return [], []

    base_url = cfg["base_url"].rstrip("/")
    days = ctx.days_since()
    events: list[Event] = []
    for day in days:
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
            if not (reqs or tok_in or tok_out):
                continue
            events.append(Event(
                date=day, source=name, model=model,
                requests=reqs, tokens_in=tok_in, tokens_out=tok_out,
            ))

    print(f"[ok] {name}: 取到 {len(events)} 条用量事件")
    # 这个源按天逐个查询，所以负责范围就是查过的那些天，不依赖返回内容。
    return events, days
