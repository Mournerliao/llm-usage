# LLM 用量

> 自动展示我每周在 AI 编码工具上的 token 消耗与折算成本。数据从 Cursor 官方接口采集
> 后推回本仓库，GitHub Actions 据此重新生成下面这张卡片。

<!-- WIDGET_START -->
<div>
<img src="assets/widget-light.svg#gh-light-mode-only" alt="本周 LLM 用量" width="760">
<img src="assets/widget-dark.svg#gh-dark-mode-only" alt="本周 LLM 用量" width="760">
</div>
<!-- WIDGET_END -->

这里只放**本周**一张静态图。要翻看过去几周，用博客里的 [React 版本](react/)，它支持在
本周与过去三周之间切换。

## 关于「模型成本」

卡片上的金额是 **token 按各模型单价折算出的成本**，反映我用掉了多少算力。

它**不是账单金额**：不含套餐、折扣与平台抽成，也和谁付钱无关——套餐内消耗的算力同样
计入，因为本项目量的是消耗而不是账单。接口另外返回的实际计费额与抽成字段不进入本仓库
的任何提交物。

## 原理

```
Cursor 官方接口 → data/raw/<源>/<月>.json    （原始事件，本机采集）
                → data/stats.json            （CI 聚合产物）
                → assets/*.svg + React 组件   （两个渲染器共用同一份视图函数）
```

采集需要本机 Cursor 的登录态，只能在本机跑。聚合与渲染是纯归约，只读仓库内的文件，
所以放在 CI 单点生成，两台机器都不必碰产物文件。

**采集幂等**：每次重采「起点到今天」的全部数据并覆盖写回，跑一次和跑十次结果相同。
漏跑几天补跑一次即可，不会产生重复记录——用量历史在 Cursor 账号侧，不会因为本机没采
而丢失。

**产物由数据决定，不由时钟决定**：「本周」取的是最近有用量的那天所在的 ISO 周，不是
运行时的当天。所以同一份原始数据在任何时刻重跑都得到同一份产物。

## 两台机器

我在公司用 Mac、在家用 Windows。Cursor 的用量来自**账号级**接口，两台机器采到的是同
一份数据，所以原始数据只按源和月份分片，不按机器分——按机器分片反而会把同一份数据算
两遍。

代价是失去了「哪台机器用得多」这个维度。接口不提供这个信息，硬造一个只会是假的。

## 采什么，不采什么

| 源 | token 明细 | 成本 | 说明 |
| --- | --- | --- | --- |
| `cursor` | 输入 / 输出 / 缓存写入 / 缓存读取 | 有 | 官方 dashboard 接口，可回溯到账号开通日 |
| OpenAI 兼容接口 | 仅输入 / 输出 | 无 | 各家 `/v1/usage` 口径，缓存与成本字段留空 |

拿不到某个口径时字段**缺失**而不是填 0，展示层据此显示横线。「不报 token」和「报了但
确实是零」是两件事。

缓存读取通常占总 token 的九成以上，所以四类 token 始终分开存，绝不合并成一个总数。

已排除的数据源，以及排除的实测依据，见 `collectors/cursor.py` 的模块文档与
[`docs/DESIGN.md`](docs/DESIGN.md)：

- Cursor 本机的 `ai-code-tracking.db`：只有请求数，没有任何 token 或成本字段。
- Cursor 本机的 `state.vscdb`：token 字段当前时段覆盖率为 0%，是旧版本残留。
- WorkBuddy：`session_usage.used` 实为上下文占用，不是 token 消耗，展示它会误导。

## 运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config/sources.example.yaml sources.yaml
.venv/bin/python run.py                       # 采集 + 汇总 + 渲染
```

采集默认从本机 Cursor 的登录态读凭据，本机登录着 Cursor 就不用配任何东西。换机时可设
`CURSOR_SESSION_TOKEN=<sub>::<jwt>`（值从 dashboard 请求的 `WorkosCursorSessionToken`
cookie 复制）。

常用参数：

- `--only cursor` 只采某个源
- `--since 2026-07-01` 覆盖采集起点
- `--skip-collect` 只重跑汇总与渲染，CI 用的就是这条

日常自动更新：用 cron / 任务计划程序每天跑一次 `./update-local.sh`，它会采集、推送原始
数据，剩下的交给 CI。

## 配置分两份

| 文件 | 是否提交 | 内容 |
| --- | --- | --- |
| `sources.yaml` | 否 | 采集起点、各源的 `base_url` 与凭据环境变量名 |
| `config/aggregate.yaml` | 是 | 时区、模型别名表 |

拆开是因为读者不同：采集只在本机跑，而 CI 需要时区和别名表才能重新聚合，又不该拿到任
何凭据。

模型别名表用来把同一模型的不同标签归一，否则模型排行会把同一个模型拆成多行。原始事件
保留原名，归一只在聚合阶段做，映射改错了重跑即可修正。

## 数据契约

`stats.schema.json` 是单一事实源，当前为 v3。`schema_version` 供消费方校验，避免字段
语义变更后静默渲染错误数据。

`daily` 只保留最近四个 ISO 周的明细；`year` 是当年汇总，**目前不展示，先存着**，等数据
攒够一年再用。完整历史始终在 `data/raw` 里，随时可以重新切窗口。

## 测试

```bash
.venv/bin/python tests/test_core.py      # 纯函数与契约
.venv/bin/python tests/test_parity.py    # Python 与 TS 的口径必须逐字段一致
```

parity 测试把真实的那份 TS 代码交给 node 执行，再与 Python 的输出逐字段比对，**包括
每一个显示字符串**。SVG 和 React 组件因此不可能对同一份数据显示出不同的数。

本机没装 node 时它会自动跳过，不挡住 Python 侧的测试。CI 里设了 `PARITY_STRICT=1`，
此时跳过一律算失败——否则工具链装漏了会让 CI 绿着通过，而这是唯一能拦住两边漂移的
测试。

设计取舍与实现偏差见 [`docs/DESIGN.md`](docs/DESIGN.md)，产品前提见
[`PRODUCT.md`](PRODUCT.md)。
