// 视图构建：与 Python 侧 ranking.build_view 同口径的纯函数。
//
// 刻意放在独立模块而不是组件文件里：它不依赖 React，可以被 Node 直接导入，
// 于是 tests/test_parity.py 能把它的输出和 Python 实现逐字段对比，
// 用一个断言锁住「两个渲染器口径一致」这件事，而不是靠人工保持同步。

import type { GroupBy, Unit, UsageRow, UsageView } from "./types";
import { unitSortKey } from "./types";

/**
 * 从 daily 中过滤某天，按 groupBy 维度合并，再按 unit 切成若干小节。
 *
 * 每节内部各自算 100%：不同源的计量单位不可加（请求数 + 会话数没有意义），
 * 跨单位求和会让占比被量级最大的单位主导。
 */
export function buildView(
  daily: UsageRow[],
  date: string | null,
  limit = 8,
  groupBy: GroupBy = "model",
): UsageView {
  if (date === null) {
    return { date: null, groupBy, totals: [], sections: [] };
  }

  const dayRows = daily.filter((r) => r.date === date);

  const perUnit = new Map<Unit, Map<string, number>>();
  for (const row of dayRows) {
    const bucket = perUnit.get(row.unit) ?? new Map<string, number>();
    const label = row[groupBy] || "unknown";
    bucket.set(label, (bucket.get(label) ?? 0) + row.amount);
    perUnit.set(row.unit, bucket);
  }

  const units = [...perUnit.keys()].sort(
    (a, b) => unitSortKey(a) - unitSortKey(b) || a.localeCompare(b),
  );

  const totals: UsageView["totals"] = [];
  const sections: UsageView["sections"] = [];

  for (const unit of units) {
    const bucket = perUnit.get(unit)!;
    const total = [...bucket.values()].reduce((sum, n) => sum + n, 0);
    totals.push({ unit, amount: total });
    sections.push({
      unit,
      total,
      rows: [...bucket.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, limit)
        .map(([label, amount]) => ({
          label,
          amount,
          pct: total ? (amount / total) * 100 : 0,
        })),
    });
  }

  return { date, groupBy, totals, sections };
}
