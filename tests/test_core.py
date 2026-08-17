"""核心纯函数单测：事件折叠、周窗口、视图构建、格式化、原始数据读写、契约、SVG。

运行：python tests/test_core.py   （只需 pyyaml，无其他第三方依赖）
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import aggregate  # noqa: E402
import ranking  # noqa: E402
import render  # noqa: E402
from collectors import CollectContext, Event, read_all_events, write_events  # noqa: E402
from collectors import chatgpt as chatgpt_collector  # noqa: E402
from collectors import cursor as cursor_collector  # noqa: E402
from schema import validate_stats  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")

# 一个完整的 ISO 周（周一到周日），后面多处复用。
WEEK = {"week": "2026-08-10", "start": "2026-08-10", "end": "2026-08-16"}


def row(date, model, source="cursor", requests=1, **kwargs):
    """构造一条日记录（fold_events 的输出形态）。"""
    return {"date": date, "source": source, "model": model,
            "requests": requests, **kwargs}


def tokens(**kwargs):
    """token 四分类的简写，未给出的按 0 填，避免每次写四个字段。"""
    return {"tokens_in": kwargs.get("i", 0), "tokens_out": kwargs.get("o", 0),
            "cache_write": kwargs.get("cw", 0), "cache_read": kwargs.get("cr", 0)}


class TestEventContract(unittest.TestCase):
    def test_to_dict_drops_missing_optionals(self):
        """不报 token 的源不该留下 tokens_in: null 这种半真半假的字段。"""
        d = Event(date="2026-01-01", source="s", model="x", requests=3).to_dict()
        self.assertNotIn("tokens_in", d)
        self.assertNotIn("cost_cents", d)
        self.assertEqual(d["requests"], 3)

    def test_tokens_total_is_none_when_source_reports_nothing(self):
        """「不报 token」必须区别于「报了但是零」。"""
        self.assertIsNone(
            Event(date="d", source="s", model="x", requests=1).tokens_total)

    def test_tokens_total_is_zero_when_source_reports_zeros(self):
        e = Event(date="d", source="s", model="x", requests=1, **tokens())
        self.assertEqual(e.tokens_total, 0)

    def test_tokens_total_sums_all_four_kinds(self):
        e = Event(date="d", source="s", model="x", requests=1,
                  **tokens(i=1, o=2, cw=4, cr=8))
        self.assertEqual(e.tokens_total, 15)

    def test_partial_report_counts_missing_as_zero(self):
        """只报输入输出的源（如 OpenAI 兼容接口）总量就是这两项之和。"""
        e = Event(date="d", source="s", model="x", requests=1,
                  tokens_in=10, tokens_out=5)
        self.assertEqual(e.tokens_total, 15)


class TestFoldEvents(unittest.TestCase):
    def test_sums_same_key(self):
        daily = aggregate.fold_events([
            Event(date="d", source="cursor", model="m", requests=2,
                  **tokens(i=10)).to_dict(),
            Event(date="d", source="cursor", model="m", requests=3,
                  **tokens(i=5)).to_dict(),
        ])
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["requests"], 5)
        self.assertEqual(daily[0]["tokens_in"], 15)

    def test_keeps_sources_separate(self):
        daily = aggregate.fold_events([
            row("d", "m", source="cursor"),
            row("d", "m", source="deepseek"),
        ])
        self.assertEqual(len(daily), 2)

    def test_applies_model_aliases(self):
        daily = aggregate.fold_events(
            [row("d", "hy3", requests=1), row("d", "hy3-ioa", requests=2)],
            aliases={"hy3-ioa": "hy3"},
        )
        self.assertEqual(len(daily), 1)
        self.assertEqual((daily[0]["model"], daily[0]["requests"]), ("hy3", 3))

    def test_missing_field_stays_missing(self):
        """所有参与事件都不报 cost 时，结果里不该凭空出现一个 0。"""
        daily = aggregate.fold_events([row("d", "m"), row("d", "m")])
        self.assertNotIn("cost_cents", daily[0])
        self.assertNotIn("cache_read", daily[0])

    def test_partial_report_is_summed_not_dropped(self):
        """一半的事件报了 cost，结果就是那一半之和——报了的数据不该因为别人没报而丢。"""
        daily = aggregate.fold_events([
            row("d", "m", cost_cents=12.5),
            row("d", "m"),
        ])
        self.assertAlmostEqual(daily[0]["cost_cents"], 12.5)

    def test_cost_keeps_sub_cent_precision(self):
        """三次各 0.4 分的调用应得 1.2 分。若中途取整成 0，求和会系统性偏小。"""
        daily = aggregate.fold_events([row("d", "m", cost_cents=0.4)] * 3)
        self.assertAlmostEqual(daily[0]["cost_cents"], 1.2, places=6)

    def test_empty(self):
        self.assertEqual(aggregate.fold_events([]), [])


class TestWeekWindow(unittest.TestCase):
    def test_iso_week_start_is_monday(self):
        # 2026-08-17 是周一，2026-08-23 是周日，同属一周。
        self.assertEqual(aggregate.iso_week_start("2026-08-17").isoformat(),
                         "2026-08-17")
        self.assertEqual(aggregate.iso_week_start("2026-08-23").isoformat(),
                         "2026-08-17")

    def test_sunday_belongs_to_the_week_that_started_monday(self):
        """周日归上一个周一，而不是开启新的一周——这是 ISO 周与「自然周」的分歧点。"""
        self.assertEqual(aggregate.iso_week_start("2026-08-16").isoformat(),
                         "2026-08-10")

    def test_recent_weeks_is_newest_first_and_contiguous(self):
        weeks = aggregate.recent_weeks("2026-08-19", count=4)
        self.assertEqual([w["start"] for w in weeks],
                         ["2026-08-17", "2026-08-10", "2026-08-03", "2026-07-27"])
        for week in weeks:
            self.assertEqual(aggregate.iso_week_start(week["end"]).isoformat(),
                             week["start"])

    def test_weeks_are_derived_from_data_not_from_today(self):
        """周次由最新数据日推出，所以同一份 raw 在任何时刻重跑都得到同一批周。"""
        daily = aggregate.fold_events([row("2026-05-06", "m")])
        stats = aggregate.build_stats(daily)
        self.assertEqual(stats["weeks"][0]["start"], "2026-05-04")

    def test_daily_window_is_trimmed_to_the_four_weeks(self):
        daily = aggregate.fold_events([
            row("2026-08-17", "m"),      # 本周
            row("2026-07-27", "m"),      # 窗口内最早一天
            row("2026-07-26", "m"),      # 窗口外，应被裁掉
        ])
        stats = aggregate.build_stats(daily)
        self.assertEqual(sorted(r["date"] for r in stats["daily"]),
                         ["2026-07-27", "2026-08-17"])

    def test_year_summary_keeps_data_outside_the_display_window(self):
        """裁掉的历史仍要进年度汇总，否则「先收集，后展示」就落空了。"""
        daily = aggregate.fold_events([
            row("2026-04-09", "m", requests=7, cost_cents=100.0),
            row("2026-08-17", "m", requests=3, cost_cents=50.0),
        ])
        stats = aggregate.build_stats(daily)
        year = stats["year"]
        self.assertEqual(year["year"], "2026")
        self.assertEqual(year["start"], "2026-04-09")
        self.assertEqual(year["requests"], 10)
        self.assertAlmostEqual(year["cost_cents"], 150.0)
        self.assertEqual(year["days_active"], 2)
        self.assertEqual([m["month"] for m in year["months"]],
                         ["2026-04", "2026-08"])

    def test_empty_stats_has_no_weeks(self):
        stats = aggregate.build_stats([])
        self.assertIsNone(stats["latest_date"])
        self.assertEqual(stats["weeks"], [])


class TestFormatters(unittest.TestCase):
    def test_token_magnitudes(self):
        self.assertEqual(ranking.format_tokens(0), "0")
        self.assertEqual(ranking.format_tokens(999), "999")
        self.assertEqual(ranking.format_tokens(1_000), "1.0K")
        self.assertEqual(ranking.format_tokens(1_500_000), "1.5M")
        self.assertEqual(ranking.format_tokens(479_000_000), "479.0M")
        self.assertEqual(ranking.format_tokens(5_770_000_000), "5.77B")

    def test_missing_tokens_render_as_dash_not_zero(self):
        """不报 token 的源必须显示横线：显示 0 会被读成「一个 token 都没用」。"""
        self.assertEqual(ranking.format_tokens(None), "—")
        self.assertEqual(ranking.format_cost(None), "—")

    def test_cost_is_cents_to_dollars_with_grouping(self):
        self.assertEqual(ranking.format_cost(0), "$0.00")
        self.assertEqual(ranking.format_cost(4056), "$40.56")
        self.assertEqual(ranking.format_cost(405_519), "$4,055.19")

    def test_rounds_half_away_from_zero(self):
        """定点格式化在半分位上远离零取整，与 TS 侧逐位一致。

        0.125 和 0.25 在二进制里是精确值，所以是真正的平局。Python 内建的
        ``f"{0.125:.2f}"`` 走银行家舍入给出 0.12，这里必须是 0.13——JS 没有等价的
        银行家舍入内建，两边若各用内建，边界值就会显示成不同的数。
        """
        self.assertEqual(f"{0.125:.2f}", "0.12")        # 内建的行为，作为对照
        self.assertEqual(ranking._fixed(0.125, 2), "0.13")
        self.assertEqual(ranking._fixed(0.25, 1), "0.3")
        self.assertEqual(ranking._fixed(-0.25, 1), "-0.3")

    def test_day_and_range(self):
        self.assertEqual(ranking.format_day("2026-08-03"), "8月3日")
        self.assertEqual(ranking.format_range("2026-08-10", "2026-08-16"),
                         "8月10日 – 8月16日")


class TestBuildWeekView(unittest.TestCase):
    def _daily(self):
        return aggregate.fold_events([
            # 周内
            row("2026-08-10", "big", requests=10, cost_cents=1000.0,
                **tokens(i=100, o=50, cw=200, cr=9000)),
            row("2026-08-12", "big", requests=5, cost_cents=500.0,
                **tokens(i=50, o=25, cw=100, cr=4000)),
            row("2026-08-12", "small", requests=2, cost_cents=100.0,
                **tokens(i=10, o=5, cw=20, cr=900)),
            # 周外，不该出现
            row("2026-08-17", "next-week", requests=99, cost_cents=9999.0,
                **tokens(i=1)),
        ])

    def test_filters_to_the_week(self):
        view = ranking.build_week_view(self._daily(), WEEK)
        self.assertEqual({m["label"] for m in view["models"]}, {"big", "small"})
        self.assertEqual(view["basis"], "tokens")
        self.assertEqual([m["label"] for m in view["models"]], ["big", "small"])
        self.assertAlmostEqual(view["models"][0]["pct"],
                               (100 + 50 + 200 + 9000 + 50 + 25 + 100 + 4000)
                               / view["tokens_total"] * 100)

    def test_totals_are_summed_over_the_week(self):
        view = ranking.build_week_view(self._daily(), WEEK)
        self.assertEqual(view["requests"], 17)
        self.assertAlmostEqual(view["cost_cents"], 1600.0)
        self.assertEqual(view["tokens_total"], 100 + 50 + 200 + 9000
                         + 50 + 25 + 100 + 4000 + 10 + 5 + 20 + 900)

    def test_ranks_by_tokens_even_when_cost_is_available(self):
        """订阅源没有成本，排行必须按 token，不能再被 Cursor 的美元金额带走。"""
        daily = aggregate.fold_events([
            row("2026-08-10", "cheap-heavy", requests=1, cost_cents=1.0,
                **tokens(i=10_000)),
            row("2026-08-10", "pricey-light", requests=1, cost_cents=9_999.0,
                **tokens(i=10)),
        ])
        view = ranking.build_week_view(daily, WEEK)
        self.assertEqual(view["basis"], "tokens")
        self.assertEqual([m["label"] for m in view["models"]],
                         ["cheap-heavy", "pricey-light"])

    def test_subscription_source_renders_as_label_not_dash(self):
        daily = aggregate.fold_events([
            row("2026-08-10", "gpt-5.6-sol", source="chatgpt", requests=3,
                **tokens(i=100, o=20, cr=800)),
        ])
        view = ranking.build_week_view(daily, WEEK,
                                       subscription_sources=["chatgpt"])
        self.assertEqual(view["cost_display"], "订阅")
        self.assertEqual(view["models"][0]["cost_display"], "订阅")

    def test_paid_and_subscription_share_the_cost_cell(self):
        daily = aggregate.fold_events([
            row("2026-08-10", "opus", source="cursor", requests=1,
                cost_cents=100.0, **tokens(i=10)),
            row("2026-08-10", "gpt-5.6-sol", source="chatgpt", requests=1,
                **tokens(i=20)),
        ])
        view = ranking.build_week_view(daily, WEEK,
                                       subscription_sources=["chatgpt"])
        self.assertEqual(view["cost_display"], "$1.00 · 订阅")
        by_label = {m["label"]: m["cost_display"] for m in view["models"]}
        self.assertEqual(by_label["opus"], "$1.00")
        self.assertEqual(by_label["gpt-5.6-sol"], "订阅")

    def test_same_model_from_two_sources_is_aggregated(self):
        """展示层按模型聚合；chatgpt 与中转站的同名模型合成一行。"""
        daily = aggregate.fold_events([
            row("2026-08-10", "gpt-5.5", source="chatgpt", requests=2,
                **tokens(i=100)),
            row("2026-08-10", "gpt-5.5", source="krill", requests=3,
                **tokens(i=50)),
        ])
        view = ranking.build_week_view(daily, WEEK,
                                       subscription_sources=["chatgpt"])
        self.assertEqual(len(view["models"]), 1)
        self.assertEqual(view["models"][0]["requests"], 5)
        self.assertEqual(view["models"][0]["tokens_total"], 150)
        self.assertEqual(view["models"][0]["cost_display"], "订阅")

    def test_falls_back_to_requests_when_no_tokens_or_cost(self):
        daily = aggregate.fold_events([
            row("2026-08-10", "a", requests=3),
            row("2026-08-10", "b", requests=9),
        ])
        view = ranking.build_week_view(daily, WEEK)
        self.assertEqual(view["basis"], "requests")
        self.assertEqual([m["label"] for m in view["models"]], ["b", "a"])
        self.assertEqual(view["tokens_display"], "—")

    def test_breakdown_is_in_fixed_order_not_by_size(self):
        """配色按分类固定，不能因为某周缓存占比变了就换颜色。"""
        view = ranking.build_week_view(self._daily(), WEEK)
        self.assertEqual([s["kind"] for s in view["breakdown"]],
                         list(ranking.TOKEN_KINDS))
        self.assertAlmostEqual(sum(s["pct"] for s in view["breakdown"]), 100.0)

    def test_days_always_has_seven_entries(self):
        """没有用量的那天也要在，否则日条形图的横轴会随数据伸缩。"""
        view = ranking.build_week_view(self._daily(), WEEK)
        self.assertEqual(len(view["days"]), 7)
        self.assertEqual([d["date"] for d in view["days"]][0], "2026-08-10")
        self.assertEqual([d["date"] for d in view["days"]][-1], "2026-08-16")
        self.assertEqual(view["days"][1]["requests"], 0)      # 周二无用量
        self.assertEqual(view["days"][2]["requests"], 7)      # 周三 5 + 2

    def test_limit_truncates_models(self):
        view = ranking.build_week_view(self._daily(), WEEK, limit=1)
        self.assertEqual([m["label"] for m in view["models"]], ["big"])

    def test_ties_break_on_label_so_both_languages_agree(self):
        daily = aggregate.fold_events([
            row("2026-08-10", "tie-b", requests=7),
            row("2026-08-10", "tie-a", requests=7),
        ])
        view = ranking.build_week_view(daily, WEEK)
        self.assertEqual([m["label"] for m in view["models"]], ["tie-a", "tie-b"])

    def test_empty_week(self):
        view = ranking.build_week_view(self._daily(), None)
        self.assertIsNone(view["week"])
        self.assertEqual(view["models"], [])
        self.assertEqual(view["tokens_display"], "—")

    def test_week_with_no_usage(self):
        view = ranking.build_week_view(
            [], {"week": "x", "start": "2026-08-10", "end": "2026-08-16"})
        self.assertEqual(view["requests"], 0)
        self.assertEqual(len(view["days"]), 7)
        self.assertEqual(view["breakdown"], [])


class TestCursorCollector(unittest.TestCase):
    def _raw(self):
        ms = int(datetime(2026, 8, 17, 10, 0, tzinfo=TZ).timestamp() * 1000)
        return [
            {"timestamp": ms, "model": "opus", "kind": "USAGE_EVENT_KIND_USAGE_BASED",
             "tokenUsage": {"inputTokens": 10, "outputTokens": 20,
                            "cacheWriteTokens": 30, "cacheReadTokens": 40,
                            "totalCents": 1.5}},
            {"timestamp": ms, "model": "opus",
             "kind": "USAGE_EVENT_KIND_INCLUDED_IN_BUSINESS",
             "tokenUsage": {"inputTokens": 1, "outputTokens": 2,
                            "cacheWriteTokens": 3, "cacheReadTokens": 4,
                            "totalCents": 0.25}},
            {"timestamp": ms, "model": "opus",
             "kind": "USAGE_EVENT_KIND_ERRORED_NOT_CHARGED", "tokenUsage": {}},
            {"timestamp": ms, "model": "opus",
             "kind": "USAGE_EVENT_KIND_ABORTED_NOT_CHARGED", "tokenUsage": {}},
        ]

    def _day_of(self, ms):
        return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d")

    def test_aggregates_by_day_and_model(self):
        events = cursor_collector.to_events(self._raw(), self._day_of)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e.date, "2026-08-17")
        self.assertEqual(e.tokens_in, 11)
        self.assertEqual(e.cache_read, 44)
        self.assertAlmostEqual(e.cost_cents, 1.75)

    def test_skips_events_that_produced_no_tokens(self):
        """出错与中止的调用没有产生 token，计入会虚增请求数。"""
        events = cursor_collector.to_events(self._raw(), self._day_of)
        self.assertEqual(events[0].requests, 2)

    def test_included_in_business_still_counts(self):
        """套餐内的调用同样消耗了算力，本项目量的是消耗而不是账单。"""
        only = [r for r in self._raw()
                if r["kind"] == "USAGE_EVENT_KIND_INCLUDED_IN_BUSINESS"]
        events = cursor_collector.to_events(only, self._day_of)
        self.assertEqual(events[0].requests, 1)
        self.assertAlmostEqual(events[0].cost_cents, 0.25)

    def test_empty_input(self):
        self.assertEqual(cursor_collector.to_events([], self._day_of), [])


class TestChatgptCollector(unittest.TestCase):
    def _day_of(self, ts):
        return chatgpt_collector._day_of_timestamp(ts, TZ)

    def _records(self, *, provider="openai", model="gpt-5.6-sol", usage=None):
        usage = usage or {
            "input_tokens": 80453,
            "cached_input_tokens": 79616,
            "cache_write_input_tokens": 0,
            "output_tokens": 179,
            "reasoning_output_tokens": 41,
            "total_tokens": 80632,
        }
        return [
            {"type": "session_meta",
             "payload": {"model_provider": provider}},
            {"type": "turn_context", "payload": {"model": model}},
            {"timestamp": "2026-08-17T08:39:50.890Z", "type": "event_msg",
             "payload": {"type": "token_count",
                         "info": {"last_token_usage": usage,
                                  "total_token_usage": {
                                      "input_tokens": 999999,
                                      "output_tokens": 999999}}}},
        ]

    def test_openai_provider_becomes_chatgpt_source(self):
        raw = chatgpt_collector.parse_rollout(self._records())
        events = chatgpt_collector.to_events(raw, self._day_of)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "chatgpt")
        self.assertEqual(events[0].model, "gpt-5.6-sol")
        self.assertEqual(events[0].date, "2026-08-17")

    def test_input_does_not_double_count_cache(self):
        raw = chatgpt_collector.parse_rollout(self._records())
        e = chatgpt_collector.to_events(raw, self._day_of)[0]
        self.assertEqual(e.tokens_in, 80453 - 79616)
        self.assertEqual(e.cache_read, 79616)
        self.assertEqual(e.tokens_out, 179)
        self.assertEqual(e.cache_write, 0)
        self.assertIsNone(e.cost_cents)
        # reasoning 是 output 的子集，总量不应再加一次
        self.assertEqual(e.tokens_total, (80453 - 79616) + 179 + 0 + 79616)

    def test_relay_provider_is_its_own_source(self):
        raw = chatgpt_collector.parse_rollout(
            self._records(provider="krill", model="gpt-5.5"))
        events = chatgpt_collector.to_events(raw, self._day_of)
        self.assertEqual(events[0].source, "krill")
        self.assertEqual(events[0].model, "gpt-5.5")

    def test_skips_zero_token_counts(self):
        raw = chatgpt_collector.parse_rollout(self._records(usage={
            "input_tokens": 0, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "output_tokens": 0,
        }))
        self.assertEqual(chatgpt_collector.to_events(raw, self._day_of), [])

    def test_does_not_sum_cumulative_total(self):
        """同一会话两条 last，总量应是两次 last 之和，不是 total_token_usage。"""
        records = self._records(usage={
            "input_tokens": 10, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "output_tokens": 2,
        })
        records.append({
            "timestamp": "2026-08-17T09:00:00.000Z", "type": "event_msg",
            "payload": {"type": "token_count", "info": {
                "last_token_usage": {
                    "input_tokens": 30, "cached_input_tokens": 20,
                    "cache_write_input_tokens": 0, "output_tokens": 4,
                },
                "total_token_usage": {
                    "input_tokens": 40, "output_tokens": 6,
                },
            }},
        })
        events = chatgpt_collector.to_events(
            chatgpt_collector.parse_rollout(records), self._day_of)
        self.assertEqual(events[0].requests, 2)
        self.assertEqual(events[0].tokens_in, 10 + (30 - 20))
        self.assertEqual(events[0].tokens_out, 6)
        self.assertEqual(events[0].cache_read, 20)

    def test_source_for_provider(self):
        self.assertEqual(chatgpt_collector.source_for_provider("openai"),
                         "chatgpt")
        self.assertEqual(chatgpt_collector.source_for_provider("xiaomi-mimo"),
                         "xiaomi-mimo")
        self.assertEqual(chatgpt_collector.source_for_provider(None), "chatgpt")


class TestRawLayer(unittest.TestCase):
    def _event(self, date="2026-08-17", requests=3):
        return Event(date=date, source="cursor", model="x", requests=requests)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "cursor", [self._event()], ["2026-08-17"])
            back = read_all_events(root)
            self.assertEqual(len(back), 1)
            self.assertEqual(back[0]["requests"], 3)
            self.assertEqual(back[0]["source"], "cursor")

    def test_rerun_is_idempotent(self):
        """同一天重复采集不应累积出重复记录。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for _ in range(3):
                write_events(root, "cursor", [self._event()], ["2026-08-17"])
            self.assertEqual(len(read_all_events(root)), 1)

    def test_untouched_days_survive(self):
        """只负责今天的一次采集，不能抹掉昨天已经记下的数据。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "cursor", [self._event("2026-08-16")],
                         ["2026-08-16"])
            write_events(root, "cursor", [self._event("2026-08-17")],
                         ["2026-08-17"])
            self.assertEqual(sorted(r["date"] for r in read_all_events(root)),
                             ["2026-08-16", "2026-08-17"])

    def test_day_in_window_with_no_usage_is_cleared(self):
        """负责的那天若这次没有用量，旧记录要被清掉，不能留成幽灵。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "cursor", [self._event()], ["2026-08-17"])
            write_events(root, "cursor", [], ["2026-08-17"])
            self.assertEqual(read_all_events(root), [])

    def test_sources_do_not_share_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source in ("cursor", "deepseek"):
                write_events(root, source, [
                    Event(date="2026-08-17", source=source, model="x",
                          requests=1)], ["2026-08-17"])
            self.assertEqual(
                sorted(p.relative_to(root).as_posix()
                       for p in root.glob("data/raw/*/*.json")),
                ["data/raw/cursor/2026-08.json", "data/raw/deepseek/2026-08.json"])
            self.assertEqual(len(read_all_events(root)), 2)

    def test_machine_shard_does_not_collide_with_account_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "chatgpt", [Event(
                date="2026-08-17", source="chatgpt", model="x", requests=1)],
                ["2026-08-17"], shard="work-mac")
            write_events(root, "chatgpt", [Event(
                date="2026-08-17", source="chatgpt", model="x", requests=2)],
                ["2026-08-17"], shard="home-win")
            paths = sorted(p.relative_to(root).as_posix()
                           for p in root.rglob("*.json"))
            self.assertEqual(paths, [
                "data/raw/chatgpt/home-win/2026-08.json",
                "data/raw/chatgpt/work-mac/2026-08.json",
            ])
            self.assertEqual(sum(r["requests"] for r in read_all_events(root)), 3)

    def test_legacy_machine_first_layout_is_ignored(self):
        """旧的 data/raw/<machine>/<source>/ 不能再折进总量。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data" / "raw" / "work-mac" / "cursor" / "2026-08.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "source": "cursor", "month": "2026-08",
                "days": {"2026-08-17": [{
                    "date": "2026-08-17", "source": "cursor",
                    "model": "x", "requests": 9,
                }]},
            }), encoding="utf-8")
            write_events(root, "cursor", [self._event(requests=3)], ["2026-08-17"])
            back = read_all_events(root)
            self.assertEqual(len(back), 1)
            self.assertEqual(back[0]["requests"], 3)

    def test_spans_month_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_events(root, "cursor",
                         [self._event("2026-07-31"), self._event("2026-08-01")],
                         ["2026-07-31", "2026-08-01"])
            self.assertEqual(len(read_all_events(root)), 2)
            self.assertEqual(sorted(p.name for p in root.glob("data/raw/*/*.json")),
                             ["2026-07.json", "2026-08.json"])

    def test_corrupt_file_is_rebuilt_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data" / "raw" / "cursor" / "2026-08.json"
            path.parent.mkdir(parents=True)
            path.write_text("{ 这不是 json", encoding="utf-8")
            write_events(root, "cursor", [self._event()], ["2026-08-17"])
            self.assertEqual(len(read_all_events(root)), 1)


class TestCollectContext(unittest.TestCase):
    def test_days_since_is_ascending_and_includes_today(self):
        ctx = CollectContext(tz=TZ, root=Path("."))
        days = ctx.days_between("2026-08-10", "2026-08-12")
        self.assertEqual(days, ["2026-08-10", "2026-08-11", "2026-08-12"])

    def test_days_between_is_empty_when_reversed(self):
        ctx = CollectContext(tz=TZ, root=Path("."))
        self.assertEqual(ctx.days_between("2026-08-12", "2026-08-10"), [])

    def test_day_of_uses_configured_tz_not_utc(self):
        """UTC+8 的凌晨零点半必须归到当天，而不是被 UTC 拉回前一天。"""
        ctx = CollectContext(tz=TZ, root=Path("."))
        ms = int(datetime(2026, 8, 17, 0, 30, tzinfo=TZ).timestamp() * 1000)
        self.assertEqual(ctx.day_of(ms), "2026-08-17")

    def test_since_ms_covers_the_whole_first_day(self):
        ctx = CollectContext(tz=TZ, root=Path("."), since="2026-07-01")
        self.assertEqual(ctx.day_of(ctx.since_ms()), "2026-07-01")


class TestContract(unittest.TestCase):
    def _stats(self):
        return aggregate.build_stats(aggregate.fold_events([
            row("2026-08-17", "m", requests=2, cost_cents=5.5, **tokens(i=1))]))

    def test_valid_stats_pass(self):
        self.assertEqual(validate_stats(self._stats()), [])

    def test_missing_fields_are_reported(self):
        self.assertTrue(validate_stats({"daily": []}))

    def test_wrong_schema_version_is_reported(self):
        stats = self._stats()
        stats["schema_version"] = 2
        self.assertTrue(any("schema_version" in e for e in validate_stats(stats)))

    def test_null_token_field_is_reported(self):
        """显式的 null 意味着上游把「没有」和「零」搞混了，必须报出来。"""
        stats = self._stats()
        stats["daily"][0]["tokens_in"] = None
        self.assertTrue(any("tokens_in" in e for e in validate_stats(stats)))

    def test_negative_amount_is_reported(self):
        stats = self._stats()
        stats["daily"][0]["requests"] = -1
        self.assertTrue(any("requests" in e for e in validate_stats(stats)))

    def test_malformed_week_is_reported(self):
        stats = self._stats()
        stats["weeks"][0]["week"] = "2026-34"
        self.assertTrue(any("week" in e for e in validate_stats(stats)))

    def test_generated_stats_conforms(self):
        path = os.path.join(ROOT, "data", "stats.json")
        if not os.path.exists(path):
            self.skipTest("data/stats.json 尚未生成，先跑 run.py")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(validate_stats(json.load(f)), [])


class TestSvgRenderer(unittest.TestCase):
    def _view(self, **over):
        daily = aggregate.fold_events([
            row("2026-08-10", "opus", requests=10, cost_cents=2650.0,
                **tokens(i=100, o=50, cw=200, cr=9000)),
            row("2026-08-11", "grok <x>", requests=4, cost_cents=430.0,
                **tokens(i=40, o=20, cw=80, cr=3000)),
        ])
        return ranking.build_week_view(daily, WEEK, **over)

    def test_escapes_labels(self):
        svg = render.render_svg(self._view())
        self.assertIn("grok &lt;x&gt;", svg)
        self.assertNotIn("grok <x>", svg)

    def test_shows_tokens_and_cost(self):
        svg = render.render_svg(self._view())
        self.assertIn("12.5K", svg)          # token 总量 12,490
        self.assertIn("$30.80", svg)         # 折算成本
        self.assertIn("14 次请求", svg)

    def test_omits_cost_disclaimer(self):
        """口径说明放在 README，不印在卡片上。"""
        svg = render.render_svg(self._view())
        self.assertNotIn("非账单金额", svg)
        self.assertNotIn("缓存读取占", svg)

    def test_height_grows_with_model_count(self):
        few = render.render_svg(ranking.build_week_view(
            aggregate.fold_events([row("2026-08-10", "only", cost_cents=1.0,
                                       **tokens(i=1))]), WEEK))
        many = render.render_svg(self._view())
        self.assertGreater(_svg_height(many), _svg_height(few))

    def test_theme_changes_colors(self):
        light = render.render_svg(self._view(), "light")
        dark = render.render_svg(self._view(), "dark")
        self.assertIn(render.THEMES["light"]["bg"], light)
        self.assertIn(render.THEMES["dark"]["bg"], dark)
        self.assertNotIn(render.THEMES["dark"]["bg"], light)

    def test_breakdown_bar_right_edge_is_flush(self):
        """末段吃掉舍入误差，否则四段之和会差出一两个像素的白缝。"""
        svg = render.render_svg(self._view())
        import re
        rects = [(float(x), float(w)) for x, w in
                 re.findall(r'<rect x="([\d.]+)" y="164" width="([\d.]+)"', svg)]
        self.assertTrue(rects)
        right = max(x + w for x, w in rects)
        self.assertAlmostEqual(right, render.CARD_W - render.PAD, places=3)

    def test_empty_week_renders_placeholder(self):
        svg = render.render_svg(ranking.build_week_view([], None))
        self.assertIn("暂无数据", svg)

    def test_has_accessible_label(self):
        svg = render.render_svg(self._view())
        self.assertIn("<title>", svg)
        self.assertIn('role="img"', svg)

    def test_render_files_writes_both_themes(self):
        stats = aggregate.build_stats(aggregate.fold_events([
            row("2026-08-10", "m", cost_cents=1.0, **tokens(i=1))]))
        original = render.ASSETS
        with tempfile.TemporaryDirectory() as tmp:
            render.ASSETS = Path(tmp)
            try:
                written = render.render_files(stats)
            finally:
                render.ASSETS = original
            self.assertEqual(sorted(p.name for p in written),
                             ["widget-dark.svg", "widget-light.svg"])


def _svg_height(svg: str) -> float:
    import re
    return float(re.search(r'height="([\d.]+)"', svg).group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
