"""编排：加载配置 → 采集 → 写原始数据 → 汇总 → 渲染。

用法：
    python -m llm_usage                      # 采集所有源
    python -m llm_usage --only cursor        # 只采某个源
    python -m llm_usage --since 2026-07-01   # 覆盖采集起点
    python -m llm_usage --collect-only       # 只采集，不汇总不渲染（本机推 raw）
    python -m llm_usage --skip-collect       # 只重跑汇总与渲染（CI 用这条）

采集是幂等的：每次重采 [起点, 今天] 的全部数据并覆盖写回，跑一次和跑十次结果相同，
漏跑补跑都能自愈。所以不需要维护游标文件，也不怕中途失败。
"""
from __future__ import annotations

import argparse

from llm_usage import REPO_ROOT, config, fold, render
from llm_usage.collect import COLLECTORS, CollectContext, persist


def run_collect(ctx: CollectContext, sources: list[dict], only: str | None) -> int:
    """逐源采集。某一个采集器失败时继续后面的源；落盘错误仍中止。"""
    total = 0
    ok = 0
    failed = 0
    for src in sources:
        name, stype = src.get("name"), src.get("type")
        if only and name != only:
            continue
        module = COLLECTORS.get(stype)
        if module is None:
            print(f"[warn] {name}: 未知源类型 {stype}，跳过")
            continue
        try:
            result = module.collect(ctx, src)
        except (SystemExit, Exception) as exc:
            failed += 1
            print(f"[error] {name}: {exc}")
            continue
        total += persist(ctx, result)
        ok += 1
    if failed and not ok:
        raise SystemExit(f"{failed} 个源采集失败，没有任何数据写入")
    if failed:
        print(f"[warn] {failed} 个源失败，已写入其余源的 {total} 条")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只采集指定名字的源")
    ap.add_argument("--since", help="采集起点（YYYY-MM-DD），覆盖 sources.yaml 的设置")
    ap.add_argument("--collect-only", action="store_true",
                    help="只采集并写 raw，跳过汇总与渲染")
    ap.add_argument("--skip-collect", action="store_true",
                    help="跳过采集，只重跑汇总与渲染")
    args = ap.parse_args()
    if args.collect_only and args.skip_collect:
        raise SystemExit("--collect-only 与 --skip-collect 不能同时使用")

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

    if args.collect_only:
        return

    stats = fold.aggregate(REPO_ROOT)
    render.render_files(stats)
    print(f"[done] latest_date={stats['latest_date']} "
          f"{stats.get('updated_display', '')}")


if __name__ == "__main__":
    main()
