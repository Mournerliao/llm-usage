"""把 stats.json 渲染成静态 SVG 卡片，写到 assets/。

== 为什么是静态文件而不是动态端点 ==

数据一天更新一次，push 的那一刻内容就已确定；GitHub 的 camo 还会把图片缓存 5~10
分钟。动态端点换不来实时性，却要维护一份复制的渲染逻辑（Vercel 只打包 api/ 目录），
并且引入一个可能 502 的外部依赖。所以改成构建期生成、随仓库提交，本模块成为唯一
的 SVG 实现。

主题用 GitHub 的 ``#gh-light-mode-only`` / ``#gh-dark-mode-only`` 图片语法解决，
所以每个维度各生成亮/暗两份，而不是靠 CSS 媒体查询。
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

import ranking

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ASSETS = ROOT / "assets"

WIDTH = 560
PAD = 18
ROW_H = 28
SECTION_HEAD_H = 22
SECTION_GAP = 6
BODY_TOP = 68
LABEL_W = 112
TRACK_X = 145

PALETTES = {
    "light": {"surface": "#ffffff", "border": "#e5e7eb", "primary": "#111827",
              "secondary": "#6b7280", "muted": "#f3f4f6", "accent": "#378add"},
    "dark": {"surface": "#0d1117", "border": "#30363d", "primary": "#f0f6fc",
             "secondary": "#8b949e", "muted": "#21262d", "accent": "#378add"},
}

FONT = ("-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, "
        "Roboto, sans-serif")


def _fmt(n: int) -> str:
    return f"{n:,}"


def _totals_text(totals: list[dict]) -> str:
    """把各单位的汇总拼成一行，例如「136 次请求 · 2 个会话」。

    刻意不给出跨单位的「总量」：请求数和会话数相加没有意义。
    """
    if not totals:
        return "暂无用量"
    return "  ·  ".join(
        ranking.unit_counted(t["unit"], t["amount"]) for t in totals)


def build_svg(
    stats: dict,
    date: str | None = None,
    group_by: str = "model",
    theme: str = "light",
    width: int = WIDTH,
    limit: int = 8,
) -> str:
    """根据 stats.json 构建一张 SVG 字符串（纯函数，不写盘）。"""
    theme = theme if theme in PALETTES else "light"
    c = PALETTES[theme]
    if date is None:
        date = stats.get("latest_date")

    view = ranking.build_view(stats.get("daily", []), date, limit=limit,
                              group_by=group_by)
    sections = [s for s in view["sections"] if s["rows"]]
    track_w = max(width - TRACK_X - 60, 80)

    # 只有一种单位时，小节标题会和顶部汇总行显示同一个数，是冗余，省掉。
    show_headers = len(sections) > 1

    body: list[str] = []
    y = BODY_TOP
    for section in sections:
        if show_headers:
            body.append(
                f'<text x="{PAD}" y="{y + 14}" fill="{c["secondary"]}" font-size="11" '
                f'font-weight="500">{escape(ranking.unit_label(section["unit"]))}'
                f'<tspan fill="{c["primary"]}" font-weight="600"> '
                f'{_fmt(section["total"])}</tspan></text>'
            )
            y += SECTION_HEAD_H
        for row in section["rows"]:
            pct = min(max(row["pct"], 0), 100)
            bar_w = max(3, round(track_w * pct / 100))
            body.append(
                f'<text x="{PAD}" y="{y + 16}" fill="{c["secondary"]}" font-size="12" '
                f'clip-path="url(#label-clip)">{escape(str(row["label"]))}</text>'
                f'<rect x="{TRACK_X}" y="{y + 8}" width="{track_w}" height="8" rx="4" '
                f'fill="{c["muted"]}"/>'
                f'<rect x="{TRACK_X}" y="{y + 8}" width="{bar_w}" height="8" rx="4" '
                f'fill="{c["accent"]}"/>'
                f'<text x="{width - PAD}" y="{y + 16}" fill="{c["secondary"]}" '
                f'text-anchor="end" font-size="11">{pct:.0f}%</text>'
            )
            y += ROW_H
        y += SECTION_GAP

    if not sections:
        body.append(f'<text x="{PAD}" y="{BODY_TOP + 16}" fill="{c["secondary"]}" '
                    f'font-size="12">暂无用量数据</text>')
        y = BODY_TOP + ROW_H

    height = y + 8
    dim = ranking.dimension_label(view["group_by"])
    shown_date = escape(str(view["date"] or "—"))
    title = f"LLM 每日用量，按{dim}，{shown_date}"

    return f'''<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" \
role="img" aria-labelledby="card-title" xmlns="http://www.w3.org/2000/svg" \
font-family="{FONT}">
  <title id="card-title">{escape(title)}</title>
  <defs><clipPath id="label-clip"><rect x="{PAD}" y="0" width="{LABEL_W}" \
height="{height}"/></clipPath></defs>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="13.5" \
fill="{c["surface"]}" stroke="{c["border"]}"/>
  <text x="{PAD}" y="27" fill="{c["primary"]}" font-size="15" font-weight="600">\
LLM 每日用量</text>
  <rect x="{width - 118}" y="13" width="100" height="22" rx="6" fill="{c["muted"]}"/>
  <text x="{width - 68}" y="28" fill="{c["secondary"]}" text-anchor="middle" \
font-size="11">{shown_date}</text>
  <text x="{PAD}" y="52" fill="{c["secondary"]}" font-size="12">\
{escape(_totals_text(view["totals"]))}</text>
  <text x="{width - PAD}" y="52" fill="{c["secondary"]}" text-anchor="end" \
font-size="11">按{escape(dim)}</text>
  {"".join(body)}
</svg>
'''


def render_files(stats: dict, out_dir: Path = ASSETS,
                 date: str | None = None) -> list[Path]:
    """为每个维度生成亮/暗两份 SVG，返回写出的文件列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for group_by in ("model", "source"):
        for theme in ("light", "dark"):
            path = out_dir / f"widget-{group_by}-{theme}.svg"
            path.write_text(
                build_svg(stats, date=date, group_by=group_by, theme=theme),
                encoding="utf-8")
            written.append(path)
    return written


def render(date: str | None = None) -> list[Path]:
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    written = render_files(stats, date=date)
    print(f"[ok] 渲染完成：{', '.join(p.name for p in written)}")
    return written


if __name__ == "__main__":
    render()
