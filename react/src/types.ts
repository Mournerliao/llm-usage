// TS 侧对数据契约的唯一镜像。单一事实源是仓库根的 stats.schema.json，
// 字段名必须与 schema 完全一致；一旦漂移，isValidStats 会在运行时告警。
// SVG 渲染器（render.py → ranking.build_week_view）与本组件消费同一份契约。

export const SCHEMA_VERSION = 3;

/** token 的四个分类。缓存读写与输入输出的单价差一个量级，永远分开存。 */
export const TOKEN_KINDS = [
  "tokens_in",
  "tokens_out",
  "cache_write",
  "cache_read",
] as const;

export type TokenKind = (typeof TOKEN_KINDS)[number];

export interface UsageRow {
  date: string;
  source: string;
  model: string;
  requests: number;
  /** 以下字段缺失表示「这个源不报该口径」，与「报了但是零」不是一回事。 */
  tokens_in?: number;
  tokens_out?: number;
  cache_write?: number;
  cache_read?: number;
  /** token 按各模型单价折算出的成本，单位为分。不是账单金额。 */
  cost_cents?: number;
}

/** 可切换的一周。取自 stats.json 的 weeks，新的在前。 */
export interface WeekRef {
  week: string;
  start: string;
  end: string;
}

/** 年度汇总。现在不展示，先存着。 */
export interface YearSummary {
  year: string;
  start: string | null;
  end: string | null;
  days_active: number;
  requests?: number;
  tokens_total?: number | null;
  cost_cents?: number | null;
  months: { month: string; requests: number; tokens_total: number | null }[];
  models: { model: string; requests: number; tokens_total: number | null }[];
}

export interface UsageStats {
  schema_version: number;
  timezone: string;
  latest_date: string | null;
  weeks: WeekRef[];
  sources: string[];
  daily: UsageRow[];
  year: YearSummary | null;
}

/** 主题模式：跟随系统，或强制浅色 / 深色。 */
export type WidgetTheme = "auto" | "light" | "dark";

/** 排序与占比的口径。有成本按成本，否则退到 token，再退到请求数。 */
export type Basis = "cost" | "tokens" | "requests";

export interface ModelRow {
  label: string;
  requests: number;
  tokens_total: number | null;
  cost_cents: number | null;
  tokens_display: string;
  cost_display: string;
  requests_display: string;
  /** 在本周内的占比（0~100）。 */
  pct: number;
}

export interface BreakdownSegment {
  kind: TokenKind;
  label: string;
  amount: number;
  display: string;
  pct: number;
}

export interface DayCell {
  date: string;
  weekday: string;
  requests: number;
  tokens_total: number | null;
  cost_cents: number | null;
}

export interface WeekView {
  week: string | null;
  start: string | null;
  end: string | null;
  range_display: string;
  basis: Basis;
  requests: number;
  tokens_total: number | null;
  cost_cents: number | null;
  tokens_display: string;
  cost_display: string;
  requests_display: string;
  breakdown: BreakdownSegment[];
  models: ModelRow[];
  days: DayCell[];
}

export interface UsageWidgetProps {
  /** 运行时拉取的数据地址（如 jsDelivr / GitHub raw）。与 data 二选一。 */
  dataUrl?: string;
  /** 构建时直接注入的数据（无需网络请求）。 */
  data?: UsageStats;
  /** 指定初始展示哪一周（ISO 周编号，如 2026-W34），默认最新一周。 */
  week?: string;
  /** 模型行展示前 N 个，默认 6。 */
  limit?: number;
  /** 卡片标题，默认 “LLM 用量”。 */
  title?: string;
  /** 卡片最大宽度（px），默认 760；窄容器中自动收缩。 */
  width?: number;
  /** 主题模式，默认跟随系统。 */
  theme?: WidgetTheme;
}

/** 运行时契约校验：stats.json 一旦不匹配契约，组件不再静默渲染错乱数据。 */
export function isValidStats(v: unknown): v is UsageStats {
  if (!v || typeof v !== "object") return false;
  const s = v as Record<string, unknown>;
  if (s.schema_version !== SCHEMA_VERSION) return false;
  if (!Array.isArray(s.daily) || !Array.isArray(s.weeks)) return false;
  const weeksOk = s.weeks.every((w) => {
    const week = w as Record<string, unknown>;
    return (
      typeof week?.week === "string" &&
      typeof week?.start === "string" &&
      typeof week?.end === "string"
    );
  });
  if (!weeksOk) return false;
  return s.daily.every((r) => {
    if (!r || typeof r !== "object") return false;
    const row = r as Record<string, unknown>;
    return (
      typeof row.date === "string" &&
      typeof row.source === "string" &&
      typeof row.model === "string" &&
      typeof row.requests === "number"
    );
  });
}

/** token 分类的中文名。与 Python 侧 ranking.TOKEN_LABELS 一致。 */
export const TOKEN_LABELS: Record<TokenKind, string> = {
  tokens_in: "输入",
  tokens_out: "输出",
  cache_write: "缓存写入",
  cache_read: "缓存读取",
};

/** 排序口径的表头文案。与 Python 侧 ranking.BASIS_LABELS 一致。 */
export const BASIS_LABELS: Record<Basis, string> = {
  cost: "成本",
  tokens: "Tokens",
  requests: "请求",
};

export const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"] as const;
