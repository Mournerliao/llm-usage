"""编排：加载配置 → 运行采集（cloud / local 两侧）→ 汇总 → 渲染。

用法：
  python run.py --mode cloud  --date 2026-08-16   # 在 GitHub Action 中运行（API 类源）
  python run.py --mode local  --date 2026-08-16   # 在本机运行（Cursor / WorkBuddy 等）
  python run.py --mode all    --date 2026-08-16   # 本地一次性全跑（调试用）
"""
import argparse
from datetime import date as _date
from pathlib import Path

import yaml

from collectors import save_records
from collectors import openai_compatible, cursor, workbuddy
import aggregate
import render

ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "sources.yaml"
LOCAL_SIDE = {"cursor": cursor, "workbuddy": workbuddy}
CLOUD_SIDE = {"openai_compatible": openai_compatible}


def load_config():
    if not CFG_PATH.exists():
        raise SystemExit(
            f"找不到 {CFG_PATH}，请复制 config/sources.example.yaml 为 sources.yaml")
    return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")).get("sources", [])


def run_mode(mode, run_date):
    cfg = load_config()
    cloud_recs, local_recs = [], []

    for src in cfg:
        name = src["name"]
        stype = src["type"]
        if stype in CLOUD_SIDE and mode in ("cloud", "all"):
            recs = CLOUD_SIDE[stype].collect(name, src, run_date)
            if recs:
                save_records(recs, ROOT / "data" / "cloud" / f"{name}.json")
            cloud_recs += recs
        elif stype in LOCAL_SIDE and mode in ("local", "all"):
            recs = LOCAL_SIDE[stype].collect(name, src, run_date)
            if recs:
                save_records(recs, ROOT / "data" / "local" / f"{name}.json")
            local_recs += recs

    print(f"[summary] cloud={len(cloud_recs)} 条, local={len(local_recs)} 条")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cloud", "local", "all"], default="all")
    ap.add_argument("--date", default=_date.today().isoformat())
    args = ap.parse_args()

    (ROOT / "data" / "cloud").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "local").mkdir(parents=True, exist_ok=True)

    run_mode(args.mode, args.date)
    aggregate.aggregate()
    render.render(args.date)


if __name__ == "__main__":
    main()
