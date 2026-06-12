"""The SQL showcase — the four aggregate queries from technical-plan.md §6.

These are written as explicit SQLAlchemy Core ``select`` statements (set-based SQL,
never ORM row loops) so the database does the aggregation. Each function is pure:
it takes the bounds it needs and returns small typed dataclasses, which the routers
wrap in Pydantic response models. All money is integer cents.
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.models import Budget, Category, GoalContribution, SavingsGoal, Transaction


def month_bounds(month_start: dt.date) -> tuple[dt.date, dt.date]:
    """Half-open ``[first-of-month, first-of-next-month)`` range for date filters."""
    if month_start.month == 12:
        nxt = dt.date(month_start.year + 1, 1, 1)
    else:
        nxt = dt.date(month_start.year, month_start.month + 1, 1)
    return month_start, nxt


def parse_month(month: str | None, *, today: dt.date) -> dt.date:
    """``"2026-06"`` -> first of that month; ``None`` -> first of ``today``'s month."""
    if month is None:
        return today.replace(day=1)
    year, mon = (int(part) for part in month.split("-"))
    return dt.date(year, mon, 1)


def _elapsed_fraction(month_start: dt.date, today: dt.date) -> float:
    """How far through the month we are: 1.0 if it is already past, 0.0 if future."""
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
    if today < month_start:
        return 0.0
    if today >= month_start + dt.timedelta(days=days_in_month):
        return 1.0
    return (today.day) / days_in_month


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
            func.coalesce(func.sum(Transaction.amount_cents), 0).label("spent"),
        )
        .join(Category, Category.id == Transaction.category_id, isouter=True)
        .where(
            Transaction.user_id == user_id,
            Transaction.kind == "expense",
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .group_by(Transaction.category_id, Category.name, Category.color)
        .order_by(func.sum(Transaction.amount_cents).desc())
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


def _spend_per_category_subquery(user_id: uuid.UUID, start: dt.date, end: dt.date) -> Subquery:
    return (
        select(
            Transaction.category_id.label("category_id"),
            func.coalesce(func.sum(Transaction.amount_cents), 0).label("spent"),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.kind == "expense",
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
        .where(Budget.user_id == user_id, Budget.month == month_start)
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


@dataclass(frozen=True)
class SafeToSpend:
    income_cents: int
    spent_cents: int
    remaining_budgets_cents: int  # money still earmarked inside this month's budgets
    goal_contributions_cents: int  # set aside toward goals this month
    safe_to_spend_cents: int


def safe_to_spend(
    db: Session,
    user_id: uuid.UUID,
    monthly_income_cents: int | None,
    month_start: dt.date,
) -> SafeToSpend:
    """income − spent − remaining budget allowance − goal contributions (§6.3).

    The four components are computed in a single statement of correlated scalar
    subqueries. "Income this month" prefers the user's stated monthly income and
    falls back to income actually logged. v1 has no per-goal monthly cadence, so
    "goal contributions planned" is taken as contributions logged this month — the
    closest faithful approximation to §6.3 given the schema.
    """
    start, end = month_bounds(month_start)

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
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(
            Transaction.user_id == user_id,
            Transaction.kind == "expense",
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .scalar_subquery()
    )
    spend = _spend_per_category_subquery(user_id, start, end)
    remaining_budgets = (
        select(
            func.coalesce(
                func.sum(func.greatest(Budget.limit_cents - func.coalesce(spend.c.spent, 0), 0)),
                0,
            )
        )
        .select_from(Budget)
        .join(spend, spend.c.category_id == Budget.category_id, isouter=True)
        .where(Budget.user_id == user_id, Budget.month == month_start)
        .scalar_subquery()
    )
    goal_contribs = (
        select(func.coalesce(func.sum(GoalContribution.amount_cents), 0))
        .select_from(GoalContribution)
        .join(SavingsGoal, SavingsGoal.id == GoalContribution.goal_id)
        .where(
            SavingsGoal.user_id == user_id,
            GoalContribution.occurred_on >= start,
            GoalContribution.occurred_on < end,
        )
        .scalar_subquery()
    )

    row = db.execute(
        select(
            income_logged.label("income_logged"),
            spent.label("spent"),
            remaining_budgets.label("remaining_budgets"),
            goal_contribs.label("goal_contributions"),
        )
    ).one()

    income_cents = (
        monthly_income_cents if monthly_income_cents is not None else int(row.income_logged)
    )
    spent_cents = int(row.spent)
    remaining_budgets_cents = int(row.remaining_budgets)
    goal_contributions_cents = int(row.goal_contributions)
    return SafeToSpend(
        income_cents=income_cents,
        spent_cents=spent_cents,
        remaining_budgets_cents=remaining_budgets_cents,
        goal_contributions_cents=goal_contributions_cents,
        safe_to_spend_cents=(
            income_cents - spent_cents - remaining_budgets_cents - goal_contributions_cents
        ),
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
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.user_id == user_id,
            Transaction.kind == "expense",
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
    """Per-category change vs. the previous month, via a ``LAG()`` window function.

    Monthly sums are computed per category, then ``LAG`` pulls each row's previous
    month into the same row so we can return the delta the Insights screen plots.
    """
    month_expr = func.date_trunc("month", Transaction.occurred_on)
    monthly = (
        select(
            Transaction.category_id.label("category_id"),
            month_expr.label("month"),
            func.sum(Transaction.amount_cents).label("spent"),
        )
        .where(Transaction.user_id == user_id, Transaction.kind == "expense")
        .group_by(Transaction.category_id, month_expr)
        .subquery()
    )
    windowed = select(
        monthly.c.category_id,
        monthly.c.month,
        monthly.c.spent,
        func.lag(monthly.c.spent)
        .over(partition_by=monthly.c.category_id, order_by=monthly.c.month)
        .label("prev_spent"),
    ).subquery()

    target = dt.datetime(month_start.year, month_start.month, 1)
    stmt = (
        select(
            windowed.c.category_id,
            Category.name,
            Category.color,
            windowed.c.spent,
            func.coalesce(windowed.c.prev_spent, 0).label("prev_spent"),
        )
        .join(Category, Category.id == windowed.c.category_id, isouter=True)
        .where(windowed.c.month == target)
        .order_by(Category.name)
    )
    out: list[CategoryMoM] = []
    for row in db.execute(stmt):
        this_cents = int(row.spent)
        prev_cents = int(row.prev_spent)
        out.append(
            CategoryMoM(
                category_id=row.category_id,
                category_name=row.name,
                color=row.color,
                this_month_cents=this_cents,
                prev_month_cents=prev_cents,
                delta_cents=this_cents - prev_cents,
            )
        )
    return out
