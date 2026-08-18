"""编排：加载配置 → 采集 → 写原始数据 → 汇总 → 渲染。

用法：
    python -m llm_usage                      # 采集所有源
    python -m llm_usage --only cursor        # 只采某个源
    python -m llm_usage --since 2026-07-01   # 覆盖采集起点
    python -m llm_usage --skip-collect       # 只重跑汇总与渲染（CI 用这条）

采集是幂等的：每次重采 [起点, 今天] 的全部数据并覆盖写回，跑一次和跑十次结果相同，
漏跑补跑都能自愈。所以不需要维护游标文件，也不怕中途失败。
"""
from __future__ import annotations

import argparse

from llm_usage import REPO_ROOT, config, fold, render
from llm_usage.collect import COLLECTORS, CollectContext, persist


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
        total += persist(ctx, module.collect(ctx, src))
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
            root=REPO_ROOT,
            since=args.since or sources_cfg.get("since", "2026-01-01"),
            machine=sources_cfg.get("machine"),
        )
        print(f"[start] tz={ctx.tz} since={ctx.since}")
        count = run_collect(ctx, sources_cfg["sources"], args.only)
        print(f"[summary] 采集到 {count} 条日模型记录")

    stats = fold.aggregate(REPO_ROOT)
    render.render_files(stats)
    print(f"[done] latest_date={stats['latest_date']} "
          f"{stats.get('updated_display', '')}")


if __name__ == "__main__":
    main()
