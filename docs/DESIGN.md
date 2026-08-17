# LLM 用量看板 · 重构设计

> 状态：**阶段 0~3 已实现**，阶段 4 待做
> 目标读者：本人
> 关联：日常使用说明见仓库根 `README.md`

本文描述一次数据层重构。展示层（分层思路、`stats.schema.json` 的单一契约、React 组件）基本保留，要动的是它下面那层：原有的原始数据组织方式是按「一台机器、一天跑一次」写的，而实际场景是两台机器长期累积。

第 2 节记录改造前的问题（含实测证据），第 3 节是目标架构，第 7 节记录实现后与原计划的偏差。

---

## 1. 约束与目标

### 硬约束

- **两台机器**：Windows 在家，Mac 在公司。两边都会产生用量，都需要采集，都需要推回同一个仓库。
- **多种源，口径不同**：WorkBuddy 给的是会话累计积分，Cursor 给的是请求数，OpenAI 兼容接口给的是真 token。
- **公开仓库**：`Mournerliao/llm-usage` 是 public，README 的图片依赖它可公开访问。
- **零运维预算**：不希望为这个玩具项目长期维护服务器或数据库。

### 目标

1. 任何一台机器的采集都不会覆盖或丢失另一台的历史数据。
2. 历史是累积的，且可从原始数据完整重建。
3. 跨天的长会话，用量归到实际发生的那一天。
4. 不同单位的用量不被混在一起相加。
5. 减少组件数量和外部依赖，故障面越小越好。

---

## 2. 现方案的问题

以下都在当前代码和实际数据库里核实过，不是推测。其中 2.8 最严重：它说明现在展示的那个数字本身就不是用量。

### 2.1 原始数据按源名整文件覆盖，第二台机器必然丢数据

`collectors.save_records` 的落盘路径是 `data/local/<source>.json`，文件名只由源名决定，写入方式是整文件覆盖。`aggregate()` 又是从 `data/cloud` + `data/local` 全量重读、重算、重写 `stats.json`。

后果：在 Mac 上跑一次 local 采集，`data/local/workbuddy.json` 被今天的记录整个盖掉，昨天在 Windows 上采的 `2026-08-16` 两条记录永久消失。`stats.json` 目前只有一天数据，是这个结构的必然结果，不是数据量不够。

### 2.2 `data/cloud/` 被 gitignore，云端数据会被本地聚合抹掉

`.gitignore` 第 5 行忽略了 `data/cloud/`，所以 API 类源采到的数据从未进入仓库。一旦在某台机器上跑过 `--mode cloud` 并推送，另一台机器跑 local 时 `load_side("cloud")` 读到空目录，重算出的 `stats.json` 会把云端数据清空。

### 2.3 WorkBuddy 采集口径错误，跨天会话的增量永远采不到

`session_usage.used` 是**会话累计值**。而 `collectors/workbuddy.py` 按 `sessions.created_at` 归日，并用 `if day != date: continue` 只保留当天创建的会话。

两条组合起来：昨天创建的会话今天继续用，`used` 从 12 万涨到 30 万，这 18 万增量不会被任何一天采集到（归日看创建时间，过滤只留今天创建的）。反过来，跨三天的长会话，全部用量记在第一天。

### 2.4 时区口径在两处不一致

`update-local.sh` 用 `date -u` 取日期，`collectors/workbuddy.py` 用 `datetime.fromtimestamp()`（运行机器的本地时区）。在 UTC+8 的早上八点之前运行，两者相差一天。

### 2.5 推送没有 rebase，第二台机器直接失败

`update-local.sh` 结尾是 `git push origin main`，前面没有 `git pull`。

### 2.6 不同单位的数字被相加

`Record` 只有 `input_tokens` / `output_tokens` 两个数值槽，WorkBuddy 的积分被整体塞进 `input_tokens`（代码注释里已承认）。当前只有一个源，所以 SVG 顶部的 `187,604 tokens` 还看得过去；接入第二个源后，这个总量就是把积分、请求数和 token 加在一起，排行的百分比会被单位量级最大的源主导。

### 2.7 排行与 SVG 模板存在两份

`ranking.py` + `render.py` 和 `api/widget.py` 各有一份，原因是 Vercel 只打包 `api/` 目录。`tests/test_core.py::test_renderers_stay_in_sync` 用字符串全等把两份锁在一起。这个测试能防漏改，但它保护的是重复本身——改一次配色要动两处。

### 2.8 `session_usage.used` 不是用量，是上下文占用

在本机 `~/.workbuddy/workbuddy.db`（10 个会话，2026-06-17 至 2026-08-05）实测：

| model | used | size | used/size |
| --- | --- | --- | --- |
| hy3-ioa | 155380 | 192000 | 0.81 |
| hy3-ioa | 96715 | 192000 | 0.50 |
| auto | 48070 | **168000** | 0.29 |
| auto | 35795 | **168000** | 0.21 |

`size` 并非如现有 README 所说「恒为 192000」，它随模型变化：`hy3-ioa` 是 192000，`auto` 是 168000。这两个数字正是模型的上下文窗口大小。而 `used` 在全部 10 条记录中始终小于 `size`，比值分布在 0.18 到 0.81 之间，从未接近或越过 1。

结论：`used` 是**该会话结束时的上下文占用长度**，不是累计消耗。把它跨会话求和没有「用了多少」的含义——一个聊了 50 轮但中途压缩过上下文的会话，`used` 可能很低；一个只读了一个大文件就结束的会话，`used` 反而很高。

因此 `data/stats.json` 里现有那条 `187,604 tokens` 并不是 8 月 16 日的 token 消耗，而是当天两个会话的上下文占用之和，一个没有业务含义的数。这条要在迁移时明确作废，不能当作历史保留。

这也意味着 3.3 的快照差分不能对 `used` 做：`used` 会因上下文压缩而下降，不是单调累加量，差分出来的正增量没有意义。

### 2.9 模型名跨机器不一致，且 `auto` 不是模型

Windows 采到的模型名是 `hy3`，Mac 库里是 `hy3-ioa` 和 `auto`。同一个底层模型在两台机器上会被记成两个不同标签，模型维度的排行会被拆散。

`auto` 更是个路由别名而非模型——实际使用的模型 id 出现在 `session_usage.credit_json` 的 key 里（32 位 hex）。直接把 `auto` 当模型展示是错的。

---

## 3. 目标架构

### 3.1 三层数据

```
data/state/<machine>/<source>.json          # 采集游标：上次快照，用于差分。每台机器独立
data/raw/<machine>/<source>/<YYYY-MM>.jsonl # 增量事件，append-only，永不重写
data/stats.json                             # 产物，由 raw 全量 fold 得到
assets/widget-*.svg                         # 产物，由 stats.json 渲染
```

三条设计原则：

**路径里带 `machine`。** 两台机器写不同文件，git 层面不存在同一文件的并发修改，rebase 永远不需要手工解冲突。

**raw 只追加，不重写。** 每月一个 JSONL 文件，新事件追加在末尾，git diff 天然是纯增量。`aggregate` 退化为对 raw 的纯 fold，重跑任意次结果一致，历史永远可从 raw 完整重建。

**产物与原始数据分离。** `stats.json` 和 SVG 都是可重新生成的，不参与冲突解决（见 3.7）。

按 `<machine>/<source>/<月>` 分片，两台机器三个源一年约 72 个文件，规模可控，按月归档和裁剪也方便。

### 3.2 先确定测量什么

2.8 之后，「WorkBuddy 用了多少 token」这个问题在当前的库里没有可靠答案。三个候选字段的实测情况：

| 字段 | 语义 | 可用性 |
| --- | --- | --- |
| `session_usage.used` | 会话结束时的上下文占用 | 不是消耗量，作废 |
| `session_usage.credit_json` | `{模型id: 浮点数}`，疑似真实计费 | 10 条里只有 3 条有值，覆盖不全且规律不明 |
| `sessions` 行本身 | 会话数、模型、时间 | 完整可靠 |

`credit_json` 的样本形如 `{"26db62...":5.03,"aefa1d...":254.18}`，浮点值、按模型 id 分开，很像真实的积分消耗，而且能顺带解开 `auto` 背后的真实模型。但它只在 10 个会话中的 3 个里有值，且不呈时间规律（最新的 2026-08-05 两条没有，最早的 2026-06-17 反而有），成因未知，暂时不能作为主指标。

所以本次重构对 WorkBuddy **先测能可靠测到的东西**：

- `sessions` 数（按天、按模型、按机器）
- 会话时长（`created_at` → `last_activity_at`）
- 上下文占用峰值 `used / size`，作为一个独立的辅助指标，明确标注它是「上下文占用率」而不是用量

对应到契约，WorkBuddy 的 `unit` 取 `sessions`，`amount` 就是会话数。这个数字诚实、可加、跨机器可比，代价是失去了「token 消耗」这个更想要的口径。等 `credit_json` 的规律搞清楚（见 6.1），再把它作为第二个 unit 加进来。

不必为此惋惜：真正有 token 口径的是 OpenAI 兼容那一路，它们本来就返回准确的 input/output。多单位并存本来就是 3.5 要解决的问题。

### 3.3 快照差分：处理累计型数据源

对于确实单调累加的字段（如 `credit_json` 的积分值、或将来接入的其他累计型源），不再问「今天用了多少」，改成「和上次观测比多了多少」。会话数这类可以直接按事件时间归日的指标不需要差分。

```
采集一次（source, machine, 观测时刻 T）：
    cur  = 读 db 全量 → {session_id: (model, used)}
    prev = load_state(machine, source)

    if prev is None:                      # 冷启动
        save_state(cur, at=T)
        return []                         # 只写基线，不产出事件

    events = []
    for sid, (model, used) in cur.items():
        before = prev.get(sid, 0)
        delta  = used - before
        if delta > 0:
            events.append(Event(
                at=T, machine=machine, source=source, model=model,
                unit="credits", amount=delta,
                requests=1 if sid not in prev else 0,
            ))
        elif delta < 0:
            warn(f"{sid} 的 used 变小了（{before} → {used}），可能是 db 被重置，本次跳过")

    save_state(cur, at=T)
    return events
```

要点：

- **归日按事件的 `at` 在统一时区下计算**，与 `sessions.created_at` 无关。跨天会话被自然切分到各自那天。
- **冷启动只写基线不产出事件**。第一次在 Mac 上跑时，db 里已有的历史累计值不会被一次性算成当天用量。代价是这部分历史永久缺失，但它本来也无法归日，这是正确的取舍。
- **`used` 变小时告警并跳过**，不产生负增量。
- **`requests` 语义收紧**：只在会话首次出现时记 1，后续增量不重复计。这比现行的「每会话恒记 1」准确。真实的请求/轮次数拿不到——库里只有 `sessions` / `session_usage` / `workspaces` / `automations*` 几张表，没有任何 messages 或 turns 表，所以会话级是 WorkBuddy 能给到的最细粒度。

采集频率建议提到每小时一次（只写本地，不推送），每天推送一次。成本几乎不变，但差分粒度细 24 倍，日切不再是需要小心处理的边界。

对 API 类源（OpenAI 兼容接口），接口本身就返回区间用量，不需要差分，直接把返回结果转成事件追加到 raw 即可。但同样要落到 `data/raw/` 而不是被 gitignore 的目录。

### 3.4 事件格式

`data/raw/work-mac/workbuddy/2026-08.jsonl`：

```jsonl
{"at":"2026-08-17T09:00:00+08:00","machine":"work-mac","source":"workbuddy","model":"hy3","unit":"credits","amount":12000,"amount_in":null,"amount_out":null,"requests":1}
{"at":"2026-08-17T10:00:00+08:00","machine":"work-mac","source":"workbuddy","model":"hy3","unit":"credits","amount":3400,"amount_in":null,"amount_out":null,"requests":0}
```

`amount_in` / `amount_out` 在源能拆分输入输出时填写，不能拆分时为 `null`。这比把积分塞进 `input_tokens` 诚实。

### 3.5 单位分层

新增 `unit` 字段，取值 `tokens` / `credits` / `requests`。聚合时**按 `unit` 分桶，不跨单位求和**。

`stats.json` 契约升到 v2：

```json
{
  "schema_version": 2,
  "latest_date": "2026-08-17",
  "total_dates": 2,
  "daily": [
    {
      "date": "2026-08-17",
      "machine": "work-mac",
      "source": "workbuddy",
      "model": "hy3",
      "unit": "credits",
      "amount": 15400,
      "amount_in": null,
      "amount_out": null,
      "requests": 1
    }
  ]
}
```

顶层加 `schema_version`，让 React 组件和渲染器能识别契约漂移，而不是靠字段名沉默地对不上。`stats.schema.json` 同步更新为 v2，仍然是单一事实源。

### 3.6 machine 维度

`machine` 既是分片键，也是一条有价值的展示轴：Windows 在家、Mac 在公司，这条轴大致等于「个人时间 / 工作时间」，比现有的 ADE 维度更能说明问题。数据里始终保留，展示时默认聚合掉，需要时切换。

标识符**在 `sources.yaml` 里显式配置**，不用 `socket.gethostname()` 探测。显式的名字稳定、可读，也避免把公司内网主机名写进公开仓库。

```yaml
machine: work-mac          # 或 home-win
timezone: Asia/Shanghai    # 所有日切统一按它计算

model_aliases:             # 见下：跨机器归一
  hy3-ioa: hy3

sources:
  - name: workbuddy
    type: workbuddy
```

时区用标准库 `zoneinfo`（Python 3.12 自带），不引入新依赖。

**模型名归一。** 2.9 已确认同一模型在两台机器上的标签不同（`hy3` 与 `hy3-ioa`），不归一的话模型排行会把同一个模型拆成两行。归一表放在配置里而不是代码里，新增别名不需要改代码。

原始事件里**保留原名**，归一只在聚合阶段做。这样将来发现映射错了可以重跑修正，而不是把错误固化进 raw。

`auto`（WorkBuddy）和 `auto-smart`（Cursor）不进归一表——它们是路由别名，不是模型。

原计划把它们改标成 `auto (未解析)`，实现时放弃了：SVG 的标签列只有 112px，加后缀会被截断成更难读的样子，而 `auto` 本身对我这个唯一读者已经足够自解释。等 6.2 解出背后的真实模型 id 再处理，届时是把它们**换成真名**，而不是加注释。

### 3.7 两台机器的同步

采用文件分片 + 产物单点生成。

**机器侧**（`update-local.sh`）只负责推送自己分片的原始数据：

```
git pull --rebase --autostash origin main
git add data/state/<machine> data/raw/<machine>
git commit -m "chore(<machine>): usage raw @ <date>"
git push origin main        # 失败则重试一次 pull --rebase && push
```

因为 `data/state/` 和 `data/raw/` 的路径都以 `<machine>` 开头，两台机器改的永远是不同文件，rebase 不会产生冲突。

**产物侧**由 GitHub Actions 生成。监听 `push` 到 `data/raw/**`，跑 `aggregate` + `render`，把 `data/stats.json` 和 `assets/*.svg` 提交回 main。

这样机器永远不提交产物，产物永远由单点串行生成，冲突面归零。聚合和渲染是纯 stdlib、不需要任何 secret，public 仓库的 Actions 免费。

**无 CI 的退路**：如果不想用 Actions，机器侧改成两阶段——先提交并推送 raw，成功后本地重跑聚合渲染，再单独提交产物。冲突只可能出现在产物上，而产物遇到冲突时不需要合并，直接 `git checkout --theirs` 后重新生成覆盖即可。

### 3.8 展示层：移除 Vercel

数据一天更新一次，push 的那一刻内容就已确定；GitHub 的 camo 还会缓存图片 5 到 10 分钟。动态端点没有换来实时性，却引入了一个可能 502 的外部依赖（端点运行时从 raw.githubusercontent 拉数据，那边抽风时 README 就是裂图）。

改为 CI 在产物阶段生成静态 SVG 提交进仓库，README 直接引用：

```markdown
<img src="assets/widget-model-light.svg#gh-light-mode-only">
<img src="assets/widget-model-dark.svg#gh-dark-mode-only">
```

可以删掉：`api/`、`vercel.json`、`pyproject.toml` 里的 Vercel 配置、`api/widget.py` 中复制的排行与模板逻辑、以及锁住这份重复的 `test_renderers_stay_in_sync`。`ranking.py` / `render.py` 成为唯一实现。

损失的能力：`?date=` 和 `?theme=` 查询参数。theme 用上面的 `#gh-*-mode-only` 双图解决；`?date=` 在 README 场景没有使用者。博客的 React 组件本来就直接读 `stats.json`，不受影响，真正的交互留在它那边。

---

## 4. 混合单位的展示口径

这是本次改动里唯一还没定的展示问题。当一天内同时存在 tokens、credits、requests 三种单位时：

- 顶部汇总行按单位并列，例如 `412,003 tokens · 187,604 credits · 34 requests`，不再有单一「总量」。
- 排行的百分比只在同单位内计算。

倾向的做法：SVG 卡片按 unit 分节渲染，每节内部各自算占比；单位超过两种时只渲染前两节，其余并入汇总行。React 组件因为有 Tab，可以做得更完整。

替代方案是引入一个统一折算口径（比如按各源单价折成人民币），把所有源拉到同一标尺上。这样能恢复单一总量和全局排行，但需要维护一张价格表，且 WorkBuddy 的内部积分没有公开单价。倾向暂不做。

---

## 5. 迁移路径

每一阶段独立可用，不做一次性重写。

**阶段 0：作废现有数据，从零开始。** 原计划是迁移 `data/local/workbuddy.json` 里 `2026-08-16` 的两条记录，但 2.8 证明那两个数（128659 / 58945）是上下文占用而非消耗，迁过去只会把一个错误口径带进新库。直接丢弃，`data/stats.json` 从空开始重建。

顺带确认一个边界：Mac 库里有 2026-06-17 至 2026-08-05 共 10 个历史会话。按 3.3 的冷启动规则，首次采集只写基线、不产出事件，所以这批历史不会被一次性算成某一天的用量。它们本来也无法可靠归日，丢掉是正确的。

如果确实想要历史曲线，可以做一次性回填：按 `sessions.created_at` 把 10 个会话摊到 6 至 8 月，`unit` 记为 `sessions`。这个口径（会话数）不受 2.8 影响，是可靠的。事件里加 `backfill: true` 标记，与差分产出的数据区分开。

**阶段 1：数据层。**（已完成）引入 `machine` / `timezone` / `model_aliases` 配置、`unit` 字段、raw 新布局；WorkBuddy 采集器改为按 3.2 的口径产出会话事件；`aggregate` 改为对 raw 的 fold；契约升 v2。

**阶段 2：同步。**（已完成）`update-local.sh` 加 rebase 与重试；加 GitHub Actions 生成产物；`data/cloud/` 目录随新布局废弃。

**阶段 3：移除 Vercel。**（已完成）静态 SVG 进仓库，删 `api/` 与 `vercel.json`。

**阶段 4：把 WorkBuddy 的消耗口径找回来。** 取决于 6.1 能否解出 `credit_json` 的规律。这是目前唯一还缺的东西——Cursor 侧已经有可用口径（见 7.1）。

---

## 6. 待确认

> **已排除：两台机器的会话不重叠。** 原本担心 WorkBuddy 云端同步会话导致双重计数。实测 Mac 库有 10 个会话（2026-06-17 至 2026-08-05），Windows 那批的 `used` 值 128659 / 58945 在 Mac 库里一条都没有，模型标签也不同（Mac 是 `hy3-ioa` / `auto`，Windows 是 `hy3`）。两台机器的库是各自独立的本地文件，按 `machine` 分片安全，3.6 的 machine 维度成立。

### 6.1 WorkBuddy 整体待重做（当前已摘除）

第 2.8 节证明 `used` 不是消耗量，替代方案（只统计会话数）虽然诚实但信息量太低，不值得为它维护一个采集器和一条公开数据。**所以 WorkBuddy 采集器已从代码里摘除**，等口径想清楚再重做。

被摘除的内容：`collectors/workbuddy.py`、`sources.example.yaml` 里的源配置、`data/raw/*/workbuddy/` 下的原始数据、以及 `hy3-ioa → hy3` 的别名。实现代码可在 git 历史里找回，探查结论保留在本文 2.8 与下面的 `credit_json` 分析里。

重做的前提是先解出 `credit_json` 的规律。已知：

- 格式为 `{32位hex模型id: 浮点数}`，例如 `{"26db62...":5.03,"aefa1d...":254.18}`
- 10 个会话里只有 3 个有值
- 不呈时间规律：最新的两个 2026-08-05 会话没有值，最早的 2026-06-17 反而有

需要弄清楚：值的单位是什么（积分？人民币？），为什么大部分会话是空的（只有跨 expert / 跨模型调用才记录？只有计费模型才记录？某个版本之后才开始写？），以及 hex id 到模型名的映射从哪来。

可行的探查方式是在 WorkBuddy 里主动跑几个不同类型的会话，观察哪些会写入 `credit_json`。搞清楚之后，WorkBuddy 就能以 `credits` 为 unit 接入 3.3 的差分逻辑——`credit_json` 是累计值，这会是第一个真正需要差分的源。

顺带能解决另一件事：`sessions.model = 'auto'` 时真实模型未知，而 `credit_json` 的 key 恰好是 32 位 hex 模型 id。解出 id 到名字的映射，`auto` 就能显示成真实模型名。

### 6.2 Cursor 的路由别名 `auto-smart`

同上，`auto-smart` 是 Cursor 的自动选型，不是模型。目前原样显示。要解开它需要另找映射来源，`ai_code_hashes` 表里没有。优先级低——实测它只占 17 / 597 个请求。

### 6.3 公开仓库的信息暴露

`hy3` 是内部模型名。加上 `machine` 维度后，公开数据会包含：在用哪些内部工具、每天什么时段在工作、工作日与周末的差异。这可能是有意为之，但值得先确认公司对这类信息的口径，比事后清理 commit 历史容易。

如果需要收敛，可选的做法是给源配置一个 `public_alias`（`hy3` → `internal-model-a`），raw 保留真名并留在私有仓库，只把脱敏后的产物推到公开仓库。这会引入第二个仓库，复杂度上升，仅在确实需要时再做。

### 6.4 raw 的长期保留策略

按月分片后，一年约 72 个文件。暂不做裁剪。如果 `stats.json` 的体积成为问题（daily 行数随天数线性增长，React 组件每次要全量拉取），可以让产物只保留最近 90 天的明细，更早的数据折叠成月度汇总。等实际数据量到了再说。

---

## 7. 实现后与原计划的偏差

### 7.1 Cursor 有比预期好得多的数据源

原计划（旧 6.3）倾向走 Cursor 官方 usage 接口，因为担心本地库结构不稳。实际探查发现一个更合适的库：`~/.cursor/ai-tracking/ai-code-tracking.db`。它是 Cursor 自己用来统计「AI 写了多少代码」的库，表结构窄、字段语义明确，不需要解析 `state.vscdb`（本机 4.2 GB）里的 composer 结构。

`ai_code_hashes` 表每行是一段 AI 产出的代码，带 `requestId` / `conversationId` / `model` / `source` / `createdAt`。实测本机有 60,350 行、597 个 requestId、130 个会话、9 个模型，覆盖 2026-07-20 至 08-17。

采用的口径是**按模型的 distinct requestId 数**（`unit="requests"`）。没有选 hash 行数，因为那反映的是单次请求改了多少代码，量级受改动大小影响太大（均值约 100 行/请求）。

已核实的边界，都写进了 `collectors/cursor.py` 的模块文档：

- `requestId` 从不跨天（实测 0 例），所以一次请求只归一天，不需要差分。
- `source='human'` 的行 `requestId` 与 `model` 全为 NULL，是人工代码，整段跳过。
- `source='tab'` 的行有 `requestId` 但 `model` 为 NULL，归为 `cursor-tab`。
- 极少数 `requestId` 跨两个模型（2 / 597），在两个模型下各记一次，不做归属判定。

一个重要约束：**该库只保留最近约一个月**。好处是首次采集一次性回填了 21 天历史（比从零开始好得多）；代价是必须定期采集，否则更早的数据滚出窗口后永久丢失。

### 7.2 不需要快照差分，改成幂等的窗口重采

原计划的核心机制是快照差分（3.3），针对「只暴露累计值」的源。但实际接入的两个源都不需要它：

- Cursor 的 `ai_code_hashes` 带时间戳，可以直接按天查询。
- WorkBuddy 的会话数同样按 `created_at` 直接归日。

所以实现改成更简单的方案：每次采集重算回看窗口（默认 30 天）内的每一天，覆盖写回。这让采集天然幂等——跑一次和跑十次结果相同，补跑漏跑都能自愈，也不需要维护 `data/state/` 游标文件。3.3 的差分逻辑保留在文档里，等真的接入累计型源（比如 `credit_json`）时再实现。

对应地，原计划的 `data/state/` 目录没有创建，raw 布局简化为：

```
data/raw/<machine>/<source>/<YYYY-MM>.json
```

文件内容是 `{"days": {"2026-08-17": [事件...]}}`，写入时按天替换。「负责的那天没有用量」和「那天没被采过」因此可以区分：前者留一个空数组，旧记录会被正确清掉，不会留成幽灵。

### 7.3 单位标签需要两套中文写法

小节标题用名词（「请求」），汇总行要带量词（「14 次请求」）。中文量词的位置不能靠拼接推出来，所以 `ranking.py` 与 `types.ts` 各维护 `UNIT_LABELS` 和 `UNIT_COUNTED` 两张表。

另外发现一个冗余：只有一种单位时，小节标题和顶部汇总行显示同一个数。现在单节时省掉标题。

### 7.4 用跨语言 parity 测试替代 SVG 字符串比对

原方案里 `test_renderers_stay_in_sync` 用字符串全等锁住两份 SVG 模板，2.7 批评过它「保护的是重复本身」。移除 Vercel 后 SVG 只剩一份实现，那个测试自然消失。

但 Python 与 TS 两个渲染器的**计算口径**仍然可能漂移，这是真实风险。新增 `tests/test_parity.py`：用 esbuild 把 TS 的 `buildView` 打包成单文件，交给 node 执行，再与 Python 的 `ranking.build_view` 逐字段对比（分节顺序、每节总量、行顺序、占比到小数 9 位）。测试用例刻意覆盖多单位、跨机器、同名模型跨源、以及并列值排序这几个容易漂移的点，并额外用仓库里真实的 `stats.json` 再对一遍。

为此把 `buildView` 从 `UsageWidget.tsx` 拆到 `react/src/view.ts`——纯函数不该住在组件文件里，拆开后 node 可以直接导入，不必拉进 React。

缺 node 或 `react/node_modules` 时该测试自动跳过，不阻塞 Python 侧；CI 里把两者都装上，确保断言真的跑到。

### 7.5 配置拆成两份

原计划只提到「machine 写在 sources.yaml 里」。实现时发现一个矛盾：`model_aliases` 和 `timezone` 是聚合阶段需要的，而聚合跑在 CI 上，`sources.yaml` 又因为含 `base_url` 等本机信息被 gitignore 掉了，CI 永远读不到。

所以拆成两份：`sources.yaml`（不提交，本机采集用）与 `config/aggregate.yaml`（提交，时区与别名表）。CI 拿着仓库就能重新生成产物，不需要任何 secret。
