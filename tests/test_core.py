"""核心纯函数单测：compute_daily（聚合）与 rank_models（排行）。

运行：python tests/test_core.py   （无需任何第三方依赖）
"""
import os
import sys
import unittest

# 让 tests/ 也能 import 到仓库根级的 ranking / collectors
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import aggregate  # noqa: E402  (根级模块，非 collectors 包内)
from ranking import rank_models  # noqa: E402
from schema import validate_stats  # noqa: E402


class TestComputeDaily(unittest.TestCase):
    def _recs(self):
        return [
            {"source": "a", "model": "m1", "date": "2026-01-01",
             "requests": 1, "input_tokens": 10, "output_tokens": 5},
            {"source": "a", "model": "m1", "date": "2026-01-01",
             "requests": 2, "input_tokens": 20, "output_tokens": 0},
            {"source": "a", "model": "m2", "date": "2026-01-01",
             "requests": 1, "input_tokens": 100, "output_tokens": 0},
            {"source": "a", "model": "m1", "date": "2026-01-02",
             "requests": 1, "input_tokens": 7, "output_tokens": 7},
        ]

    def test_aggregates_same_key(self):
        daily = aggregate.compute_daily(self._recs())
        by = {(d["source"], d["model"], d["date"]): d for d in daily}
        self.assertEqual(by[("a", "m1", "2026-01-01")]["requests"], 3)
        self.assertEqual(by[("a", "m1", "2026-01-01")]["input_tokens"], 30)
        self.assertEqual(by[("a", "m1", "2026-01-01")]["total_tokens"], 35)

    def test_one_row_per_key(self):
        daily = aggregate.compute_daily(self._recs())
        self.assertEqual(len(daily), 3)  # (a,m1,01)(a,m2,01)(a,m1,02)

    def test_sorted_by_date_source_model(self):
        daily = aggregate.compute_daily(self._recs())
        keys = [(d["date"], d["source"], d["model"]) for d in daily]
        self.assertEqual(keys, sorted(keys))

    def test_empty(self):
        self.assertEqual(aggregate.compute_daily([]), [])


class TestRankModels(unittest.TestCase):
    def _daily(self):
        return [
            {"source": "a", "model": "m1", "date": "d", "requests": 1,
             "input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
            {"source": "a", "model": "m2", "date": "d", "requests": 1,
             "input_tokens": 50, "output_tokens": 0, "total_tokens": 50},
            {"source": "a", "model": "m3", "date": "d", "requests": 1,
             "input_tokens": 30, "output_tokens": 0, "total_tokens": 30},
            {"source": "a", "model": "m1", "date": "other", "requests": 1,
             "input_tokens": 999, "output_tokens": 0, "total_tokens": 999},
        ]

    def test_filters_by_date(self):
        view = rank_models(self._daily(), "d")
        self.assertEqual(view["date"], "d")
        self.assertEqual({r["label"] for r in view["rows"]}, {"m1", "m2", "m3"})

    def test_ranks_desc_and_limits(self):
        view = rank_models(self._daily(), "d", limit=2)
        self.assertEqual([r["label"] for r in view["rows"]], ["m2", "m3"])
        self.assertEqual(view["total_tokens"], 90)

    def test_pct_of_total(self):
        view = rank_models(self._daily(), "d")
        top = view["rows"][0]
        self.assertAlmostEqual(top["pct"], 50 / 90 * 100, places=4)

    def test_merges_same_model_across_rows(self):
        daily = self._daily() + [
            {"source": "b", "model": "m2", "date": "d", "requests": 1,
             "input_tokens": 0, "output_tokens": 0, "total_tokens": 10},
        ]
        view = rank_models(daily, "d")
        m2 = next(r for r in view["rows"] if r["label"] == "m2")
        self.assertEqual(m2["tokens"], 60)  # 50 + 10 合并

    def test_group_by_source(self):
        daily = self._daily() + [
            {"source": "b", "model": "m2", "date": "d", "requests": 1,
             "input_tokens": 0, "output_tokens": 0, "total_tokens": 10},
        ]
        view = rank_models(daily, "d", group_by="source")
        labels = [r["label"] for r in view["rows"]]
        self.assertEqual(labels, ["a", "b"])  # 按来源合并，且降序
        a = next(r for r in view["rows"] if r["label"] == "a")
        self.assertEqual(a["tokens"], 90)  # a 名下 m1+m2+m3

    def test_empty_date(self):
        self.assertEqual(rank_models(self._daily(), None)["rows"], [])
        self.assertEqual(rank_models([], "d")["rows"], [])


class TestContract(unittest.TestCase):
    """stats.json 必须符合仓库根 stats.schema.json 契约（单一事实源）。"""

    def test_generated_stats_conforms(self):
        import json

        path = os.path.join(ROOT, "data", "stats.json")
        if not os.path.exists(path):
            self.skipTest("data/stats.json 尚未生成，先跑 aggregate")
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
        errs = validate_stats(stats)
        self.assertEqual(errs, [], f"stats.json 不符合契约：{errs}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
