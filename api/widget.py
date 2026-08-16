"""Vercel 动态 SVG 端点：每次请求现拉 stats.json 并渲染，无需重新部署。

GET /api/widget[?date=YYYY-MM-DD][&group_by=model|source][&theme=auto|light|dark]

- 数据来源：环境变量 STATS_URL（默认 raw.githubusercontent 上的 data/stats.json）。
  仓库需为 public，或在 Vercel 后台把 STATS_URL 指向 jsDelivr / 带 token 的 GitHub API。
- 渲染逻辑与仓库根 ranking.py / render.py 的 _build_svg 保持一致。
  此处自包含、纯 stdlib，以避免 Vercel 仅打包 api/ 目录导致的 import 失败。
"""
import json
import os
import urllib.request
from html import escape
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WIDTH = 560

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


def _build_svg(view, width=WIDTH, group_by="model", theme="auto"):
    """与 render.py 的 _build_svg 同源的 SVG 模板。"""
    group_by = group_by if group_by in {"model", "source"} else "model"
    theme = theme if theme in {"auto", "light", "dark"} else "auto"
    rows_view = view["rows"]
    total_tokens = view["total_tokens"]
    total_requests = view["total_requests"]
    date = escape(str(view["date"] or "—"))
    row_h = 28
    rows_y = 84
    height = rows_y + max(len(rows_view), 1) * row_h + 14
    track_x = 145
    track_w = max(width - track_x - 60, 80)
    rows = []
    y = rows_y
    for r in rows_view:
        label = escape(str(r["label"]))
        pct = r["pct"]
        bar_w = max(3, round(track_w * min(max(pct, 0), 100) / 100))
        rows.append(
            f'<text class="secondary label" x="18" y="{y + 16}" font-size="12">{label}</text>'
            f'<rect class="muted" x="{track_x}" y="{y + 8}" width="{track_w}" height="8" rx="4"/>'
            f'<rect class="accent" x="{track_x}" y="{y + 8}" width="{bar_w}" height="8" rx="4"/>'
            f'<text class="secondary" x="{width - 18}" y="{y + 16}" text-anchor="end" font-size="11">{pct:.0f}%</text>'
        )
        y += row_h
    bars = "".join(rows) or '<text class="secondary" x="18" y="100" font-size="12">暂无用量数据</text>'
    dimension_title = "ADE 排行" if group_by == "source" else "模型排行"
    return f'''<svg class="theme-{theme}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-labelledby="widget-title" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, Roboto, sans-serif">
  <title id="widget-title">LLM 每日用量，{dimension_title}，{date}</title>
  <style>
    .surface {{ fill: #ffffff; stroke: #e5e7eb; }}
    .primary {{ fill: #111827; }}
    .secondary {{ fill: #6b7280; }}
    .muted {{ fill: #f3f4f6; }}
    .accent {{ fill: #378add; }}
    .label {{ clip-path: url(#label-clip); }}
    .theme-dark .surface {{ fill: #0d1117; stroke: #30363d; }}
    .theme-dark .primary {{ fill: #f0f6fc; }}
    .theme-dark .secondary {{ fill: #8b949e; }}
    .theme-dark .muted {{ fill: #21262d; }}
    @media (prefers-color-scheme: dark) {{
      .theme-auto .surface {{ fill: #0d1117; stroke: #30363d; }}
      .theme-auto .primary {{ fill: #f0f6fc; }}
      .theme-auto .secondary {{ fill: #8b949e; }}
      .theme-auto .muted {{ fill: #21262d; }}
    }}
  </style>
  <defs><clipPath id="label-clip"><rect x="18" y="{rows_y}" width="112" height="{max(len(rows_view), 1) * row_h}"/></clipPath></defs>
  <rect class="surface" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="13.5"/>
  <text class="primary" x="18" y="27" font-size="15" font-weight="600">LLM 每日用量</text>
  <rect class="muted" x="{width - 118}" y="13" width="100" height="22" rx="6"/>
  <text class="secondary" x="{width - 68}" y="28" text-anchor="middle" font-size="11">{date}</text>
  <text class="secondary" x="18" y="52" font-size="12"><tspan class="primary" font-weight="600">{total_tokens:,}</tspan> tokens</text>
  <text class="secondary" x="170" y="52" font-size="12"><tspan class="primary" font-weight="600">{total_requests:,}</tspan> 次会话/请求</text>
  <text class="secondary" x="18" y="76" font-size="11" font-weight="500">{dimension_title}</text>
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
        theme = qs.get("theme", ["auto"])[0]
        group_by = group_by if group_by in {"model", "source"} else "model"
        theme = theme if theme in {"auto", "light", "dark"} else "auto"
        stats_url = os.environ.get("STATS_URL") or DEFAULT_STATS_URL
        try:
            req = urllib.request.Request(stats_url, headers={"User-Agent": "llm-usage-widget"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                stats = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._send(502, f"fetch stats failed: {e}", "text/plain; charset=utf-8")
            return
        if date is None:
            date = stats.get("latest_date")
        view = _rank_models(stats.get("daily", []), date, limit=8, group_by=group_by)
        svg = _build_svg(view, group_by=group_by, theme=theme)
        self._send(200, svg, "image/svg+xml; charset=utf-8")
