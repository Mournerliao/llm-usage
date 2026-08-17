// TS 侧对数据契约的唯一镜像。单一事实源是仓库根的 stats.schema.json，
// 字段名必须与 schema 完全一致；一旦漂移，isValidStats 会在运行时告警。
// SVG 渲染器（render.py → ranking.build_view）与本组件消费同一份契约。

export const SCHEMA_VERSION = 2;

/** 计量单位。不同源口径不同，展示时必须按 unit 分节，绝不跨单位相加。 */
export type Unit = "requests" | "sessions" | "tokens" | "credits" | "lines";

export interface UsageRow {
  date: string;
  machine: string;
  source: string;
  model: string;
  unit: Unit;
  amount: number;
  /** 仅当源能拆分输入输出时存在（目前只有 OpenAI 兼容接口）。 */
  amount_in?: number;
  amount_out?: number;
}

export interface UsageStats {
  schema_version: number;
  latest_date: string | null;
  total_dates: number;
  units: Unit[];
  machines: string[];
  daily: UsageRow[];
}

/** 分组维度：按模型（默认，与 SVG 一致）、按来源，或按采集机器。 */
export type GroupBy = "model" | "source" | "machine";

/** 主题模式：跟随系统，或强制浅色 / 深色。 */
export type WidgetTheme = "auto" | "light" | "dark";

export interface RankedRow {
  label: string;
  amount: number;
  /** 在所在小节内的占比（0~100），不是全局占比。 */
  pct: number;
}

/** 一个单位对应一节，节内自成 100%。 */
export interface ViewSection {
  unit: Unit;
  total: number;
  rows: RankedRow[];
}

export interface UsageView {
  date: string | null;
  groupBy: GroupBy;
  totals: { unit: Unit; amount: number }[];
  sections: ViewSection[];
}

export interface UsageWidgetProps {
  /** 运行时拉取的数据地址（如 jsDelivr / GitHub raw）。与 data 二选一。 */
  dataUrl?: string;
  /** 构建时直接注入的数据（无需网络请求）。 */
  data?: UsageStats;
  /** 指定展示哪一天，默认取 latest_date。 */
  date?: string;
  /** 每节展示前 N 个，默认 8。 */
  limit?: number;
  /** 初始分组维度，默认 model。 */
  defaultGroupBy?: GroupBy;
  /** 条形主色，默认 #378ADD。 */
  accent?: string;
  /** 卡片标题，默认 “LLM 每日用量”。 */
  title?: string;
  /** 卡片最大宽度（px），默认 560；窄容器中自动收缩。 */
  width?: number;
  /** 主题模式，默认跟随系统。 */
  theme?: WidgetTheme;
}

const UNITS: readonly string[] = [
  "requests",
  "sessions",
  "tokens",
  "credits",
  "lines",
];

/** 运行时契约校验：stats.json 一旦不匹配契约，组件不再静默渲染错乱数据。 */
export function isValidStats(v: unknown): v is UsageStats {
  if (!v || typeof v !== "object") return false;
  const s = v as Record<string, unknown>;
  if (s.schema_version !== SCHEMA_VERSION) return false;
  if (!Array.isArray(s.daily)) return false;
  return s.daily.every((r) => {
    if (!r || typeof r !== "object") return false;
    const row = r as Record<string, unknown>;
    return (
      typeof row.date === "string" &&
      typeof row.machine === "string" &&
      typeof row.source === "string" &&
      typeof row.model === "string" &&
      typeof row.unit === "string" &&
      UNITS.includes(row.unit) &&
      typeof row.amount === "number"
    );
  });
}

/** 单位的中文名。与 Python 侧 ranking.UNIT_LABELS / UNIT_COUNTED 保持一致。 */
export const UNIT_LABELS: Record<Unit, string> = {
  tokens: "Tokens",
  requests: "请求",
  sessions: "会话",
  credits: "积分",
  lines: "代码行",
};

const UNIT_COUNTED: Record<Unit, (n: string) => string> = {
  tokens: (n) => `${n} tokens`,
  requests: (n) => `${n} 次请求`,
  sessions: (n) => `${n} 个会话`,
  credits: (n) => `${n} 积分`,
  lines: (n) => `${n} 行代码`,
};

export const DIMENSION_LABELS: Record<GroupBy, string> = {
  model: "模型",
  source: "ADE",
  machine: "机器",
};

/** 单位展示顺序，与 Python 侧 ranking.UNIT_ORDER 一致。 */
const UNIT_ORDER: readonly Unit[] = [
  "tokens",
  "requests",
  "sessions",
  "credits",
  "lines",
];

export function unitLabel(unit: Unit): string {
  return UNIT_LABELS[unit] ?? unit;
}

export function unitCounted(unit: Unit, amount: number): string {
  const n = amount.toLocaleString("en-US");
  return UNIT_COUNTED[unit]?.(n) ?? `${n} ${unit}`;
}

export function unitSortKey(unit: Unit): number {
  const index = UNIT_ORDER.indexOf(unit);
  return index === -1 ? UNIT_ORDER.length : index;
}
