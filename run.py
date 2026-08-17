"""编排：加载配置 → 采集 → 写原始数据 → 汇总 → 渲染。

用法：
    python run.py                      # 采集本机所有源（默认回看 30 天）
    python run.py --only cursor        # 只采某个源
    python run.py --lookback 7         # 缩短回看窗口
    python run.py --skip-collect       # 只重跑汇总与渲染（CI 用这条）

采集是幂等的：每次重采回看窗口内的每一天并覆盖写回，跑一次和跑十次结果相同。
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

        events = module.collect(ctx, src)
        days = module.collected_days(ctx)
        write_events(ctx.root, ctx.machine, name, events, days)
        total += len(events)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只采集指定名字的源")
    ap.add_argument("--lookback", type=int, default=30,
                    help="回看天数，窗口内每天都会被重采并覆盖写回")
    ap.add_argument("--skip-collect", action="store_true",
                    help="跳过采集，只重跑汇总与渲染")
    args = ap.parse_args()

    if not args.skip_collect:
        sources_cfg = config.load_sources_config()
        ctx = CollectContext(
            machine=sources_cfg["machine"],
            tz=config.timezone(),
            root=ROOT,
            lookback_days=args.lookback,
        )
        print(f"[start] machine={ctx.machine} tz={ctx.tz} lookback={ctx.lookback_days}d")
        count = run_collect(ctx, sources_cfg["sources"], args.only)
        print(f"[summary] 采集到 {count} 条事件")

    stats = aggregate.aggregate(ROOT)
    render.render_files(stats)
    print(f"[done] latest_date={stats['latest_date']}")


if __name__ == "__main__":
    main()
