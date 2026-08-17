"""核心纯函数单测：事件折叠、视图构建、原始数据读写、契约校验、SVG 渲染。

运行：python tests/test_core.py   （只需 pyyaml，无其他第三方依赖）
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import aggregate  # noqa: E402
import render  # noqa: E402
from collectors import CollectContext, Event, read_all_events, write_events  # noqa: E402
from ranking import build_view, unit_counted  # noqa: E402
from schema import validate_stats  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")


def event(date, model, unit="requests", amount=1, machine="m1", source="cursor",
          **kwargs):
    return Event(date=date, machine=machine, source=source, model=model,
                 unit=unit, amount=amount, **kwargs).to_dict()


class TestEventContract(unittest.TestCase):
    def test_rejects_unknown_unit(self):
        with self.assertRaises(ValueError):
            Event(date="2026-01-01", machine="m", source="s", model="x",
                  unit="bananas", amount=1)

    def test_to_dict_drops_empty_optionals(self):
        """拆不开输入输出的源不应留下 amount_in: null 这种半真半假的字段。"""
        d = Event(date="2026-01-01", machine="m", source="s", model="x",
                  unit="requests", amount=3).to_dict()
        self.assertNotIn("amount_in", d)
        self.assertNotIn("surface", d)


class TestFoldEvents(unittest.TestCase):
    def test_sums_same_key(self):
        daily = aggregate.fold_events([
            event("2026-01-01", "m1", amount=2),
            event("2026-01-01", "m1", amount=3),
        ])
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["amount"], 5)

    def test_keeps_units_separate(self):
        """同一天同一模型的不同单位必须留在不同行，绝不相加。"""
        daily = aggregate.fold_events([
            event("2026-01-01", "m1", unit="requests", amount=2),
            event("2026-01-01", "m1", unit="sessions", amount=7),
        ])
        self.assertEqual({(r["unit"], r["amount"]) for r in daily},
                         {("requests", 2), ("sessions", 7)})

    def test_keeps_machines_separate(self):
        daily = aggregate.fold_events([
            event("2026-01-01", "m1", machine="work-mac", amount=2),
            event("2026-01-01", "m1", machine="home-win", amount=5),
        ])
        self.assertEqual(len(daily), 2)

    def test_applies_model_aliases(self):
        daily = aggregate.fold_events(
            [event("2026-01-01", "hy3", amount=1),
             event("2026-01-01", "hy3-ioa", amount=2)],
            aliases={"hy3-ioa": "hy3"},
        )
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["model"], "hy3")
        self.assertEqual(daily[0]["amount"], 3)

    def test_split_dropped_when_any_source_cannot_split(self):
        """一半有拆分一半没有时，整体不给拆分，避免展示出偏小的 input/output。"""
        daily = aggregate.fold_events([
            event("2026-01-01", "m1", unit="tokens", amount=10,
                  amount_in=6, amount_out=4),
            event("2026-01-01", "m1", unit="tokens", amount=5),
        ])
        self.assertEqual(daily[0]["amount"], 15)
        self.assertNotIn("amount_in", daily[0])

    def test_split_kept_when_all_sources_split(self):
        daily = aggregate.fold_events([
            event("2026-01-01", "m1", unit="tokens", amount=10,
                  amount_in=6, amount_out=4),
            event("2026-01-01", "m1", unit="tokens", amount=10,
                  amount_in=7, amount_out=3),
        ])
        self.assertEqual((daily[0]["amount_in"], daily[0]["amount_out"]), (13, 7))

    def test_empty(self):
        self.assertEqual(aggregate.fold_events([]), [])

    def test_build_stats_summarises_axes(self):
        stats = aggregate.build_stats(aggregate.fold_events([
            event("2026-01-01", "m1", machine="a"),
            event("2026-01-02", "m2", machine="b", unit="sessions"),
        ]))
        self.assertEqual(stats["schema_version"], aggregate.SCHEMA_VERSION)
        self.assertEqual(stats["latest_date"], "2026-01-02")
        self.assertEqual(stats["total_dates"], 2)
        self.assertEqual(stats["units"], ["requests", "sessions"])
        self.assertEqual(stats["machines"], ["a", "b"])


class TestBuildView(unittest.TestCase):
    def _daily(self):
        return aggregate.fold_events([
            event("d", "m1", amount=10),
            event("d", "m2", amount=50),
            event("d", "m3", amount=30),
            event("d", "s1", unit="sessions", amount=4, source="other-ade"),
            event("other", "m1", amount=999),
        ])

    def test_filters_by_date(self):
        view = build_view(self._daily(), "d")
        labels = {r["label"] for s in view["sections"] for r in s["rows"]}
        self.assertEqual(labels, {"m1", "m2", "m3", "s1"})

    def test_one_section_per_unit(self):
        view = build_view(self._daily(), "d")
        self.assertEqual([s["unit"] for s in view["sections"]],
                         ["requests", "sessions"])

    def test_pct_is_within_section_not_global(self):
        """会话那节只有一行，占比必须是 100%，不能被请求数摊薄。"""
        view = build_view(self._daily(), "d")
        sessions = next(s for s in view["sections"] if s["unit"] == "sessions")
        self.assertEqual(sessions["rows"][0]["pct"], 100.0)
        requests = next(s for s in view["sections"] if s["unit"] == "requests")
        top = requests["rows"][0]
        self.assertAlmostEqual(top["pct"], 50 / 90 * 100, places=4)

    def test_totals_are_per_unit(self):
        view = build_view(self._daily(), "d")
        self.assertEqual(view["totals"],
                         [{"unit": "requests", "amount": 90},
                          {"unit": "sessions", "amount": 4}])

    def test_ranks_desc_and_limits(self):
        view = build_view(self._daily(), "d", limit=2)
        requests = next(s for s in view["sections"] if s["unit"] == "requests")
        self.assertEqual([r["label"] for r in requests["rows"]], ["m2", "m3"])

    def test_group_by_source(self):
        view = build_view(self._daily(), "d", group_by="source")
        requests = next(s for s in view["sections"] if s["unit"] == "requests")
        self.assertEqual([r["label"] for r in requests["rows"]], ["cursor"])

    def test_group_by_machine(self):
        daily = aggregate.fold_events([
            event("d", "m1", machine="work-mac", amount=3),
            event("d", "m1", machine="home-win", amount=7),
        ])
        view = build_view(daily, "d", group_by="machine")
        rows = view["sections"][0]["rows"]
        self.assertEqual([r["label"] for r in rows], ["home-win", "work-mac"])

    def test_invalid_dimension_falls_back_to_model(self):
        view = build_view(self._daily(), "d", group_by="nonsense")
        self.assertEqual(view["group_by"], "model")

    def test_empty_date(self):
        self.assertEqual(build_view(self._daily(), None)["sections"], [])
        self.assertEqual(build_view([], "d")["sections"], [])

    def test_unit_counted_uses_chinese_measure_words(self):
        self.assertEqual(unit_counted("requests", 1234), "1,234 次请求")
        self.assertEqual(unit_counted("sessions", 2), "2 个会话")


class TestRawLayer(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [Event(date="2026-08-17", machine="m1", source="cursor",
                            model="x", unit="requests", amount=3)]
            write_events(root, "m1", "cursor", events, ["2026-08-17"])
            back = read_all_events(root)
            self.assertEqual(len(back), 1)
            self.assertEqual(back[0]["amount"], 3)
            self.assertEqual(back[0]["machine"], "m1")

    def test_rerun_is_idempotent(self):
        """同一天重复采集不应累积出重复记录。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [Event(date="2026-08-17", machine="m1", source="cursor",
                            model="x", unit="requests", amount=3)]
            for _ in range(3):
                write_events(root, "m1", "cursor", events, ["2026-08-17"])
            self.assertEqual(len(read_all_events(root)), 1)

    def test_untouched_days_survive(self):
        """只负责今天的一次采集，不能抹掉昨天已经记下的数据。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "m1", "cursor", [
                Event(date="2026-08-16", machine="m1", source="cursor",
                      model="x", unit="requests", amount=1)], ["2026-08-16"])
            write_events(root, "m1", "cursor", [
                Event(date="2026-08-17", machine="m1", source="cursor",
                      model="x", unit="requests", amount=2)], ["2026-08-17"])
            dates = sorted(r["date"] for r in read_all_events(root))
            self.assertEqual(dates, ["2026-08-16", "2026-08-17"])

    def test_day_in_window_with_no_usage_is_cleared(self):
        """负责的那天若这次没有用量，旧记录要被清掉，不能留成幽灵。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "m1", "cursor", [
                Event(date="2026-08-17", machine="m1", source="cursor",
                      model="x", unit="requests", amount=9)], ["2026-08-17"])
            write_events(root, "m1", "cursor", [], ["2026-08-17"])
            self.assertEqual(read_all_events(root), [])

    def test_machines_do_not_share_files(self):
        """两台机器写不同文件，是「互不覆盖」这个性质的根据。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for machine in ("work-mac", "home-win"):
                write_events(root, machine, "cursor", [
                    Event(date="2026-08-17", machine=machine, source="cursor",
                          model="x", unit="requests", amount=1)], ["2026-08-17"])
            files = sorted(p.relative_to(root).as_posix()
                           for p in root.glob("data/raw/*/*/*.json"))
            self.assertEqual(files, [
                "data/raw/home-win/cursor/2026-08.json",
                "data/raw/work-mac/cursor/2026-08.json",
            ])
            self.assertEqual(len(read_all_events(root)), 2)

    def test_spans_month_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                Event(date="2026-07-31", machine="m1", source="cursor",
                      model="x", unit="requests", amount=1),
                Event(date="2026-08-01", machine="m1", source="cursor",
                      model="x", unit="requests", amount=2),
            ]
            write_events(root, "m1", "cursor", events,
                         ["2026-07-31", "2026-08-01"])
            self.assertEqual(len(read_all_events(root)), 2)
            self.assertEqual(
                sorted(p.name for p in root.glob("data/raw/*/*/*.json")),
                ["2026-07.json", "2026-08.json"])


class TestCollectContext(unittest.TestCase):
    def test_recent_days_is_ascending_and_includes_today(self):
        ctx = CollectContext(machine="m", tz=TZ, root=Path("."))
        days = ctx.recent_days(3)
        self.assertEqual(len(days), 3)
        self.assertEqual(days, sorted(days))
        self.assertEqual(days[-1], ctx.today())

    def test_day_of_uses_configured_tz_not_utc(self):
        """UTC+8 的凌晨零点半必须归到当天，而不是被 UTC 拉回前一天。"""
        ctx = CollectContext(machine="m", tz=TZ, root=Path("."))
        ms = int(datetime(2026, 8, 17, 0, 30, tzinfo=TZ).timestamp() * 1000)
        self.assertEqual(ctx.day_of(ms), "2026-08-17")

    def test_lookback_start_covers_whole_first_day(self):
        ctx = CollectContext(machine="m", tz=TZ, root=Path("."))
        start_ms = ctx.day_of_start_ms(7)
        self.assertEqual(ctx.day_of(start_ms), ctx.recent_days(7)[0])
        expected = datetime.now(TZ).date() - timedelta(days=6)
        self.assertEqual(ctx.recent_days(7)[0], expected.isoformat())


class TestContract(unittest.TestCase):
    def test_valid_stats_pass(self):
        stats = aggregate.build_stats(aggregate.fold_events([event("d", "m1")]))
        self.assertEqual(validate_stats(stats), [])

    def test_missing_fields_are_reported(self):
        self.assertTrue(validate_stats({"daily": []}))

    def test_wrong_schema_version_is_reported(self):
        stats = aggregate.build_stats(aggregate.fold_events([event("d", "m1")]))
        stats["schema_version"] = 1
        self.assertTrue(any("schema_version" in e for e in validate_stats(stats)))

    def test_unknown_unit_is_reported(self):
        stats = aggregate.build_stats(aggregate.fold_events([event("d", "m1")]))
        stats["daily"][0]["unit"] = "bananas"
        self.assertTrue(any("unit" in e for e in validate_stats(stats)))

    def test_generated_stats_conforms(self):
        path = os.path.join(ROOT, "data", "stats.json")
        if not os.path.exists(path):
            self.skipTest("data/stats.json 尚未生成，先跑 run.py")
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
        self.assertEqual(validate_stats(stats), [])


class TestSvgRenderer(unittest.TestCase):
    def _stats(self):
        return aggregate.build_stats(aggregate.fold_events([
            event("2026-01-01", "m1", amount=5, source="ADE <local>"),
            event("2026-01-01", "m2", amount=3),
            event("2026-01-01", "s1", unit="sessions", amount=2,
                  source="other-ade"),
        ]))

    def test_escapes_labels(self):
        svg = render.build_svg(self._stats(), group_by="source")
        self.assertIn("ADE &lt;local&gt;", svg)
        self.assertNotIn("ADE <local>", svg)

    def test_height_grows_with_sections(self):
        """两个单位比一个单位高：高度是按内容算的，不是写死的。"""
        one = aggregate.build_stats(aggregate.fold_events(
            [event("2026-01-01", "m1")]))
        tall = render.build_svg(self._stats())
        short = render.build_svg(one)
        self.assertGreater(_svg_height(tall), _svg_height(short))

    def test_single_unit_omits_redundant_section_header(self):
        one = aggregate.build_stats(aggregate.fold_events(
            [event("2026-01-01", "m1", amount=4)]))
        svg = render.build_svg(one)
        self.assertIn("4 次请求", svg)          # 顶部汇总行
        self.assertNotIn(">请求<", svg)          # 不再重复一次小节标题

    def test_multi_unit_shows_section_headers(self):
        svg = render.build_svg(self._stats())
        self.assertIn("请求", svg)
        self.assertIn("会话", svg)

    def test_totals_never_merge_units(self):
        """8 次请求 + 2 个会话，绝不能出现一个 10。"""
        svg = render.build_svg(self._stats())
        self.assertIn("8 次请求", svg)
        self.assertIn("2 个会话", svg)
        self.assertNotIn("10 ", svg)

    def test_theme_changes_colors(self):
        light = render.build_svg(self._stats(), theme="light")
        dark = render.build_svg(self._stats(), theme="dark")
        self.assertIn(render.PALETTES["light"]["surface"], light)
        self.assertIn(render.PALETTES["dark"]["surface"], dark)

    def test_invalid_options_fall_back_safely(self):
        svg = render.build_svg(self._stats(), group_by="nonsense",
                               theme="nonsense")
        self.assertIn("按模型", svg)
        self.assertIn(render.PALETTES["light"]["surface"], svg)

    def test_empty_day_renders_placeholder(self):
        svg = render.build_svg({"daily": [], "latest_date": None})
        self.assertIn("暂无用量数据", svg)

    def test_render_files_writes_both_themes_and_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = render.render_files(self._stats(), out_dir=Path(tmp))
            self.assertEqual(sorted(p.name for p in written), [
                "widget-model-dark.svg", "widget-model-light.svg",
                "widget-source-dark.svg", "widget-source-light.svg",
            ])


def _svg_height(svg: str) -> int:
    import re
    return int(re.search(r'height="(\d+)"', svg).group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
