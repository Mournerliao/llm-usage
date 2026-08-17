"use client";

import { memo, useEffect, useState, type CSSProperties } from "react";

import { Card } from "./components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import "./index.css";
import type { GroupBy, UsageStats, UsageWidgetProps, WidgetTheme } from "./types";
import { DIMENSION_LABELS, isValidStats, unitCounted, unitLabel } from "./types";
import { buildView } from "./view";

export { buildView };

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
  const view = buildView(stats.daily, day, limit, groupBy);
  // 只有一种单位时，小节标题会和顶部汇总行显示同一个数，是冗余，省掉。
  const showSectionHeaders = view.sections.length > 1;
  const hasRows = view.sections.some((section) => section.rows.length > 0);
  // 机器维度只在确实有多台机器时才提供，单机时那个 Tab 永远是 100%，没有信息量。
  const dimensions: GroupBy[] = ["source", "model"];
  if (stats.machines.length > 1) dimensions.push("machine");

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
        {view.totals.length > 0 ? (
          view.totals.map((total) => (
            <span key={total.unit}>{unitCounted(total.unit, total.amount)}</span>
          ))
        ) : (
          <span>暂无用量</span>
        )}
      </div>

      <Tabs
        className="mt-3"
        value={groupBy}
        onValueChange={(value) => setGroupBy(value as GroupBy)}
      >
        <TabsList aria-label="排行维度">
          {dimensions.map((dimension) => (
            <TabsTrigger key={dimension} value={dimension}>
              {DIMENSION_LABELS[dimension]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {hasRows ? (
        <div className="mt-3 grid gap-4" aria-live="polite">
          {view.sections
            .filter((section) => section.rows.length > 0)
            .map((section) => (
              <section key={section.unit} className="grid gap-2.5">
                {showSectionHeaders && (
                  <h3 className="text-[11px] font-medium text-muted-foreground">
                    {unitLabel(section.unit)}{" "}
                    <span className="font-semibold tabular-nums text-foreground">
                      {section.total.toLocaleString("en-US")}
                    </span>
                  </h3>
                )}
                {section.rows.map((row) => (
                  <BarRow
                    key={row.label}
                    label={row.label}
                    pct={row.pct}
                    accent={accent}
                  />
                ))}
              </section>
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
