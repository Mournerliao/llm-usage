# LLM 用量 · React 组件

React 实现的用量看板组件，复用仓库根 `data/stats.json` 的数据。界面使用 Tailwind CSS v4 与 shadcn 风格的 `Card` / `Tabs`，其中 Tab 基于 Radix UI，支持键盘操作和焦点状态。

React 与 SVG 并不是互相转换：通用 React DOM、shadcn 和 Tailwind CSS 无法无损转成 GitHub 可用的 SVG。两端采用同一套视觉 token 和布局规则分别渲染，从而避免截图式转换，并保持稳定、接近像素级的视觉一致性；交互层有意不同，React 使用真正的 Tab，SVG 只标明当前维度。

## 本地预览

```bash
npm install
npm run dev
```

Vite 通过 `publicDir` 直接读取仓库根的 `data/stats.json`，所以预览即所见。

## 数据来源（两种模式）

- **运行时拉取（推荐用于博客）**：传 `dataUrl`，组件自行 fetch。
  ```tsx
  <UsageWidget dataUrl="https://cdn.jsdelivr.net/gh/<你>/<仓库>@main/data/stats.json" />
  ```
  仓库 `data/stats.json` 一更新，博客组件自动变新，无需重新构建。

- **构建时注入**：在博客构建阶段拿到数据后作为 `data` 传入，零运行时请求。
  ```tsx
  <UsageWidget data={stats} />
  ```

## 集成到不同博客框架

- **Next.js（App Router）**：组件已带 `"use client"`，直接 `import { UsageWidget } from "./UsageWidget"` 使用。
- **Astro**：`<UsageWidget client:load dataUrl="..." />`。
- **Vite / CRA / 任意 React**：直接 `import` 使用。

## Props

| 名称 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `dataUrl` | `string` | — | 运行时数据地址 |
| `data` | `UsageStats` | — | 构建时注入的数据 |
| `date` | `string` | `latest_date` | 展示哪一天 |
| `limit` | `number` | `8` | 展示前 N 个模型 |
| `defaultGroupBy` | `"model" \| "source"` | `"model"` | 初始 Tab；source 对应 ADE |
| `accent` | `string` | `#378ADD` | 条形主色 |
| `title` | `string` | `LLM 每日用量` | 卡片标题 |
| `width` | `number` | `560` | 卡片最大宽度 (px)，窄容器自动收缩 |
| `theme` | `"auto" \| "light" \| "dark"` | `"auto"` | 主题模式 |

## 数据契约

> **单一事实源**：仓库根的 `stats.schema.json`（JSON Schema）是契约的权威定义；
> 下方 TS 接口是它的镜像，字段名必须保持一致。若 `data/stats.json` 漂移，
> 组件会在运行时通过 `isValidStats` 告警而不是静默渲染错乱数据。

组件消费的 `UsageStats` 结构与 `aggregate.py` 生成的 `data/stats.json` 一致：

**分组维度（卡片内 Tab）**：组件默认「模型」排行（与 `api/widget.py` 口径一致）；
也可切到「ADE」按来源聚合。`aggregate.py` 与 `render.py`、本组件三者共用同一份契约，
排行/分组逻辑都收敛到 `ranking.rank_models`（Python）与 `rankModels`（TS）这对纯函数。

```ts
interface UsageStats {
  latest_date: string | null;
  total_dates: number;
  daily: {
    source: string;
    model: string;
    date: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }[];
}
```
