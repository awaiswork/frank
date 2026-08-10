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
| 1 | Accounts (no transfers) | M | **Done** |
| 2a | Transfers | M | **Done** |
| 2b | Refunds + reconcile | M | **Done** |
| 3 | IOUs / informal lending | S | **Done** |
| 4a | Recurring — templates + materialisation | L | **Done** |
| 4b | Recurring — forecast + skip | M | **Done** |
| 5 | Assets + net worth trend | M | **Done** |
| 6 | Weekly digest email | L | **Done** |
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

### Phase 1 — Accounts · M · **done**

Accounts exist, balances are real, a Wealth section shows them. No transfers yet.

**Three corrections to what was planned here:**

- **Reconcile moved to Phase 2.** It was recorded as widening `source`. That was wrong:
  `source` is provenance and no aggregate reads it. An adjustment moves a balance while
  being neither income nor expense, so it needs a **`kind`** — and it inherits exactly
  the double-counting problem transfers have. It belongs where the conservation test
  already guards that.
- **`physical` and `investment` are not account types.** An account has a *ledger*
  (entries move it); an asset has *valuations* (you state what it is worth). A car has no
  ledger. Types are `current | savings | cash | liability`, and Phase 5 owns valued
  things. Investments are genuinely dual-natured — contributions *and* market movement —
  which is a decision for the phase that is about it, not one to smuggle in here.
- **`sort_order` cut.** Ordered by type then name; a reorder UI can come later.

- `accounts`: `user_id, name, type, currency CHAR(3) NOT NULL, opening_balance_cents,
  opened_on DATE, archived_at, sort_order`.
  Types: `current | savings | cash | investment | physical | liability`.
- `transactions.account_id`, nullable, `ON DELETE RESTRICT` — never `SET NULL`, which
  would silently orphan entries and corrupt balances.
- Balance = `opening_balance_cents + Σ(entries where occurred_on >= opened_on)`.
- Account CRUD and archive. `QuickAdd` gains an account picker with a remembered default.
- New `/wealth` route: accounts grouped liquid / investments / physical, each with a
  balance and a total, plus a "Ledger starts <date>" line while it still matters.
**The balance is the first sign-based aggregation on the server**, and so the first place
a new kind can be silently mishandled: a `CASE … ELSE 0` contributes *nothing* for a kind
nobody remembered, so a transfer would move no money and the balance would just be wrong.
`services/accounts.BALANCE_SIGNS` is the single source of that CASE, and
`test_balance_signs_cover_every_kind` reads the permitted values straight out of the
`ck_transactions_kind` constraint. Widening that CHECK in Phase 2 fails the suite until
someone decides what the new kind does to a balance. Verified to fail, not merely to pass.

*Schema:* migration `0007` — `accounts` plus a nullable `transactions.account_id` with
`ON DELETE RESTRICT`, deliberately unlike `categories`' SET NULL: losing a category costs
a label, losing an entry costs money out of a balance with nothing on screen to explain
it. Purely additive, no backfill, round-trips down and up with the drift test clean.

Checked in a browser rather than only in tests: Wealth and the capture picker at 320px and
at desktop, negative balances rendering in `--over`, no console errors.

**Known rough edge:** in the capture sheet the account chips and the category chips are
two adjacent unlabelled pill rows, distinguished only by the category dots. Fine with
three accounts; worth revisiting with more.

---

### Phase 2a — Transfers · M · **done**

Split from refunds on risk profile, and the split earned itself: **transfers touch no
existing aggregate** — all six filter `kind` positively, so a third value is excluded
for free — while **refunds touch all six**. Keeping them apart is what let 2a assert
that every spending figure is byte-identical with transfers present, an assertion
simply unavailable if refunds rewrote those same queries in the same diff.

One row with `counter_account_id`, not a matched pair, guarded by
`ck_transactions_transfer_shape`: both ends present, different, and no category, so a
transfer can never reach a budget however the row is written.

**The balance query was rebuilt around legs, and that was the real work.** `LEG_SIGNS`
maps a kind to what it does to its own account *and* to a counter account, because a
transfer's effect depends on which account is being asked about. The flat `{kind: sign}`
map from Phase 1 could not express that, and its natural-looking fix — `"transfer": -1`
— takes money out of the source and puts it nowhere. That variant fails 7 tests,
including every conservation case; verified rather than assumed. Note the *guard* test
still passes there. It forces a decision; conservation checks the decision was right.

A transfer emits −x and +x, so conservation is a property of the query's shape rather
than something anyone has to remember.

*Schema:* migration `0008` — `counter_account_id` (`ON DELETE RESTRICT`), widened kind
CHECK, and the shape CHECK. Additive; existing rows satisfy it with no backfill.
Round-trips down and up with the drift test clean.

**A bug caught in design rather than in production:** `has_entries` looked only at
`account_id`, so an account that had only ever *received* transfers looked empty and
was offered for a deletion the RESTRICT foreign key would then refuse — a 500 where
the user deserved a sentence.

On the client, `lib/net.ts` replaces the `income ? +x : -x` reducer that would have
counted every transfer as spending. `Record<TransactionKind, number>` makes the
compiler refuse an unhandled kind, which is the type-level twin of the server guard —
and `net.test.ts` is its behavioural twin, since the type catches an *omitted* kind but
not a *wrong* sign.

Checked in a browser at 320px: "from Everyday to Savings" reads on one line, categories
disappear for a transfer, the destination list excludes the source, and a day of
nothing but moves nets `+0,00 €`.

**Deliberately not here:** goal contributions still write no transaction, so
`safe_to_spend` can still double-subtract if the bank move is also logged. Transfers do
not make it worse — they are excluded from safe-to-spend — and linking goals to accounts
is its own change, not one to bundle with a balance-query rewrite.

---

### Phase 2b — Refunds + reconcile · M · **done**

The first change to rewrite the spending aggregates. Five of the six now sign their
sums through one helper (`SPEND_SIGNS` + `_spent()` + `_is_spend()`) rather than five
copies of the rule.

**A refund is a negative expense, not income.** It gives back the category's spend, the
budget's allowance and the burn rate, and leaves what someone earned alone — logged as
income it would inflate earnings *and* raise safe-to-spend, counting the money twice.
Stored as a positive magnitude with direction in the kind, the pattern the schema
already uses. Rejected: negative-amount expenses, which need no aggregate changes at
all but relax `amount_cents > 0` for every row.

**The invariant needed restating, and that is the durable result of this phase.**
"Positive equality" was too narrow once filters became `IN ('expense','refund')`. The
real property is: **allow-list, never deny-list.** `!= 'income'` selects the same rows
today and diverges the moment a kind is added. `test_spend_signs_are_an_allow_list`
asserts the partition — which kinds are spending, which are deliberately outside every
figure — so a new kind has to declare its side. Verified: swapping the allow-list for
`!= 'income'` fails three tests.

**Reconcile writes a visible correction**, as `adjustment_up` / `adjustment_down`. Two
kinds rather than one signed amount keeps `amount_cents > 0` intact. Rejected: quietly
editing `opening_balance_cents`, which needs no migration but makes "the balance at the
start of `opened_on`" false, silently moves every past balance, and leaves nothing on
screen to say a correction happened. The form states the correction it will write
before writing it, and the row appears in Activity.

*Schema:* migration `0009` — widened kind CHECK, plus `source` gaining `reconcile`
(provenance only; no aggregate reads it). Additive, round-trips.

**Caught by measuring rather than assuming:** the refund row action was `opacity-0` but
still reserved 38px, and on a 320px row that came straight out of the merchant name —
"jacket" rendered as "j…". Now `hidden` below `sm`, where there is no room for it
anyway. The four-segment capture row, which I expected to overflow at 320px, fits.

Checked end to end in a browser: a €40 jacket refunded leaves spend at 0, income
unchanged at 320000, the balance restored, and the day's net at `+0,00 €`.

**Known gap:** row actions (Refund, and the pre-existing Delete) are hover-only, so
they are desktop-only. A standalone refund is reachable on a phone through the capture
sheet's Refund mode; deleting on a phone was already unreachable and remains so.

---

### Phase 3 — IOUs / informal lending · S · **done**

"I lent Sam €50", with partial repayments and settling. The smallest phase so far,
because an IOU is a transfer between one of your accounts and a person's — conservation,
the shape constraint and the exclusion from every spending figure all arrived already
built from 2a.

**Two corrections to what was planned, both shrinking it:**

- **One account type, not a `receivable`/`payable` pair.** The direction is the sign of
  the balance. A pair cannot represent having lent Sam 50 *and* borrowed 80 from Sam —
  that is one relationship worth −30, and a pair leaves two accounts for one person that
  a reader has to net in their head. Grouping by sign is also truer than grouping by a
  label chosen at creation: a balance cannot go stale.
- **No `counterparty_name` column.** The account's `name` is the person. A second field
  would have to agree with the one beside it forever.

So the schema change is one CHECK value — migration `0010`, nothing else.

**The latent bug this would have hit.** `Wealth.tsx` mapped over a list of groups and
filtered by type, so an account whose type was in no group rendered **nowhere** while
still counting toward the total — the rows would have stopped adding up to the figure
above them with nothing on screen to say why. TypeScript did not catch it: the list
shape compiled fine. It is now an exhaustive `switch` with a `never` fallthrough, so a
new account type fails the build until it is placed. Verified by adding a fake type.

**Caught by a test rather than in review:** the endpoint created the person *before*
validating the source account, so a failure left a half-made person behind. Nothing
committed, so the session discarded it — but "no orphan survives" resting on transaction
semantics is thin. It now validates everything before writing anything.

Checked end to end: lend Sam 50, borrow 80 back, lend Alex 25, settle Alex. Sam nets to
one balance of −30, the total never moves off 1000,00 €, no spending figure changes, and
the visible Wealth rows sum to exactly the displayed total.

Person accounts are filtered out of the capture sheet — you do not buy coffee "from Sam".

---

### Phase 4a — Recurring: templates + materialisation · L · **done**

Rent stops needing typing. A template describes the schedule; occurrences whose date
has arrived become **ordinary transactions**, so spending, budgets, balances and the
daily note see them without knowing they were generated. Nothing in the future is
stored, and nothing counts as spent before it has been.

**Sized L, not M** — the backlog was optimistic. Two schema objects, date arithmetic, a
write-on-read service with concurrency handling, a dependency plus its coverage test, a
CRUD router and a screen, even after the cuts below.

**Two things cut, one for a reason worth keeping:**

- **Variable amounts.** Materialising an estimate creates a row that *looks* like a
  transaction and isn't — it would land in `spend_by_category`, the burn rate and
  safe-to-spend at a number the app **guessed**. That is the app asserting a figure it
  does not know, which is what `income_known` exists to prevent one level down. A
  design problem, not a bolt-on.
- **Skip.** Skipping a future occurrence barely shows until forecasting exists, and
  "this one didn't happen" is already covered by deleting the row. It belongs with 4b.

**`last_materialised_on` is the design.** Asking the transactions table "is there a row
for this date?" would resurrect an entry the user deleted, on their next page load, for
ever. Generation only ever moves forward from that column, so a deleted row stays
deleted — verified by sabotage, and by deleting a July rent and hammering every money
route. It is also what keeps this cheap: the ordinary case is one indexed read
returning nothing.

The **partial unique index** is the separate concern — two requests reading the same
stale value would both insert; the database refuses the second.

**Writes on GET, and a test so a route cannot be forgotten.** Materialised rows must
exist before any money figure is computed, which is four routers plus the recurring
list itself (its `next_on` is derived from how far generation has reached). A helper
called in five places is four places to forget, so it is a dependency and
`test_every_money_route_is_up_to_date` asserts every one of them declares it. Verified
by removing it from `/insights/summary`.

**Semantics that cost nothing.** Generated rows are ordinary transactions and generation
only runs to today, so "edit this one" is editing a transaction and "edit this and all
future" is editing the template — rows already written keep what was actually paid.
`ON DELETE SET NULL` on the link, unlike `account_id`'s RESTRICT: deleting a template
must not delete rent that really left.

**Month-end clamping tracks the anchor**: the 31st becomes the 28th in February and
returns to the 31st in March, rather than drifting down and staying there.

*Schema:* migration `0011` — `recurring_templates`, `transactions.recurring_template_id`,
the partial unique index, `source` gaining `recurring`. Additive, round-trips.

**Worth knowing:** a backdated template generates its history, and those rows are dated
before a new account's `opened_on`, so they count as spending but not against the
balance. That is the Phase 1 ledger rule working correctly — the opening balance already
reflects them — but it reads as surprising the first time.

---

### Phase 4b — Recurring: forecast + skip · M · **done**

Upcoming recurring expenses are held back from safe-to-spend, and one occurrence can be
skipped before it happens.

**The rule this backlog proposed was wrong, and got replaced rather than added.** It
said a category must not carry both a budget and a recurring template, warned about at
creation. But a Bills budget of 900 covering a fixed 800 rent *and* a variable water
bill is entirely reasonable, and that rule forbids it — while only ever being a warning,
so the double count stayed reachable anyway.

The correct answer is arithmetic, not policy: **`max(budget_remaining, upcoming)` per
category**, never the sum.

| Situation | Budget left | Still to come | Reserved | Why |
| --- | --- | --- | --- | --- |
| Bills budget covers the rent | 900 | 800 | **900** | the budget already accounts for it |
| Rent, no budget | — | 800 | **800** | the rent happens anyway |
| Budget set too low | 100 | 800 | **800** | the rent ignores the limit written down |

No user-facing rule, no warning, nothing to maintain. Verified by sabotage — summing
instead of maxing fails with `assert 170000 == 90000`, exactly the month's rent — and
live: adding an 800 rent inside a 900 Bills budget left safe-to-spend unmoved at
2100,00 €.

**Income is never forecast.** A recurring salary and `monthly_income_cents` are the same
statement twice; counting an upcoming salary would inflate the month by a month's pay
for anyone who has stated both. (A recurring salary arguably ought to satisfy
`income_known` for someone who never stated a figure — genuinely useful, touches the
most safety-critical flag in the app, and therefore its own change.)

**The figure has to explain itself.** `safe_to_spend` reports `upcoming_cents` and Home's
existing subline gained one clause: *"800,00 € of repeating bills is already held back."*
A hero number dropping by a month's rent with nothing to say why is the unexplained
movement this app exists not to show. Upcoming occurrences are listed on the Repeating
screen, not on Home — Home is already four viewport-heights and needs the removal
conversation first.

**Skip** (`recurring_skips`, migration `0012`) suppresses a date in both places: never
materialised, never forecast. Only one of the two would be a bug in opposite directions.
Skipping a past date is refused — by then the row either exists (delete it) or generation
has moved past it, and a skip would change nothing while looking as though it had.

*Structural note:* `safe_to_spend` is no longer one statement. The budget remainder comes
back per category and the two-way `max` folds in Python, because occurrence dates are
computed there. The aggregation is still set-based SQL; it is just less of a showpiece.

**A latent bug from 4a, found by chasing a circular import:** `_add_months` clamped month
ends using `aggregates.days_in_period`, which answers *"how long is the budgeting
period"*. That equals a calendar month today and would not if periods were ever anchored
to a payday — a monthly recurrence would then clamp to the wrong length. It uses
`calendar` directly now, with the distinction written down.

**Also fixed:** `next_on` named a date the user had just skipped.

---

### Phase 5 — Assets + net worth trend · M · **done**

`assets` + append-only `asset_valuations`, and net worth as a derived time series. The
counter-proposal from the original planning session, built.

**The argument against snapshots, demonstrated rather than asserted.** Live: a car
valued only today made net worth "jump" 2 500 → 10 500 on one point, with `complete_from`
correctly marking the whole earlier line as incomplete. Stating what the car had been
worth in February then rewrote the trend from February and moved `complete_from` back
with it. A snapshot taken in February could not have been corrected by information that
arrived in August — it would have sat there disagreeing with the ledger, with no way to
tell which was right.

**The honesty problem is the real work here.** Value something for the first time and net
worth rises by it — nothing was gained; Frankly was told something. Rejected: extending
the earliest valuation backwards (fabrication) and hiding the trend until everything is
valued (useless). Instead `complete_from` is the earliest date at which every account and
live asset was already known; the line is drawn dashed before it, and says why.

**I then made that exact mistake in my own component and caught it on screen.** The
caption read *"Up 10 500,00 € over this stretch"* — measured from a point the caption
itself says is not comparable, asserting precisely what the dashing warns against. It now
measures from `complete_from` ("Down 1 500,00 € since February 2026"), with a test
confirmed to fail otherwise.

**Selling needs no special case:** an archived asset counts its last stated value up to
`archived_at` and nothing after, so the trend falls on the day of the sale by itself.

*Schema:* migration `0013` — `assets`, `asset_valuations` with one valuation per asset
per day. `value_cents` is signed, unlike every other money column, because a thing can be
worth less than nothing.

*Query shape:* two queries and a Python fold, not one windowed statement. The constraint
that matters here is round trips behind a cold start, and an as-of join plus a running
total in a single statement is materially harder to verify than the arithmetic it
replaces. Stated plainly rather than presented as the SQL showpiece.

*Charting:* hand-rolled SVG polyline, like the existing donut and bars. No dependency.

Also proves conservation **across the whole series** — a transfer left all twelve points
identical — where 2a only proved it at a point.

---

### Phase 6 — Weekly digest email · L · **done**

Sized **L**, not M — two security surfaces, a table, a content service, an email
template, a page, a Settings toggle, a workflow and an env var.

The precondition set in the original planning session was met first: a digest of your own
typed-in data tells you nothing you did not type, and only becomes worth opening once
recurring exists. *"€340 of repeating things lands in the next seven days"* is now a real
sentence.

**Default on**, by decision. Which makes the unsubscribe path load-bearing rather than a
courtesy, and the tests are weighted accordingly.

#### The two surfaces

**The cron route fails closed.** An unset `CRON_SECRET` refuses every request. That is
deliberately the opposite of email degrading to the console sender when unconfigured:
that is a graceful fallback, and an unauthenticated route that mails every user is not.

**Unsubscribe is a signed capability, not a session** (`core/signing` — HMAC over user +
kind under `SECRET_KEY`). It must work from a six-month-old email on a device that never
signed in, so there is nothing to store and nothing to expire. Scoped to one user and one
kind, unlocks no data, invalidated wholesale by rotating `SECRET_KEY`. The emailed link
points at the **app**, which POSTs — mail scanners prefetch links, and a GET that
unsubscribed would fire unread. The reply never varies with whether the token names
anyone, so it cannot be used to test which addresses have accounts.

**Sends are claimed before delivery** — `UPDATE … RETURNING` with the "not sent recently"
predicate inside it, so two overlapping runs cannot both pick up the same person. A
failure after claiming costs one missed week, which beats a duplicate.

**Hourly cron, not weekly.** A weekly job at a fixed UTC hour ignores `users.timezone`
entirely; the endpoint instead picks out whoever's *local* Monday morning has arrived. The
weekday check is what keeps it well behaved — enabling on a Wednesday fires nothing until
Monday.

#### An incident, and the guard it produced

While testing, I called the run endpoint against local dev **assuming it was on the
console sender**. It was not: `backend/.env` holds a live Resend key, and the call
queued five real sends to real addresses. I also printed that key into the transcript
while diagnosing it — the key needs rotating.

The fix is not a warning comment. **Nothing sends outside `ENV=prod`**: the route reports
who would receive one, sends nothing, and takes nobody's week, so a local run is
repeatable and cannot burn the real send. `?dry=true` does the same in production.
Verified by sabotage and by re-running the exact call that caused it.

A second thing that run left behind: I had `sed`-patched `SEND_HOUR` in the source to
force a send and did not restore it. **The test suite caught it** — `SEND_HOUR = 0` made
a Wednesday case pass that should have failed.

*Schema:* migration `0014` — `notification_settings(user_id, kind, enabled, last_sent_at)`.
`last_sent_at` is per-kind by nature, which is what makes the table earn itself rather
than being speculative.

*Config:* new `CRON_SECRET`, declared in `render.yaml` as `sync: false` beside
`EMAIL_API_KEY` — config nobody can read in a diff is config nobody reviews. Needs a
Render redeploy and a matching `DIGEST_CRON_SECRET` Actions secret.

*Content* uses only figures a screen already shows. `income_known` gates safe-to-spend
here exactly as on Home — an email is the one surface nobody is watching as it is written,
and so the easiest place to assert something untrue.

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
| Budgets do not roll forward | Limits evaporated at midnight on the 1st, so `remaining_budgets_cents` summed nothing and **safe-to-spend jumped by the whole of last month's unspent allowance**. | **Fixed** — carried forward on read (`effective_budget_month`); the write path settles the month so editing one category cannot orphan the rest; `DELETE /budgets` added because limits now persist. |
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
