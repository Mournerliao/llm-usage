"""渲染辅助：根据 stats.json 生成 SVG 字符串（纯函数，不写盘）。

线上 widget 由 api/widget.py 在 Vercel 端动态生成；
本模块作为同源 SVG 模板参考 / 本地调试用途。
"""
import json
from html import escape
from pathlib import Path

import ranking

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def build_svg(
    stats: dict,
    date: str | None = None,
    width: int = 560,
    group_by: str = "model",
    theme: str = "auto",
) -> str:
    """根据 stats.json 构建一张 SVG 字符串（不写盘）。"""
    group_by = group_by if group_by in {"model", "source"} else "model"
    theme = theme if theme in {"auto", "light", "dark"} else "auto"
    if date is None:
        date = stats.get("latest_date")

    view = ranking.rank_models(stats.get("daily", []), date, limit=8, group_by=group_by)
    rows_view = view["rows"]
    total_tokens = view["total_tokens"]
    total_requests = view["total_requests"]
    date = escape(str(view["date"] or "—"))
    row_h = 28
    rows_y = 104
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
    bars = "".join(rows) or '<text class="secondary" x="18" y="120" font-size="12">暂无用量数据</text>'
    tab_w = max((width - 48) // 2, 40)
    source_tab_x = 22
    model_tab_x = width - 22 - tab_w
    active_x = source_tab_x if group_by == "source" else model_tab_x
    source_label_x = source_tab_x + tab_w / 2
    model_label_x = model_tab_x + tab_w / 2
    return f'''<svg class="theme-{theme}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-labelledby="widget-title" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, Roboto, sans-serif">
  <title id="widget-title">LLM 每日用量，{date}</title>
  <style>
    .surface {{ fill: #ffffff; stroke: #e5e7eb; }}
    .primary {{ fill: #111827; }}
    .secondary {{ fill: #6b7280; }}
    .muted {{ fill: #f3f4f6; }}
    .accent {{ fill: #378add; }}
    .tab-active {{ fill: #ffffff; stroke: #e5e7eb; }}
    .label {{ clip-path: url(#label-clip); }}
    .theme-dark .surface {{ fill: #0d1117; stroke: #30363d; }}
    .theme-dark .primary {{ fill: #f0f6fc; }}
    .theme-dark .secondary {{ fill: #8b949e; }}
    .theme-dark .muted {{ fill: #21262d; }}
    .theme-dark .tab-active {{ fill: #0d1117; stroke: #30363d; }}
    @media (prefers-color-scheme: dark) {{
      .theme-auto .surface {{ fill: #0d1117; stroke: #30363d; }}
      .theme-auto .primary {{ fill: #f0f6fc; }}
      .theme-auto .secondary {{ fill: #8b949e; }}
      .theme-auto .muted {{ fill: #21262d; }}
      .theme-auto .tab-active {{ fill: #0d1117; stroke: #30363d; }}
    }}
  </style>
  <defs><clipPath id="label-clip"><rect x="18" y="{rows_y}" width="112" height="{max(len(rows_view), 1) * row_h}"/></clipPath></defs>
  <rect class="surface" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="13.5"/>
  <text class="primary" x="18" y="27" font-size="15" font-weight="600">LLM 每日用量</text>
  <rect class="muted" x="{width - 118}" y="13" width="100" height="22" rx="6"/>
  <text class="secondary" x="{width - 68}" y="28" text-anchor="middle" font-size="11">{date}</text>
  <text class="secondary" x="18" y="52" font-size="12"><tspan class="primary" font-weight="600">{total_tokens:,}</tspan> tokens</text>
  <text class="secondary" x="170" y="52" font-size="12"><tspan class="primary" font-weight="600">{total_requests:,}</tspan> 次会话/请求</text>
  <rect class="muted" x="18" y="64" width="{width - 36}" height="30" rx="8"/>
  <rect class="tab-active" x="{active_x}" y="68" width="{tab_w}" height="22" rx="6" stroke-width="0.5"/>
  <text class="{'primary' if group_by == 'source' else 'secondary'}" x="{source_label_x:g}" y="83" text-anchor="middle" font-size="12" font-weight="500">ADE</text>
  <text class="{'primary' if group_by == 'model' else 'secondary'}" x="{model_label_x:g}" y="83" text-anchor="middle" font-size="12" font-weight="500">模型</text>
  {bars}
</svg>'''


def render(date: str | None = None) -> str:
    """读取 stats.json 并返回 SVG 字符串（供本地调试打印）。"""
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    return build_svg(stats, date)


if __name__ == "__main__":
    print(render())
