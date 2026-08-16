"use client";
import {
  memo,
  useEffect,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import type {
  GroupBy,
  RankedRow,
  UsageRow,
  UsageStats,
  UsageWidgetProps,
} from "./types";
import { isValidStats } from "./types";

const fmt = (n: number) => n.toLocaleString("en-US");

/**
 * 纯函数：从 daily 中过滤某天、按 groupBy 维度合并、按 token 降序取前 N。
 * 与 Python 侧 ranking.rank_models 共用同一份数据契约（stats.json），
 * 把「筛选 + 分组 + 排序 + 截断 + 算占比」集中在此，组件只做薄渲染。
 * 派生状态在 render 阶段计算（非 effect），符合派生状态不进 effect 的原则。
 */
export function rankModels(
  daily: UsageRow[],
  date: string,
  limit = 8,
  groupBy: GroupBy = "model",
): { rows: RankedRow[]; totalTokens: number; totalRequests: number } {
  const dayRows = daily.filter((r) => r.date === date);
  const totalTokens = dayRows.reduce((s, r) => s + r.total_tokens, 0);
  const totalRequests = dayRows.reduce((s, r) => s + r.requests, 0);

  const agg = new Map<string, number>();
  for (const r of dayRows) {
    const k = groupBy === "source" ? r.source : r.model;
    agg.set(k, (agg.get(k) ?? 0) + r.total_tokens);
  }
  const rows: RankedRow[] = [...agg.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([label, tokens]) => ({
      label,
      total_tokens: tokens,
      pct: totalTokens ? (tokens / totalTokens) * 100 : 0,
    }));
  return { rows, totalTokens, totalRequests };
}

/** 单行条形。memo 化：父组件因无关 state 重渲染时，本行不重算（rerender-memo）。 */
const BarRow = memo(function BarRow({
  label,
  tokens,
  pct,
  max,
  accent,
}: {
  label: string;
  tokens: number;
  pct: number;
  max: number;
  accent: string;
}) {
  const w = max ? (tokens / max) * 100 : 0;
  return (
    <div style={row}>
      <span style={modelName}>{label}</span>
      <div style={barTrack}>
        <div
          style={{ ...barFill, width: `${Math.max(w, 1)}%`, background: accent }}
        />
      </div>
      <span style={pctText}>{pct.toFixed(0)}%</span>
    </div>
  );
});

/** Tab 切换按钮（memo 化，定义在组件外，满足 no-inline-components）。 */
const TabButton = memo(function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: 1,
        padding: "6px 0",
        fontSize: 12,
        cursor: "pointer",
        border: "none",
        borderRadius: 8,
        fontWeight: active ? 600 : 400,
        background: active ? "#EAF1FB" : "transparent",
        color: active ? "#2563EB" : "#6B7280",
      }}
    >
      {children}
    </button>
  );
});

export function UsageWidget({
  dataUrl,
  data,
  date,
  limit = 8,
  accent = "#378ADD",
  title = "LLM 每日用量",
  width = 680,
}: UsageWidgetProps) {
  const [remote, setRemote] = useState<UsageStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 分组维度：默认「按模型」与 SVG 渲染器口径一致；用户可在卡片内切到「按来源」。
  const [groupBy, setGroupBy] = useState<GroupBy>("model");

  useEffect(() => {
    if (data || !dataUrl) return;
    let alive = true;
    fetch(dataUrl)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j: UsageStats) => alive && setRemote(j))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [dataUrl, data]);

  const stats = data ?? remote;

  if (!stats && error)
    return <div style={card(width)}>加载失败：{error}</div>;
  if (!stats) return <div style={card(width)}>加载中…</div>;
  if (!isValidStats(stats))
    return <div style={card(width)}>数据格式异常（不符合 stats.schema.json 契约）</div>;

  const day = date ?? stats.latest_date ?? "";
  const { rows, totalTokens, totalRequests } = rankModels(
    stats.daily,
    day,
    limit,
    groupBy,
  );

  if (rows.length === 0)
    return <div style={card(width)}>{day || "今天"} 暂无数据</div>;

  const max = Math.max(...rows.map((r) => r.total_tokens), 1);

  return (
    <div style={card(width)}>
      <div style={{ fontSize: 15, fontWeight: 600, color: "#111827" }}>
        {title} · {day}
      </div>
      <div style={{ fontSize: 13, color: "#374151", marginTop: 8 }}>
        总 token：<b style={{ color: "#111827" }}>{fmt(totalTokens)}</b>
        {"　"}会话/请求：<b style={{ color: "#111827" }}>{fmt(totalRequests)}</b>
      </div>
      <div style={{ borderTop: "1px solid #F3F4F6", margin: "14px 0 8px" }} />

      {/* 分组维度切换：按模型 / 按来源 */}
      <div style={tabsRow}>
        <TabButton active={groupBy === "model"} onClick={() => setGroupBy("model")}>
          按模型
        </TabButton>
        <TabButton active={groupBy === "source"} onClick={() => setGroupBy("source")}>
          按来源
        </TabButton>
      </div>

      {rows.map((r) => (
        <BarRow
          key={r.label}
          label={r.label}
          tokens={r.total_tokens}
          pct={r.pct}
          max={max}
          accent={accent}
        />
      ))}
    </div>
  );
}

const card = (w: number): CSSProperties => ({
  width: w,
  boxSizing: "border-box",
  background: "#fff",
  border: "1px solid #E5E7EB",
  borderRadius: 14,
  padding: 20,
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  color: "#111827",
});

const tabsRow: CSSProperties = {
  display: "flex",
  gap: 4,
  background: "#F3F4F6",
  padding: 4,
  borderRadius: 10,
  marginBottom: 10,
};

const row: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  margin: "6px 0",
  fontSize: 12,
};
const modelName: CSSProperties = {
  width: 150,
  color: "#444441",
  flexShrink: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const barTrack: CSSProperties = {
  flex: 1,
  background: "#F3F4F6",
  borderRadius: 3,
  height: 14,
  overflow: "hidden",
};
const barFill: CSSProperties = {
  height: 14,
  borderRadius: 3,
  transition: "width .3s ease",
};
const pctText: CSSProperties = {
  width: 36,
  textAlign: "right",
  color: "#5F5E5A",
  fontSize: 11,
  flexShrink: 0,
};
