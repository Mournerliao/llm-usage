# LLM 用量 · React 组件

React 实现的用量看板组件，复用仓库根 `data/stats.json`。界面用 Tailwind CSS v4 与
shadcn 风格的 `Card` / `Tabs`，Tab 基于 Radix UI，支持键盘操作与焦点状态。

React 与 SVG 不是互相转换的关系：通用 React DOM、shadcn 和 Tailwind 无法无损转成
GitHub 可用的 SVG。两端共用同一份数据契约与同一套视觉 token，各自渲染，从而避免
截图式转换。交互层有意不同：React 用真正的 Tab，SVG 只在右上角标明当前维度。

## 本地预览

```bash
npm install
npm run dev
```

Vite 通过 `publicDir` 直接读取仓库根的 `data/stats.json`，预览即所见。

## 数据来源（两种模式）

- **运行时拉取（推荐用于博客）**：传 `dataUrl`，组件自行 fetch。

```tsx
<UsageWidget dataUrl="https://cdn.jsdelivr.net/gh/Mournerliao/llm-usage@main/data/stats.json" />
```

仓库数据一更新，博客组件自动变新，无需重新构建。

- **构建时注入**：在博客构建阶段拿到数据后作为 `data` 传入，零运行时请求。

```tsx
<UsageWidget data={stats} />
```

## 集成到不同框架

- **Next.js（App Router）**：组件已带 `"use client"`，直接 import 使用。
- **Astro**：`<UsageWidget client:load dataUrl="..." />`
- **Vite / CRA / 任意 React**：直接 import。

## Props

| 名称 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `dataUrl` | `string` | — | 运行时数据地址 |
| `data` | `UsageStats` | — | 构建时注入的数据 |
| `date` | `string` | `latest_date` | 展示哪一天 |
| `limit` | `number` | `8` | 每节展示前 N 个 |
| `defaultGroupBy` | `"model" \| "source" \| "machine"` | `"model"` | 初始维度；source 对应 ADE |
| `accent` | `string` | `#378ADD` | 条形主色 |
| `title` | `string` | `LLM 每日用量` | 卡片标题 |
| `width` | `number` | `560` | 最大宽度 (px)，窄容器自动收缩 |
| `theme` | `"auto" \| "light" \| "dark"` | `"auto"` | 主题模式 |

「机器」维度只在数据里确实有多台机器时才出现——单机时那个 Tab 恒为 100%，没有信息量。

## 数据契约

> **单一事实源**是仓库根的 `stats.schema.json`（当前 v2）。`src/types.ts` 是它的
> TS 镜像，字段名必须一致。若 `data/stats.json` 漂移，`isValidStats` 会在运行时
> 拦下并提示，而不是静默渲染错乱数据。

```ts
interface UsageStats {
  schema_version: number;      // 必须是 2
  latest_date: string | null;
  total_dates: number;
  units: Unit[];
  machines: string[];
  daily: {
    date: string;
    machine: string;
    source: string;
    model: string;
    unit: "requests" | "sessions" | "tokens" | "credits" | "lines";
    amount: number;
    amount_in?: number;        // 仅当源能拆分输入输出时存在
    amount_out?: number;
  }[];
}
```

### 为什么按 unit 分节

不同源的计量单位天然不同（Cursor 只能给出请求数，OpenAI 兼容接口给的是真 token）。
相加得到的「总量」没有意义，占比还会被量级最大的单位主导。所以组件把视图按 unit
切成若干小节，每节内部各自算 100%。

分节、合并、占比这套逻辑收敛在 `buildView`（TS）与 `ranking.build_view`（Python）
这对纯函数里，两个渲染器都只做薄渲染。
