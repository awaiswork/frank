"""Exchange rates: which way round they go, and what happens when there isn't one.

An inverted rate is the failure worth designing against here. It produces a number that
looks exactly like money and is wrong by roughly a third — no total flags it, no
constraint catches it, and it would sit in the ledger indefinitely.

So the direction is asserted as a *fact about the world* — a dollar is worth less than a
euro — rather than as arithmetic that would pass just as happily upside down.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import FxRate, Transaction, User
from app.services import fx
from app.services.money import NoRate, in_base
from tests.conftest import create_account as register

FRIDAY = dt.date(2026, 8, 7)
SATURDAY = dt.date(2026, 8, 8)
MONDAY = dt.date(2026, 8, 10)

# What Frankfurter actually returns: how much of each currency one euro buys.
PUBLISHED = {
    "amount": 1.0,
    "base": "EUR",
    "date": "2026-08-07",
    "rates": {"USD": 1.1535, "GBP": 0.85765},
}


def _client(payload: dict[str, object] = PUBLISHED) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _user(db: Session, currency: str = "EUR") -> User:
    user = User(email=f"{uuid.uuid4().hex}@ex.com", password_hash="x", currency=currency)
    db.add(user)
    db.flush()
    return user


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- direction ---------------------------------------------------------------


def test_a_dollar_is_worth_less_than_a_euro(db: Session) -> None:
    """Asserted as a fact, not as arithmetic — the latter passes upside down too."""
    fx.refresh(db, ["EUR"], client=_client())

    found = fx.rate_for(db, base="EUR", quote="USD", on=FRIDAY)
    assert found is not None
    rate, _on = found
    assert rate < 1, "a dollar came out worth more than a euro — the rate is inverted"
    assert rate == pytest.approx(Decimal(1) / Decimal("1.1535"), rel=Decimal("1e-6"))


def test_converting_uses_the_rate_the_right_way_round(db: Session) -> None:
    user = _user(db)
    fx.refresh(db, ["EUR"], client=_client())

    _code, base_cents, _rate = in_base(user, 45_00, currency="USD", db=db, on=FRIDAY)
    # $45 is about €39, not about €52.
    assert 3_800 < base_cents < 4_000


def test_a_pound_is_worth_more_than_a_euro(db: Session) -> None:
    """The other direction, so the test cannot pass by everything being < 1."""
    fx.refresh(db, ["EUR"], client=_client())

    found = fx.rate_for(db, base="EUR", quote="GBP", on=FRIDAY)
    assert found is not None
    assert found[0] > 1


# --- what gets stored --------------------------------------------------------


def test_the_published_date_is_stored_not_the_date_asked_for(db: Session) -> None:
    """The ECB works weekdays. Asking on a Saturday gets Friday's data, and says so."""
    fx.refresh(db, ["EUR"], client=_client())

    rows = list(db.scalars(select(FxRate).where(FxRate.quote == "USD")))
    assert [row.rate_on for row in rows] == [FRIDAY]


def test_a_weekend_resolves_to_the_last_published_rate(db: Session) -> None:
    fx.refresh(db, ["EUR"], client=_client())

    for day in (SATURDAY, MONDAY):
        found = fx.rate_for(db, base="EUR", quote="USD", on=day)
        assert found is not None
        assert found[1] == FRIDAY  # what was actually published


def test_refreshing_twice_stores_one_row_per_day(db: Session) -> None:
    fx.refresh(db, ["EUR"], client=_client())
    fx.refresh(db, ["EUR"], client=_client())

    assert len(list(db.scalars(select(FxRate).where(FxRate.quote == "USD")))) == 1


def test_a_provider_failure_leaves_yesterdays_rates_standing(db: Session) -> None:
    """A missed refresh is survivable; a crash during one is not."""
    fx.refresh(db, ["EUR"], client=_client())

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert fx.refresh(db, ["EUR"], client=httpx.Client(transport=httpx.MockTransport(boom))) == 0
    assert fx.rate_for(db, base="EUR", quote="USD", on=MONDAY) is not None


def test_nothing_is_stored_against_itself(db: Session) -> None:
    fx.refresh(db, ["EUR"], client=_client({**PUBLISHED, "rates": {"EUR": 1.0, "USD": 1.1535}}))
    assert db.scalar(select(FxRate).where(FxRate.quote == "EUR")) is None


# --- converting, and refusing to guess ---------------------------------------


def test_the_amount_you_were_actually_charged_wins(db: Session) -> None:
    """A statement showing both numbers beats any mid-market rate."""
    user = _user(db)
    fx.refresh(db, ["EUR"], client=_client())

    code, base_cents, rate = in_base(
        user, 45_00, currency="USD", base_amount_cents=41_20, db=db, on=FRIDAY
    )
    assert (code, base_cents) == ("USD", 41_20)
    # Derived from what happened, not from what was published.
    assert rate == Decimal(41_20) / Decimal(45_00)


def test_no_rate_and_no_amount_is_refused_rather_than_guessed(db: Session) -> None:
    user = _user(db)
    with pytest.raises(NoRate):
        in_base(user, 45_00, currency="USD", db=db, on=FRIDAY)


def test_your_own_currency_needs_no_rate_at_all(db: Session) -> None:
    user = _user(db)
    code, base_cents, rate = in_base(user, 45_00, currency="EUR", db=db, on=FRIDAY)
    assert (code, base_cents, rate) == ("EUR", 45_00, Decimal(1))


# --- through the API ---------------------------------------------------------


def test_logging_a_foreign_expense_records_both_figures(client: TestClient, db: Session) -> None:
    token = register(client, "fx@example.com")
    fx.refresh(db, ["EUR"], client=_client())

    made = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 45_00,
            "currency": "USD",
            "base_amount_cents": 41_20,
            "description": "dinner in New York",
            "occurred_on": FRIDAY.isoformat(),
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["amount_cents"], body["currency"]) == (45_00, "USD")
    assert body["base_amount_cents"] == 41_20

    # And it is the euro figure that reaches the reports.
    summary = client.get(f"/insights/summary?month={FRIDAY.strftime('%Y-%m')}", headers=_h(token))
    assert summary.json()["safe_to_spend"]["spent_cents"] == 41_20


def test_a_foreign_amount_with_no_rate_asks_instead_of_inventing(client: TestClient) -> None:
    token = register(client, "norate@example.com")
    res = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 45_00,
            "currency": "USD",
            "description": "dinner",
            "occurred_on": "2020-01-02",
        },
    )
    assert res.status_code == 422
    assert "Enter what it came to" in res.json()["detail"]


def test_a_later_rate_never_moves_a_recorded_transaction(client: TestClient, db: Session) -> None:
    """8a's rule, re-asserted through the real path rather than by editing a column."""
    token = register(client, "frozen@example.com")
    fx.refresh(db, ["EUR"], client=_client())
    client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 45_00,
            "currency": "USD",
            "description": "dinner",
            "occurred_on": FRIDAY.isoformat(),
        },
    )
    before = client.get(
        f"/insights/summary?month={FRIDAY.strftime('%Y-%m')}", headers=_h(token)
    ).json()["safe_to_spend"]["spent_cents"]

    # The euro collapses overnight. Nothing already recorded may move.
    fx.refresh(
        db,
        ["EUR"],
        client=_client({**PUBLISHED, "date": "2026-08-10", "rates": {"USD": 4.0}}),
    )
    after = client.get(
        f"/insights/summary?month={FRIDAY.strftime('%Y-%m')}", headers=_h(token)
    ).json()["safe_to_spend"]["spent_cents"]
    assert after == before


def test_the_refresh_endpoint_needs_the_shared_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cron_secret", "")
    assert client.post("/internal/fx/refresh").status_code == 503

    monkeypatch.setattr(get_settings(), "cron_secret", "right")
    assert (
        client.post("/internal/fx/refresh", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_transactions_still_default_to_your_own_currency(client: TestClient) -> None:
    """Everything that was working keeps working without saying anything new."""
    token = register(client, "plain@example.com")
    made = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 30_00,
            "description": "coffee",
            "occurred_on": FRIDAY.isoformat(),
        },
    ).json()
    assert made["currency"] == "EUR"
    assert made["base_amount_cents"] == made["amount_cents"]


def test_a_foreign_transaction_is_stored_with_its_rate(client: TestClient, db: Session) -> None:
    token = register(client, "stored@example.com")
    fx.refresh(db, ["EUR"], client=_client())
    made = client.post(
        "/transactions",
        headers=_h(token),
        json={
            "kind": "expense",
            "amount_cents": 45_00,
            "currency": "USD",
            "description": "dinner",
            "occurred_on": FRIDAY.isoformat(),
        },
    ).json()

    row = db.scalar(select(Transaction).where(Transaction.id == uuid.UUID(made["id"])))
    assert row is not None
    assert row.fx_rate < 1
    assert row.base_amount_cents == int(Decimal(45_00) * row.fx_rate)
