"""OpenAI / DeepSeek / OpenAI 兼容中转 的用量采集器（共用）。

OpenAI:  GET {base_url}/v1/usage?start_time=&end_time=
DeepSeek: GET {base_url}/v1/usage?start_time=&end_time=
返回 data[].{model, input_tokens, output_tokens, num_requests}

注意：各家 usage 接口返回字段可能略有差异，若某家中断可在此处加适配。
"""
import os
import datetime as _dt
import requests
from . import Record


def collect(name: str, cfg: dict, date: str) -> list[Record]:
    base_url = cfg["base_url"].rstrip("/")
    api_key = os.environ.get(cfg.get("api_key_env", ""), "")
    if not api_key:
        print(f"[warn] {name}: 缺少环境变量 {cfg.get('api_key_env')}，跳过")
        return []

    # 取 date 当天的时间窗（用量接口以 UTC 计；如需本地日切改这里）
    y, m, d = map(int, date.split("-"))
    tz = _dt.timezone.utc
    start = _dt.datetime(y, m, d, 0, 0, 0, tzinfo=tz)
    end = start + _dt.timedelta(days=1) - _dt.timedelta(seconds=1)
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())

    url = f"{base_url}/v1/usage"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"start_time": start_ts, "end_time": end_ts}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"[error] {name}: 请求 {url} 失败: {e}")
        return []

    payload = resp.json()
    records = []
    for item in payload.get("data", []):
        model = item.get("model") or item.get("snapshot_id") or "unknown"
        rec = Record(
            source=name,
            model=model,
            date=date,
            requests=int(item.get("num_requests", 0)),
            input_tokens=int(item.get("input_tokens", 0)),
            output_tokens=int(item.get("output_tokens", 0)),
        )
        records.append(rec)
    print(f"[ok] {name}: 取到 {len(records)} 条模型用量")
    return records
