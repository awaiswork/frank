"""Refunds and reconciliations — the kinds that touch spending, and the one that doesn't.

Phase 2a could assert that transfers left every spending figure untouched. These two
cannot: a refund is *meant* to move five of them, which is exactly why it landed in its
own change rather than alongside transfers.

The property that survives from 2a is the allow-list. Every aggregate names the kinds
it wants (`IN ('expense','refund')`, `== 'income'`) rather than excluding the ones it
doesn't, so a kind nobody has thought about is outside all of them by default.
`test_spend_signs_are_an_allow_list` is what keeps that true.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction, User
from app.services.accounts import balances
from app.services.aggregates import (
    SPEND_SIGNS,
    budget_vs_actual,
    daily_burn_rate,
    safe_to_spend,
    spend_by_category,
)
from tests.conftest import create_account as register
from tests.conftest import transaction

OPENED = dt.date(2026, 6, 1)
JUNE = dt.date(2026, 6, 1)
TODAY = dt.date(2026, 6, 15)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user(db: Session, income: int | None = 300_000) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@ex.com",
        password_hash="x",
        currency="EUR",
        monthly_income_cents=income,
    )
    db.add(user)
    db.flush()
    return user


def _account(db: Session, user: User, name: str = "Everyday", opening: int = 0) -> Account:
    account = Account(
        user_id=user.id,
        name=name,
        type="current",
        currency="EUR",
        opening_balance_cents=opening,
        opened_on=OPENED,
    )
    db.add(account)
    db.flush()
    return account


def _category(db: Session, user: User, name: str = "Clothing") -> Category:
    category = Category(user_id=user.id, name=name, kind="expense", color="#fff")
    db.add(category)
    db.flush()
    return category


def _tx(db: Session, user: User, **kw: object) -> Transaction:
    tx = transaction(
        user_id=user.id,
        description="t",
        occurred_on=kw.pop("on", dt.date(2026, 6, 10)),
        **kw,
    )
    db.add(tx)
    db.flush()
    return tx


# --- the property that has to survive ----------------------------------------


def test_spend_signs_are_an_allow_list(db: Session) -> None:
    """Every spending kind is named on purpose, and nothing else can drift in.

    `IN ('expense','refund')` and `!= 'income'` select the same rows today and diverge
    the moment a kind is added — the second would sweep in transfers, adjustments and
    whatever comes next. This asserts the allow-list is a strict subset of what the
    constraint permits, so it can never silently become a deny-list.
    """
    source = db.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_transactions_kind'"
        )
    )
    allowed = set(re.findall(r"'([a-z_]+)'", str(source)))

    assert set(SPEND_SIGNS) <= allowed, "SPEND_SIGNS names a kind the database rejects"
    # The kinds deliberately outside every spending figure. Listed rather than derived,
    # so adding a kind means stating which side of this line it falls on.
    assert allowed - set(SPEND_SIGNS) == {
        "income",
        "transfer",
        "adjustment_up",
        "adjustment_down",
    }


# --- refunds -----------------------------------------------------------------


def test_a_refund_gives_back_the_spending_it_undoes(db: Session) -> None:
    user = _user(db)
    account = _account(db, user, opening=1_000_00)
    clothing = _category(db, user)
    _tx(
        db, user, kind="expense", amount_cents=40_00, account_id=account.id, category_id=clothing.id
    )
    _tx(db, user, kind="refund", amount_cents=40_00, account_id=account.id, category_id=clothing.id)

    assert spend_by_category(db, user.id, JUNE)[0].spent_cents == 0
    assert safe_to_spend(db, user.id, user.monthly_income_cents, JUNE).spent_cents == 0
    assert daily_burn_rate(db, user.id, today=TODAY).total_spent_cents == 0
    # And the money is back in the account.
    assert balances(db, user.id)[0].balance_cents == 1_000_00


def test_a_refund_is_not_income(db: Session) -> None:
    """The whole reason it needs a kind of its own.

    Logged as income it would inflate what the user earned and raise safe-to-spend by
    the refund on top of giving the spending back — counting it twice.
    """
    user = _user(db, income=None)
    account = _account(db, user, opening=0)
    clothing = _category(db, user)
    _tx(db, user, kind="refund", amount_cents=40_00, account_id=account.id, category_id=clothing.id)

    sts = safe_to_spend(db, user.id, None, JUNE)
    assert sts.income_cents == 0
    # No income stated and none logged, so the app still owes a setup prompt rather
    # than a verdict — a refund must not look like earnings.
    assert sts.income_known is False


def test_a_refund_frees_the_budget_it_used(db: Session) -> None:
    user = _user(db)
    account = _account(db, user, opening=1_000_00)
    clothing = _category(db, user)
    from app.models import Budget

    db.add(Budget(user_id=user.id, category_id=clothing.id, month=JUNE, limit_cents=100_00))
    db.flush()

    _tx(
        db, user, kind="expense", amount_cents=80_00, account_id=account.id, category_id=clothing.id
    )
    assert budget_vs_actual(db, user.id, JUNE, today=TODAY)[0].spent_cents == 80_00

    _tx(db, user, kind="refund", amount_cents=30_00, account_id=account.id, category_id=clothing.id)
    row = budget_vs_actual(db, user.id, JUNE, today=TODAY)[0]
    assert row.spent_cents == 50_00
    assert row.spent_fraction == 0.5


def test_returning_more_than_was_bought_goes_negative(db: Session) -> None:
    """Bought last month, returned this month — the category really is below zero.

    Reporting zero would be a small lie and would stop the categories summing to the
    month's total, so the figure stays true and the UI is what clamps a bar's width.
    """
    user = _user(db)
    account = _account(db, user, opening=1_000_00)
    clothing = _category(db, user)
    _tx(
        db,
        user,
        kind="refund",
        amount_cents=40_00,
        account_id=account.id,
        category_id=clothing.id,
    )

    assert spend_by_category(db, user.id, JUNE)[0].spent_cents == -40_00
    # Money back means more is safe to spend, not less.
    assert safe_to_spend(db, user.id, user.monthly_income_cents, JUNE).spent_cents == -40_00


def test_transfers_still_change_no_spending_figure(db: Session) -> None:
    """The 2a property, re-asserted after the aggregates were rewritten.

    Signing the spend sums is exactly the change that could have let transfers back in.
    """
    user = _user(db)
    a = _account(db, user, "Everyday", opening=1_000_00)
    b = _account(db, user, "Savings", opening=0)
    clothing = _category(db, user)
    _tx(db, user, kind="expense", amount_cents=40_00, account_id=a.id, category_id=clothing.id)

    before = (
        safe_to_spend(db, user.id, user.monthly_income_cents, JUNE),
        [(r.category_id, r.spent_cents) for r in spend_by_category(db, user.id, JUNE)],
        daily_burn_rate(db, user.id, today=TODAY),
    )
    _tx(db, user, kind="transfer", amount_cents=500_00, account_id=a.id, counter_account_id=b.id)
    after = (
        safe_to_spend(db, user.id, user.monthly_income_cents, JUNE),
        [(r.category_id, r.spent_cents) for r in spend_by_category(db, user.id, JUNE)],
        daily_burn_rate(db, user.id, today=TODAY),
    )
    assert before == after


# --- reconcile ---------------------------------------------------------------


def _make_account(client: TestClient, token: str, name: str, opening: int) -> dict[str, object]:
    res = client.post(
        "/accounts",
        headers=_h(token),
        json={"name": name, "type": "current", "opening_balance_cents": opening},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_reconcile_writes_the_difference_in_both_directions(client: TestClient) -> None:
    token = register(client, "rec@example.com")
    account = _make_account(client, token, "Everyday", 1_000_00)

    short = client.post(
        f"/accounts/{account['id']}/reconcile",
        headers=_h(token),
        json={"actual_balance_cents": 995_00},
    )
    assert short.status_code == 200, short.text
    assert short.json()["balance_cents"] == 995_00

    over = client.post(
        f"/accounts/{account['id']}/reconcile",
        headers=_h(token),
        json={"actual_balance_cents": 1_020_00},
    )
    assert over.status_code == 200
    assert over.json()["balance_cents"] == 1_020_00


def test_a_reconciliation_is_visible_in_the_activity_list(client: TestClient) -> None:
    """A balance that changes for no visible reason is the failure to avoid.

    Which is why this is a transaction rather than a quiet edit to the opening balance.
    """
    token = register(client, "recvis@example.com")
    account = _make_account(client, token, "Everyday", 1_000_00)
    client.post(
        f"/accounts/{account['id']}/reconcile",
        headers=_h(token),
        json={"actual_balance_cents": 995_00},
    )

    rows = client.get("/transactions", headers=_h(token)).json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "adjustment_down"
    assert rows[0]["amount_cents"] == 5_00
    assert rows[0]["source"] == "reconcile"


def test_reconciling_to_the_same_balance_writes_nothing(client: TestClient) -> None:
    """A correction of nothing does not deserve a line in someone's history."""
    token = register(client, "recnil@example.com")
    account = _make_account(client, token, "Everyday", 1_000_00)

    res = client.post(
        f"/accounts/{account['id']}/reconcile",
        headers=_h(token),
        json={"actual_balance_cents": 1_000_00},
    )
    assert res.status_code == 200
    assert client.get("/transactions", headers=_h(token)).json() == []


def test_a_reconciliation_is_not_spending(client: TestClient) -> None:
    token = register(client, "recspend@example.com")
    account = _make_account(client, token, "Everyday", 1_000_00)
    client.post(
        f"/accounts/{account['id']}/reconcile",
        headers=_h(token),
        json={"actual_balance_cents": 900_00},
    )

    summary = client.get("/insights/summary", headers=_h(token)).json()
    assert summary["safe_to_spend"]["spent_cents"] == 0
    assert summary["daily_burn"]["total_spent_cents"] == 0


def test_reconcile_refuses_an_archived_account(client: TestClient) -> None:
    token = register(client, "recarch@example.com")
    account = _make_account(client, token, "Old", 1_000_00)
    client.patch(f"/accounts/{account['id']}", headers=_h(token), json={"archived": True})

    res = client.post(
        f"/accounts/{account['id']}/reconcile",
        headers=_h(token),
        json={"actual_balance_cents": 900_00},
    )
    assert res.status_code == 422


def test_reconcile_is_scoped_to_the_owner(client: TestClient) -> None:
    mine = register(client, "rmine@example.com")
    theirs = register(client, "rtheirs@example.com")
    other = _make_account(client, theirs, "Theirs", 1_000_00)

    res = client.post(
        f"/accounts/{other['id']}/reconcile",
        headers=_h(mine),
        json={"actual_balance_cents": 1},
    )
    assert res.status_code == 404
