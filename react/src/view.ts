// 与 Python 侧 ranking.build_week_view 一对一镜像的纯函数。
//
// 两份实现的存在理由：README 里的卡片必须是静态 SVG（GitHub 不执行 JS），博客里的
// 组件要能交互，所以渲染器必然有两个。但「取哪一周、按什么排序、怎么算占比、数字
// 怎么写」只允许有一份口径，否则同一份 stats.json 会在两处显示出不同的数。
//
// tests/test_parity.py 用 esbuild 把本文件打成单文件交给 node 跑，再与 Python 的
// 输出逐字段比对，包括每个 *_display 字符串。改这里必须同步改 ranking.py，反之亦然。
//
// 累加刻意不做中途取整：两端按同一顺序累加同一批双精度浮点，结果逐位相同。

import {
  BASIS_LABELS,
  TOKEN_KINDS,
  TOKEN_LABELS,
  WEEKDAY_LABELS,
  type Basis,
  type BreakdownSegment,
  type DayCell,
  type ModelRow,
  type TokenKind,
  type UsageRow,
  type WeekRef,
  type WeekView,
} from "./types";

export { BASIS_LABELS };

// ------------------------------------------------------------------ 数字格式化

/**
 * 定点格式化，四舍五入远离零。
 *
 * 不用 toFixed：它在恰好落在半位上时的取舍与 Python 的 f-string 不一致
 * （一个四舍五入、一个银行家舍入），会让两端在边界值上给出不同文本。
 */
function fixed(value: number, digits: number): string {
  const factor = 10 ** digits;
  const scaled = Math.floor(Math.abs(value) * factor + 0.5);
  const sign = value < 0 && scaled !== 0 ? "-" : "";
  let text = String(scaled);
  if (digits === 0) return sign + text;
  text = text.padStart(digits + 1, "0");
  return `${sign}${text.slice(0, -digits)}.${text.slice(-digits)}`;
}

/** 千分位分隔。 */
function group(intpart: string): string {
  const out: string[] = [];
  const chars = [...intpart].reverse();
  chars.forEach((ch, offset) => {
    if (offset && offset % 3 === 0) out.push(",");
    out.push(ch);
  });
  return out.reverse().join("");
}

/** token 量的紧凑写法：4,047 → 4.0K，479,000,000 → 479.0M。 */
export function formatTokens(value: number | null): string {
  if (value === null || value === undefined) return "—";
  const n = Math.abs(value);
  if (n >= 1_000_000_000) return `${fixed(value / 1_000_000_000, 2)}B`;
  if (n >= 1_000_000) return `${fixed(value / 1_000_000, 1)}M`;
  if (n >= 1_000) return `${fixed(value / 1_000, 1)}K`;
  return String(Math.trunc(value));
}

/** 分 → 美元，带千分位与两位小数。 */
export function formatCost(cents: number | null): string {
  if (cents === null || cents === undefined) return "—";
  let text = fixed(cents / 100, 2);
  const neg = text.startsWith("-");
  if (neg) text = text.slice(1);
  const [intpart, frac] = text.split(".");
  return `${neg ? "-" : ""}$${group(intpart)}.${frac}`;
}

export function formatCount(value: number | null): string {
  if (value === null || value === undefined) return "—";
  const n = Math.trunc(value);
  return n >= 0 ? group(String(n)) : `-${group(String(-n))}`;
}

/** 2026-08-17 → 8月17日。 */
export function formatDay(day: string): string {
  const [, month, dom] = day.split("-");
  return `${Number(month)}月${Number(dom)}日`;
}

export function formatRange(start: string, end: string): string {
  return `${formatDay(start)} – ${formatDay(end)}`;
}

// ---------------------------------------------------------------------- 视图

interface Totals {
  requests: number;
  tokens_in: number | null;
  tokens_out: number | null;
  cache_write: number | null;
  cache_read: number | null;
  cost_cents: number | null;
  tokens_total: number | null;
}

function sumField(rows: UsageRow[], field: TokenKind | "cost_cents"): number | null {
  const values = rows
    .map((r) => r[field])
    .filter((v): v is number => v !== null && v !== undefined);
  if (values.length === 0) return null;
  return values.reduce((acc, v) => acc + v, 0);
}

function totalsOf(rows: UsageRow[]): Totals {
  const out = {
    requests: rows.reduce((acc, r) => acc + (r.requests || 0), 0),
    tokens_in: sumField(rows, "tokens_in"),
    tokens_out: sumField(rows, "tokens_out"),
    cache_write: sumField(rows, "cache_write"),
    cache_read: sumField(rows, "cache_read"),
    cost_cents: sumField(rows, "cost_cents"),
  };
  const present = TOKEN_KINDS.map((k) => out[k]).filter(
    (v): v is number => v !== null,
  );
  return {
    ...out,
    tokens_total: present.length ? present.reduce((a, v) => a + v, 0) : null,
  };
}

function basisOf(totals: Totals): Basis {
  if (totals.cost_cents) return "cost";
  if (totals.tokens_total) return "tokens";
  return "requests";
}

function basisValue(
  row: { cost_cents: number | null; tokens_total: number | null; requests: number },
  basis: Basis,
): number {
  if (basis === "cost") return row.cost_cents || 0;
  if (basis === "tokens") return row.tokens_total || 0;
  return row.requests || 0;
}

function addDays(day: string, offset: number): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + offset));
  return date.toISOString().slice(0, 10);
}

const emptyView: WeekView = {
  week: null,
  start: null,
  end: null,
  range_display: "",
  basis: "requests",
  requests: 0,
  tokens_total: null,
  cost_cents: null,
  tokens_display: "—",
  cost_display: "—",
  requests_display: "0",
  breakdown: [],
  models: [],
  days: [],
};

/**
 * 构建某一周的展示视图。`week` 直接取自 stats.json 的 weeks。
 *
 * `models` 按 `basis` 降序，`pct` 是该行在本周内的占比（0~100）。
 * `days` 恒为 7 项（周一到周日），没有用量的那天补零，让日条形图的横轴稳定。
 */
export function buildWeekView(
  daily: UsageRow[],
  week: WeekRef | null | undefined,
  limit = 6,
): WeekView {
  if (!week) return { ...emptyView };

  const { start, end } = week;
  const rows = daily.filter((r) => {
    const date = r.date ?? "";
    return date >= start && date <= end;
  });

  const totals = totalsOf(rows);
  const basis = basisOf(totals);

  const byModel = new Map<string, UsageRow[]>();
  for (const row of rows) {
    const key = row.model || "unknown";
    const bucket = byModel.get(key);
    if (bucket) bucket.push(row);
    else byModel.set(key, [row]);
  }

  const models: ModelRow[] = [];
  for (const [label, groupRows] of byModel) {
    const agg = totalsOf(groupRows);
    models.push({
      label,
      requests: agg.requests,
      tokens_total: agg.tokens_total,
      cost_cents: agg.cost_cents,
      tokens_display: formatTokens(agg.tokens_total),
      cost_display: formatCost(agg.cost_cents),
      requests_display: formatCount(agg.requests),
      pct: 0,
    });
  }

  const basisTotal = models.reduce((acc, r) => acc + basisValue(r, basis), 0);
  for (const row of models) {
    row.pct = basisTotal ? (basisValue(row, basis) / basisTotal) * 100 : 0;
  }
  models.sort((a, b) => {
    const diff = basisValue(b, basis) - basisValue(a, basis);
    if (diff !== 0) return diff;
    return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
  });

  // token 四分类的构成，按固定顺序而非大小排，让配色在各周之间稳定。
  const breakdown: BreakdownSegment[] = [];
  if (totals.tokens_total) {
    for (const kind of TOKEN_KINDS) {
      const amount = totals[kind];
      if (amount === null) continue;
      breakdown.push({
        kind,
        label: TOKEN_LABELS[kind],
        amount,
        display: formatTokens(amount),
        pct: (amount / totals.tokens_total) * 100,
      });
    }
  }

  const byDay = new Map<string, UsageRow[]>();
  for (const row of rows) {
    const bucket = byDay.get(row.date);
    if (bucket) bucket.push(row);
    else byDay.set(row.date, [row]);
  }
  const days: DayCell[] = [];
  for (let offset = 0; offset < 7; offset += 1) {
    const date = addDays(start, offset);
    const agg = totalsOf(byDay.get(date) ?? []);
    days.push({
      date,
      weekday: WEEKDAY_LABELS[offset],
      requests: agg.requests,
      tokens_total: agg.tokens_total,
      cost_cents: agg.cost_cents,
    });
  }

  return {
    week: week.week,
    start,
    end,
    range_display: formatRange(start, end),
    basis,
    requests: totals.requests,
    tokens_total: totals.tokens_total,
    cost_cents: totals.cost_cents,
    tokens_display: formatTokens(totals.tokens_total),
    cost_display: formatCost(totals.cost_cents),
    requests_display: formatCount(totals.requests),
    breakdown,
    models: models.slice(0, limit),
    days,
  };
}
