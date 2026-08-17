"""跨语言口径一致性测试：Python 的 ranking.build_view 与 TS 的 buildView 必须给出
逐字段相同的视图。

为什么需要这个测试
------------------
SVG 卡片由 Python 渲染，博客组件由 React 渲染。两边不能共用一份实现（一个跑在
Python，一个跑在浏览器），但它们必须对「同一天的用量该怎么分节、怎么排序、占比多少」
给出完全一致的答案，否则同一份数据在两处会显示不同的数字。

以前的做法是把两份 SVG 字符串断言相等，那只能锁住渲染模板，锁不住计算口径，而且是
在保护重复而不是消除重复。现在两边各自只有一份实现，用这个测试把它们的**输出**钉在
一起：跑的是真的那份 TS 代码（经 node 执行），不是 Python 里的复刻。

跳过条件
--------
需要 node 与 react/node_modules 里的 esbuild。缺任一项时自动跳过，不阻塞 Python 侧
的测试——这个测试保护的是「两处口径一致」，而不是 Python 本身的正确性。
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
from ranking import build_view  # noqa: E402

RUNNER = Path(__file__).parent / "parity_runner.mjs"
ESBUILD = ROOT / "react" / "node_modules" / ".bin" / "esbuild"

CASES = [
    {"date": "2026-01-01", "limit": 8, "groupBy": "model"},
    {"date": "2026-01-01", "limit": 8, "groupBy": "source"},
    {"date": "2026-01-01", "limit": 8, "groupBy": "machine"},
    {"date": "2026-01-01", "limit": 2, "groupBy": "model"},
    {"date": "2026-01-02", "limit": 8, "groupBy": "model"},
    {"date": "2026-12-31", "limit": 8, "groupBy": "model"},  # 无数据的一天
]


def _events():
    """刻意覆盖几个容易漂移的点：多单位、跨机器、同名模型跨源、并列值排序。"""
    def e(date, machine, source, model, unit, amount):
        return {"date": date, "machine": machine, "source": source,
                "model": model, "unit": unit, "amount": amount}

    return [
        e("2026-01-01", "work-mac", "cursor", "grok-4.6", "requests", 50),
        e("2026-01-01", "work-mac", "cursor", "claude-opus-5", "requests", 30),
        e("2026-01-01", "work-mac", "cursor", "composer-2.5", "requests", 10),
        e("2026-01-01", "home-win", "cursor", "grok-4.6", "requests", 5),
        e("2026-01-01", "home-win", "other-ade", "some-model", "sessions", 4),
        e("2026-01-01", "work-mac", "openai", "gpt-5.6", "tokens", 12345),
        # 并列值：两个模型同为 7，排序必须靠标签字典序决定，两边要一致
        e("2026-01-01", "work-mac", "cursor", "tie-b", "requests", 7),
        e("2026-01-01", "work-mac", "cursor", "tie-a", "requests", 7),
        e("2026-01-02", "work-mac", "cursor", "grok-4.6", "requests", 1),
    ]


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
            raise unittest.SkipTest(f"跳过跨语言一致性测试：{reason}")

        cls._tmp = tempfile.TemporaryDirectory(prefix="llm-usage-parity-")
        cls.bundle = Path(cls._tmp.name) / "parity.mjs"
        proc = subprocess.run(
            [str(ESBUILD), str(RUNNER), "--bundle", "--format=esm",
             "--platform=node", f"--outfile={cls.bundle}"],
            capture_output=True, text=True, timeout=180, cwd=str(ROOT),
        )
        if proc.returncode != 0:
            raise unittest.SkipTest(f"esbuild 打包失败：{proc.stderr}")

    @classmethod
    def tearDownClass(cls):
        tmp = getattr(cls, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def _run_ts(self, daily, cases):
        proc = subprocess.run(
            ["node", str(self.bundle)],
            input=json.dumps({"daily": daily, "cases": cases}),
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            env={**os.environ, "NODE_NO_WARNINGS": "1"},
        )
        if proc.returncode != 0:
            self.fail(f"TS runner 执行失败：\n{proc.stderr}")
        return json.loads(proc.stdout)

    def _ts_views(self, daily):
        return self._run_ts(daily, CASES)

    def test_views_match_field_by_field(self):
        daily = aggregate.fold_events(_events())
        ts_views = self._ts_views(daily)

        for case, ts_view in zip(CASES, ts_views):
            with self.subTest(**case):
                py_view = build_view(daily, case["date"], limit=case["limit"],
                                     group_by=case["groupBy"])

                self.assertEqual(py_view["date"], ts_view["date"])
                self.assertEqual(py_view["group_by"], ts_view["groupBy"])
                self.assertEqual(py_view["totals"], ts_view["totals"])

                self.assertEqual(len(py_view["sections"]), len(ts_view["sections"]))
                for py_sec, ts_sec in zip(py_view["sections"], ts_view["sections"]):
                    self.assertEqual(py_sec["unit"], ts_sec["unit"])
                    self.assertEqual(py_sec["total"], ts_sec["total"])
                    self.assertEqual([r["label"] for r in py_sec["rows"]],
                                     [r["label"] for r in ts_sec["rows"]])
                    self.assertEqual([r["amount"] for r in py_sec["rows"]],
                                     [r["amount"] for r in ts_sec["rows"]])
                    for py_row, ts_row in zip(py_sec["rows"], ts_sec["rows"]):
                        self.assertAlmostEqual(py_row["pct"], ts_row["pct"],
                                               places=9)

    def test_real_stats_match(self):
        """用仓库里真实的 stats.json 再对一遍，防止只有构造数据能对上。"""
        path = ROOT / "data" / "stats.json"
        if not path.exists():
            self.skipTest("data/stats.json 尚未生成")
        stats = json.loads(path.read_text(encoding="utf-8"))
        daily = stats["daily"]
        date = stats["latest_date"]
        if not date:
            self.skipTest("stats.json 为空")

        ts_views = self._run_ts(daily, [
            {"date": date, "limit": 8, "groupBy": "model"},
            {"date": date, "limit": 8, "groupBy": "source"},
        ])

        for group_by, ts_view in zip(("model", "source"), ts_views):
            with self.subTest(group_by=group_by):
                py_view = build_view(daily, date, limit=8, group_by=group_by)
                self.assertEqual(py_view["totals"], ts_view["totals"])
                self.assertEqual(
                    [(s["unit"], s["total"], [r["label"] for r in s["rows"]])
                     for s in py_view["sections"]],
                    [(s["unit"], s["total"], [r["label"] for r in s["rows"]])
                     for s in ts_view["sections"]],
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
