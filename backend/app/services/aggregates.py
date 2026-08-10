"""The SQL showcase — the four aggregate queries from technical-plan.md §6.

These are written as explicit SQLAlchemy Core ``select`` statements (set-based SQL,
never ORM row loops) so the database does the aggregation. Each function is pure:
it takes the bounds it needs and returns small typed dataclasses, which the routers
wrap in Pydantic response models. All money is integer cents.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.models import Budget, Category, GoalContribution, SavingsGoal, Transaction
from app.services import recurring

# --- What counts as spending ------------------------------------------------
#
# A refund is a returned purchase, so it *undoes* spending rather than being income:
# it gives back the category's spend, the budget's allowance and the burn rate, and
# leaves what someone earned alone.
#
# Every aggregate below filters kind with an **allow-list** — `IN (SPEND_SIGNS)` here,
# `== "income"` for the one income sum. Never a deny-list. `!= "income"` would silently
# sweep in transfers, adjustments, and whatever gets added next; an allow-list leaves
# an unconsidered kind outside every figure by default, which is what made transfers
# free to introduce. `test_spend_signs_are_an_allow_list` holds the line.
SPEND_SIGNS: dict[str, int] = {"expense": 1, "refund": -1}


def _is_spend() -> ColumnElement[bool]:
    """The allow-list, as a predicate. Nothing outside it reaches a spending figure."""
    return Transaction.kind.in_(tuple(SPEND_SIGNS))


def _spent() -> ColumnElement[int]:
    """``SUM(±amount_cents)`` over spending — refunds subtract.

    Signed in one place rather than five, so the rule has a single home. Note this can
    legitimately come out **negative**: return something bought last month and this
    month's spend in that category really is below zero. Reporting it as zero would be
    a small lie and would stop the categories summing to the month.
    """
    return func.coalesce(
        func.sum(
            case(
                *(
                    (Transaction.kind == kind, Transaction.amount_cents * sign)
                    for kind, sign in SPEND_SIGNS.items()
                ),
                else_=None,
            )
        ),
        0,
    )


# --- Period boundaries -------------------------------------------------------
#
# Every date window in the app is derived from these three functions, and nothing
# else computes a month boundary of its own. That is deliberate: a budgeting period
# happens to be a calendar month today, but ``Budget.month`` is stored as the period's
# start date, so anchoring periods to a payday instead would be a change to
# ``month_bounds`` alone rather than a migration against every stored row. Keeping the
# arithmetic in one place is what makes that true.


def month_bounds(month_start: dt.date) -> tuple[dt.date, dt.date]:
    """Half-open ``[period start, next period start)`` range for date filters."""
    if month_start.month == 12:
        nxt = dt.date(month_start.year + 1, 1, 1)
    else:
        nxt = dt.date(month_start.year, month_start.month + 1, 1)
    return month_start, nxt


def parse_month(month: str | None, *, today: dt.date) -> dt.date:
    """``"2026-06"`` -> that period's start; ``None`` -> the period containing ``today``."""
    if month is None:
        return today.replace(day=1)
    year, mon = (int(part) for part in month.split("-"))
    return dt.date(year, mon, 1)


def previous_period(month_start: dt.date) -> dt.date:
    """The period immediately before the one beginning at ``month_start``.

    Derived by asking which period contains the day before, rather than subtracting a
    month, so it stays correct for whatever a period is defined to be.
    """
    return parse_month(None, today=month_start - dt.timedelta(days=1))


def days_in_period(month_start: dt.date) -> int:
    """How many days the period beginning at ``month_start`` runs for.

    Derived from ``month_bounds`` rather than from the calendar, so it stays correct
    for whatever a period is defined to be.
    """
    start, end = month_bounds(month_start)
    return (end - start).days


def _elapsed_fraction(month_start: dt.date, today: dt.date) -> float:
    """How far through the period we are: 1.0 if it is already past, 0.0 if future."""
    length = days_in_period(month_start)
    if today < month_start:
        return 0.0
    if today >= month_start + dt.timedelta(days=length):
        return 1.0
    return (today.day) / length


# --- §6.1  Spend by category for a month -------------------------------------


@dataclass(frozen=True)
class CategorySpend:
    category_id: uuid.UUID | None
    category_name: str | None
    color: str | None
    spent_cents: int


def spend_by_category(db: Session, user_id: uuid.UUID, month_start: dt.date) -> list[CategorySpend]:
    """``SUM(amount_cents) GROUP BY category`` for one month's expenses.

    LEFT JOIN to categories so uncategorised spend (``category_id IS NULL``) still
    shows up as its own bucket.
    """
    start, end = month_bounds(month_start)
    stmt = (
        select(
            Transaction.category_id,
            Category.name,
            Category.color,
            _spent().label("spent"),
        )
        .join(Category, Category.id == Transaction.category_id, isouter=True)
        .where(
            Transaction.user_id == user_id,
            _is_spend(),
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .group_by(Transaction.category_id, Category.name, Category.color)
        .order_by(_spent().desc())
    )
    return [
        CategorySpend(
            category_id=row.category_id,
            category_name=row.name,
            color=row.color,
            spent_cents=int(row.spent),
        )
        for row in db.execute(stmt)
    ]


# --- §6.2  Budget vs. actual, with pace --------------------------------------


@dataclass(frozen=True)
class BudgetActual:
    category_id: uuid.UUID
    category_name: str
    color: str | None
    limit_cents: int
    spent_cents: int
    spent_fraction: float  # spent / limit
    elapsed_fraction: float  # day_of_month / days_in_month
    on_track: bool  # spent_fraction <= elapsed_fraction (with a little slack)


def effective_budget_month(db: Session, user_id: uuid.UUID, month_start: dt.date) -> dt.date | None:
    """Which month's budgets apply to ``month_start`` — carrying them forward.

    A budget was a per-month declaration that evaporated at midnight on the 1st. With no
    rows for the new month, ``remaining_budgets_cents`` summed nothing and safe-to-spend
    **jumped by the whole of last month's unspent allowance** — the hero number telling
    someone the calendar turning had made them richer.

    So the most recent month that *does* have budgets applies until a newer one does.
    Read-only: nothing is written here, and looking at a month never creates rows.
    Setting a budget settles the month for real (see `routers/budgets`), which is what
    makes editing one category not orphan the rest.
    """
    return db.scalar(
        select(func.max(Budget.month)).where(Budget.user_id == user_id, Budget.month <= month_start)
    )


def _spend_per_category_subquery(user_id: uuid.UUID, start: dt.date, end: dt.date) -> Subquery:
    return (
        select(
            Transaction.category_id.label("category_id"),
            _spent().label("spent"),
        )
        .where(
            Transaction.user_id == user_id,
            _is_spend(),
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .group_by(Transaction.category_id)
        .subquery()
    )


def budget_vs_actual(
    db: Session, user_id: uuid.UUID, month_start: dt.date, *, today: dt.date
) -> list[BudgetActual]:
    """Budgets LEFT JOIN the per-category spend, returning *pace* not just percent.

    ``pace`` lets the UI say "you're at 71% of Groceries but only 60% through the
    month" — the comparison the design's budget bars are built around.
    """
    start, end = month_bounds(month_start)
    # Limits may be carried from an earlier month; spend is always this month's.
    budget_month = effective_budget_month(db, user_id, month_start)
    if budget_month is None:
        return []
    spend = _spend_per_category_subquery(user_id, start, end)
    stmt = (
        select(
            Budget.category_id,
            Category.name,
            Category.color,
            Budget.limit_cents,
            func.coalesce(spend.c.spent, 0).label("spent"),
        )
        .join(Category, Category.id == Budget.category_id)
        .join(spend, spend.c.category_id == Budget.category_id, isouter=True)
        .where(Budget.user_id == user_id, Budget.month == budget_month)
        .order_by(Category.name)
    )
    elapsed = _elapsed_fraction(month_start, today)
    out: list[BudgetActual] = []
    for row in db.execute(stmt):
        limit_cents = int(row.limit_cents)
        spent_cents = int(row.spent)
        spent_fraction = spent_cents / limit_cents if limit_cents > 0 else 0.0
        out.append(
            BudgetActual(
                category_id=row.category_id,
                category_name=row.name,
                color=row.color,
                limit_cents=limit_cents,
                spent_cents=spent_cents,
                spent_fraction=spent_fraction,
                elapsed_fraction=elapsed,
                # a small slack so "exactly on pace" doesn't read as over-spending
                on_track=spent_fraction <= elapsed + 0.05,
            )
        )
    return out


# --- §6.3  Safe to spend (one CTE-style query) -------------------------------


def _reserved(
    budget_remaining: dict[uuid.UUID | None, int],
    upcoming: dict[uuid.UUID | None, int],
) -> int:
    """Money already spoken for, per category — **the larger of the two, never both**.

    A budget and a recurring template are two ways of describing the same commitment,
    so adding them reserves the rent twice and understates what is safe to spend by a
    month's rent. Taking the larger is right in all three shapes this comes in:

    * a Bills budget of 900 that already covers 800 of rent -> 900, the budget has it;
    * rent with no budget at all -> 800, because the rent happens anyway;
    * a budget set at 100 with 800 of rent still due -> 800, because the rent does not
      care what limit was written down.

    This is deliberately arithmetic rather than a rule telling people not to budget for
    a category that also has a template. That rule would forbid a perfectly reasonable
    Bills budget covering both a fixed rent and a variable water bill, and could only
    ever be a warning — the double count would still be reachable.
    """
    return sum(
        max(budget_remaining.get(category_id, 0), upcoming.get(category_id, 0))
        for category_id in budget_remaining.keys() | upcoming.keys()
    )


@dataclass(frozen=True)
class SafeToSpend:
    income_cents: int
    spent_cents: int
    remaining_budgets_cents: int  # money still earmarked, by budget or by schedule
    goal_contributions_cents: int  # set aside toward goals this month
    # Recurring expenses still due this month. Reported so a screen can say *why* the
    # figure above it dropped — a hero number that falls by 800 with nothing to explain
    # it is the kind of unexplained movement this app exists not to have.
    upcoming_cents: int
    safe_to_spend_cents: int
    # False when we had nothing to work from — no stated monthly income and no income
    # logged this month. ``safe_to_spend_cents`` is then just negative spend, which
    # means nothing, so callers must not present it as a verdict on the user.
    income_known: bool


def safe_to_spend(
    db: Session,
    user_id: uuid.UUID,
    monthly_income_cents: int | None,
    month_start: dt.date,
    *,
    today: dt.date | None = None,
) -> SafeToSpend:
    """income − spent − remaining budget allowance − goal contributions (§6.3).

    The four components are computed in a single statement of correlated scalar
    subqueries. "Income this month" prefers the user's stated monthly income and
    falls back to income actually logged. v1 has no per-goal monthly cadence, so
    "goal contributions planned" is taken as contributions logged this month — the
    closest faithful approximation to §6.3 given the schema.
    """
    start, end = month_bounds(month_start)
    # Looking at a past or future month: nothing is "still to come" in a month that is
    # not the one being lived through.
    today = today if today is not None else start

    income_logged = (
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(
            Transaction.user_id == user_id,
            Transaction.kind == "income",
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .scalar_subquery()
    )
    spent = (
        select(_spent())
        .where(
            Transaction.user_id == user_id,
            _is_spend(),
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .scalar_subquery()
    )
    spend = _spend_per_category_subquery(user_id, start, end)
    goal_contribs = (
        select(func.coalesce(func.sum(GoalContribution.amount_cents), 0))
        .select_from(GoalContribution)
        .join(SavingsGoal, SavingsGoal.id == GoalContribution.goal_id)
        .where(
            SavingsGoal.user_id == user_id,
            # Archived goals are money the user has stopped setting aside, so holding it
            # back from safe-to-spend understates what they actually have. Every other
            # goal query already excludes them; this one did not.
            SavingsGoal.archived_at.is_(None),
            GoalContribution.occurred_on >= start,
            GoalContribution.occurred_on < end,
        )
        .scalar_subquery()
    )

    row = db.execute(
        select(
            income_logged.label("income_logged"),
            spent.label("spent"),
            goal_contribs.label("goal_contributions"),
        )
    ).one()

    # Per category rather than one figure, because it has to be compared against what
    # is still to come in that same category — see `_reserved` below.
    # Carried forward as well — a jump avoided on the budgets screen but left in
    # safe-to-spend would be the same bug, on the surface where it matters most.
    budget_month = effective_budget_month(db, user_id, month_start)
    budget_remaining = {
        cat_id: int(remaining)
        for cat_id, remaining in db.execute(
            select(
                Budget.category_id,
                func.greatest(Budget.limit_cents - func.coalesce(spend.c.spent, 0), 0),
            )
            .select_from(Budget)
            .join(spend, spend.c.category_id == Budget.category_id, isouter=True)
            .where(Budget.user_id == user_id, Budget.month == budget_month)
        )
        if budget_month is not None
    }
    upcoming = recurring.forecast(db, user_id, today=today, through=end - dt.timedelta(days=1))
    remaining_budgets_cents = _reserved(budget_remaining, upcoming)

    income_cents = (
        monthly_income_cents if monthly_income_cents is not None else int(row.income_logged)
    )
    # Falling back to logged income is fine as a number, but if there is no income at
    # all we are not entitled to any opinion about "what's safe" — say so explicitly
    # rather than letting 0 masquerade as a real budget.
    income_known = monthly_income_cents is not None or int(row.income_logged) > 0
    spent_cents = int(row.spent)
    goal_contributions_cents = int(row.goal_contributions)
    return SafeToSpend(
        income_cents=income_cents,
        spent_cents=spent_cents,
        remaining_budgets_cents=remaining_budgets_cents,
        upcoming_cents=sum(upcoming.values()),
        goal_contributions_cents=goal_contributions_cents,
        safe_to_spend_cents=(
            income_cents - spent_cents - remaining_budgets_cents - goal_contributions_cents
        ),
        income_known=income_known,
    )


# --- §6.4  Daily burn rate + month-over-month delta (window function) --------


@dataclass(frozen=True)
class BurnRate:
    trailing_days: int
    total_spent_cents: int
    daily_burn_cents: int


def daily_burn_rate(db: Session, user_id: uuid.UUID, *, today: dt.date, days: int = 30) -> BurnRate:
    """Average daily expense over the trailing ``days`` window (default 30)."""
    window_start = today - dt.timedelta(days=days - 1)
    total = db.scalar(
        select(_spent()).where(
            Transaction.user_id == user_id,
            _is_spend(),
            Transaction.occurred_on >= window_start,
            Transaction.occurred_on <= today,
        )
    )
    total_cents = int(total or 0)
    return BurnRate(
        trailing_days=days,
        total_spent_cents=total_cents,
        daily_burn_cents=total_cents // days,
    )


@dataclass(frozen=True)
class CategoryMoM:
    category_id: uuid.UUID | None
    category_name: str | None
    color: str | None
    this_month_cents: int
    prev_month_cents: int
    delta_cents: int


def month_over_month_by_category(
    db: Session, user_id: uuid.UUID, month_start: dt.date
) -> list[CategoryMoM]:
    """Per-category change against the *previous calendar month*.

    This used a ``LAG()`` window function, which technical-plan.md §6.4 lists as one of
    the showcase queries. It was wrong twice, and both faults were invisible on screen:

    * ``LAG`` orders over the rows that *exist*, so "previous month" meant "the previous
      month this category had any spending in". Skip a month and the delta compared
      against something two or three months back while being labelled as last month.
    * Filtering to rows in the target month dropped every category that had spending
      last month and none this month — which is exactly the change worth seeing. Stop
      buying something entirely and it vanished rather than showing a fall to zero.

    Two straightforward reads over the union of both months fix both, and are far easier
    to check than a window over a densified series. Correctness over showmanship — the
    note is here so the swap reads as a decision rather than an oversight.
    """
    this_month = {row.category_id: row for row in spend_by_category(db, user_id, month_start)}
    last_month = {
        row.category_id: row for row in spend_by_category(db, user_id, previous_period(month_start))
    }

    out: list[CategoryMoM] = []
    for category_id in this_month.keys() | last_month.keys():
        current = this_month.get(category_id)
        previous = last_month.get(category_id)
        # Present in at least one of the two, and that one carries the name and colour.
        named = current or previous
        if named is None:  # pragma: no cover — the key came from one of the two maps
            continue
        this_cents = current.spent_cents if current else 0
        prev_cents = previous.spent_cents if previous else 0
        out.append(
            CategoryMoM(
                category_id=category_id,
                category_name=named.category_name,
                color=named.color,
                this_month_cents=this_cents,
                prev_month_cents=prev_cents,
                delta_cents=this_cents - prev_cents,
            )
        )
    return sorted(out, key=lambda row: (row.category_name or "", str(row.category_id or "")))
