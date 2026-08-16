# LLM 每日用量

> 自动展示我每天在各 AI 编码工具（Cursor / OpenAI / DeepSeek / 中转站 / WorkBuddy）上使用的模型、对话数与 token 消耗。
> 数据由本机 `update-local.sh` 采集并推送到本仓库，线上端点据此实时渲染。

<!-- WIDGET_START -->
![LLM 每日用量](https://llm-usage.vercel.app/widget.svg?group_by=model&theme=auto)
<!-- WIDGET_END -->

> GitHub README 会把 SVG 当作静态图片，因此每张卡片只展示当前维度：`group_by=source` 为 ADE，`group_by=model` 为模型。主页可用两个 `<details>` 折叠区提供原生切换，博客里的 React 版本则提供真正可交互的 Tab。

## 原理
采集（cloud 类走 API，local 类走本机脚本）→ 聚合为统一 schema（`data/stats.json`）→ 线上 Vercel 端点动态渲染 SVG，React 组件读取同一份数据展示。详见各 collector。

## 运行
- **云端（API 类源）**：`python run.py --mode cloud --date <YYYY-MM-DD>`（需配置对应 API key，手动运行）。
- **本机（Cursor / WorkBuddy 等本地源）**：`python run.py --mode local --date <YYYY-MM-DD>`，跑完把 `data/local/*.json` 推回仓库（见 `update-local.sh`）。
- **每日自动更新**：在本机用任务计划程序 / cron 定时运行 `./update-local.sh`，它会采集、汇总并推送 `data/stats.json`，GitHub 主页与博客组件随之刷新。
- 配置：复制 `config/sources.example.yaml` 为 `sources.yaml` 并填入你的源。

## React 组件（博客用）

本项目同时提供一个 React 版本的用量组件，方便嵌进博客：复用同一份 `data/stats.json`，并与 Vercel SVG 端点保持相同的颜色、圆角、间距、排版和百分比口径。

- 代码：`react/src/UsageWidget.tsx`（Tailwind CSS v4 + shadcn 风格的 `Card` / `Tabs`，Tab 基于 Radix UI）。
- 本地预览：`cd react && npm install && npm run dev`（Vite 直接读取仓库根的 `data/stats.json`）。
- 集成：组件接受 `dataUrl`（运行时从 CDN 拉取，随仓库 `data/stats.json` 更新自动刷新）或 `data`（构建时注入）两种模式，可放入 Next.js / Astro / Vite 等任意 React 环境。详见 `react/README.md`。

SVG 端点还支持以下参数：

- `group_by=model|source`：模型 / ADE 维度。
- `theme=auto|light|dark`：跟随系统或固定主题。
- `date=YYYY-MM-DD`：指定日期，默认展示最新日期。

## WorkBuddy 接入（local 采集器）

WorkBuddy 用量通过读它自身运行库 `~/.workbuddy/workbuddy.db` 采集（无需 API key）：

- `session_usage.used` → 该会话累计消耗（token / 积分；`size` 字段恒为 192000，疑似配额上限）
- `sessions.model` → 模型名（如 `hy3`）
- `sessions.created_at` → 归到该会话的创建日

限制（当前 db 只落盘到这种粒度）：

- 只有每会话累计 `used`，**无 input / output 拆分**，故整体计入 `input_tokens`（`total_tokens = used`）。
- 无 requests 计数，按每会话计 `requests = 1`。
- 全账号共享（所有项目的 session 都在这张库里），不限于当前项目。
- 走 named pipe 通信，不监听 TCP，故 8080 本地 API / quota 日志目录在当前版本均不可用。

回流：本采集器是 local 模式，需本机跑 `python run.py --mode local --date <YYYY-MM-DD>`，产物 `data/local/workbuddy.json` 已将该目录从 `.gitignore` 放行，需 `git add` 并提交回仓库，线上端点才读得到。
