"""Accounts and their derived balances.

The balance is the first sign-based aggregation on the server, which makes it the first
place a new transaction kind can be silently mishandled. `test_balance_signs_cover_every_kind`
is the guard: it compares BALANCE_SIGNS against the CHECK constraint itself, so widening
the constraint fails the suite until someone says what the new kind does to a balance.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Account, Transaction, User
from app.services.accounts import BALANCE_SIGNS, balances
from tests.conftest import create_account as register

OPENED = dt.date(2026, 6, 1)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user(db: Session) -> User:
    user = User(email=f"{uuid.uuid4().hex}@ex.com", password_hash="x", currency="EUR")
    db.add(user)
    db.flush()
    return user


def _account(db: Session, user: User, name: str = "Current", opening: int = 0) -> Account:
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


def _tx(
    db: Session,
    user: User,
    account: Account | None,
    cents: int,
    on: dt.date,
    kind: str = "expense",
) -> None:
    db.add(
        Transaction(
            user_id=user.id,
            account_id=account.id if account else None,
            kind=kind,
            amount_cents=cents,
            description="t",
            occurred_on=on,
        )
    )
    db.flush()


# --- the guard ---------------------------------------------------------------


def test_balance_signs_cover_every_kind(db: Session) -> None:
    """Every value the CHECK permits must have a decided effect on a balance.

    Read from the constraint rather than hardcoded, so this fails the moment the kinds
    are widened — a `CASE ... ELSE 0` would otherwise contribute nothing for the new
    kind and leave every balance quietly wrong.
    """
    source = db.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_transactions_kind'"
        )
    )
    assert source, "ck_transactions_kind is missing"
    allowed = set(re.findall(r"'([a-z_]+)'", str(source)))

    assert allowed == set(BALANCE_SIGNS), (
        "transactions.kind and BALANCE_SIGNS disagree. A kind with no entry in "
        "BALANCE_SIGNS contributes nothing to a balance, silently. Decide what "
        f"{allowed ^ set(BALANCE_SIGNS)} does to an account balance."
    )


# --- balances ----------------------------------------------------------------


def test_balance_is_opening_plus_signed_entries(db: Session) -> None:
    user = _user(db)
    account = _account(db, user, opening=100_00)
    _tx(db, user, account, 30_00, dt.date(2026, 6, 5))  # expense
    _tx(db, user, account, 250_00, dt.date(2026, 6, 6), kind="income")

    [row] = balances(db, user.id)
    assert row.balance_cents == 100_00 - 30_00 + 250_00
    assert row.entry_count == 2


def test_entries_before_opened_on_are_excluded(db: Session) -> None:
    """The opening balance already contains them; counting them again doubles them."""
    user = _user(db)
    account = _account(db, user, opening=100_00)
    _tx(db, user, account, 40_00, OPENED - dt.timedelta(days=1))
    _tx(db, user, account, 10_00, OPENED)  # on the day itself: counts

    [row] = balances(db, user.id)
    assert row.balance_cents == 100_00 - 10_00
    assert row.entry_count == 1


def test_unassigned_transactions_touch_no_balance(db: Session) -> None:
    """The pre-ledger history stays out of every balance — migration 0007's whole point."""
    user = _user(db)
    _account(db, user, opening=100_00)
    _tx(db, user, None, 75_00, dt.date(2026, 6, 9))

    [row] = balances(db, user.id)
    assert row.balance_cents == 100_00
    assert row.entry_count == 0


def test_liability_balances_go_negative(db: Session) -> None:
    user = _user(db)
    card = Account(
        user_id=user.id,
        name="Card",
        type="liability",
        currency="EUR",
        opening_balance_cents=-200_00,
        opened_on=OPENED,
    )
    db.add(card)
    db.flush()
    _tx(db, user, card, 50_00, dt.date(2026, 6, 4))

    [row] = balances(db, user.id)
    assert row.balance_cents == -250_00


def test_balances_exclude_other_users(db: Session) -> None:
    mine, theirs = _user(db), _user(db)
    _account(db, mine, name="Mine", opening=10_00)
    other = _account(db, theirs, name="Theirs", opening=999_00)
    _tx(db, theirs, other, 5_00, dt.date(2026, 6, 4))

    rows = balances(db, mine.id)
    assert [r.balance_cents for r in rows] == [10_00]


def test_archived_accounts_are_hidden_unless_asked_for(db: Session) -> None:
    user = _user(db)
    _account(db, user, name="Open", opening=10_00)
    old = _account(db, user, name="Closed", opening=20_00)
    old.archived_at = dt.datetime.now(dt.UTC)
    db.flush()

    assert len(balances(db, user.id)) == 1
    assert len(balances(db, user.id, include_archived=True)) == 2


# --- the endpoints -----------------------------------------------------------


def test_account_crud_round_trip(client: TestClient) -> None:
    token = register(client, "acct@example.com")

    made = client.post(
        "/accounts",
        headers=_h(token),
        json={"name": "Everyday", "type": "current", "opening_balance_cents": 500_00},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["balance_cents"] == 500_00
    assert body["currency"] == "EUR"
    assert body["entry_count"] == 0

    listed = client.get("/accounts", headers=_h(token)).json()
    assert listed["total_cents"] == 500_00
    assert listed["ledger_starts_on"] == body["opened_on"]

    renamed = client.patch(f"/accounts/{body['id']}", headers=_h(token), json={"name": "Main"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Main"


def test_account_names_are_unique_per_user(client: TestClient) -> None:
    token = register(client, "dupe@example.com")
    payload = {"name": "Everyday", "type": "current"}
    assert client.post("/accounts", headers=_h(token), json=payload).status_code == 201
    clash = client.post("/accounts", headers=_h(token), json={**payload, "name": "everyday"})
    assert clash.status_code == 409


def test_a_second_currency_is_refused_for_now(client: TestClient) -> None:
    """The column exists; a second value would make every total silently incomparable."""
    token = register(client, "fx@example.com")
    res = client.post(
        "/accounts",
        headers=_h(token),
        json={"name": "US", "type": "current", "currency": "USD"},
    )
    assert res.status_code == 422
    assert "EUR" in res.json()["detail"]


def test_accounts_with_history_are_archived_not_deleted(client: TestClient) -> None:
    token = register(client, "keep@example.com")
    account = client.post(
        "/accounts", headers=_h(token), json={"name": "Everyday", "type": "current"}
    ).json()

    empty = client.post(
        "/accounts", headers=_h(token), json={"name": "Spare", "type": "cash"}
    ).json()
    assert client.delete(f"/accounts/{empty['id']}", headers=_h(token)).status_code == 204

    client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 1000,
            "description": "lunch",
            "occurred_on": account["opened_on"],
            "account_id": account["id"],
        },
    )
    blocked = client.delete(f"/accounts/{account['id']}", headers=_h(token))
    assert blocked.status_code == 409
    assert "Archive" in blocked.json()["detail"]

    archived = client.patch(
        f"/accounts/{account['id']}", headers=_h(token), json={"archived": True}
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert client.get("/accounts", headers=_h(token)).json()["accounts"] == []


def test_transactions_reject_accounts_that_are_not_yours(client: TestClient) -> None:
    mine = register(client, "mine@example.com")
    theirs = register(client, "theirs@example.com")
    other = client.post(
        "/accounts", headers=_h(theirs), json={"name": "Theirs", "type": "current"}
    ).json()

    res = client.post(
        "/transactions",
        headers=_h(mine),
        json={
            "kind": "expense",
            "amount_cents": 500,
            "description": "nope",
            "occurred_on": "2026-06-05",
            "account_id": other["id"],
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "Unknown account"


def test_new_entries_cannot_land_in_an_archived_account(client: TestClient) -> None:
    token = register(client, "closed@example.com")
    account = client.post(
        "/accounts", headers=_h(token), json={"name": "Old", "type": "current"}
    ).json()
    client.patch(f"/accounts/{account['id']}", headers=_h(token), json={"archived": True})

    res = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 500,
            "description": "late",
            "occurred_on": account["opened_on"],
            "account_id": account["id"],
        },
    )
    assert res.status_code == 422
    assert "archived" in res.json()["detail"]


def test_spending_aggregates_ignore_accounts_entirely(client: TestClient, db: Session) -> None:
    """Assigning an account must not change a single spending figure.

    The six expense/income aggregates filter on kind, never on account, and this pins
    that: the same two transactions produce the same insights whether or not they sit
    in an account.
    """
    token = register(client, "same@example.com")
    account = client.post(
        "/accounts", headers=_h(token), json={"name": "Everyday", "type": "current"}
    ).json()
    on = account["opened_on"]

    for account_id in (None, account["id"]):
        client.post(
            "/transactions",
            headers=_h(token),
            json={
                "kind": "expense",
                "amount_cents": 20_00,
                "description": "coffee",
                "occurred_on": on,
                "account_id": account_id,
            },
        )

    summary = client.get("/insights/summary", headers=_h(token)).json()
    assert summary["safe_to_spend"]["spent_cents"] == 40_00
