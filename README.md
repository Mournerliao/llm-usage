# LLM 每日用量

> 自动展示我每天在各 AI 编码工具上使用的模型与用量。数据由本机采集并推回本仓库，
> GitHub Actions 据此重新生成下面这张卡片。

<!-- WIDGET_START -->
<img src="assets/widget-model-light.svg#gh-light-mode-only" alt="LLM 每日用量（按模型）" width="560">
<img src="assets/widget-model-dark.svg#gh-dark-mode-only" alt="LLM 每日用量（按模型）" width="560">
<!-- WIDGET_END -->

<details>
<summary>按 ADE 维度看</summary>

<img src="assets/widget-source-light.svg#gh-light-mode-only" alt="LLM 每日用量（按 ADE）" width="560">
<img src="assets/widget-source-dark.svg#gh-dark-mode-only" alt="LLM 每日用量（按 ADE）" width="560">

</details>

博客里的 [React 版本](react/) 提供真正可交互的维度切换。

## 原理

```
本机采集器 → data/raw/<机器>/<源>/<月>.json   （原始事件，各机器互不干扰）
           → data/stats.json                  （CI 聚合产物）
           → assets/*.svg + React 组件         （两个渲染器共用同一份契约）
```

原始数据的路径里带机器名，所以两台机器永远写不同文件，同步时不会互相覆盖。产物由
CI 单点生成，本机不提交产物。聚合是纯归约，重跑任意次结果一致。

## 计量单位不能混算

不同工具的口径天然不同：Cursor 能给出请求数，OpenAI 兼容接口给的是真 token。把它们
相加得到的「总量」没有意义，占比也会被量级最大的单位主导。所以每条记录都带 `unit`，
展示时按单位分节，各节内部自成 100%。

| 源 | unit | 口径 | 说明 |
| --- | --- | --- | --- |
| `cursor` | `requests` | 按模型的 AI 请求数 | 读 `ai-code-tracking.db`，见 `collectors/cursor.py` |
| OpenAI 兼容 | `tokens` + `requests` | 真实 token，含输入输出拆分 | 唯一有 token 口径的源 |

## 运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config/sources.example.yaml sources.yaml   # 填上 machine，两台机器取不同值
.venv/bin/python run.py                       # 采集 + 汇总 + 渲染
```

常用参数：

- `--only cursor` 只采某个源
- `--lookback 7` 缩短回看窗口（默认 30 天）
- `--skip-collect` 只重跑汇总与渲染，CI 用的就是这条

日常自动更新：用 cron / 任务计划程序每天跑一次 `./update-local.sh`，它会采集、
推送原始数据，剩下的交给 CI。

## 配置分两份

| 文件 | 是否提交 | 内容 |
| --- | --- | --- |
| `sources.yaml` | 否 | 机器名、各源的 `base_url` 与 key 环境变量名 |
| `config/aggregate.yaml` | 是 | 时区、模型别名表 |

拆开是因为读者不同：采集只在本机跑，而 CI 需要时区和别名表才能重新聚合，又不该
拿到任何密钥。

模型别名表用来把同一模型在不同工具或不同机器上的标签归一，否则模型排行会把同一个
模型拆成多行。原始事件保留原名，归一只在聚合阶段做，映射改错了可以重跑修正。

## Cursor 采集的注意事项

数据来自 `~/.cursor/ai-tracking/ai-code-tracking.db`，这是 Cursor 自己统计「AI 写了
多少代码」的库，表结构窄、字段语义明确。**它只保留最近约一个月**，所以：

- 首次采集能一次性回填近一个月历史。
- 但必须定期采集，否则更早的数据滚出窗口后永久丢失。

口径细节与已核实的边界（requestId 不跨天、`human` 行跳过、Tab 补全不上报模型）都写在
`collectors/cursor.py` 的模块文档里。

## 数据契约

`stats.schema.json` 是单一事实源，当前为 v2。`schema_version` 字段供消费方校验，
避免字段语义变更后静默渲染错误数据。

设计取舍与待办见 [`docs/DESIGN.md`](docs/DESIGN.md)。
