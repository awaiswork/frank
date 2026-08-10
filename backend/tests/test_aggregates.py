"""The §6 aggregate queries against seeded fixtures with known totals.

These are the interview-material SQL queries; the assertions pin the exact cents
so a regression in the SQL is caught immediately.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.models import Budget, Category, GoalContribution, SavingsGoal, User
from app.services.aggregates import (
    budget_vs_actual,
    daily_burn_rate,
    days_in_period,
    month_over_month_by_category,
    previous_period,
    safe_to_spend,
    spend_by_category,
)
from tests.conftest import transaction

JUNE = dt.date(2026, 6, 1)
TODAY = dt.date(2026, 6, 15)  # halfway through a 30-day month -> elapsed 0.5


def _user(db: Session, income: int | None = None) -> User:
    user = User(email=f"{uuid.uuid4().hex}@ex.com", password_hash="x", monthly_income_cents=income)
    db.add(user)
    db.flush()
    return user


def _cat(db: Session, user: User, name: str, kind: str = "expense") -> Category:
    cat = Category(user_id=user.id, name=name, kind=kind, color="#fff")
    db.add(cat)
    db.flush()
    return cat


def _tx(
    db: Session,
    user: User,
    cat: Category | None,
    cents: int,
    on: dt.date,
    kind: str = "expense",
) -> None:
    db.add(
        transaction(
            user_id=user.id,
            category_id=cat.id if cat else None,
            kind=kind,
            amount_cents=cents,
            description="t",
            occurred_on=on,
        )
    )
    db.flush()


def _seed(db: Session, income: int | None = 300_00) -> tuple[User, Category, Category]:
    """Groceries 150€ + Transport 40€ in June; Groceries 120€ in May (for MoM)."""
    user = _user(db, income=income)
    groceries = _cat(db, user, "Groceries")
    transport = _cat(db, user, "Transport")
    _tx(db, user, groceries, 100_00, dt.date(2026, 6, 5))
    _tx(db, user, groceries, 50_00, dt.date(2026, 6, 8))
    _tx(db, user, transport, 40_00, dt.date(2026, 6, 10))
    _tx(
        db, user, None, 200_00, dt.date(2026, 6, 1), kind="income"
    )  # must be ignored by expense aggs
    _tx(db, user, groceries, 120_00, dt.date(2026, 5, 10))  # previous month, outside 30-day window
    return user, groceries, transport


def test_spend_by_category(db: Session) -> None:
    user, groceries, transport = _seed(db)
    rows = spend_by_category(db, user.id, JUNE)
    by_id = {r.category_id: r.spent_cents for r in rows}
    assert by_id[groceries.id] == 150_00
    assert by_id[transport.id] == 40_00
    # ordered by spend desc, and income is excluded
    assert rows[0].category_id == groceries.id
    assert all(r.category_name != "income" for r in rows)


def test_budget_vs_actual_pace(db: Session) -> None:
    user, groceries, transport = _seed(db)
    db.add_all(
        [
            Budget(user_id=user.id, category_id=groceries.id, month=JUNE, limit_cents=200_00),
            Budget(user_id=user.id, category_id=transport.id, month=JUNE, limit_cents=100_00),
        ]
    )
    db.flush()
    rows = {r.category_id: r for r in budget_vs_actual(db, user.id, JUNE, today=TODAY)}

    g = rows[groceries.id]
    assert g.spent_cents == 150_00
    assert g.limit_cents == 200_00
    assert g.spent_fraction == 0.75
    assert g.elapsed_fraction == 0.5
    assert g.on_track is False  # 75% spent only halfway through the month

    t = rows[transport.id]
    assert t.spent_fraction == 0.4
    assert t.on_track is True


def test_safe_to_spend_uses_stated_income(db: Session) -> None:
    user, groceries, transport = _seed(db, income=300_000)
    db.add_all(
        [
            Budget(user_id=user.id, category_id=groceries.id, month=JUNE, limit_cents=200_00),
            Budget(user_id=user.id, category_id=transport.id, month=JUNE, limit_cents=100_00),
        ]
    )
    goal = SavingsGoal(user_id=user.id, name="Trip", target_cents=1_000_00)
    db.add(goal)
    db.flush()
    db.add(GoalContribution(goal_id=goal.id, amount_cents=50_00, occurred_on=dt.date(2026, 6, 3)))
    db.flush()

    s = safe_to_spend(db, user.id, user.monthly_income_cents, JUNE)
    assert s.income_cents == 300_000
    assert s.spent_cents == 190_00  # 150€ groceries + 40€ transport
    assert s.remaining_budgets_cents == 110_00  # (200-150) + (100-40)
    assert s.goal_contributions_cents == 50_00
    assert s.safe_to_spend_cents == 300_000 - 190_00 - 110_00 - 50_00


def test_safe_to_spend_excludes_archived_goals(db: Session) -> None:
    """Archiving a goal releases the money it was holding back.

    Every other goal query already filters archived goals out; this one did not, so a
    goal the user had stopped funding went on suppressing safe-to-spend for the rest of
    the month — understating what they actually had left.
    """
    user = _user(db, income=1_000_00)
    active = SavingsGoal(user_id=user.id, name="Trip", target_cents=500_00)
    dropped = SavingsGoal(
        user_id=user.id,
        name="Abandoned",
        target_cents=500_00,
        archived_at=dt.datetime(2026, 6, 20, tzinfo=dt.UTC),
    )
    db.add_all([active, dropped])
    db.flush()
    db.add_all(
        [
            GoalContribution(
                goal_id=active.id, amount_cents=40_00, occurred_on=dt.date(2026, 6, 3)
            ),
            GoalContribution(
                goal_id=dropped.id, amount_cents=90_00, occurred_on=dt.date(2026, 6, 4)
            ),
        ]
    )
    db.flush()

    s = safe_to_spend(db, user.id, user.monthly_income_cents, JUNE)
    assert s.goal_contributions_cents == 40_00  # the archived goal's 90€ is not withheld
    assert s.safe_to_spend_cents == 1_000_00 - 40_00


def test_days_in_period_spans_month_lengths_and_year_end() -> None:
    """Period length comes from ``month_bounds``, so it has to survive every edge."""
    assert days_in_period(dt.date(2026, 6, 1)) == 30
    assert days_in_period(dt.date(2026, 7, 1)) == 31
    assert days_in_period(dt.date(2026, 2, 1)) == 28
    assert days_in_period(dt.date(2028, 2, 1)) == 29  # leap February
    assert days_in_period(dt.date(2026, 12, 1)) == 31  # rolls into the next year


def test_safe_to_spend_falls_back_to_logged_income(db: Session) -> None:
    user = _user(db, income=None)
    _tx(db, user, None, 250_00, dt.date(2026, 6, 2), kind="income")
    s = safe_to_spend(db, user.id, user.monthly_income_cents, JUNE)
    assert s.income_cents == 250_00
    assert s.safe_to_spend_cents == 250_00


def test_daily_burn_rate_trailing_30(db: Session) -> None:
    user, _g, _t = _seed(db)
    burn = daily_burn_rate(db, user.id, today=TODAY)
    # only the June rows fall inside [May 17, Jun 15]; May 10 row is excluded
    assert burn.total_spent_cents == 190_00
    assert burn.daily_burn_cents == 190_00 // 30


def test_month_over_month(db: Session) -> None:
    user, groceries, transport = _seed(db)
    rows = {r.category_id: r for r in month_over_month_by_category(db, user.id, JUNE)}
    assert rows[groceries.id].this_month_cents == 150_00
    assert rows[groceries.id].prev_month_cents == 120_00
    assert rows[groceries.id].delta_cents == 30_00
    assert rows[transport.id].prev_month_cents == 0
    assert rows[transport.id].delta_cents == 40_00


def test_a_gap_month_compares_against_the_gap_not_the_last_time_you_spent(
    db: Session,
) -> None:
    """The bug a window function hid.

    ``LAG`` orders over the rows that exist, so with nothing in May, June's "previous
    month" silently became April — two months back, labelled as last month. Skipping a
    category for a month is ordinary, and the delta was quietly comparing the wrong
    thing whenever it happened.
    """
    user = _user(db, income=300_00)
    groceries = _cat(db, user, "Groceries")
    _tx(db, user, groceries, 200_00, dt.date(2026, 4, 10))
    # nothing at all in May
    _tx(db, user, groceries, 50_00, dt.date(2026, 6, 10))

    [row] = month_over_month_by_category(db, user.id, JUNE)
    assert row.this_month_cents == 50_00
    assert row.prev_month_cents == 0, "compared against April instead of May"
    assert row.delta_cents == 50_00


def test_stopping_entirely_shows_a_fall_rather_than_disappearing(db: Session) -> None:
    """The other half: the change most worth seeing was the one that vanished.

    Rows were filtered to the target month, so a category you spent on last month and
    not at all this month left the comparison altogether — the app quietly dropping
    "you stopped buying this" instead of reporting it.
    """
    user = _user(db, income=300_00)
    fun = _cat(db, user, "Fun")
    _tx(db, user, fun, 80_00, dt.date(2026, 5, 12))

    rows = {r.category_name: r for r in month_over_month_by_category(db, user.id, JUNE)}
    assert "Fun" in rows, "a category dropped to zero disappeared instead of showing it"
    assert rows["Fun"].this_month_cents == 0
    assert rows["Fun"].prev_month_cents == 80_00
    assert rows["Fun"].delta_cents == -80_00


def test_previous_period_steps_back_one_month() -> None:
    assert previous_period(dt.date(2026, 6, 1)) == dt.date(2026, 5, 1)
    assert previous_period(dt.date(2026, 1, 1)) == dt.date(2025, 12, 1)
    assert previous_period(dt.date(2026, 3, 1)) == dt.date(2026, 2, 1)
