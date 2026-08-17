# LLM 用量

把作者自己真实的 LLM 消耗量公开出来：按天、按源、按模型归集 token 与模型成本，渲染成 GitHub 上的静态卡片和博客里可切换周次的组件。

## Language

**Event**:
某一天、某个源、某个模型上的用量。`requests` 必填；四类 token 与 `cost_cents` 可缺席（缺席 ≠ 0）。
_Avoid_: Record, unit/amount

**Source**:
用量来源身份，落在 `Event.source` 与 raw 路径第一段。如 `cursor`、`chatgpt`、中转站名。
_Avoid_: provider（那是 Codex 日志里的字段，翻译成 Source 之后才进契约）

**Collector**:
把某源的外部形态翻译成 Event 的 adapter。声明是否按机器分片，不自己碰文件系统。

**Raw**:
`data/raw/` 下按月分片的原始事件。账号级源 `<source>/<月>.json`；本机源 `<source>/<machine>/<月>.json`。

**Fold**:
读全部 Event，归一模型名，按 (date, source, model) 累加，切出展示窗口与年度汇总。

**WeekView**:
某一周已经算好的展示视图：总量、显示字符串、构成条、模型排行、七天格子。写在 `stats.json` 的 `weeks[].view` 里。
_Avoid_: 视图函数（渲染器不再计算）

**模型成本**:
token 按各模型单价折算出的成本，单位为分（`cost_cents`）。不是账单金额。

**Subscription source**:
没有逐次成本的源。金额列显示「订阅」而不是横线或估出来的单价。

**Machine**:
本机标识。只当 raw 分片键，不进 Event，也不进公开展示。
