"""Lending — an IOU is an account, and everything else was already built.

A person you have lent to is an account whose balance is what is outstanding, and
moving money to or from them is an ordinary transfer. So conservation, the transfer
shape constraint and the exclusion from every spending figure all arrive from Phase 2a
without being restated here. What these test is the part that is new: that one type
plus a sign describes a relationship a receivable/payable pair could not.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import create_account as register


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, token: str, name: str, opening: int = 0) -> dict[str, object]:
    res = client.post(
        "/accounts",
        headers=_h(token),
        json={"name": name, "type": "current", "opening_balance_cents": opening},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def _balances(client: TestClient, token: str) -> dict[str, int]:
    payload = client.get("/accounts", headers=_h(token)).json()
    return {row["name"]: row["balance_cents"] for row in payload["accounts"]}


def _total(client: TestClient, token: str) -> int:
    return int(client.get("/accounts", headers=_h(token)).json()["total_cents"])


def test_lending_moves_money_without_changing_what_you_have(client: TestClient) -> None:
    """Lending is not spending — the money is with someone else, not gone."""
    token = register(client, "lend@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)
    before = _total(client, token)

    res = client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Sam", "amount_cents": 50_00, "account_id": everyday["id"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["type"] == "person"
    assert res.json()["balance_cents"] == 50_00  # positive: Sam owes you

    assert _balances(client, token) == {"Everyday": 950_00, "Sam": 50_00}
    assert _total(client, token) == before


def test_borrowing_drives_the_balance_negative(client: TestClient) -> None:
    token = register(client, "borrow@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)

    res = client.post(
        "/accounts/lend",
        headers=_h(token),
        json={
            "person": "Alex",
            "amount_cents": 100_00,
            "account_id": everyday["id"],
            "borrowing": True,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["balance_cents"] == -100_00  # negative: you owe Alex

    assert _balances(client, token) == {"Everyday": 1_100_00, "Alex": -100_00}


def test_one_person_nets_lending_against_borrowing(client: TestClient) -> None:
    """The case a receivable/payable pair cannot describe.

    Lend Sam 50, borrow 80 back, and the relationship is worth −30 — one number, not
    two accounts for one person that a reader has to net in their head.
    """
    token = register(client, "net@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)

    client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Sam", "amount_cents": 50_00, "account_id": everyday["id"]},
    )
    client.post(
        "/accounts/lend",
        headers=_h(token),
        json={
            "person": "Sam",
            "amount_cents": 80_00,
            "account_id": everyday["id"],
            "borrowing": True,
        },
    )

    balances = _balances(client, token)
    assert balances["Sam"] == -30_00
    assert list(balances).count("Sam") == 1


def test_lending_to_the_same_person_builds_one_balance(client: TestClient) -> None:
    """Matched case-insensitively, the way account names are already unique."""
    token = register(client, "again@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)

    for name, amount in (("Sam", 20_00), ("sam", 30_00)):
        res = client.post(
            "/accounts/lend",
            headers=_h(token),
            json={"person": name, "amount_cents": amount, "account_id": everyday["id"]},
        )
        assert res.status_code == 201, res.text

    balances = _balances(client, token)
    assert balances == {"Everyday": 950_00, "Sam": 50_00}


def test_repaying_settles_the_balance_to_zero(client: TestClient) -> None:
    """A repayment is the same transfer running the other way."""
    token = register(client, "repay@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)
    sam = client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Sam", "amount_cents": 50_00, "account_id": everyday["id"]},
    ).json()

    part = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "transfer",
            "amount_cents": 20_00,
            "description": "Sam paid back",
            "occurred_on": everyday["opened_on"],
            "account_id": sam["id"],
            "counter_account_id": everyday["id"],
        },
    )
    assert part.status_code == 201, part.text
    assert _balances(client, token)["Sam"] == 30_00

    client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "transfer",
            "amount_cents": 30_00,
            "description": "settled",
            "occurred_on": everyday["opened_on"],
            "account_id": sam["id"],
            "counter_account_id": everyday["id"],
        },
    )
    assert _balances(client, token) == {"Everyday": 1_000_00, "Sam": 0}


def test_lending_changes_no_spending_figure(client: TestClient, db: Session) -> None:
    token = register(client, "lendspend@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)
    before = client.get("/insights/summary", headers=_h(token)).json()

    client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Sam", "amount_cents": 50_00, "account_id": everyday["id"]},
    )
    after = client.get("/insights/summary", headers=_h(token)).json()
    assert before == after


def test_lending_refuses_a_name_already_used_by_a_real_account(client: TestClient) -> None:
    """Otherwise "lend to Savings" would quietly turn a savings account into a person."""
    token = register(client, "clash@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)
    _account(client, token, "Savings")

    res = client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Savings", "amount_cents": 10_00, "account_id": everyday["id"]},
    )
    assert res.status_code == 422
    assert "Savings" in res.json()["detail"]


def test_lending_is_scoped_to_the_owner(client: TestClient) -> None:
    mine = register(client, "lmine@example.com")
    theirs = register(client, "ltheirs@example.com")
    other = _account(client, theirs, "Theirs", 1_000_00)

    res = client.post(
        "/accounts/lend",
        headers=_h(mine),
        json={"person": "Sam", "amount_cents": 10_00, "account_id": other["id"]},
    )
    assert res.status_code == 404
    # And no half-made person is left behind by the failure.
    assert client.get("/accounts", headers=_h(mine)).json()["accounts"] == []


def test_lending_again_reopens_an_archived_person(client: TestClient) -> None:
    """A settled IOU gets archived; lending again is a live relationship, not a second one."""
    token = register(client, "reopen@example.com")
    everyday = _account(client, token, "Everyday", 1_000_00)
    sam = client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Sam", "amount_cents": 50_00, "account_id": everyday["id"]},
    ).json()
    client.patch(f"/accounts/{sam['id']}", headers=_h(token), json={"archived": True})
    assert "Sam" not in _balances(client, token)

    res = client.post(
        "/accounts/lend",
        headers=_h(token),
        json={"person": "Sam", "amount_cents": 10_00, "account_id": everyday["id"]},
    )
    assert res.status_code == 201
    assert res.json()["archived_at"] is None
    assert _balances(client, token)["Sam"] == 60_00
    assert uuid.UUID(res.json()["id"]) == uuid.UUID(sam["id"])
