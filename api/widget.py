"""Vercel 动态 SVG 端点：每次请求现拉 stats.json 并渲染，无需重新部署。

GET /api/widget[?date=YYYY-MM-DD][&group_by=model|source]

- 数据来源：环境变量 STATS_URL（默认 raw.githubusercontent 上的 data/stats.json）。
  仓库需为 public，或在 Vercel 后台把 STATS_URL 指向 jsDelivr / 带 token 的 GitHub API。
- 渲染逻辑与仓库根 ranking.py / render.py 的 _build_svg 保持一致。
  此处自包含、纯 stdlib，以避免 Vercel 仅打包 api/ 目录导致的 import 失败。
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WIDTH = 680

# 默认指向 Mournerliao/llm-usage（public 仓库），
# 仍可在 Vercel 后台用环境变量 STATS_URL 覆盖此默认值。
DEFAULT_STATS_URL = (
    "https://raw.githubusercontent.com/Mournerliao/llm-usage/main/data/stats.json"
)


def _rank_models(daily, date, limit=8, group_by="model"):
    """与 ranking.rank_models 同口径的纯函数（此处自包含）。"""
    if date is None:
        return {"date": None, "total_tokens": 0, "total_requests": 0, "rows": []}
    day_rows = [r for r in daily if r.get("date") == date]
    total_tokens = sum(r.get("total_tokens", 0) for r in day_rows)
    total_requests = sum(r.get("requests", 0) for r in day_rows)
    agg = {}
    for r in day_rows:
        key = (r.get("source") or "unknown") if group_by == "source" else (r.get("model") or "unknown")
        agg[key] = agg.get(key, 0) + r.get("total_tokens", 0)
    ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    rows = [
        {"label": label, "tokens": toks, "pct": (toks / total_tokens * 100) if total_tokens else 0.0}
        for label, toks in ranked
    ]
    return {"date": date, "total_tokens": total_tokens, "total_requests": total_requests, "rows": rows}


def _build_svg(view, width=WIDTH):
    """与 render.py 的 _build_svg 同源的 SVG 模板。"""
    rows_view = view["rows"]
    total_tokens = view["total_tokens"]
    total_requests = view["total_requests"]
    date = view["date"] or "—"
    bar_max = max([r["tokens"] for r in rows_view], default=1) or 1
    row_h = 26
    chart_h = len(rows_view) * row_h + 20
    height = 150 + chart_h
    rows = []
    y = 110
    for r in rows_view:
        label = r["label"]
        toks = r["tokens"]
        pct = r["pct"]
        w = int(360 * (toks / bar_max)) if bar_max else 0
        rows.append(
            f'<text x="20" y="{y + 14}" font-size="12" fill="#444441">{label}</text>'
            f'<rect x="170" y="{y + 4}" width="{max(w, 2)}" height="14" rx="3" fill="#378ADD"/>'
            f'<text x="540" y="{y + 14}" font-size="11" fill="#5F5E5A">{pct:.0f}%</text>'
        )
        y += row_h
    bars = "".join(rows)
    return f'''<svg viewBox="0 0 {width} {height}" width="{width}" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, Segoe UI, Roboto, sans-serif">
  <rect x="0" y="0" width="{width}" height="{height}" rx="14" fill="#ffffff" stroke="#E5E7EB"/>
  <text x="20" y="34" font-size="15" font-weight="600" fill="#111827">ADE 每日用量 · {date}</text>
  <text x="20" y="64" font-size="13" fill="#374151">总 token：<tspan fill="#111827" font-weight="600">{total_tokens:,}</tspan>　会话/请求：<tspan fill="#111827" font-weight="600">{total_requests:,}</tspan></text>
  <line x1="20" y1="80" x2="{width - 20}" y2="80" stroke="#F3F4F6"/>
  <text x="20" y="100" font-size="12" fill="#6B7280">模型排行（按 token）</text>
  {bars}
</svg>'''


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("image/svg+xml"):
            self.send_header("Cache-Control", "public, max-age=300, s-maxage=300")
        self.end_headers()
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.wfile.write(data)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        date = qs.get("date", [None])[0]
        group_by = qs.get("group_by", ["model"])[0]
        stats_url = os.environ.get("STATS_URL") or DEFAULT_STATS_URL
        try:
            req = urllib.request.Request(stats_url, headers={"User-Agent": "ade-widget"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                stats = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._send(502, f"fetch stats failed: {e}", "text/plain; charset=utf-8")
            return
        if date is None:
            date = stats.get("latest_date")
        view = _rank_models(stats.get("daily", []), date, limit=8, group_by=group_by)
        svg = _build_svg(view)
        self._send(200, svg, "image/svg+xml; charset=utf-8")
