"""Cursor 本地用量采集，读 ``~/.cursor/ai-tracking/ai-code-tracking.db``。

== 为什么用这个库 ==

Cursor 的会话内容存在 ``workspaceStorage/*/state.vscdb``（本机 4.2 GB）和
``globalStorage``，结构跨版本会变、解析成本高，而且里面没有现成的用量口径。
``ai-code-tracking.db`` 是 Cursor 自己用来统计「AI 写了多少代码」的库，表结构窄、
字段语义明确，正好能给出按模型的用量，因此选它。

== 表结构（实测） ==

``ai_code_hashes``：每一段 AI 产出的代码一行。
    requestId      本次 AI 请求 id
    conversationId 会话 id
    model          模型名，如 grok-4.5 / claude-opus-5 / composer-2.5
    source         入口：composer / cli / tab / human
    createdAt      毫秒时间戳

== 口径 ==

一天内某模型的 **distinct requestId 数** 记为 ``requests``。选它而不是 hash 行数，
因为 requestId 对应一次真实的 AI 请求，hash 行数只反映那次请求改了多少代码，
量级受单次改动大小影响太大（实测均值约 100 行/请求）。

已核实的边界：
  - requestId 从不跨天（实测 0 例），所以一次请求只会归到一天，不需要差分。
  - source='human' 的行 requestId 与 model 全为 NULL，是人工代码，整段跳过。
  - source='tab' 的行有 requestId 但 model 为 NULL，Tab 补全不上报模型，
    归为 ``cursor-tab`` 而不是丢掉——它确实是 Cursor 的用量。
  - 极少数 requestId 跨两个模型（实测 2 例 / 597），会在两个模型下各记一次。
    不去做归属判定，2/597 的误差不值得引入猜测逻辑。

== 保留窗口 ==

库里只保留最近约一个月（实测 2026-07-20 起，共 29 天），更早的数据被 Cursor
自己清理掉了。所以首次采集能一次性回填近一个月历史，但也必须定期采集，
否则数据会在滚出窗口后永久丢失。
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import CollectContext, Event, find_db, sqlite_snapshot

# Tab 补全不上报模型名，用一个显式标签代替 NULL，避免它在排行里变成 "unknown"
TAB_MODEL = "cursor-tab"


def _candidates(cfg: dict) -> list[Path]:
    if cfg.get("db_path"):
        return [Path(cfg["db_path"]).expanduser()]
    home = Path.home()
    return [
        home / ".cursor" / "ai-tracking" / "ai-code-tracking.db",
        home / "AppData" / "Roaming" / "Cursor" / "ai-tracking" / "ai-code-tracking.db",
    ]


def collect(ctx: CollectContext, cfg: dict) -> list[Event]:
    name = cfg.get("name", "cursor")
    db_path = find_db(_candidates(cfg))
    if not db_path:
        print(f"[warn] {name}: 未找到 ai-code-tracking.db，跳过（需在本机运行）")
        return []

    cutoff = ctx.day_of_start_ms(ctx.lookback_days)
    try:
        with sqlite_snapshot(db_path) as con:
            rows = con.execute(
                """
                SELECT requestId, model, source, createdAt
                FROM ai_code_hashes
                WHERE createdAt >= ? AND source <> 'human'
                """,
                (cutoff,),
            ).fetchall()
    except Exception as exc:
        print(f"[error] {name}: 读取 {db_path} 失败: {exc}")
        return []

    # (day, model, surface) -> {requestId}
    buckets: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        request_id = row["requestId"]
        if not request_id:
            continue
        surface = row["source"] or "unknown"
        model = row["model"] or (TAB_MODEL if surface == "tab" else "")
        if not model:
            continue
        buckets[(ctx.day_of(row["createdAt"]), model, surface)].add(request_id)

    events = [
        Event(
            date=day,
            machine=ctx.machine,
            source=name,
            model=model,
            unit="requests",
            amount=len(request_ids),
            surface=surface,
        )
        for (day, model, surface), request_ids in sorted(buckets.items())
    ]

    total = sum(e.amount for e in events)
    print(f"[ok] {name}: 近 {ctx.lookback_days} 天 {total} 次请求，"
          f"覆盖 {len({e.date for e in events})} 天")
    return events


def collected_days(ctx: CollectContext) -> list[str]:
    """本采集器本次「负责」的日期：回看窗口内的每一天。

    这些天会被覆盖式写回原始文件。之所以要显式列出而不是只写有用量的天，
    是为了让「某天其实没有用量」这件事也能被正确记录——否则删掉的旧记录会留成幽灵。
    """
    return ctx.recent_days(ctx.lookback_days)
