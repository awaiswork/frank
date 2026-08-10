"""Budgets carry forward, so safe-to-spend stops jumping on the 1st.

A budget used to be a declaration about one month that evaporated at midnight. With no
rows for the new month, `remaining_budgets_cents` summed nothing and safe-to-spend rose
by the whole of last month's unspent allowance — the hero number telling someone the
calendar turning had made them richer. `test_safe_to_spend_does_not_jump_on_the_first`
is that bug.

The read half is only half. Writing one row into a month that had none would make it a
month that *has* rows, and the carry-forward read would then use only that row — every
other category silently losing its budget. So the first write settles the month.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Budget, Category, Transaction, User
from app.services.aggregates import budget_vs_actual, safe_to_spend
from tests.conftest import create_account as register

JULY = dt.date(2026, 7, 1)
AUGUST = dt.date(2026, 8, 1)
FIRST_OF_AUGUST = dt.date(2026, 8, 1)
INCOME = 3_000_00


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user(db: Session) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@ex.com",
        password_hash="x",
        currency="EUR",
        monthly_income_cents=INCOME,
    )
    db.add(user)
    db.flush()
    return user


def _category(db: Session, user: User, name: str) -> Category:
    category = Category(user_id=user.id, name=name, kind="expense", color="#fff")
    db.add(category)
    db.flush()
    return category


def _budget(db: Session, user: User, category: Category, month: dt.date, cents: int) -> None:
    db.add(Budget(user_id=user.id, category_id=category.id, month=month, limit_cents=cents))
    db.flush()


# --- the bug -----------------------------------------------------------------


def test_safe_to_spend_does_not_jump_on_the_first(db: Session) -> None:
    """The whole point.

    July is budgeted and untouched. On 1 August, before anything is spent or set, the
    same commitments still exist — so the figure must not rise by 900.
    """
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    bills = _category(db, user, "Bills")
    _budget(db, user, groceries, JULY, 400_00)
    _budget(db, user, bills, JULY, 500_00)

    july = safe_to_spend(db, user.id, INCOME, JULY, today=dt.date(2026, 7, 15))
    august = safe_to_spend(db, user.id, INCOME, AUGUST, today=FIRST_OF_AUGUST)

    assert july.remaining_budgets_cents == 900_00
    assert august.remaining_budgets_cents == 900_00
    assert august.safe_to_spend_cents == INCOME - 900_00


def test_limits_carry_but_spending_does_not(db: Session) -> None:
    """August inherits July's limits against August's own spend, not July's."""
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    _budget(db, user, groceries, JULY, 400_00)
    for on, cents in ((dt.date(2026, 7, 20), 300_00), (dt.date(2026, 8, 3), 50_00)):
        db.add(
            Transaction(
                user_id=user.id,
                category_id=groceries.id,
                kind="expense",
                amount_cents=cents,
                description="x",
                occurred_on=on,
            )
        )
    db.flush()

    [row] = budget_vs_actual(db, user.id, AUGUST, today=dt.date(2026, 8, 10))
    assert row.limit_cents == 400_00
    assert row.spent_cents == 50_00


def test_a_month_of_its_own_wins(db: Session) -> None:
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    _budget(db, user, groceries, JULY, 400_00)
    _budget(db, user, groceries, AUGUST, 250_00)

    [row] = budget_vs_actual(db, user.id, AUGUST, today=dt.date(2026, 8, 10))
    assert row.limit_cents == 250_00


def test_nothing_is_carried_from_before_budgets_existed(db: Session) -> None:
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    _budget(db, user, groceries, AUGUST, 400_00)

    assert budget_vs_actual(db, user.id, JULY, today=dt.date(2026, 7, 10)) == []
    assert safe_to_spend(db, user.id, INCOME, JULY, today=JULY).remaining_budgets_cents == 0


def test_a_skipped_month_still_carries(db: Session) -> None:
    """The most recent month with budgets applies, not merely the one immediately before."""
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    _budget(db, user, groceries, dt.date(2026, 5, 1), 400_00)

    [row] = budget_vs_actual(db, user.id, AUGUST, today=dt.date(2026, 8, 10))
    assert row.limit_cents == 400_00


def test_reading_a_month_creates_nothing(db: Session) -> None:
    """Carrying forward is a query. Looking at August must not write August rows."""
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    _budget(db, user, groceries, JULY, 400_00)

    budget_vs_actual(db, user.id, AUGUST, today=dt.date(2026, 8, 10))
    safe_to_spend(db, user.id, INCOME, AUGUST, today=FIRST_OF_AUGUST)

    months = set(db.scalars(select(Budget.month).where(Budget.user_id == user.id)))
    assert months == {JULY}


# --- the write half ----------------------------------------------------------


def test_editing_one_category_does_not_orphan_the_rest(client: TestClient) -> None:
    """The half that is easy to leave out, and turns the fix back into the bug.

    Writing a single row into a month that had none makes it a month that *has* rows —
    at which point the carry-forward read would use only that row.
    """
    token = register(client, "settle@example.com")
    cats = client.get("/categories", headers=_h(token)).json()[:3]
    for cat in cats:
        client.put(
            f"/budgets/{cat['id']}?month=2026-07", headers=_h(token), json={"limit_cents": 100_00}
        )

    august = client.get("/budgets?month=2026-08", headers=_h(token)).json()
    assert len(august) == 3  # carried

    client.put(
        f"/budgets/{cats[0]['id']}?month=2026-08", headers=_h(token), json={"limit_cents": 250_00}
    )
    after = {
        row["category_id"]: row["limit_cents"]
        for row in client.get("/budgets?month=2026-08", headers=_h(token)).json()
    }

    assert len(after) == 3, "editing one budget dropped the others"
    assert after[cats[0]["id"]] == 250_00
    assert after[cats[1]["id"]] == 100_00


def test_deleting_stops_budgeting_one_category(client: TestClient) -> None:
    """Needed because limits carry now — otherwise one would follow you for ever."""
    token = register(client, "stop@example.com")
    cats = client.get("/categories", headers=_h(token)).json()[:2]
    for cat in cats:
        client.put(
            f"/budgets/{cat['id']}?month=2026-07", headers=_h(token), json={"limit_cents": 100_00}
        )

    gone = client.delete(f"/budgets/{cats[0]['id']}?month=2026-08", headers=_h(token))
    assert gone.status_code == 204

    after = client.get("/budgets?month=2026-08", headers=_h(token)).json()
    assert [row["category_id"] for row in after] == [cats[1]["id"]]
    # July is untouched — deleting in August is not rewriting history.
    assert len(client.get("/budgets?month=2026-07", headers=_h(token)).json()) == 2


def test_deleting_the_last_one_falls_back(client: TestClient) -> None:
    """The documented edge, pinned so it is a known shape rather than a surprise.

    With no rows left in the month, the read falls back and the old limits reappear.
    Recording "this month was emptied deliberately" would be a column, and one deletion
    edge does not earn it.
    """
    token = register(client, "lastone@example.com")
    cat = client.get("/categories", headers=_h(token)).json()[0]
    client.put(
        f"/budgets/{cat['id']}?month=2026-07", headers=_h(token), json={"limit_cents": 100_00}
    )

    client.delete(f"/budgets/{cat['id']}?month=2026-08", headers=_h(token))
    after = client.get("/budgets?month=2026-08", headers=_h(token)).json()
    assert len(after) == 1 and after[0]["limit_cents"] == 100_00


def test_deleting_someone_elses_budget_is_refused(client: TestClient) -> None:
    mine = register(client, "bmine@example.com")
    theirs = register(client, "btheirs@example.com")
    other_cat = client.get("/categories", headers=_h(theirs)).json()[0]

    res = client.delete(f"/budgets/{other_cat['id']}?month=2026-08", headers=_h(mine))
    assert res.status_code == 404
