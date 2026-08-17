"""编排：加载配置 → 采集 → 写原始数据 → 汇总 → 渲染。

用法：
    python run.py                      # 采集所有源
    python run.py --only cursor        # 只采某个源
    python run.py --since 2026-07-01   # 覆盖采集起点
    python run.py --skip-collect       # 只重跑汇总与渲染（CI 用这条）

采集是幂等的：每次重采 [起点, 今天] 的全部数据并覆盖写回，跑一次和跑十次结果相同，
漏跑补跑都能自愈。所以不需要维护游标文件，也不怕中途失败。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import aggregate
import config
import render
from collectors import CollectContext, write_events
from collectors import cursor, openai_compatible

ROOT = Path(__file__).resolve().parent

# 源类型 → 采集器模块。新增一类源只需在这里登记。
COLLECTORS = {
    "cursor": cursor,
    "openai_compatible": openai_compatible,
}


def run_collect(ctx: CollectContext, sources: list[dict], only: str | None) -> int:
    total = 0
    for src in sources:
        name, stype = src.get("name"), src.get("type")
        if only and name != only:
            continue
        module = COLLECTORS.get(stype)
        if module is None:
            print(f"[warn] {name}: 未知源类型 {stype}，跳过")
            continue

        events, days = module.collect(ctx, src)
        if days:
            write_events(ctx.root, name, events, days)
        total += len(events)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只采集指定名字的源")
    ap.add_argument("--since", help="采集起点（YYYY-MM-DD），覆盖 sources.yaml 的设置")
    ap.add_argument("--skip-collect", action="store_true",
                    help="跳过采集，只重跑汇总与渲染")
    args = ap.parse_args()

    if not args.skip_collect:
        sources_cfg = config.load_sources_config()
        ctx = CollectContext(
            tz=config.timezone(),
            root=ROOT,
            since=args.since or sources_cfg.get("since", "2026-01-01"),
        )
        print(f"[start] tz={ctx.tz} since={ctx.since}")
        count = run_collect(ctx, sources_cfg["sources"], args.only)
        print(f"[summary] 采集到 {count} 条日模型记录")

    stats = aggregate.aggregate(ROOT)
    render.render_files(stats)
    print(f"[done] latest_date={stats['latest_date']}")


if __name__ == "__main__":
    main()
