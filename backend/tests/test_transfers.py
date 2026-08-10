"""Transfers, and the two properties that stop them corrupting anything.

A transfer is the change most able to break this app quietly: it touches money without
being income or spending, so a mistake shows up as a total that is merely *wrong*
rather than as an error anyone sees. Two properties are what make that safe, and they
are the first two tests here.

**Conservation.** Moving money between your own accounts cannot change how much you
have. `Σ(balances)` is identical before and after, for any amount between any pair.

**Aggregate invariance.** A transfer is not spending and not income, so every spending
figure must be untouched by one existing. That holds today because all six aggregates
filter `kind` positively rather than with `!=`; this is what stops someone changing
that without noticing.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction, User
from app.services.accounts import balances
from app.services.aggregates import (
    daily_burn_rate,
    month_over_month_by_category,
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


def _user(db: Session) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@ex.com",
        password_hash="x",
        currency="EUR",
        monthly_income_cents=300_000,
    )
    db.add(user)
    db.flush()
    return user


def _account(
    db: Session, user: User, name: str, opening: int = 0, kind: str = "current"
) -> Account:
    account = Account(
        user_id=user.id,
        name=name,
        type=kind,
        currency="EUR",
        opening_balance_cents=opening,
        opened_on=OPENED,
    )
    db.add(account)
    db.flush()
    return account


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


def _net_worth(db: Session, user: User) -> int:
    return sum(r.balance_cents for r in balances(db, user.id))


def _spending_snapshot(db: Session, user: User) -> object:
    """Every figure a transfer must leave completely alone."""
    sts = safe_to_spend(db, user.id, user.monthly_income_cents, JUNE)
    return (
        sts,
        [(r.category_id, r.spent_cents) for r in spend_by_category(db, user.id, JUNE)],
        daily_burn_rate(db, user.id, today=TODAY),
        [
            (r.category_id, r.this_month_cents)
            for r in month_over_month_by_category(db, user.id, JUNE)
        ],
    )


# --- the two properties ------------------------------------------------------


@pytest.mark.parametrize("amount", [1, 999, 50_00, 1_234_56, 9_999_999])
def test_a_transfer_conserves_total_worth(db: Session, amount: int) -> None:
    """Moving your own money cannot change how much of it you have.

    The single assertion that catches every double-counting bug in this area, present
    and future: if a transfer ever contributes anything but −x and +x, this moves.
    """
    user = _user(db)
    a = _account(db, user, "Everyday", opening=1_000_00)
    b = _account(db, user, "Savings", opening=250_00)

    before = _net_worth(db, user)
    _tx(db, user, kind="transfer", amount_cents=amount, account_id=a.id, counter_account_id=b.id)
    assert _net_worth(db, user) == before


def test_a_transfer_moves_both_ends_by_the_same_amount(db: Session) -> None:
    """The half-transfer trap.

    Under a flat {kind: sign} map the natural fix is `"transfer": -1`, which takes the
    money out of the source and puts it nowhere. Conservation alone would not catch a
    variant that got both signs wrong symmetrically, so pin the two ends directly.
    """
    user = _user(db)
    a = _account(db, user, "Everyday", opening=1_000_00)
    b = _account(db, user, "Savings", opening=250_00)
    _tx(db, user, kind="transfer", amount_cents=200_00, account_id=a.id, counter_account_id=b.id)

    by_name = {r.account.name: r for r in balances(db, user.id)}
    assert by_name["Everyday"].balance_cents == 800_00  # left here
    assert by_name["Savings"].balance_cents == 450_00  # and arrived here
    # It belongs to both histories, so it counts once in each.
    assert by_name["Everyday"].entry_count == 1
    assert by_name["Savings"].entry_count == 1


def test_transfers_change_no_spending_figure(db: Session) -> None:
    """Not spending, not income — so every aggregate must read exactly the same.

    This is the regression net for the positive-filter property: the six aggregates
    exclude an unknown kind only because they say `kind == 'expense'` rather than
    `kind != 'income'`. If anyone reverses that, this fails.
    """
    user = _user(db)
    groceries = Category(user_id=user.id, name="Groceries", kind="expense", color="#fff")
    db.add(groceries)
    db.flush()
    a = _account(db, user, "Everyday", opening=1_000_00)
    b = _account(db, user, "Savings", opening=0)
    _tx(db, user, kind="expense", amount_cents=40_00, account_id=a.id, category_id=groceries.id)
    _tx(db, user, kind="income", amount_cents=300_00, account_id=a.id)

    before = _spending_snapshot(db, user)
    _tx(db, user, kind="transfer", amount_cents=500_00, account_id=a.id, counter_account_id=b.id)
    assert _spending_snapshot(db, user) == before


# --- the shape, enforced by the database -------------------------------------


@pytest.mark.parametrize(
    "kind,source,destination,with_category",
    [
        ("transfer", "a", None, False),  # no far end
        ("transfer", None, "b", False),  # no near end
        ("transfer", "a", "a", False),  # to itself
        ("transfer", "a", "b", True),  # carrying a category, so reaching a budget
        ("expense", "a", "b", False),  # a counter on something that is not a transfer
    ],
)
def test_malformed_transfers_are_unrepresentable(
    db: Session,
    kind: str,
    source: str | None,
    destination: str | None,
    with_category: bool,
) -> None:
    """Not merely rejected by the router — rejected by the database.

    A rule that lives only in a router is a rule the next writer can route around, and
    these are the shapes that would let a transfer reach a budget or lose an end.
    """
    user = _user(db)
    accounts = {"a": _account(db, user, "A"), "b": _account(db, user, "B")}
    category_id = None
    if with_category:
        category = Category(user_id=user.id, name="Fun", kind="expense", color="#fff")
        db.add(category)
        db.flush()
        category_id = category.id

    with pytest.raises(IntegrityError):
        _tx(
            db,
            user,
            kind=kind,
            amount_cents=10_00,
            account_id=accounts[source].id if source else None,
            counter_account_id=accounts[destination].id if destination else None,
            category_id=category_id,
        )
    db.rollback()


# The kind vocabulary used to be pinned here as an exact set. That moved to
# `test_refunds.test_spend_signs_are_an_allow_list`, which asserts the same names *and*
# which side of the spending line each falls on — strictly more than this said, and one
# place to update instead of two.


# --- through the API ---------------------------------------------------------


def _make_account(client: TestClient, token: str, name: str, opening: int = 0) -> dict[str, object]:
    res = client.post(
        "/accounts",
        headers=_h(token),
        json={"name": name, "type": "current", "opening_balance_cents": opening},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_transfer_round_trip_over_the_api(client: TestClient) -> None:
    token = register(client, "xfer@example.com")
    a = _make_account(client, token, "Everyday", 1_000_00)
    b = _make_account(client, token, "Savings", 0)

    made = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "transfer",
            "amount_cents": 300_00,
            "description": "to savings",
            "occurred_on": a["opened_on"],
            "account_id": a["id"],
            "counter_account_id": b["id"],
        },
    )
    assert made.status_code == 201, made.text
    assert made.json()["counter_account_id"] == b["id"]

    payload = client.get("/accounts", headers=_h(token)).json()
    by_name = {row["name"]: row["balance_cents"] for row in payload["accounts"]}
    assert by_name == {"Everyday": 700_00, "Savings": 300_00}
    assert payload["total_cents"] == 1_000_00  # unmoved


@pytest.mark.parametrize(
    "patch,expected",
    [
        ({"counter_account_id": None}, "both ends"),
        ({"same_account": True}, "two different"),
        ({"category": True}, "no category"),
    ],
)
def test_the_api_explains_a_bad_transfer(
    client: TestClient, patch: dict[str, object], expected: str
) -> None:
    """A sentence, not a 500 from a violated CHECK."""
    token = register(client, f"bad{uuid.uuid4().hex[:6]}@example.com")
    a = _make_account(client, token, "Everyday", 1_000_00)
    b = _make_account(client, token, "Savings")
    categories = client.get("/categories", headers=_h(token)).json()

    body: dict[str, object] = {
        "kind": "transfer",
        "amount_cents": 10_00,
        "description": "x",
        "occurred_on": a["opened_on"],
        "account_id": a["id"],
        "counter_account_id": b["id"],
    }
    if patch.pop("same_account", False):
        body["counter_account_id"] = a["id"]
    if patch.pop("category", False):
        body["category_id"] = categories[0]["id"]
    body.update(patch)

    res = client.post("/transactions", headers=_h(token), json=body)
    assert res.status_code == 422, res.text
    assert expected in res.json()["detail"]


def test_a_counter_account_must_be_yours(client: TestClient) -> None:
    mine = register(client, "m@example.com")
    theirs = register(client, "t@example.com")
    a = _make_account(client, mine, "Everyday", 1_000_00)
    other = _make_account(client, theirs, "Theirs")

    res = client.post(
        "/transactions",
        headers=_h(mine),
        json={
            "kind": "transfer",
            "amount_cents": 10_00,
            "description": "x",
            "occurred_on": a["opened_on"],
            "account_id": a["id"],
            "counter_account_id": other["id"],
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "Unknown account"


def test_an_account_that_only_receives_transfers_is_not_empty(client: TestClient) -> None:
    """The bug the RESTRICT foreign key would otherwise turn into a 500.

    A destination account has no rows naming it as `account_id`, so a one-sided
    emptiness check calls it deletable and the database then refuses.
    """
    token = register(client, "dest@example.com")
    a = _make_account(client, token, "Everyday", 1_000_00)
    b = _make_account(client, token, "Savings")
    client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "transfer",
            "amount_cents": 10_00,
            "description": "x",
            "occurred_on": a["opened_on"],
            "account_id": a["id"],
            "counter_account_id": b["id"],
        },
    )

    res = client.delete(f"/accounts/{b['id']}", headers=_h(token))
    assert res.status_code == 409
    assert "Archive" in res.json()["detail"]
