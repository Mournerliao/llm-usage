"use client";

import { memo, useEffect, useState, type CSSProperties } from "react";

import { Card } from "./components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import "./index.css";
import type {
  BreakdownSegment,
  DayCell,
  ModelRow,
  TokenKind,
  UsageStats,
  UsageWidgetProps,
  WidgetTheme,
} from "./types";
import { EMPTY_VIEW, isValidStats } from "./types";

// 与 CSS 变量一一对应，顺序即构成条的绘制顺序（固定顺序而非按大小，让配色稳定）。
const KIND_COLOR: Record<TokenKind, string> = {
  tokens_in: "var(--kind-in)",
  tokens_out: "var(--kind-out)",
  cache_write: "var(--kind-cache-write)",
  cache_read: "var(--kind-cache-read)",
};

/** 相对当前周的说法。第 0 项永远是最新一周。 */
function weekLabel(index: number): string {
  if (index === 0) return "本周";
  if (index === 1) return "上周";
  return `${index} 周前`;
}

/** 周次按钮上的短标签：该周周一的月/日。 */
function shortStart(start: string): string {
  const [, month, day] = start.split("-");
  return `${Number(month)}/${Number(day)}`;
}

type WidgetStyle = CSSProperties & { maxWidth: number | string };

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
      className="usage-widget p-6 text-sm text-muted-foreground"
      data-theme={theme}
      role="status"
      style={{ width: "100%", maxWidth: width }}
    >
      {children}
    </Card>
  );
}

const Rule = () => <div className="h-px bg-border" role="presentation" />;

/** token 四分类构成条。缓存读取通常占九成以上，这条线的用途正是让它一眼可见。 */
const Breakdown = memo(function Breakdown({
  segments,
}: {
  segments: BreakdownSegment[];
}) {
  if (segments.length === 0) return null;

  return (
    <div className="grid gap-3">
      {/* 1px 缝隙把相邻段切开，让只有几个像素宽的段也仍然读作独立的段，
          而不是让整条看起来像一条「只填了 7%」的进度条。比例保持线性。 */}
      <div className="flex h-2 gap-px overflow-hidden">
        {segments.map((seg) => (
          <div
            key={seg.kind}
            className="min-w-px transition-[flex-grow] duration-500 ease-out motion-reduce:transition-none"
            style={{ flexGrow: seg.pct, flexBasis: 0, backgroundColor: KIND_COLOR[seg.kind] }}
          />
        ))}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11.5px] @xl:grid-cols-4">
        {segments.map((seg) => (
          <div key={seg.kind} className="flex min-w-0 items-center gap-2">
            <span
              className="size-[7px] shrink-0"
              style={{ backgroundColor: KIND_COLOR[seg.kind] }}
              aria-hidden="true"
            />
            <dt className="shrink-0 text-muted-foreground">{seg.label}</dt>
            <dd className="truncate font-mono tabular-nums text-foreground">
              {seg.display}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
});

/** 七天条形。SVG 卡片里放不下，是这个组件比静态图多出来的那层信息。 */
const DayStrip = memo(function DayStrip({ days }: { days: DayCell[] }) {
  const peak = Math.max(...days.map((d) => d.tokens_total ?? 0), 1);

  return (
    <div className="grid gap-1.5">
      <div className="grid grid-cols-7 items-end">
        {days.map((day) => {
          const value = day.tokens_total ?? 0;
          // 有用量的日子至少留 4% 高度，否则轻量的那天会和完全没用量的一样是空的。
          const height = value > 0 ? Math.max((value / peak) * 100, 4) : 0;
          return (
            <div
              key={day.date}
              className="flex h-11 items-end justify-center"
              title={`${day.date}　${day.tokens_display} tokens`}
            >
              <div
                className="w-2.5 bg-foreground/70 transition-[height] duration-500 ease-out motion-reduce:transition-none"
                style={{ height: `${height}%` }}
              />
            </div>
          );
        })}
      </div>
      {/* 一条贯通的基线，让没有用量的那天读作「零」而不是「这天缺数据」。
          若把基线放进每一列，列间距会把它切成七段虚线。 */}
      <div className="h-px bg-border" role="presentation" />
      <div className="grid grid-cols-7">
        {days.map((day) => (
          <span
            key={day.date}
            className="text-center text-[10.5px] text-muted-foreground"
          >
            {day.weekday}
          </span>
        ))}
      </div>
    </div>
  );
});

const ModelTable = memo(function ModelTable({
  models,
}: {
  models: ModelRow[];
}) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-[minmax(0,1fr)_4.5rem] items-center gap-4 text-[11px] tracking-wider text-muted-foreground @xl:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem_4.5rem]">
        <span>模型</span>
        <span className="hidden @xl:block" aria-hidden="true" />
        <span className="text-right">成本</span>
        <span className="hidden text-right @xl:block">Tokens</span>
      </div>

      {models.map((row) => (
        <div
          key={row.label}
          className="grid grid-cols-[minmax(0,1fr)_4.5rem] items-center gap-4 text-[12.5px] @xl:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem_4.5rem]"
        >
          <span className="truncate text-foreground" title={row.label}>
            {row.label}
          </span>
          {/* 窄容器里条形先让位：名字和金额是必须读到的，占比条是锦上添花。 */}
          <div className="hidden h-1.5 bg-track @xl:block" aria-hidden="true">
            <div
              className="h-full bg-foreground/85 transition-[width] duration-500 ease-out motion-reduce:transition-none"
              style={{ width: `${Math.max(row.pct, row.pct > 0 ? 0.6 : 0)}%` }}
            />
          </div>
          <span className="text-right font-mono tabular-nums text-foreground">
            {row.cost_display}
          </span>
          <span className="hidden text-right font-mono text-[12px] tabular-nums text-muted-foreground @xl:block">
            {row.tokens_display}
          </span>
        </div>
      ))}
    </div>
  );
});

export function UsageWidget({
  dataUrl,
  data,
  week,
  title = "LLM 用量",
  width = 760,
  theme = "auto",
}: UsageWidgetProps) {
  const [remote, setRemote] = useState<UsageStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(week ?? null);

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
  const valid = stats !== null && isValidStats(stats);
  const weeks = valid ? stats.weeks : [];
  const activeWeek = weeks.find((w) => w.week === selected) ?? weeks[0] ?? null;
  const activeIndex = activeWeek ? weeks.indexOf(activeWeek) : 0;

  const view = activeWeek?.view ?? EMPTY_VIEW;

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
  if (!valid) {
    return (
      <StatusCard width={width} theme={theme}>
        数据格式异常，请检查 stats.schema.json 契约。
      </StatusCard>
    );
  }

  const style: WidgetStyle = { width: "100%", maxWidth: width };

  return (
    // @container 让排版跟着卡片自己的宽度走，而不是视口。博客里这个组件的宽度由
    // 正文栏决定：视口 1440 而正文只有 600 是常态，用视口断点就会在窄栏里错版。
    <Card
      className="usage-widget @container grid gap-5 overflow-hidden p-6 @xl:p-8"
      data-theme={theme}
      style={style}
    >
      <header className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[12.5px] tracking-[0.08em] text-muted-foreground">
          {title}
        </h2>
        <time className="font-mono text-[12.5px] tabular-nums text-muted-foreground">
          {view.range_display || "—"}
        </time>
      </header>

      {weeks.length > 1 && (
        <Tabs
          value={activeWeek?.week ?? ""}
          onValueChange={(value) => setSelected(value)}
        >
          <TabsList aria-label="选择周次">
            {weeks.map((item, index) => (
              <TabsTrigger
                key={item.week}
                value={item.week}
                aria-label={`${weekLabel(index)}，${item.start} 至 ${item.end}`}
              >
                <span className="font-mono tabular-nums">
                  {shortStart(item.start)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}

      {/* 切周时整块数据做一次短促的上浮，是这个组件唯一一处编排过的动作。
          key 变化触发重播；动画从已经可见的状态开始，不会在任何时刻是全透明的。 */}
      <div key={view.week ?? "empty"} className="animate-week-in grid gap-5">
        {view.week === null || view.requests === 0 ? (
          <p className="text-[13px] text-muted-foreground" role="status">
            {weekLabel(activeIndex)}（{view.range_display || "—"}）暂无用量数据。
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
              <div className="min-w-0">
                <p className="flex items-baseline gap-2">
                  <span className="font-mono text-[2.75rem] leading-none font-semibold tabular-nums text-foreground">
                    {view.tokens_display}
                  </span>
                  <span className="text-[13px] text-muted-foreground">tokens</span>
                </p>
                <p className="mt-2 text-[12px] text-muted-foreground">
                  {weekLabel(activeIndex)}共 {view.requests_display} 次请求
                </p>
              </div>
              {/* 窄容器里成本会换到下一行，此时跟着左边缘对齐；只有和 token 量并排
                  时才右对齐，否则数字贴左而标签贴右，两行读起来是错开的。 */}
              <div className="text-left @xl:text-right">
                <p className="font-mono text-[1.875rem] leading-none font-semibold tabular-nums text-accent">
                  {view.cost_display}
                </p>
                <p className="mt-2 text-[12px] text-muted-foreground">模型成本</p>
              </div>
            </div>

            <Rule />
            <Breakdown segments={view.breakdown} />

            <Rule />
            <DayStrip days={view.days} />

            <Rule />
            <ModelTable models={view.models} />
          </>
        )}
      </div>
    </Card>
  );
}
