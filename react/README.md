# LLM 用量 · React 组件

React 实现的用量卡片，复用仓库根 `data/stats.json`。界面用 Tailwind CSS v4 与 shadcn
风格的 `Card` / `Tabs`，周次切换基于 Radix UI，支持键盘操作与焦点状态。

React 与 SVG 不是互相转换的关系：通用 React DOM、shadcn 和 Tailwind 无法无损转成
GitHub 可用的 SVG。两端共用同一份数据契约与同一个视图函数，各自渲染。

**分工**：README 里的 SVG 只有本周一张，因为 GitHub 不执行 JS，静态图里塞多周只会变
拥挤。这个组件负责本周与过去三周的切换，另外多一条七天条形——静态卡片里放不下。

## 本地预览

```bash
npm install
npm run dev
```

Vite 通过 `publicDir` 直接读取仓库根的 `data/stats.json`，预览即所见。预览页默认按 760
/ 560 / 380 三档容器宽度并排渲染亮暗两版；也可以用查询参数只看一档，方便截图核对：

```
http://localhost:5173/?w=380&theme=light&week=2026-W33
```

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
| `week` | `string` | 最新一周 | 初始周次，ISO 周编号如 `2026-W34` |
| `limit` | `number` | `6` | 模型行展示前 N 个 |
| `title` | `string` | `LLM 用量` | 卡片标题 |
| `width` | `number` | `760` | 最大宽度 (px)，窄容器自动收缩 |
| `theme` | `"auto" \| "light" \| "dark"` | `"auto"` | 主题模式 |

## 断点是容器查询，不是视口

排版跟着**卡片自己的宽度**走（`@container` + `@xl:`），不是视口宽度。博客里这个组件的
宽度由正文栏决定，视口 1440 而正文只有 600 是常态；用视口断点就会在窄栏里错版。

容器窄于 576px 时，模型行的占比条与 Tokens 列先让位——名字和金额是必须读到的，占比条是
锦上添花。

## 数据契约

> **单一事实源**是仓库根的 `stats.schema.json`（当前 v3）。`src/types.ts` 是它的 TS
> 镜像，字段名必须一致。若 `data/stats.json` 漂移，`isValidStats` 会在运行时拦下并
> 提示，而不是静默渲染错乱数据。

```ts
interface UsageStats {
  schema_version: number;      // 必须是 3
  timezone: string;
  latest_date: string | null;
  weeks: { week: string; start: string; end: string }[];   // 4 个，新的在前
  sources: string[];
  daily: {
    date: string;
    source: string;
    model: string;
    requests: number;
    // 以下字段缺失表示「这个源不报该口径」，与「报了但是零」不是一回事
    tokens_in?: number;
    tokens_out?: number;
    cache_write?: number;
    cache_read?: number;
    cost_cents?: number;       // token 按模型单价的折算成本，不是账单金额
  }[];
  year: YearSummary | null;    // 当年汇总，目前不展示
}
```

## 口径只有一份

取哪一周、按什么排序、占比多少、数字写成什么样，全部收敛在 `buildWeekView`（TS）与
`ranking.build_week_view`（Python）这对纯函数里，两个渲染器都只做薄渲染。

视图里带 `*_display` 字符串，格式化也在这一层。因为「479.0M」这种写法涉及量级选择与舍
入方向，两边各写一遍必然漂移。仓库根的 `tests/test_parity.py` 把真实的这份 TS 交给 node
执行，与 Python 的输出逐字段比对（含每个显示字符串），改动其中一侧必须同步另一侧。

舍入不用各语言的内建格式化：Python 的 `f"{x:.1f}"` 是银行家舍入，JS 的 `toFixed` 是四舍
五入，恰好落在半分位上的值会给出不同文本。两边都手写 `floor(|x| * 10^n + 0.5)`。
