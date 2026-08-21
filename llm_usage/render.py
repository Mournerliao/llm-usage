"""把某一周的视图渲染成静态 SVG，供 README 直接引用。

只渲染**本周**一张卡片（亮暗两版）。历史与四周切换交给博客里的 widget——
README 里的图是静态的，塞进多周内容只会让它变拥挤，而看历史的人本来就会点进组件。

== 两个平台约束决定了排版 ==

GitHub 会把 README 里的 SVG 当图片渲染（camo 代理），所以：**不能加载外部字体**，
**不能有 JS、hover、动画**。字体只能用系统栈。

因此数字统一用系统等宽栈：一是等宽字形天生按位对齐，金额与 token 量成列后小数点
自然对齐；二是它在三个平台上都存在，不会退化成后备字体导致排版错位。语言文字
（标签、模型名）用系统无衬线栈。

宽度按 760 个用户单位排版（``CARD_W``），``viewBox`` 钉死这个坐标系。真正显示时
由 ``<img width="100%">`` 拉满 README 栏宽——放大没事，缩小才会把 13px 注解压糊，
那是 GitHub 窄屏自己的 ``max-width: 100%``，拦不住。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_usage import REPO_ROOT, view as weekview

ASSETS = REPO_ROOT / "assets"

CARD_W = 760

SANS = ("-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif")
MONO = ("ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
        "'Liberation Mono',monospace")

# 亮暗两套色板。暗色底取 GitHub 暗色主题的正文底色，卡片才不会浮在页面上。
# 所有正文级文字对底色的对比度都在 4.5:1 以上，小字不用更浅的灰。
THEMES = {
    "light": {
        "bg": "#FFFFFF",
        "border": "#E6E4DF",
        "ink": "#16181C",
        "muted": "#6C7076",
        # 只有左上角那个 token 总量用 GitHub Primer 的 success 绿。其余数字和条
        # 都走 ink / 灰阶，费用也不再单独染色。
        "accent": "#1A7F37",
        "track": "#EFEDE8",
        "bar": "#16181C",
        # 四个色阶之间的明度差刻意拉开：相邻两段挨在一起时边界要能看出来。
        # 最浅的一阶仍明显深于卡片底色——缓存读取常占九成宽度，若取到接近白色，
        # 整条会被读成「只填了 7% 的进度条」，而它其实是填满的四段构成。
        "kinds": {
            "tokens_in": "#16181C",
            "tokens_out": "#5A6066",
            "cache_write": "#939AA1",
            "cache_read": "#C6CACE",
        },
    },
    "dark": {
        "bg": "#0D1117",
        "border": "#242B33",
        "ink": "#E8E4DC",
        "muted": "#98A0A9",
        "accent": "#3FB950",
        "track": "#1C232B",
        "bar": "#D8D3CA",
        "kinds": {
            "tokens_in": "#E8E4DC",
            "tokens_out": "#9BA2AA",
            "cache_write": "#666E77",
            "cache_read": "#3F4750",
        },
    },
}

PAD = 32


def esc(text: Any) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _text(x: float, y: float, content: str, *, size: float, fill: str,
          family: str = SANS, weight: str | None = None,
          anchor: str | None = None, spacing: float | None = None,
          clip: str | None = None) -> str:
    attrs = [f'x="{x:g}"', f'y="{y:g}"', f'font-family="{family}"',
             f'font-size="{size:g}"', f'fill="{fill}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if spacing:
        attrs.append(f'letter-spacing="{spacing:g}"')
    if clip:
        attrs.append(f'clip-path="url(#{clip})"')
    return f'<text {" ".join(attrs)}>{esc(content)}</text>'


def _rule(y: float, theme: dict, x0: float = PAD, x1: float = CARD_W - PAD) -> str:
    return (f'<line x1="{x0:g}" y1="{y:g}" x2="{x1:g}" y2="{y:g}" '
            f'stroke="{theme["border"]}" stroke-width="1"/>')


def render_svg(view: dict[str, Any], theme_name: str = "light", *,
               updated_display: str = "") -> str:
    """把一周的视图渲染成一张卡片。``view`` 来自 ``stats.weeks[0].view``。

    ``updated_display`` 是产物刷新时刻，来自 ``stats.updated_display``，不是周视图
    的一部分。缺省则不印右端时间，方便单测只盯某一周的内容。
    """
    t = THEMES[theme_name]
    models = view.get("models") or []
    inner_w = CARD_W - PAD * 2
    body: list[str] = []

    # ---- 页眉：窗口身份在左（哪一周 + 区间），产物新鲜度在右。
    # 刷新时刻是快照元数据，跟区间同属这一行，不单独占一节。
    body.append(_window_title(t, view.get("range_display") or ""))
    if updated_display:
        body.append(_text(CARD_W - PAD, 44, updated_display, size=12.5,
                          fill=t["muted"], family=MONO, anchor="end"))

    if not view.get("week"):
        body.append(_text(PAD, 92, "No data", size=22, fill=t["ink"],
                          family=MONO, weight="600"))
        alt = "No usage data"
        if updated_display:
            alt += f". {updated_display}"
        return _wrap(body, 132, t, alt)

    # ---- 主数字：左 token 量，右折算成本。两者字号刻意差一级，token 是主角。
    #
    # "tokens" 用同一个 <text> 里的第二个 tspan 接在数字后面，让它按前一段的实际
    # 排版宽度自然流动。若改成算偏移量，就得假设等宽字形的 advance 是 0.6em——
    # macOS 的 SF Mono 是这个值，Windows 的 Consolas 不是，后缀会贴上或飘开。
    body.append(
        f'<text x="{PAD}" y="104" font-family="{MONO}" font-size="44" '
        f'fill="{t["accent"]}" font-weight="600">{esc(view["tokens_display"])}'
        f'<tspan font-family="{SANS}" font-size="13" fill="{t["ink"]}"'
        f' font-weight="400" dx="9">tokens</tspan></text>')
    body.append(_text(PAD, 126, f"{view['requests_display']} requests", size=12,
                      fill=t["ink"]))

    body.append(_text(CARD_W - PAD, 104, view["cost_display"], size=30,
                      fill=t["ink"], family=MONO, weight="600", anchor="end"))
    body.append(_text(CARD_W - PAD, 126, "Model cost", size=12, fill=t["muted"],
                      anchor="end"))

    body.append(_rule(146, t))

    # ---- token 四分类构成条。缓存读取通常占九成以上，这条线的用途正是让这件事
    # 一眼可见，而不是被一个总数盖住。
    y_bar = 164
    if view.get("breakdown"):
        # 缓存读取通常占九成以上，所以前三段被挤在最左边一小截里。用 1px 底色缝隙
        # 把相邻段切开，让它们即使只有几个像素宽也仍然读作独立的段，而不是让整条
        # 看起来像一条「只填了 7%」的进度条。比例保持线性，不做视觉放大。
        x = PAD
        segs = view["breakdown"]
        for i, seg in enumerate(segs):
            w = inner_w * seg["pct"] / 100
            if i == len(segs) - 1:
                w = CARD_W - PAD - x          # 末段吃掉舍入误差，右端严格对齐
            else:
                w -= 1
            if w <= 0:
                continue
            body.append(f'<rect x="{x:g}" y="{y_bar}" width="{max(w, 1):g}" '
                        f'height="8" fill="{t["kinds"][seg["kind"]]}"/>')
            x += w + (0 if i == len(segs) - 1 else 1)

        # 图例：色块 + 名称 + 数量，横向排开。列宽固定，避免长短不齐。
        col = inner_w / max(len(view["breakdown"]), 1)
        for i, seg in enumerate(view["breakdown"]):
            cx = PAD + col * i
            body.append(f'<rect x="{cx:g}" y="{y_bar + 22:g}" width="7" height="7" '
                        f'fill="{t["kinds"][seg["kind"]]}"/>')
            body.append(_text(cx + 13, y_bar + 29, seg["label"], size=11.5,
                              fill=t["muted"]))
            # 中文约 1em、拉丁约 0.56em；英文标签比原来的两到四字中文长，
            # 不能再按「一字 12px」估宽度，否则金额会叠到下一列上。
            body.append(_text(cx + 13 + _label_advance(seg["label"], 11.5) + 8,
                              y_bar + 29, seg["display"], size=11.5,
                              fill=t["ink"], family=MONO))

    y = y_bar + 46
    body.append(_rule(y, t))

    # ---- 模型行。条形长度按 token 占比，右侧两列是计费与 token 量。
    # 表头上方留得比下方多，让它归属于下面的表格，而不是漂在两块之间。
    y += 28
    body.append(_text(PAD, y, "Model", size=11, fill=t["muted"], spacing=1.2))
    body.append(_text(CARD_W - PAD - 96, y, "Cost", size=11, fill=t["muted"],
                      anchor="end", spacing=1.2))
    body.append(_text(CARD_W - PAD, y, "Tokens", size=11, fill=t["muted"],
                      anchor="end", spacing=1.2))

    name_w = 236
    bar_x = PAD + name_w + 20
    bar_w = 216                            # 英文 Subscription 比「订阅」宽，条形右端让出一截
    row_h = 27
    y += 8
    for i, row in enumerate(models):
        cy = y + row_h * i + 12
        body.append(_text(PAD, cy, row["label"], size=12.5, fill=t["ink"],
                          clip="nameclip"))
        body.append(f'<rect x="{bar_x}" y="{cy - 8:g}" width="{bar_w}" height="6" '
                    f'fill="{t["track"]}"/>')
        w = bar_w * row["pct"] / 100
        if w > 0:
            body.append(f'<rect x="{bar_x}" y="{cy - 8:g}" width="{max(w, 1):g}" '
                        f'height="6" fill="{t["bar"]}" fill-opacity="0.85"/>')
        body.append(_text(CARD_W - PAD - 96, cy, row["cost_display"], size=12.5,
                          fill=t["ink"], family=MONO, anchor="end"))
        body.append(_text(CARD_W - PAD, cy, row["tokens_display"], size=12,
                          fill=t["muted"], family=MONO, anchor="end"))

    y = y + row_h * max(len(models), 1) + 4
    height = y + 28
    alt = (f"This week {view['range_display']}: {view['tokens_display']} tokens, "
           f"model cost {view['cost_display']}")
    if updated_display:
        alt += f". {updated_display}"
    return _wrap(body, height, t, alt, clip_w=name_w)


def _window_title(theme: dict, range_display: str) -> str:
    """页眉左侧：This week 与日期区间收成一簇，区间不再独占右端。"""
    title = (
        f'<tspan letter-spacing="0.9">{esc("This week")}</tspan>'
    )
    if range_display:
        title += f'<tspan dx="8">· {esc(range_display)}</tspan>'
    return (
        f'<text x="{PAD}" y="44" font-family="{SANS}" font-size="12.5" '
        f'fill="{theme["muted"]}">{title}</text>'
    )


def _label_advance(label: str, size: float) -> float:
    """图例标签的估算宽度。中文按 1em，拉丁按 0.56em。"""
    return sum(size if ord(ch) > 0x2E80 else size * 0.56 for ch in label)


def _wrap(body: list[str], height: float, theme: dict, alt: str,
          clip_w: float = 236) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'height="{height:g}" viewBox="0 0 {CARD_W} {height:g}" role="img" '
        f'aria-label="{esc(alt)}">',
        f"<title>{esc(alt)}</title>",
        f'<defs><clipPath id="nameclip">'
        f'<rect x="{PAD}" y="0" width="{clip_w:g}" height="{height:g}"/>'
        f"</clipPath></defs>",
        f'<rect x="0.5" y="0.5" width="{CARD_W - 1}" height="{height - 1:g}" '
        f'rx="13" fill="{theme["bg"]}" stroke="{theme["border"]}"/>',
        *body,
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def render_files(stats: dict) -> list[Path]:
    """渲染本周卡片的亮暗两版，写入 assets/。"""
    weeks = stats.get("weeks") or []
    card = (weeks[0].get("view") if weeks else None) or weekview.build_week_view([], None)
    ASSETS.mkdir(exist_ok=True)
    written = []
    for theme in ("light", "dark"):
        path = ASSETS / f"widget-{theme}.svg"
        path.write_text(
            render_svg(card, theme,
                       updated_display=stats.get("updated_display") or ""),
            encoding="utf-8")
        written.append(path)
    print(f"[ok] 渲染 {len(written)} 个 SVG：{card.get('week') or '空'}")
    return written
