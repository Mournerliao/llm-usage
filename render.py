"""渲染辅助：根据 stats.json 生成 SVG 字符串（纯函数，不写盘）。

线上 widget 由 api/widget.py 在 Vercel 端**动态生成**，
本模块只作为 SVG 模板参考 / 本地调试用途，不再写 assets/widget.svg，
也不再改动 README.md（README 现在固定嵌入 Vercel 动态地址）。
"""
import json
from pathlib import Path

import ranking

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def build_svg(stats: dict, date: str | None = None, width: int = 680) -> str:
    """根据 stats.json 构建一张 SVG 字符串（不写盘）。"""
    if date is None:
        date = stats.get("latest_date")

    view = ranking.rank_models(stats.get("daily", []), date, limit=8)
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


def render(date: str | None = None) -> str:
    """读取 stats.json 并返回 SVG 字符串（供本地调试打印）。"""
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    return build_svg(stats, date)


if __name__ == "__main__":
    print(render())
