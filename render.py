"""渲染：根据 stats.json 生成 assets/widget.svg，并更新 README.md 中的组件。"""
import json
import re
from pathlib import Path

import ranking

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
README = ROOT / "README.md"


def render(date: str | None = None) -> str:
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    if date is None:
        date = stats.get("latest_date")

    # 排行归约交给纯函数 ranking.rank_models；此处只做「薄渲染」（排版 + 输出）。
    view = ranking.rank_models(stats.get("daily", []), date, limit=8)

    svg = _build_svg(view)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "widget.svg").write_text(svg, encoding="utf-8")
    print(f"[ok] 已生成 {ASSETS / 'widget.svg'}")

    _update_readme()
    return svg


def _build_svg(view: dict, width=680):
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


def _update_readme():
    img = "![ADE 每日用量](./assets/widget.svg)"
    if README.exists():
        text = README.read_text(encoding="utf-8")
    else:
        text = "# ADE 每日用量\n\n<!-- WIDGET_START -->\n<!-- WIDGET_END -->\n"
    if "<!-- WIDGET_START -->" in text:
        text = re.sub(r"<!-- WIDGET_START -->.*?<!-- WIDGET_END -->",
                      f"<!-- WIDGET_START -->\n{img}\n<!-- WIDGET_END -->",
                      text, flags=re.S)
    else:
        text = text.rstrip() + f"\n\n{img}\n"
    README.write_text(text, encoding="utf-8")
    print("[ok] 已更新 README.md 组件占位")


if __name__ == "__main__":
    render()
