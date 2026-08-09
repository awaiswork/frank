# BACKLOG — Frankly

The plan for taking Frankly from a spend tracker to the app that holds the whole
financial picture: accounts, transfers, recurring items, net worth, lending, and
eventually multi-currency.

This file is the durable record. `CLAUDE.md` holds invariants that are already true of
the code; this holds what is *going* to be true, why the order is what it is, and what
was deliberately rejected. Anything decided here and later contradicted needs a reason
written down, not a quiet reversal.

Two constraints govern everything below:

1. **Home is a ten-second glance, not a dashboard.**
2. **This holds real money. Correctness beats features.** `SafeToSpend.income_known` is
   the precedent — the app refuses to state a number it cannot justify. Every surface
   added here inherits that rule.

**Working agreement:** phases ship one at a time and each leaves the app fully working.
No phase depends on a later one. Within a phase: approach → approve → schema/migration
for review → approve → implement → diff → review → tests → stop.

---

## 1. Status

| Phase | Scope | Size | Status |
| --- | --- | --- | --- |
| 0a | Foundations — period helpers, schema-drift test, two bug fixes | S | **Done** |
| 0b | Per-user timezone | S | **Done** |
| 1 | Accounts (no transfers) | M | Not started |
| 2 | Transfers + refunds | M | Not started |
| 3 | IOUs / informal lending | S | Not started |
| 4a | Recurring — templates + materialisation | M | Not started |
| 4b | Recurring — forecast into safe-to-spend | S | Not started |
| 5 | Assets + net worth trend | M | Not started |
| 6 | Weekly digest email | M | Not started |
| 7 | Income flows / allocation *(optional)* | S | Not started |
| 8 | True multi-currency | L | Not started |

---

## 2. Invariants this expansion adds

Each moves into `CLAUDE.md` as the phase that establishes it lands. They are listed
here first so the reasoning survives even if a phase slips.

- **Direction filters on `transactions.kind` are always positive equality.** Never
  `!=`, never `NOT IN`. Today all six aggregates that touch transactions are written
  `kind == "expense"` or `kind == "income"`, which is precisely why a third kind is
  excluded from every one of them without a query edit. That property is load-bearing —
  preserve it deliberately in every new aggregate.
- **Account balances are always derived.** `opening_balance_cents` is the only stored
  money-position number in the schema. A stored balance rots the first time anything is
  edited, deleted or backdated, and it rots silently.
- **A balance counts only entries on or after the account's `opened_on`.** Transactions
  logged before the ledger existed carry `account_id = NULL` and contribute to spending
  analysis only. A balance derived from an incomplete log is confidently wrong, which is
  the failure `income_known` exists to prevent, one level down.
- **A transfer is one row**, with `counter_account_id` and no category, enforced by a
  CHECK constraint. Malformed transfers are unrepresentable, not merely untested.
- **Net worth history is derived, never snapshotted.** Manually-valued assets keep an
  append-only valuation log; everything else is reconstructed from the ledger.
- **A category must not carry both a budget and a recurring template.** Both model
  "money already spoken for", and running both double-subtracts from safe-to-spend.
- **`amount_cents` always denominates the transaction's own currency.** Base-currency
  conversion arrives as additional columns, never by rewriting `amount_cents`.
- **Home is a glance.** Any addition is paired with a removal. There is no global
  account filter — Home is all-accounts, unconditionally.

---

## 3. One-way-door register

Decided 2026-08-10. Changing any of these after data accumulates is a migration with
real edge cases, not a refactor.

| # | Decision | Ruling |
| --- | --- | --- |
| 1 | Transfer representation | **One row + `counter_account_id`**, not two linked rows. Two-row makes every future aggregate a place to forget the exclusion; one row makes half a transfer impossible. |
| 2 | What `amount_cents` denominates | **The transaction's own currency.** Storing base-converted amounts there destroys the native amount irrecoverably. |
| 3 | Account balance: stored or derived | **Derived, always.** |
| 4 | Net worth history | **Derived from an append-only valuation log**, not periodic snapshots. Snapshots and a ledger that disagree cannot be reconciled after the fact. |
| 5 | Ledger start date | **`opened_on` per account; pre-existing transactions stay `account_id = NULL`.** Never backfill history onto an account whose balance cannot be verified. |
| 6 | Period definition | **Calendar months stay.** But `Budget.month` is documented as *period start*, and all boundary math goes through one helper, so payday anchoring remains possible later as a helper change rather than a migration. |
| 7 | Splits | **Shape decided, build deferred.** If splits ever happen the answer is a `transaction_lines` child table. Parent/child transactions must not be built as a stopgap — the two models are incompatible. |
| 8 | Account currency | **`accounts.currency CHAR(3) NOT NULL` from Phase 1**, constrained to the user's base currency until Phase 8. This is the only multi-currency groundwork that must land early: currency is an account's identity, and adding it later means auditing every query that silently assumed homogeneity. |

Reversible, defer freely: recurring cadence model, digest content and cadence, IOU UI,
allocation buckets, FX provider choice, investment tracking depth, whether `/more`
becomes a route.

---

## 4. Phases

### Phase 0a — Foundations · S · **done**

The safety net everything else lands on. **No migration** — see the correction below.

- All period arithmetic now comes from `aggregates.month_bounds` / `parse_month` /
  `days_in_period`. Removed `transactions._month_range` and the inline variants in
  `services/advisor.py` and `services/daily.py`. `Budget.month` is documented as
  *period start* (door 6), and `days_in_period` derives from `month_bounds` rather than
  the calendar, so re-anchoring periods stays a one-helper change.
- **`tests/test_schema_drift.py`** — runs the real migration chain against its own
  scratch database and autogenerates against `Base.metadata`, asserting an empty diff.
  Verified to fail on real drift, not merely to pass.
- Fixed archived goals leaking into `safe_to_spend`.
- Fixed the `savings_goals.archived_at` ORM/migration divergence.

**Correction to the original plan:** this was recorded as needing a migration. It did
not. Migration `0001` created `archived_at` as `timestamptz` correctly; the *model*
passed no type to `mapped_column` and inferred a naive `DateTime()` from its annotation.
The database was right and the ORM was wrong, so the fix is one type annotation. Which
is exactly the divergence the drift test exists to catch — tests build from the metadata,
production builds from the migrations, and nothing compared them.

*Risk:* low, and lower than planned with no migration involved. *Why first:* every later
phase adds migrations and period math.

Two behaviour changes, both covered by tests that were confirmed to fail beforehand:
safe-to-spend rises for anyone with an archived goal funded this month; and `days_left`
in `compute_mood` still excludes today (today's spend is already inside the burn rate) —
now pinned, because the natural rewrite of that arithmetic counts today twice and flips
moods from `go` to `wait`.

Deliberately **not** here: budget roll-forward. It is a real bug (see §6) but a product
decision, not a refactor. Also left alone: `seed_demo.py`'s three month helpers — a
standalone script with no runtime path and no coverage, so touching it is risk without
benefit.

---

### Phase 0b — Per-user timezone · S · **done**

`users.timezone` (IANA, nullable) plus `today_in(tz, *, now=None)` and the `Today`
FastAPI dependency in `app/deps.py`. **No router calls `dt.date.today()` any more** —
all eight sites take `Today`, which resolves the user's zone. A Settings picker writes
it, seeded from `Intl.supportedValuesOf('timeZone')` with the device zone detected.

Split out of Phase 0a because it is the only part needing a migration and it changes
what "today" means — a behaviour change that shouldn't ride along with a risk-free
refactor.

*Schema:* migration `0006`, one nullable column. Round-trips (`downgrade` → `upgrade`)
with the drift test still clean. No new dependency: verified `zoneinfo` resolves all 599
zones inside the real `python3.12-bookworm-slim` image, so no `tzdata` package is needed.

**Nullable rather than `NOT NULL DEFAULT 'UTC'`,** against the `currency` precedent: UTC
is a fallback, not an answer, so NULL has to keep meaning "never told us" — Phase 6 needs
that difference to know whether it can pick a send hour or must ask.

Two things worth remembering:

- **Production behaviour is unchanged; local dev behaviour is not.** The container runs
  UTC and NULL reads as UTC, so no deployed user sees a different date. But `date.today()`
  used to be *server-local*, so a developer machine off UTC now matches production
  instead of quietly disagreeing with it. A test asserting against `date.today()` caught
  exactly this.
- **`useUpdateMe` now invalidates via `invalidateMoney`,** not just `['insights']`. It had
  to: the daily note holds an hour-long `staleTime`, so a timezone (or income) change left
  it on screen contradicting the figure above it.

Accepted, not compensated for: changing zone can repeat a `daily_notes` date (the unique
constraint absorbs it) or skip one, breaking a streak. Rare and self-healing.

---

### Phase 1 — Accounts · M

Accounts exist, balances are real, a Wealth section shows them. No transfers yet.

- `accounts`: `user_id, name, type, currency CHAR(3) NOT NULL, opening_balance_cents,
  opened_on DATE, archived_at, sort_order`.
  Types: `current | savings | cash | investment | physical | liability`.
- `transactions.account_id`, nullable, `ON DELETE RESTRICT` — never `SET NULL`, which
  would silently orphan entries and corrupt balances.
- Balance = `opening_balance_cents + Σ(entries where occurred_on >= opened_on)`.
- Account CRUD and archive. `QuickAdd` gains an account picker with a remembered default.
- New `/wealth` route: accounts grouped liquid / investments / physical, each with a
  balance and a total, plus a "Ledger starts <date>" line while it still matters.
- **Reconcile:** "the real balance is X" writes an adjustment entry. `source` widens to
  include `adjustment`.

*Touches:* `models.py`, `schemas.py`, `routers/transactions.py`, new `routers/accounts.py`,
`services/aggregates.py` (balance query only — the six spend aggregates are untouched),
`QuickAdd.tsx`, `Transactions.tsx`, new `pages/Wealth.tsx`, `Layout.tsx`, `api/hooks.ts`.
*Risk:* medium — first change to the transaction write path.
*Why here:* this is the log-entry → ledger-entry semantic change. Everything downstream
assumes it.

---

### Phase 2 — Transfers + refunds · M

Money moves between accounts without corrupting a single report.

- `kind` CHECK widens to `('expense','income','transfer','refund')`; add
  `counter_account_id` and the shape constraint:

  ```sql
  CHECK (
    (kind = 'transfer'
       AND account_id IS NOT NULL
       AND counter_account_id IS NOT NULL
       AND counter_account_id <> account_id
       AND category_id IS NULL)
    OR
    (kind <> 'transfer' AND counter_account_id IS NULL)
  )
  ```

- **Refunds** are a genuine aggregate change, unlike transfers: a refund should reduce
  spend in its category rather than count as income. Two candidates — a signed `CASE` in
  the expense sums, or negative-signed companion rows. Settle at schema review; the
  existing `amount_cents > 0` CHECK forces it to be a decision rather than an accident.
- Fix `frontend/src/pages/Transactions.tsx` `net` — an `if income / else negative`
  binary, the only sign-based aggregation in the codebase, which would otherwise count
  transfers as spend.
- Resolve goal contributions vs transfers (see §6): a contribution to a goal with a
  linked savings account becomes a transfer, and `safe_to_spend` stops double-subtracting.
- Transfer UI in `QuickAdd` (from / to, no category field).

**Tests that prove it — conservation first:**

1. **Conservation.** `Σ(all account balances)` is identical before and after inserting a
   transfer of any amount between any two accounts. Property-style over generated
   amounts and pairs. One assertion that catches every double-counting bug, present and
   future.
2. **Aggregate invariance.** `safe_to_spend`, `spend_by_category`, `budget_vs_actual`,
   `daily_burn_rate` and `month_over_month_by_category` return identical results before
   and after transfers exist. The regression net for the positive-filter discipline.
3. **Shape.** Direct inserts of each malformed variant raise `IntegrityError`: transfer
   with a category, transfer to itself, transfer with a null counter, non-transfer with
   a counter set.
4. **Client net** excludes transfers.

*Risk:* **highest in the roadmap** — this is where reports corrupt silently. The
conservation test is the mitigation, and it lands before any transfer UI is merged.

---

### Phase 3 — IOUs / informal lending · S

"I lent Sam €50" in one tap, with partial repayments and a settle action.

Account types `receivable | payable` plus `counterparty_name`. A dedicated screen shows
"people I owe / people who owe me" and writes ordinary transfers underneath; these types
are hidden from the general account picker but counted in net worth, correctly, as
assets and liabilities. Partial repayments and settle fall out of the balance reaching
zero.

*Schema:* `accounts.counterparty_name` + widened type CHECK. No new tables.
*Risk:* low — UI over Phase 2 mechanics.
*Why here:* it is most of the real-world lending use, and after Phase 2 it is nearly free.

---

### Phase 4a — Recurring: templates + materialisation · M

`recurring_templates` (amount, category, account, cadence, start, optional end,
`is_variable`, `estimate_cents`) and `recurring_skips (template_id, occurrence_date)`.

Materialise-on-read, following the `GET /advisor/daily` pattern: when a month is read,
occurrences **whose date has arrived** are written as real `transactions` rows carrying
`recurring_template_id` and `source = 'recurring'`. Future occurrences are computed on
the fly and never stored.

That single choice gives the semantics for free:

- *Edit this one* → edit the materialised transaction.
- *Edit this and all future* → edit the template; past rows are real and unaffected.
- *Skip one* → a `recurring_skips` row.
- *Variable amount* → materialise the estimate, flag `needs_confirmation`, confirm on
  arrival through the existing confirm-before-commit flow.

**Double-materialisation is prevented by a constraint, not application logic:**
`UNIQUE (recurring_template_id, occurred_on)`. Two concurrent GETs cannot both insert.
Cap how far back one request will materialise so a long absence doesn't turn a single
cold-start request into hundreds of inserts.

*Schema:* `recurring_templates`, `recurring_skips`,
`transactions.recurring_template_id` + `needs_confirmation`, `source` widened.
*Risk:* medium — writes on GET.

---

### Phase 4b — Recurring: forecast · S

Not-yet-posted occurrences feed safe-to-spend.

**The double-count landmine.** `safe_to_spend` already subtracts
`remaining_budgets_cents` — money reserved inside this month's budgets. If rent is also
a recurring template, subtracting the forecast too counts rent twice and understates the
hero number. Forecast and budgets are competing models of the same thing; pick one per
category, never both.

Rule, chosen because it is explainable on screen: **budgets are for variable categories,
recurring templates are for fixed costs, and a category should not have both.** Warn at
template creation; test that safe-to-spend never double-subtracts a category carrying both.

*Risk:* medium-high — touches the hero number.

---

### Phase 5 — Assets + net worth trend · M

`assets` (`user_id, name, group ∈ physical|investment, archived_at`) and append-only
`asset_valuations (asset_id, valued_on DATE, value_cents)` with
`UNIQUE (asset_id, valued_on)`.

> **net worth on date D** = Σ(derived account balances at D)
>                         + Σ(per asset: most recent valuation with `valued_on <= D`)

A complete time series computed on read — no cron, no scheduler, no gaps, and correct
under backdated edits, which snapshots never are. "Last valued on" and the stale-valuation
flag fall out of `max(valued_on)`. Entering a valuation takes a date, so a purchase price
can be backfilled for real history from day one.

Investments stay manual. No broker integrations, no price feeds.

*Engineering caution:* a 12-point trend must be **one** query using `generate_series` and
a window function. On Neon's free tier per-query latency dominates, and twelve serial
queries behind a cold start is a visibly slow screen.

*Note:* no charting library is installed — the existing charts are hand-rolled SVG and a
sparkline should be too. Adding one is a conversation, not an assumption.

---

### Phase 6 — Weekly digest email · M

Per-type notification preferences; a signed unsubscribe token that works without login;
send in the user's timezone (Phase 0's column); `POST /internal/digest/run` protected by
a shared secret and hit by a weekly GitHub Actions cron; a `last_sent_at` guard that
makes a double send impossible even when the cron fires twice.

Content — worth opening only because Phase 4 exists: spend vs last week, top categories,
budget pace, goal progress, **what lands next week**, one Frank observation. Not a nag.

*Risk:* medium. This is the first token-protected endpoint and the first unauthenticated
state-changing surface in a deliberately closed auth system; it deserves the same care
the OTP work got. GitHub's scheduler is best-effort, skews under load, and disables
scheduled workflows after 60 days without a push — `keep-warm.yml` already documents this
and a weekly job inherits it more visibly.

---

### Phase 7 — Income flows / allocation · S · optional

Per-account income history, and an allocation view (fixed / savings / discretionary) via
a `bucket` column on categories. Low information gain — most people can predict the
answer. Pull it forward only if the Wealth section leaves a real hole.

---

### Phase 8 — True multi-currency · L

`currency`, `base_amount_cents` and `fx_rate` on transactions (door 2); base currency on
users; an `fx_rates` table fed daily from Frankfurter/ECB via the same cron, with
graceful fallback to the last known rate; manual per-transaction rate override, because a
bank's real rate never matches mid-market.

**The FX rate is stored at transaction time. Historical totals are never recomputed.**

Backfill is clean and honest: everything captured while single-currency gets
`currency = base`, `fx_rate = 1.0`, `base_amount_cents = amount_cents`. That is not a
guess, it is the truth.

The real cost is on the frontend: `formatMoney` hardcodes `€`, there are eight more
literal `€` in JSX plus the CSV header, and `Intl.NumberFormat` is not used anywhere.
That is a frontend-wide sweep, not a backend feature.

*Why last:* it is the deepest change, and nothing in Phases 0–7 forces a decision that
makes it painful — provided doors 2 and 8 hold.

---

## 5. Cut and deferred — with reasons, so it isn't re-litigated

- **Display-only currency conversion.** Cut. Converting historical totals at today's rate
  produces a number that looks authoritative and is wrong — the same class of failure as
  a safe-to-spend with no income. Go straight to true multi-currency when it's needed.
- **Payday-anchored months (25th → 24th).** Cut. It reads as small and is not: it changes
  the meaning of `Budget.month`, which has stored rows and a unique constraint behind it,
  plus `month_bounds`, `parse_month`, `_elapsed_fraction`, the `date_trunc('month')`
  window function, `daily_notes.note_date` uniqueness, `MonthSwitcher` and `lib/date.ts`.
  Every aggregate, for an aesthetic gain. Door 6 keeps it possible later at helper cost.
- **Formal amortizing loans (mortgage, car).** Deferred, and deferring is genuinely free:
  a mortgage is a liability account (Phase 1) + a recurring transfer (Phase 4) + an
  interest/principal split. The amortization schedule is derivable from principal, rate
  and term and needs no historical storage. No schema is broken by waiting.
- **Splits.** Deferred; shape decided (door 7).
- **Pending vs cleared.** Skipped. With manual entry the reconcile action covers the same
  drift more cheaply.
- **Bank / open-banking integration, price feeds, broker integrations.** Out of scope.
- **A persistent global account switcher.** Rejected. A sticky filter makes every number
  on every screen ambiguous — someone leaves it on "Current", reads a safe-to-spend that
  excludes their savings, and gets no signal they are looking at a slice. Account
  filtering lives on Activity as a visible, non-sticky chip row, and inside Wealth.

---

## 6. Known pre-existing bugs

Independent of this expansion, but several get worse once accounts exist.

| Issue | Detail | Fixed in |
| --- | --- | --- |
| Goal contributions are structurally double-countable | A contribution writes a `goal_contributions` row and **no transaction**, yet `safe_to_spend` subtracts `goal_contributions_cents`. Log the real bank transfer as an expense too and the same money is subtracted twice. | Phase 2 |
| Budgets do not roll forward | Nothing copies limits into a new month and `budget_vs_actual` matches `Budget.month` exactly, so on the 1st `remaining_budgets_cents` sums zero rows and **safe-to-spend jumps by the entire previous month's unspent allowance**. A live honesty bug on the hero number. | Unscheduled — needs a product decision (copy last month? prompt?) |
| Archived goals leak into safe-to-spend | `aggregates.safe_to_spend`'s goal term filters only `user_id` and the date window. Every other goal query excludes archived. | Phase 0a |
| Month-over-month `LAG` is not calendar-aware | `LAG` orders over *rows that exist*, so "previous month" means "the previous month that had spend in that category". A gap month produces a misleading delta. | Unscheduled |
| `savings_goals.archived_at` ORM/migration drift | The model passes no type and infers naive `DateTime()`; the migration created `timestamptz`. Tests build from ORM metadata, production from migrations, so the two disagree. | Phase 0a |
| Month arithmetic implemented six times | `aggregates.month_bounds`, `transactions._month_range`, `advisor.py`, `daily.py`, `_elapsed_fraction`, and three more in `seed_demo.py`. The frontend has its own in `lib/date.ts`, mixing UTC and local. | Phase 0a for every runtime path. `seed_demo.py` (standalone script, no coverage) and the frontend's `lib/date.ts` are still separate — unscheduled. |
| No per-user timezone | `dt.date.today()` is server-local in eight places and decides the daily note's date, the streak, the burn window and the default month. | Phase 0b |
| Migrations are never proven to match the models | Tests build the schema from `Base.metadata.create_all`; CI separately proves migrations *apply*. Nothing checks they agree. | Phase 0a |

---

## 7. Free-tier constraints

| Concern | Reality |
| --- | --- |
| A second service or worker | Not affordable. Keep-warm consumes roughly 744 of Render's 750 free instance-hours. Everything scheduled must be an endpoint on the existing API, hit by GitHub Actions. |
| Materialise-on-read writes | Writes on GET against Neon free. Fine at this scale, given the lookback cap in Phase 4a. |
| Net worth trend | Latency-bound, not CPU-bound. One `generate_series` + window query, never twelve round trips. |
| Cron reliability | GitHub's scheduler is best-effort, skews under load, and disables schedules after 60 days without a push. Acceptable weekly, given `last_sent_at`. |
| Query cost | `GET /advisor/daily` already re-runs the full context on *every* read — budgets, safe-to-spend, burn rate, goals — and caches only the note text. Accounts and forecast add to that same path. Watch it rather than assuming headroom. |
| Build minutes | Not binding (~2–3 min per build, 500/month). Instance-hours are the constraint. |
| New dependencies | None assumed anywhere in this roadmap. Timezones use stdlib `zoneinfo`; FX needs no SDK (`httpx` is already a direct dependency); a sparkline is hand-rolled SVG like the existing charts. Any exception is a conversation first. |

---

## 8. Verification, per phase

- `cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`
- `cd backend && uv run alembic upgrade head` against a scratch database, then
  `alembic downgrade` back, then the Phase 0 drift assertion.
- `cd frontend && npm run build && npm test && npm run lint && npm run format:check`
  (typecheck is `npm run build`; `npx tsc --noEmit` is a false green here).
- `./dev.sh`, then exercise the phase's flow by hand at **320px** and at desktop.
- Phase 2 specifically: conservation and aggregate-invariance tests pass before any
  transfer UI merges.
- PR preview check — noting that a Vercel preview points at **production**
  `VITE_API_URL`, so preview writes are real data and migrations are never tested through one.
