# Plus / Codex token × 单价：社区有没有把订阅用量折成美元

> 目标读者：本人
> 日期：2026-08-18
> 问题：社区是否已经把 ChatGPT Plus / Codex / GPT 订阅用量，用 tokens × 公开 API（或其他）单价折成美元？那是不是一种被接受的展示口径。
> 关联：本仓库现状见 `PRODUCT.md`、`docs/DESIGN.md` §11、`llm_usage/pricing.py`
>
> **已落地（2026-08-18）：** 走 ccusage 那条路。Cursor 仍用官方 `totalCents`；Codex 在 fold 时按 `config/aggregate.yaml` 的公开 API 牌价补 model cost。raw 不改。对不上牌价的模型仍显示 Subscription。主数字只写一个 `$`，不再拼 Subscription。

本文只跟一手来源：官方文档、仓库源码、第一方 API / CLI、GitHub issue。HN / 论坛帖只当指针，结论仍回到物主。

---

## 直接答案

**部分成立（partial）。** 本地 CLI / 桌面用量工具已经把这条路走成事实标准：从 `~/.codex` 读 token，再乘 LiteLLM / models.dev / 内置 API 单价，输出 `costUSD`。最强先例是 [ccusage](https://github.com/ryoppippi/ccusage)，它明确说这是 **API-equivalent estimate**，不是 ChatGPT 账单。同类还有 tokmeter、token-pulse、CodexBar 的可选 local cost scan、usage-tracker。

**官方 OpenAI 不做这件事。** Plus / Pro / Codex 订阅侧没有逐次美元；第一方界面给的是 5 小时 / 周配额百分比、token 活动、以及 **credits** 费率卡。Platform 的 Usage / Costs API 只管 API key 组织账单，和 ChatGPT 订阅不相交。Codex CLI 上游还关过「用公开单价估 session 成本」的 RFC。

所以：在「本地分析工具、自用看板」里，`$` 是被接受的**强度口径**；在「官方计费 / 公开声称这是花费」里，它不是。本仓库选择跟 ccusage 对齐：两个来源都叫 model cost，README 写明 Codex 是 API-equivalent，不是账单。主数字只留一个 `$`，不再写成 `$X · Subscription`。

---

## 工具对照

| 项目 | URL | 订阅用量展示什么 | 是否用 token × 单价发明 `$` | 证据 |
| --- | --- | --- | --- | --- |
| **ccusage**（最强先例） | https://github.com/ryoppippi/ccusage | 日 / 月 / session 表：token + `Cost (USD)`；Codex 走 `ccusage codex daily` | **是。** Codex 日志没有 `costUSD`，一律按 LiteLLM / models.dev 单价算。文档写明 `costUSD` is an API-equivalent estimate, not a ChatGPT credit balance | [Codex guide](https://github.com/ryoppippi/ccusage/blob/main/docs/guide/codex/index.md)；`rust/crates/ccusage-core/src/cost.rs` 的 `calculate_cost_from_tokens` |
| **tokmeter** | https://github.com/lich99/tokmeter | 本地 dashboard：token 分桶 + 折算成本曲线 | **是。** 内置 OpenAI GPT-5.x list price（含 272K 长上下文与 Fast 倍率） | README：「The dollars here are the **equivalent standard-API cost** of the same workload… Not your actual invoice.」 |
| **token-pulse** | https://github.com/Wilgrass/token-pulse | Claude Max + ChatGPT Plus/Codex：配额 %、精确 token、USD | **是。** 「Cost (USD list-price equivalent)」；配额走 `chatgpt.com/backend-api/codex/usage`，成本走本地 jsonl × 单价 | README Known limitations：「Subscription users (Max, Plus) pay flat fees, not per-token. The cost shown is "what the API would have charged for the same volume"」 |
| **CodexBar** | https://github.com/steipete/CodexBar | 默认：5h / 周配额 %、reset credits、credits 余额。**可选**「Local session cost estimates」 | **默认否，可选是。** 本地扫描 `~/.codex` jsonl，用 bundled `CostUsagePricing`（GPT-5 为 `$1.25 / 1M` input 等 API 单价） | [docs/codex.md](https://github.com/steipete/CodexBar/blob/main/docs/codex.md)「dashboard labels its values as local estimates」；`CostUsagePricing.swift` |
| **vibeusage** | https://github.com/joshuadavidthomas/vibeusage | Codex：session / weekly / code-review **配额 %**、reset credits、pace 着色 | **否。** 读 Codex OAuth 的 live usage，不乘单价 | README：「Reports session, weekly, code review, and model-specific limits」 |
| **escoffier-labs/usage-tracker** | https://github.com/escoffier-labs/usage-tracker | 把每次调用标成 `oauth`（订阅烧掉的 API 等值）或 `api`（真金白银） | **是，但分栏。** Codex rollout 一律 `oauth`；token × 内置价表；缺价的模型 `costUsd: null`，不当 0 | README Billing classification |
| **gpt-worth-it** | https://github.com/phuocnguyen90/gpt-worth-it | ChatGPT **网页导出** × 可编辑 1M token 单价，对比 $20 Plus 线 | **是。** 用途是「值不值得续 Plus」，不是账单 | README：「Numbers are **estimates** for your own insight, not official billing.」 |
| **paperclip** | https://github.com/paperclipai/paperclip/issues/339 | 订阅 run 记 `cost_cents = 0` | **目前否。** 开着 issue 要求按 token × 参考价估 `cost_estimate_cents`，并在 UI 标 `est.` | issue 仍 open；作者写明「OpenAI does not return cost information for subscription usage」 |
| **Codex CLI（官方）** | https://github.com/openai/codex ；docs: [slash commands](https://developers.openai.com/codex/cli/reference) | `/status`：模型、context %、5h/周 **% left**；`/usage`：daily / weekly / cumulative **token activity** + redeem reset | **否。** 不展示美元。RFC [#5085](https://github.com/openai/codex/issues/5085) 提议用公开单价估成本，2026-01-14 被指向 Enterprise analytics 后关闭 | CLI reference；issue 关闭评论 |
| **chatgpt.com Codex usage dashboard** | https://chatgpt.com/codex/settings/usage | 当前 limits、credits 余额、recent usage | **否。** 官方单位是 credits 与消息窗口，不是 USD | [Codex Pricing](https://developers.openai.com/codex/pricing) |
| **OpenAI Platform Usage / Costs API** | `GET /v1/organization/usage/completions`、`GET /v1/organization/costs` | API key 组织的 token 与 `amount.currency = usd` | **不适用 Plus。** 要 Admin key；dashboard 在 platform.openai.com/usage | [API reference](https://developers.openai.com/api/reference/resources/admin)；[cookbook](https://developers.openai.com/cookbook/examples/completions_usage_api) |
| **cursor-costs-raycast** | https://github.com/shadeov/cursor-costs-raycast | 菜单栏 % / `$`；模型 `totalCents` | **否（不发明）。** 直接读 Cursor `get-aggregated-usage-events` 的 `totalCents` / `totalCostCents` | `src/types.ts` |
| **本仓库 llm-usage** | 本目录 | Cursor：官方 `totalCents` → `$`；Codex：fold 时按公开 API 牌价补 `$`；对不上牌价才写 `Subscription` | **是（fold，不写进 raw）。** `list_prices` 来自 OpenAI API pricing 页 | `llm_usage/pricing.py`；`config/aggregate.yaml`；`docs/DESIGN.md` §11 |

公开 GitHub 卡片里把 Plus token 折成 `$` 的近例是 [ai-coding-usage-card](https://github.com/Baek-Seunghyun/ai-coding-usage-card)（ccusage 产物，自称 API-equivalent）。本仓库现在走同一条口径。

---

## 官方口径

### 1. Plus / Pro 是定额订阅，API 另开账单

ChatGPT Plus 帮助页写明：

> Price: $20/month (billed monthly).
> Not included: API usage is separate and billed independently. See API pricing.

出处：[What is ChatGPT Plus?](https://help.openai.com/en/articles/6950777)（Intercom 403，正文由搜索命中页与 Business 同文确认）。ChatGPT Business 帮助页把同一句话再说一遍：「A ChatGPT Business subscription does not include API usage - API usage is billed separately。」([What is ChatGPT Business?](https://help.openai.com/en/articles/8792828-what-is-chatgpt-business))

Forum 里 OpenAI 人员也按产品拆：「The use of the API is actually distinct from ChatGPT… The ChatGPT Plus subscription does not imply access to the API.」([community thread](https://community.openai.com/t/cost-and-availability-for-gptplus-users/803376))

### 2. Platform Usage / Costs API 只管 API key

[Completions Usage API cookbook](https://developers.openai.com/cookbook/examples/completions_usage_api) 的入口是 `https://platform.openai.com/usage`，鉴权是 **Admin Key**（`platform.openai.com/settings/organization/admin-keys`）。Costs 返回：

```json
"amount": { "value": 0.06, "currency": "usd" }
```

过滤维度是 `api_key_id` / `project_id` / `line_item`。没有 ChatGPT 账号、Plus 套餐、Codex OAuth 这些字段。本仓库采集器注释与此一致：`/backend-api/wham/usage` 只给窗口占用百分比；Admin Usage API 只覆盖 API key，「和订阅用量不相交」(`llm_usage/collect/chatgpt.py` 第 5–7 行)。

[How do I check my token usage?](https://help.openai.com/en/articles/6614209-how-do-i-check-my-token-usage) 讲的是 **API** usage dashboard 和 chat.completion 响应里的 `usage` 键，不是 Plus。

### 3. Codex 订阅侧的官方单位是 credits，不是美元

[Codex Pricing](https://developers.openai.com/codex/pricing)（2026-08-18 抓到的 markdown）：

- Plus 卡片：$20/month，文案是用量额度 + 「Flexibly extend usage with ChatGPT credits」。
- API Key 卡片才写：「Pay only for the tokens Codex uses, based on [API pricing](https://platform.openai.com/docs/pricing)」。
- FAQ「What are tokens and credits?」：

> Credits translate token usage into a simpler unit for tracking and managing consumption.
> Usage is calculated in credits per million input tokens, cached input tokens, and output tokens.

费率卡示例（Credits per 1M tokens）：GPT-5.6 Sol 125 / 12.5 / 750；Terra 50 / 5 / 300；Luna 5 / 0.5 / 30。这是 **credits**，不是 USD。

同页：「You can find your current limits in the [usage dashboard](https://chatgpt.com/codex/settings/usage). If you want to see your remaining limits during an active Codex CLI session, you can use `/status`.」没有「本次请求花了 $x」。

超额之后 Plus/Pro 可以买 credits，不是按 API 价直接出账：[Using Credits for Flexible Usage in ChatGPT (Free/Go/Plus/Pro)](https://help.openai.com/en/articles/12642688)。Help Center 的 [Codex rate card](https://help.openai.com/en/articles/20001106-codex-rate-card) 也说 2026-04-02 起 Plus/Pro 从 per-message 改成「align with API token usage」，但落地单位仍是 credits per million tokens。

ccusage 自己把这两套表拆开了：GPT-5.6 Fast 的 API Priority 是 2×，ChatGPT credit 消耗是 2.5×；「ccusage's `costUSD` is an API-equivalent estimate, not a ChatGPT credit balance。」这等于承认：**即使用官方费率卡，乘 API 单价也和订阅侧的 credit 口径对不上。**

### 4. Codex CLI / app-server 给 Plus 用户看什么

官方 slash 命令表（[Developer commands](https://developers.openai.com/codex/cli/reference)）：

| 命令 | 文档原句 |
| --- | --- |
| `/status` | 「Display session configuration and token usage.」正文：模型、approval、writable roots、remaining context capacity。源码把 weekly 渲染成 `"weekly 81% left"` 这类字符串，没有 `$`。 |
| `/usage` | 「View account token usage or use a rate-limit reset.」子命令是 `daily` / `weekly` / `cumulative` **token activity**。 |

JSON-RPC `account/rateLimits/read` 返回 `usedPercent`、`windowDurationMins`、`resetsAt`、reset credits。`account/usage/read` 在带 `threadId` 时可以有「estimated credits, optional cost」——这是 **thread 级、服务端给的 credits/可选 cost**，不是社区用 API 价表乘出来的；Plus 账号级视图仍是 token activity。

2025-10 的 RFC [openai/codex#5085](https://github.com/openai/codex/issues/5085) 提议：「Calculator: Uses public model pricing to estimate per-session costs。」评论里有人指出「The majority of Codex users are on ChatGPT Plus subscriptions rather than using the API directly. That’s likely why the current focus is on session-based usage limits… rather than API cost tracking。」OpenAI 员工 `etraut-openai` 于 2026-01-14 关闭 issue，只回了一句去看 [Codex analytics dashboard](https://developers.openai.com/codex/enterprise#codex-analytics)（Enterprise / Teams）。后续评论：「Great if you happen to be using Enterprise or Teams. Not so cool if you're running solo.」**第一方拒绝为 Plus 用户提供美元估账。**

会话 jsonl 也没有 cost 字段。本仓库读的是 `event_msg` / `token_count` / `last_token_usage`（input / output / cached / cache_write）。ccusage 的 troubleshooting 写：Codex CLI 从 [commit 0269096](https://github.com/openai/codex/commit/0269096229e8c8bd95185173706807dc10838c7a)（2025-09-06）才开始写 `token_count`，更早的 log 连 token 都没有。

---

## Cursor `totalCents` 有没有同类

有，但那是 **厂商自己算好写进接口**，不是第三方用价表乘。

本仓库把 Cursor `tokenUsage.totalCents` 叫 model cost：token 按模型单价折算，包含 included-in-plan，不含账单抽成（`PRODUCT.md` 术语表；`README.md`「About "model cost"」）。这和 Cursor 官方文档一致：Other Models 池按「the model's API price」计量，Pro 含「$20 of third-party model usage」([models-and-pricing](https://cursor.com/docs/models-and-pricing.md))。Staff 在论坛用同一套算术拆过一次请求：input/output/cache × 公开价 + Cursor Token Fee = `totalCents` ([Clarification on request billing calculation](https://forum.cursor.com/t/clarification-on-request-billing-calculation/149386))。

2026-07 之后 Cursor **自己把个人套餐 Usage 页的 `$` 拿掉了**。员工 `kevinn`：

> We did briefly display dollar amounts for individual plans, but that led to some confusion because the dollar amounts displayed were often higher amounts than the user's plan cost (due to the generous included usage of the Cursor individual plans).
>
> …anything covered by your plan shows token counts and is marked “Included”… Usage you actually pay for… still shows a dollar figure in the Cost column.

出处：[Usage Page $$ to Token Amount?](https://forum.cursor.com/t/usage-page-to-token-amount-what/167153)。也就是说：厂商一度展示「included 仍有 list-price `$`」，然后因为和月费对不上而收回。本仓库现在展示的 Cursor `$`，是接口里还在的 `totalCents`，不是 Cursor 当前个人 UI 的默认口径。

Claude Code 有更近的同类：jsonl 里带厂商预计算的 `costUSD`。ccusage 的 `auto` 模式优先用它，没有才自己乘（[cost-modes.md](https://github.com/ryoppippi/ccusage/blob/main/docs/guide/cost-modes.md)）。**Codex / Plus 没有这个字段。** 社区工具是在补 OpenAI 没写的那一列。

paperclip 把 Cursor 缺 `total_cost_usd` 的路径标成 `costStatus: "unpriced"`，和 Codex 订阅 `cost_cents = 0` 并列——两边都拒绝静默填 0，也还没把「自己乘单价」做成默认产品行为。

---

## 明确拒绝估 Plus 成本的项目，以及理由

| 谁 | 做法 | 为什么（物主原话） |
| --- | --- | --- |
| **OpenAI Codex CLI** | 不实现 token × API 价的 session `$`；RFC 关闭 | 关闭指向 Enterprise analytics；评论认为 Plus 用户要的是 rate-limit 窗口不是 API 账单 |
| **paperclip** | 订阅 `cost_cents = 0` | 「OpenAI does not return cost information for subscription usage.」估账还是未落地的 feature request，提案要求 UI 标 `~$50` / `$50 est.` |
| **vibeusage** | 只展示配额 % | 产品目标是 headroom / pace，不是花费。Claude 段还强调它「makes **zero inference requests**」，只读 usage percentage |
| **CodexBar 默认路径** | 配额 % + credits；local `$` 必须 opt-in | 文档把 cost scan 叫 **Local session cost estimates**，并写「dashboard labels its values as local estimates」 |
| **本仓库（改前）** | raw 的 `cost_cents` 留空，金额列写 `Subscription` | 当时认为 Plus 没有官方单价，不能估。2026-08-18 已改为 fold 时按 API 牌价补，见 §11 |

没有看到「我们算过、然后因为道德/法律撤回」的 commit。拒绝方的理由都是 **证据不足**：官方不返回 cost，所以不填，而不是填了再删。

反过来，发明 `$` 的项目没有一家把它当成发票。固定disclaimer 几乎同一句：flat subscription / not your bill / API-equivalent / estimates。ccusage 在 v0.4.0 就写过：「it is not possible to measure costs accurately. Just look at it as a reference。」([release](https://github.com/ryoppippi/ccusage/releases/tag/v0.4.0))

---

## 对本仓库的含义

已按第 11 节落地：跟 ccusage 走 API-equivalent，主数字合并成一个 `$`。下面几条仍是代价，不是反对票。

1. **社区接受的是「API 等值强度」，不是「这周花了 $x」。** README 必须继续写 Codex 是 list-price equivalent，不能让卡片看起来像账单。
2. **Cursor `$` 和 Codex `$` 的证据等级不同。** 前者是厂商写进事件，后者是本仓库选价表去乘。合并进同一个 model cost 是为了和 token 总量同一标尺，不是因为两者同样「官方」。
3. **官方更近的强度单位是 credits 和配额 %，不是 USD。** 本地 jsonl 只有 token，要对齐 `/status` 得另采 credits，那是另一条产品线。
4. **价表会漂。** Fast 倍率、272K 长上下文、中转站不是 OpenAI 价、模型别名缺失——ccusage 用 `--speed` 和 `isFallback` 挡。本仓库 ADE 把 Plus 和中转站都算 `codex`（ADR 0002），中转站流量会按官方 API 价标，可能偏了。缺价的模型仍显示 Subscription，不当 0。
5. **卡片本身不印 est.** 口径说明放在 README，和 Cursor 的 model cost 同一条既有约定。

---

## 主要出处

- OpenAI Codex 定价（含 Plus vs API Key、credits 费率卡、usage dashboard）：https://developers.openai.com/codex/pricing
- OpenAI Usage / Costs API：https://developers.openai.com/api/reference/resources/admin ；cookbook https://developers.openai.com/cookbook/examples/completions_usage_api
- ChatGPT Plus / credits / Codex rate card：https://help.openai.com/en/articles/6950777 ；https://help.openai.com/en/articles/12642688 ；https://help.openai.com/en/articles/20001106-codex-rate-card
- Codex CLI `/status` `/usage`：https://developers.openai.com/codex/cli/reference
- Codex 成本 RFC（关闭）：https://github.com/openai/codex/issues/5085
- ccusage Codex 计价：https://github.com/ryoppippi/ccusage/blob/main/docs/guide/codex/index.md ；`rust/crates/ccusage-core/src/cost.rs`
- Cursor 官方模型价与 included 池：https://cursor.com/docs/models-and-pricing.md
- Cursor 收回个人 Usage `$`：https://forum.cursor.com/t/usage-page-to-token-amount-what/167153
- 本仓库 Codex 牌价补算：`llm_usage/pricing.py`、`config/aggregate.yaml`、`docs/DESIGN.md` §11
