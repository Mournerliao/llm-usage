"""跨语言口径一致性测试：Python 的 ranking.build_week_view 与 TS 的 buildWeekView
必须给出逐字段相同的视图，包括每一个用于显示的字符串。

为什么需要这个测试
------------------
README 的卡片由 Python 渲染成静态 SVG（GitHub 不执行 JS），博客组件由 React 渲染。
两边不能共用一份实现，但它们必须对「这一周该怎么汇总、怎么排序、占比多少、数字写成
什么样」给出完全一致的答案，否则同一份 stats.json 在两处会显示不同的数。

比对范围刻意包括 ``*_display`` 字符串。量级选择（479.0M 还是 0.48B）与舍入方向都是
容易各写各的地方，把格式化收进共享视图之后，这个测试就把格式本身也钉住了。

跳过条件
--------
需要 node 与 react/node_modules 里的 esbuild。本机缺任一项时自动跳过，不阻塞 Python
侧的测试——这个测试保护的是「两处口径一致」，而不是 Python 本身的正确性。

CI 里设 `PARITY_STRICT=1`，此时任何跳过都变成失败。否则 CI 会在工具链没装好的情况下
绿着通过，而这正是唯一能拦住两边漂移的测试。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aggregate  # noqa: E402
from ranking import build_week_view  # noqa: E402

RUNNER = Path(__file__).parent / "parity_runner.mjs"
ESBUILD = ROOT / "react" / "node_modules" / ".bin" / "esbuild"

FULL = {"week": "2026-W33", "start": "2026-08-10", "end": "2026-08-16"}
NEXT = {"week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23"}
EMPTY = {"week": "2026-W40", "start": "2026-09-28", "end": "2026-10-04"}

CASES = [
    {"week": FULL, "limit": 6},
    {"week": FULL, "limit": 2},      # 截断
    {"week": NEXT, "limit": 6},      # 只有一天有量
    {"week": EMPTY, "limit": 6},     # 整周无量
    {"week": None, "limit": 6},      # 没有可展示的周
]

# 视图里所有标量字段。逐个比对而不是挑几个，漏掉的字段就是将来会漂移的字段。
SCALARS = ("week", "start", "end", "range_display", "basis", "requests",
           "tokens_total", "tokens_display", "cost_display", "requests_display")


def _events():
    """刻意覆盖几个容易漂移的点。"""
    def e(date, source, model, **kw):
        return {"date": date, "source": source, "model": model, **kw}

    return [
        # 大小悬殊的成本，检验排序与占比
        e("2026-08-10", "cursor", "claude-opus-5-thinking-high", requests=120,
          tokens_in=1_800_000, tokens_out=270_000, cache_write=1_300_000,
          cache_read=310_000_000, cost_cents=26_519.37),
        e("2026-08-11", "cursor", "cursor-grok-4.5-high", requests=64,
          tokens_in=900_000, tokens_out=140_000, cache_write=700_000,
          cache_read=60_000_000, cost_cents=4_324.06),
        # 亚分成本：不能中途取整，否则两边会在末位漂开
        e("2026-08-12", "cursor", "composer-2.5", requests=9,
          tokens_in=1234, tokens_out=567, cache_write=890,
          cache_read=32_100, cost_cents=0.4137),
        # 不报 token 与成本的源：两边都该退到请求数口径并显示横线
        e("2026-08-13", "deepseek", "deepseek-v4", requests=15),
        # 只报输入输出、不报缓存的源
        e("2026-08-13", "openai", "gpt-5.6", requests=8,
          tokens_in=40_000, tokens_out=9_000),
        # 订阅源：金额列应显示「订阅」，且同名模型跨源要能聚合
        e("2026-08-12", "chatgpt", "gpt-5.6-sol", requests=4,
          tokens_in=1_000, tokens_out=200, cache_write=0, cache_read=8_000),
        e("2026-08-12", "krill", "gpt-5.6-sol", requests=1,
          tokens_in=500, tokens_out=50, cache_write=0, cache_read=2_000),
        # 并列值：排序必须靠标签字典序决定，两边要一致
        e("2026-08-14", "cursor", "tie-b", requests=7, cost_cents=100.0),
        e("2026-08-14", "cursor", "tie-a", requests=7, cost_cents=100.0),
        # 恰好落在半分位上的成本，检验两边的舍入方向一致
        e("2026-08-15", "cursor", "half-cent", requests=1, cost_cents=0.125),
        # 下一周，用来验证周窗口的边界是闭区间
        e("2026-08-17", "cursor", "claude-opus-5-thinking-high", requests=28,
          tokens_in=2_000_000, tokens_out=340_000, cache_write=1_400_000,
          cache_read=44_100_000, cost_cents=4_056.12),
    ]


def _bail(reason: str):
    """工具链或数据缺失时的退出方式。

    本机开发允许跳过——这个测试保护的是「两处口径一致」，缺 node 时不该拦住 Python
    侧的测试。但 CI 必须失败：跳过会让 CI 绿着通过，而 parity 恰恰是唯一能拦住两边
    漂移的东西，静默跳过等于没有这道防线。CI 里设 PARITY_STRICT=1。
    """
    if os.environ.get("PARITY_STRICT"):
        raise AssertionError(f"PARITY_STRICT 已开启，不允许跳过：{reason}")
    raise unittest.SkipTest(reason)


def _toolchain_reason() -> str | None:
    """返回跳过原因；None 表示工具链就绪。"""
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=15,
                       check=True)
    except (FileNotFoundError, subprocess.TimeoutExpired,
            subprocess.CalledProcessError):
        return "未安装 node"
    if not ESBUILD.exists():
        return "缺少 react/node_modules（先在 react/ 里跑 npm install）"
    return None


class TestCrossLanguageParity(unittest.TestCase):
    """把 TS 实现打包成单文件后交给 node 执行，再与 Python 输出逐字段对比。

    走 esbuild 打包而不是让 node 直接跑 TS：node 的原生 ESM 解析要求 import 带完整
    扩展名，而源码用的是 bundler 风格的无扩展名导入。为了测试去改源码导入风格是本末
    倒置，打包一步即可，顺带也覆盖了「这份 TS 能被打包工具正确处理」。
    """

    @classmethod
    def setUpClass(cls):
        reason = _toolchain_reason()
        if reason:
            _bail(f"跨语言一致性测试无法运行：{reason}")

        cls._tmp = tempfile.TemporaryDirectory(prefix="llm-usage-parity-")
        cls.bundle = Path(cls._tmp.name) / "parity.mjs"
        proc = subprocess.run(
            [str(ESBUILD), str(RUNNER), "--bundle", "--format=esm",
             "--platform=node", f"--outfile={cls.bundle}"],
            capture_output=True, text=True, timeout=180, cwd=str(ROOT),
        )
        if proc.returncode != 0:
            _bail(f"esbuild 打包失败：{proc.stderr}")

    @classmethod
    def tearDownClass(cls):
        tmp = getattr(cls, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def _run_ts(self, daily, cases, subscription_sources=None):
        proc = subprocess.run(
            ["node", str(self.bundle)],
            input=json.dumps({
                "daily": daily,
                "cases": cases,
                "subscription_sources": subscription_sources or [],
            }),
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            env={**os.environ, "NODE_NO_WARNINGS": "1"},
        )
        if proc.returncode != 0:
            self.fail(f"TS runner 执行失败：\n{proc.stderr}")
        return json.loads(proc.stdout)

    def _assert_views_match(self, py, ts):
        for key in SCALARS:
            self.assertEqual(py[key], ts[key], f"字段 {key} 不一致")

        # 成本单独比：两边按同一顺序累加同一批双精度浮点，理应逐位相同，但用
        # assertAlmostEqual 留出余量，真正把口径钉死的是上面的 cost_display。
        if py["cost_cents"] is None or ts["cost_cents"] is None:
            self.assertEqual(py["cost_cents"], ts["cost_cents"])
        else:
            self.assertAlmostEqual(py["cost_cents"], ts["cost_cents"], places=9)

        self.assertEqual([s["kind"] for s in py["breakdown"]],
                         [s["kind"] for s in ts["breakdown"]])
        for a, b in zip(py["breakdown"], ts["breakdown"]):
            self.assertEqual((a["label"], a["amount"], a["display"]),
                             (b["label"], b["amount"], b["display"]))
            self.assertAlmostEqual(a["pct"], b["pct"], places=9)

        self.assertEqual([m["label"] for m in py["models"]],
                         [m["label"] for m in ts["models"]])
        for a, b in zip(py["models"], ts["models"]):
            self.assertEqual(
                (a["label"], a["requests"], a["tokens_total"],
                 a["tokens_display"], a["cost_display"], a["requests_display"]),
                (b["label"], b["requests"], b["tokens_total"],
                 b["tokens_display"], b["cost_display"], b["requests_display"]))
            self.assertAlmostEqual(a["pct"], b["pct"], places=9)

        self.assertEqual([(d["date"], d["weekday"], d["requests"],
                           d["tokens_total"]) for d in py["days"]],
                         [(d["date"], d["weekday"], d["requests"],
                           d["tokens_total"]) for d in ts["days"]])

    def test_views_match_field_by_field(self):
        daily = aggregate.fold_events(_events())
        ts_views = self._run_ts(daily, CASES, ["chatgpt"])

        for case, ts_view in zip(CASES, ts_views):
            with self.subTest(week=(case["week"] or {}).get("week"),
                              limit=case["limit"]):
                py_view = build_week_view(daily, case["week"], case["limit"],
                                          ["chatgpt"])
                self._assert_views_match(py_view, ts_view)

    def test_real_stats_match(self):
        """用仓库里真实的 stats.json 再对一遍，防止只有构造数据能对上。"""
        path = ROOT / "data" / "stats.json"
        if not path.exists():
            _bail("data/stats.json 尚未生成")
        stats = json.loads(path.read_text(encoding="utf-8"))
        weeks = stats.get("weeks") or []
        if not weeks:
            _bail("stats.json 里没有可展示的周")

        cases = [{"week": w, "limit": 6} for w in weeks]
        subs = stats.get("subscription_sources") or []
        ts_views = self._run_ts(stats["daily"], cases, subs)

        for case, ts_view in zip(cases, ts_views):
            with self.subTest(week=case["week"]["week"]):
                py_view = build_week_view(stats["daily"], case["week"], 6, subs)
                self._assert_views_match(py_view, ts_view)


if __name__ == "__main__":
    unittest.main(verbosity=2)
