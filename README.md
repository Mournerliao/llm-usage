# LLM usage

> Automatic weekly token usage and model cost from my AI coding tools. Data is
> collected from Cursor's official API and local Codex session logs, then GitHub
> Actions rebuilds the card below.

<!-- WIDGET_START -->
<div>
<img src="assets/widget-light.svg#gh-light-mode-only" alt="This week's LLM usage" width="100%">
<img src="assets/widget-dark.svg#gh-dark-mode-only" alt="This week's LLM usage" width="100%">
</div>
<!-- WIDGET_END -->

This page only shows **this week**. To browse the last few weeks, use the blog
[widget](widget/), which can switch between this week and the previous three.

## About "model cost"

The amount on the card is **token usage priced at each model's unit rate**. It
shows how much compute I actually used.

It is **not a bill**: it excludes plan fees, discounts, and platform markup, and
it does not care who pays. Included-in-plan usage still counts, because this
project measures consumption, not invoices. The billed amount and markup fields
from the API never enter this repository.

## How it works

```
Cursor official API / Codex local logs → data/raw/<source>/…   (raw events, collected locally)
                → data/stats.json            (CI fold output, with four WeekViews)
                → assets/*.svg + widget      (both renderers only consume weeks[].view)
```

Collection needs a local Cursor login and the local Codex session directory
(`~/.codex`), so it only runs on the machines that produced the usage. Fold and
render are pure reductions over files in the repo, so CI can regenerate artifacts
without either machine touching them.

**Collection is idempotent**: each run re-fetches `[since, today]` and overwrites.
Running once or ten times yields the same files. Miss a few days, run again — no
duplicates. Cursor keeps the usage history on the account, so a missed local run
does not lose data.

**Artifacts are determined by data, not by the clock.** "This week" is the ISO
week of the most recent day that has usage, not the runtime calendar. The same
raw files always produce the same artifacts.

## Two machines

Cursor usage comes from an account-level API, so both machines collect the same
payload. Codex sessions exist only on the machine that produced them, so both the
work Mac and the home Windows box need to collect; files are sharded as
`data/raw/<source>/<machine>/` and do not overwrite each other.

## What is collected, and what is not

| Source | Token detail | Cost | Notes |
| --- | --- | --- | --- |
| `cursor` | input / output / cache write / cache read | yes | Official dashboard API, back to account creation |
| `chatgpt` | input / output / cache write / cache read | Subscription | Codex local session logs; ChatGPT Plus has no per-request cost |
| Relays (other Codex providers) | same | none | Stored separately from chatgpt; same model names still fold together in the view |

When a source cannot report a metric, the field is **omitted**, not filled with 0.
The view then shows a dash. "Does not report tokens" and "reported zero" are
different.

Cache reads are usually more than 90% of total tokens, so the four kinds are
always stored separately and never merged into one total.

Excluded sources, and the measurements that excluded them, are in the module docs
of `llm_usage/collect/cursor.py` and [`docs/DESIGN.md`](docs/DESIGN.md):

- Cursor's local `ai-code-tracking.db`: request counts only, no token or cost fields.
- Cursor's local `state.vscdb`: token fields have 0% coverage in the current window; leftover from an older version.
- WorkBuddy: `session_usage.used` is context occupancy, not token consumption. Showing it would mislead.

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config/sources.example.yaml sources.yaml
.venv/bin/python run.py                       # collect + fold + render
# equivalent: python -m llm_usage
```

Collection reads credentials from the local Cursor login by default. If Cursor is
signed in, nothing else is needed. On a new machine, set
`CURSOR_SESSION_TOKEN=<sub>::<jwt>` (copy the `WorkosCursorSessionToken` cookie
from a dashboard request).

Common flags:

- `--only cursor` collect one source
- `--since 2026-07-01` override the collection start
- `--skip-collect` fold and render only; this is what CI runs

For daily updates, cron / Task Scheduler can run `./update-local.sh`. It collects
and pushes raw data; CI builds the rest.

## Config is two files

| File | Committed | Contents |
| --- | --- | --- |
| `sources.yaml` | no | Collection start, each source's `base_url` and credential env var names |
| `config/aggregate.yaml` | yes | Timezone and model alias table |

They are split because the readers differ: collection runs only locally, while CI
needs the timezone and aliases to fold, and must not receive any credentials.

The alias table normalizes the same model under different labels; otherwise the
ranking splits one model into several rows. Raw events keep the original name.
Normalization happens only at fold time, so a bad mapping is fixed by re-running.

## Data contract

`stats.schema.json` is the single source of truth, currently v4. Consumers should
check `schema_version` so a semantic change cannot silently render wrong data.
Each display week carries a precomputed `view` (sort, share, display strings).
The SVG and the blog widget only render; they do not recompute.

`daily` keeps detail for the last four ISO weeks; `year` is the year-to-date
summary, **stored but not shown yet**, until a full year of data exists. Full
history always lives in `data/raw` and can be re-windowed at any time.

## Tests

```bash
.venv/bin/python tests/test_core.py
```

Design tradeoffs are in [`docs/DESIGN.md`](docs/DESIGN.md); product premises are
in [`PRODUCT.md`](PRODUCT.md).
