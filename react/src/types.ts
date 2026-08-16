// TS 侧对数据契约的唯一镜像。单一事实源是仓库根的 stats.schema.json，
// 字段名必须与 schema 完全一致；一旦漂移，isValidStats 会在运行时告警。
// SVG 渲染器（render.py → ranking.rank_models）与 React 组件都消费同一份契约。

export interface UsageRow {
  source: string;
  model: string;
  date: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface UsageStats {
  latest_date: string | null;
  total_dates: number;
  daily: UsageRow[];
}

/** 分组维度：按模型（默认，与 SVG 一致）或按来源（ADE）。 */
export type GroupBy = "model" | "source";

/** 排行后的单行（已按 tokens 降序、截断到 limit）。 */
export interface RankedRow {
  label: string;
  total_tokens: number;
  pct: number;
}

export interface UsageWidgetProps {
  /** 运行时拉取的数据地址（如 jsDelivr / GitHub raw）。与 data 二选一。 */
  dataUrl?: string;
  /** 构建时直接注入的数据（无需网络请求）。 */
  data?: UsageStats;
  /** 指定展示哪一天，默认取 latest_date。 */
  date?: string;
  /** 展示前 N 个，默认 8。 */
  limit?: number;
  /** 条形主色，默认 #378ADD。 */
  accent?: string;
  /** 卡片标题，默认 “ADE 每日用量”。 */
  title?: string;
  /** 卡片宽度（px），默认 680。 */
  width?: number;
}

/** 运行时契约校验：stats.json 一旦不匹配契约，组件不再静默渲染错乱数据。 */
export function isValidStats(v: unknown): v is UsageStats {
  if (!v || typeof v !== "object") return false;
  const s = v as Record<string, unknown>;
  if (!Array.isArray(s.daily)) return false;
  return s.daily.every((r) => {
    if (!r || typeof r !== "object") return false;
    const row = r as Record<string, unknown>;
    return (
      typeof row.source === "string" &&
      typeof row.model === "string" &&
      typeof row.date === "string" &&
      typeof row.total_tokens === "number"
    );
  });
}
