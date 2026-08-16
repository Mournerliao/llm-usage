"use client";

import { memo, useEffect, useState, type CSSProperties } from "react";

import { Card } from "./components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import "./index.css";
import type {
  GroupBy,
  RankedRow,
  UsageRow,
  UsageStats,
  UsageWidgetProps,
  WidgetTheme,
} from "./types";
import { isValidStats } from "./types";

const fmt = (n: number) => n.toLocaleString("en-US");

/**
 * 纯函数：从 daily 中过滤某天、按 groupBy 维度合并、按 token 降序取前 N。
 * 与 Python 侧 ranking.rank_models 共用同一份数据契约（stats.json）。
 */
export function rankModels(
  daily: UsageRow[],
  date: string,
  limit = 8,
  groupBy: GroupBy = "model",
): { rows: RankedRow[]; totalTokens: number; totalRequests: number } {
  const dayRows = daily.filter((r) => r.date === date);
  const totalTokens = dayRows.reduce((sum, row) => sum + row.total_tokens, 0);
  const totalRequests = dayRows.reduce((sum, row) => sum + row.requests, 0);

  const aggregate = new Map<string, number>();
  for (const row of dayRows) {
    const key = groupBy === "source" ? row.source : row.model;
    aggregate.set(key, (aggregate.get(key) ?? 0) + row.total_tokens);
  }

  const rows: RankedRow[] = [...aggregate.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([label, tokens]) => ({
      label,
      total_tokens: tokens,
      pct: totalTokens ? (tokens / totalTokens) * 100 : 0,
    }));

  return { rows, totalTokens, totalRequests };
}

const BarRow = memo(function BarRow({
  label,
  pct,
  accent,
}: {
  label: string;
  pct: number;
  accent: string;
}) {
  const visibleWidth = Math.max(Math.min(pct, 100), 1);

  return (
    <div
      className="grid grid-cols-[5.5rem_minmax(0,1fr)_2.5rem] items-center gap-2 text-xs sm:grid-cols-[7rem_minmax(0,1fr)_2.75rem] sm:gap-3"
      aria-label={`${label}，${pct.toFixed(0)}%`}
    >
      <span className="truncate text-foreground/80" title={label}>
        {label}
      </span>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out motion-reduce:transition-none"
          style={{ width: `${visibleWidth}%`, backgroundColor: accent }}
        />
      </div>
      <span className="text-right text-[11px] tabular-nums text-muted-foreground">
        {pct.toFixed(0)}%
      </span>
    </div>
  );
});

type WidgetStyle = CSSProperties & { "--widget-accent": string };

const widgetStyle = (width: number, accent: string): WidgetStyle => ({
  width: "100%",
  maxWidth: width,
  "--widget-accent": accent,
});

function StatusCard({
  width,
  theme,
  children,
}: {
  width: number;
  theme: WidgetTheme;
  children: string;
}) {
  return (
    <Card
      className="usage-widget p-[18px] text-sm text-muted-foreground"
      data-theme={theme}
      role="status"
      style={widgetStyle(width, "#378ADD")}
    >
      {children}
    </Card>
  );
}

export function UsageWidget({
  dataUrl,
  data,
  date,
  limit = 8,
  defaultGroupBy = "model",
  accent = "#378ADD",
  title = "LLM 每日用量",
  width = 560,
  theme = "auto",
}: UsageWidgetProps) {
  const [remote, setRemote] = useState<UsageStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>(defaultGroupBy);

  useEffect(() => {
    if (data || !dataUrl) return;

    const controller = new AbortController();
    setError(null);

    fetch(dataUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((json: UsageStats) => setRemote(json))
      .catch((cause: Error) => {
        if (cause.name !== "AbortError") setError(cause.message);
      });

    return () => controller.abort();
  }, [dataUrl, data]);

  const stats = data ?? remote;

  if (!stats && error) {
    return (
      <StatusCard width={width} theme={theme}>
        {`用量数据加载失败（${error}），请稍后重试。`}
      </StatusCard>
    );
  }
  if (!stats) {
    return (
      <StatusCard width={width} theme={theme}>
        正在加载用量数据…
      </StatusCard>
    );
  }
  if (!isValidStats(stats)) {
    return (
      <StatusCard width={width} theme={theme}>
        数据格式异常，请检查 stats.schema.json 契约。
      </StatusCard>
    );
  }

  const day = date ?? stats.latest_date ?? "";
  const { rows, totalTokens, totalRequests } = rankModels(
    stats.daily,
    day,
    limit,
    groupBy,
  );

  return (
    <Card
      className="usage-widget overflow-hidden p-4 sm:p-[18px]"
      data-theme={theme}
      style={widgetStyle(width, accent)}
    >
      <header className="flex min-w-0 items-center justify-between gap-3">
        <h2 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-foreground">
          {title}
        </h2>
        <time
          className="shrink-0 rounded-md bg-muted px-2 py-1 text-[11px] tabular-nums text-muted-foreground"
          dateTime={day}
        >
          {day || "—"}
        </time>
      </header>

      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span>
          <strong className="font-semibold tabular-nums text-foreground">
            {fmt(totalTokens)}
          </strong>{" "}
          tokens
        </span>
        <span>
          <strong className="font-semibold tabular-nums text-foreground">
            {fmt(totalRequests)}
          </strong>{" "}
          次会话/请求
        </span>
      </div>

      <Tabs
        className="mt-3"
        value={groupBy}
        onValueChange={(value) => setGroupBy(value as GroupBy)}
      >
        <TabsList aria-label="排行维度">
          <TabsTrigger value="source">ADE</TabsTrigger>
          <TabsTrigger value="model">模型</TabsTrigger>
        </TabsList>
      </Tabs>

      {rows.length > 0 ? (
        <div className="mt-3 grid gap-2.5" aria-live="polite">
          {rows.map((row) => (
            <BarRow
              key={row.label}
              label={row.label}
              pct={row.pct}
              accent={accent}
            />
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground" role="status">
          {day || "今天"}暂无用量数据
        </p>
      )}
    </Card>
  );
}
