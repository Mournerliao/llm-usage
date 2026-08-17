"""Cursor 采集器：走官方 dashboard 用量接口，拿逐次请求的 token 明细与折算成本。

== 为什么不用本机数据库 ==

本机有两个候选库，都实测排除了：

``~/.cursor/ai-tracking/ai-code-tracking.db`` 只记「AI 写了多少代码」，有 requestId
和模型，但没有任何 token 或成本字段，最多只能数出请求数。

``state.vscdb`` 的 ``cursorDiskKV`` 里确实有 token 字段，但覆盖率为零：69,433 条带
``tokenCount`` 的 bubble 中只有 516 条非零（0.7%），且这 516 条里只有 1 条带
``requestId``，与 ai-code-tracking 库当前窗口的 600 个 requestId 交集为 0。换句话说
它们是旧版本 Cursor 留下的残留，当前时段的 token 覆盖率是 0%。同一个库里的
``composerData.usageData.costInCents`` 同样是遗留字段：3,147 个会话里只有 28 个有值
（0.9%），且全部停在 2025-10。

所以本机拿不到 token 和成本，唯一的真实来源是账号级的官方接口。

== 接口 ==

``POST /api/dashboard/get-filtered-usage-events``，用本机 Cursor 登录态的 session
cookie 认证。它是 dashboard 用量页背后的接口，返回逐次调用的记录：

    timestamp, model, kind,
    tokenUsage { inputTokens, outputTokens, cacheWriteTokens, cacheReadTokens,
                 totalCents },
    chargedCents, cursorTokenFee, conversationId, owningTeam, owningUser

三个已核实的性质：

- **账号级**。两台机器的用量都在同一份返回里，所以采集不按机器分片，在哪台机器上
  跑都一样。
- **可按任意区间查询**，因此每次重采 [since, 今天] 全量覆盖写回，采集天然幂等。
- **能回溯到账号开通日**（本账号为 2026-04-09），不像本机库只留最近一个月。

== 成本口径 ==

只取 ``tokenUsage.totalCents``，即 token 按各模型单价折算出的成本，落盘字段名
``cost_cents``。

刻意不取另外两个：``chargedCents`` 是实际计费额（含 Cursor 抽成），
``cursorTokenFee`` 是抽成本身。本账号是企业账号、账单挂在公司 team 下，而本仓库是
公开的，所以计费额与套餐信息不进入任何提交物。折算成本反映的是「用掉了多少算力」，
和账单无关，可以公开。

同理，事件里的 ``conversationId`` / ``owningTeam`` / ``owningUser`` 不落盘——聚合到
(日期, 模型) 粒度后它们自然消失。

== kind 的处理 ==

接口返回五种 kind，实测分布与处理方式：

    USAGE_BASED             4239 条  按量计费，计入
    INCLUDED_IN_BUSINESS    1971 条  企业套餐内，有真实 token 与折算成本，计入
    FREE_CREDIT               17 条  赠送额度，有 token，计入
    ERRORED_NOT_CHARGED       97 条  出错未计费，token 与成本均为空，跳过
    ABORTED_NOT_CHARGED       10 条  中止未计费，同上，跳过

前三种都是真实发生的算力消耗，区别只在谁付钱，而本项目量的是消耗不是账单，所以
一并计入。后两种没有产生任何 token，计入会虚增请求数。
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from . import CollectResult, Event

API_HOST = "https://cursor.com"
USAGE_ENDPOINT = "/api/dashboard/get-filtered-usage-events"
PAGE_SIZE = 500
MAX_PAGES = 200

# 没有产生 token 的 kind，计入会虚增请求数。
SKIP_KINDS = {
    "USAGE_EVENT_KIND_ERRORED_NOT_CHARGED",
    "USAGE_EVENT_KIND_ABORTED_NOT_CHARGED",
}

STATE_DB_CANDIDATES = (
    "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb",          # macOS
    "~/AppData/Roaming/Cursor/User/globalStorage/state.vscdb",                      # Windows
    "~/.config/Cursor/User/globalStorage/state.vscdb",                              # Linux
)


# ------------------------------------------------------------------------ 认证

def _jwt_payload(token: str) -> dict:
    """解出 JWT 的 payload。只用来读 sub 和 exp，不验签——签名由服务端验。"""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    body = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(body))
    except Exception:
        return {}


def _read_local_session() -> tuple[str, str] | None:
    """从本机 Cursor 的 state.vscdb 里读出 access token 与用户 sub。

    以 ``immutable=1`` 打开：这个库有几 GB，不能复制，而宿主 Cursor 正持有它并以 WAL
    模式写入，只读模式打开需要对 -wal/-shm 有写权限。immutable 会忽略 WAL 中尚未
    checkpoint 的部分，对 ``ItemTable`` 里这类极少变动的键没有影响。
    """
    for candidate in STATE_DB_CANDIDATES:
        path = Path(os.path.expanduser(candidate))
        if not path.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
            con.text_factory = lambda b: b.decode("utf-8", "replace")
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'"
                ).fetchone()
            finally:
                con.close()
        except Exception as exc:
            print(f"[warn] 读取 {path} 失败: {exc}")
            continue
        if not row or not row[0]:
            continue
        token = str(row[0]).strip().strip('"')
        payload = _jwt_payload(token)
        sub = payload.get("sub")
        if not sub:
            continue
        exp = payload.get("exp")
        if exp and exp < time.time():
            print(f"[warn] {path} 里的登录态已于 "
                  f"{time.strftime('%Y-%m-%d', time.localtime(exp))} 过期")
            continue
        return sub, token
    return None


def _session_cookie(cfg: dict) -> str:
    """组出接口需要的 session cookie。

    优先用环境变量（CI 或换机时不必依赖本机 Cursor 安装），否则读本机登录态。
    环境变量名可在源配置里改，默认 ``CURSOR_SESSION_TOKEN``，值的格式是
    dashboard 请求里的 ``WorkosCursorSessionToken``，即 ``<sub>::<jwt>``。
    """
    env_name = cfg.get("token_env", "CURSOR_SESSION_TOKEN")
    raw = os.environ.get(env_name)
    if raw:
        raw = raw.strip()
        if "::" in raw:
            sub, token = raw.split("::", 1)
        else:  # 只给了 JWT，从中取 sub
            token = raw
            sub = _jwt_payload(token).get("sub", "")
            if not sub:
                raise SystemExit(f"{env_name} 不是有效的 JWT，也没有 <sub>::<jwt> 前缀")
    else:
        found = _read_local_session()
        if not found:
            raise SystemExit(
                "拿不到 Cursor 登录态。要么在本机登录 Cursor（采集器会从 "
                "state.vscdb 读取），要么设置环境变量 "
                f"{env_name}=<sub>::<jwt>（值可从 dashboard 请求的 "
                "WorkosCursorSessionToken cookie 里复制）。")
        sub, token = found

    quoted = urllib.parse.quote(sub, safe="")
    return f"WorkosCursorSessionToken={quoted}%3A%3A{token}"


# ------------------------------------------------------------------------ 拉取

def _post(path: str, body: dict, cookie: str) -> dict:
    req = urllib.request.Request(API_HOST + path, method="POST")
    # Origin 与 Referer 是必需的：接口对状态变更类请求做同源校验，缺了会返回
    # 403 "Invalid origin for state-changing request"，即使 cookie 完全正确。
    for key, value in (
        ("Content-Type", "application/json"),
        ("Cookie", cookie),
        ("Origin", API_HOST),
        ("Referer", f"{API_HOST}/dashboard"),
    ):
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, json.dumps(body).encode(), timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        if exc.code in (401, 403):
            raise SystemExit(
                f"Cursor 接口拒绝了请求（HTTP {exc.code}）：{detail}\n"
                "登录态可能已过期，重新登录 Cursor 后再试。") from exc
        raise SystemExit(f"Cursor 接口返回 HTTP {exc.code}：{detail}") from exc


def fetch_events(cookie: str, start_ms: int, end_ms: int) -> list[dict]:
    """翻页拉取区间内的全部用量事件。"""
    events: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _post(USAGE_ENDPOINT, {
            "teamId": 0,
            "startDate": str(start_ms),
            "endDate": str(end_ms),
            "page": page,
            "pageSize": PAGE_SIZE,
        }, cookie)
        batch = payload.get("usageEventsDisplay") or []
        events.extend(batch)
        total = int(payload.get("totalUsageEventsCount") or 0)
        if not batch or len(events) >= total:
            break
    return events


# ------------------------------------------------------------------------ 翻译

def to_events(raw: list[dict], day_of, source: str = "cursor") -> list[Event]:
    """把接口返回翻译成 ``Event``，按 (日期, 模型) 聚合。

    纯函数（``day_of`` 负责时区），因此可以拿固定的接口返回样本单测，不需要网络。
    """
    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"requests": 0, "tokens_in": 0, "tokens_out": 0,
                 "cache_write": 0, "cache_read": 0, "cost_cents": 0.0})

    for row in raw:
        if row.get("kind") in SKIP_KINDS:
            continue
        usage = row.get("tokenUsage") or {}
        key = (day_of(int(row["timestamp"])), row.get("model") or "unknown")
        bucket = buckets[key]
        bucket["requests"] += 1
        bucket["tokens_in"] += int(usage.get("inputTokens") or 0)
        bucket["tokens_out"] += int(usage.get("outputTokens") or 0)
        bucket["cache_write"] += int(usage.get("cacheWriteTokens") or 0)
        bucket["cache_read"] += int(usage.get("cacheReadTokens") or 0)
        bucket["cost_cents"] += float(usage.get("totalCents") or 0.0)

    events = [
        Event(
            date=date,
            source=source,
            model=model,
            requests=bucket["requests"],
            tokens_in=bucket["tokens_in"],
            tokens_out=bucket["tokens_out"],
            cache_write=bucket["cache_write"],
            cache_read=bucket["cache_read"],
            # 折算成本保留四位小数：单次调用常在一分以下，过早取整会让求和偏小。
            cost_cents=round(bucket["cost_cents"], 4),
        )
        for (date, model), bucket in buckets.items()
    ]
    events.sort(key=lambda e: (e.date, e.model))
    return events


def collect(ctx, cfg: dict, *, fetch=None) -> CollectResult:
    """拉取并翻译，同时给出本次采集「负责」的日期范围。

    ``fetch(start_ms, end_ms) -> list[dict]`` 是远端 adapter。默认走官方接口；
    测试传入 fixture，不必碰网络或登录态。

    负责范围从**最早一条事件所在的那天**算到今天，而不是从配置的 ``since`` 算起。
    区别在于：账号开通之前的日子根本不可能有数据，把它们也列入负责范围只会在 raw
    里生成一堆全是空数组的月份文件。范围内确实没有用量的那天仍然会留空数组，那是
    有意义的「采过，没有用量」。
    """
    if fetch is None:
        cookie = _session_cookie(cfg)

        def fetch(start, end, _cookie=cookie):
            return fetch_events(_cookie, start, end)
    raw = fetch(ctx.since_ms(), int(time.time() * 1000))
    events = to_events(raw, ctx.day_of, cfg.get("name", "cursor"))

    kept = sum(1 for r in raw if r.get("kind") not in SKIP_KINDS)
    print(f"[cursor] 接口返回 {len(raw)} 条事件（计入 {kept} 条）"
          f" → {len(events)} 条日模型记录，起点 {ctx.since}")

    if not events:
        return CollectResult(events=[], days=[], machine_shard=False)
    return CollectResult(
        events=events,
        days=ctx.days_between(min(e.date for e in events), ctx.today()),
        machine_shard=False,
    )
