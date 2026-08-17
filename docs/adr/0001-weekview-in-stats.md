# WeekView 写进 stats.json，渲染器不再各算一份

v3 用 Python `ranking.build_week_view` 与 TS `buildWeekView` 两份函数锁同一口径，靠 parity 测试防漂移。改一次格式化要动三处。v4 把四周视图在 fold 时算一次，写入 `weeks[].view`；SVG 与 widget 只读产物。代价是 `limit` 等展示参数在聚合时钉死，不能再由 widget 运行时改。
