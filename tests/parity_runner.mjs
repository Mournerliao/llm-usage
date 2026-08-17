// 供 tests/test_parity.py 调用：从 stdin 读 { daily, cases }，
// 用 TS 侧的 buildWeekView 算出每个 case 的视图，以 JSON 写回 stdout。
//
// 单独一个 runner 而不是在 Python 里重写一遍 TS 逻辑，是因为这个测试的意义正是
// 「跑真的那份 TS 代码」——重写一遍就只能证明重写本身是对的。

import { buildWeekView } from "../react/src/view.ts";

const input = JSON.parse(await new Promise((resolve, reject) => {
  let buf = "";
  process.stdin.setEncoding("utf-8");
  process.stdin.on("data", (chunk) => (buf += chunk));
  process.stdin.on("end", () => resolve(buf));
  process.stdin.on("error", reject);
}));

const out = input.cases.map(({ week, limit }) =>
  buildWeekView(input.daily, week, limit, input.subscription_sources ?? []),
);

process.stdout.write(JSON.stringify(out));
