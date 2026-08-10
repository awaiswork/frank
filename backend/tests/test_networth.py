"""Net worth over time — derived, and why that is the whole point.

The argument against snapshots is not tidiness. A snapshot is a frozen guess taken by
whatever ran at the time; it cannot be corrected by later information, and when it
disagrees with the ledger there is no way to tell which is right.

`test_a_backdated_valuation_rewrites_the_trend` and
`test_a_backdated_transaction_moves_every_later_point` are that argument, made twice.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Account, Asset, AssetValuation, User
from app.services.networth import net_worth, series_dates
from tests.conftest import create_account as register
from tests.conftest import transaction

TODAY = dt.date(2026, 8, 10)
OPENED = dt.date(2026, 1, 1)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user(db: Session) -> User:
    user = User(email=f"{uuid.uuid4().hex}@ex.com", password_hash="x", currency="EUR")
    db.add(user)
    db.flush()
    return user


def _account(db: Session, user: User, opening: int = 0, opened_on: dt.date = OPENED) -> Account:
    account = Account(
        user_id=user.id,
        name=f"Acct {uuid.uuid4().hex[:6]}",
        type="current",
        currency="EUR",
        opening_balance_cents=opening,
        opened_on=opened_on,
    )
    db.add(account)
    db.flush()
    return account


def _asset(db: Session, user: User, name: str = "Car", group: str = "physical") -> Asset:
    asset = Asset(user_id=user.id, name=name, group=group)
    db.add(asset)
    db.flush()
    return asset


def _value(db: Session, asset: Asset, cents: int, on: dt.date) -> None:
    db.add(AssetValuation(asset_id=asset.id, valued_on=on, value_cents=cents))
    db.flush()


def _at(db: Session, user: User, on: dt.date) -> int:
    """Total on one date, by asking for a series ending there."""
    return net_worth(db, user.id, today=on, months=2).points[-1].total_cents


# --- the shape of the series -------------------------------------------------


def test_the_series_ends_today_and_walks_back_by_month() -> None:
    dates = series_dates(dt.date(2026, 8, 10), months=4)
    assert dates == [
        dt.date(2026, 5, 31),
        dt.date(2026, 6, 30),
        dt.date(2026, 7, 31),
        dt.date(2026, 8, 10),
    ]


def test_month_ends_survive_february_and_the_year_turn() -> None:
    assert dt.date(2028, 2, 29) in series_dates(dt.date(2028, 3, 15), months=3)
    assert dt.date(2025, 12, 31) in series_dates(dt.date(2026, 2, 5), months=4)


# --- the argument against snapshots ------------------------------------------


def test_a_backdated_valuation_rewrites_the_trend(db: Session) -> None:
    """Saying today what a car was worth in March corrects March.

    A snapshot taken in March could not be corrected by information that arrived in
    August; it would sit there, wrong, disagreeing with everything else.
    """
    user = _user(db)
    car = _asset(db, user)
    _value(db, car, 8_000_00, dt.date(2026, 8, 1))

    march = dt.date(2026, 3, 31)
    assert _at(db, user, march) == 0  # nothing was known about the car then

    _value(db, car, 9_500_00, dt.date(2026, 3, 1))
    assert _at(db, user, march) == 9_500_00
    # And the later statement still governs later dates.
    assert _at(db, user, TODAY) == 8_000_00


def test_a_backdated_transaction_moves_every_later_point(db: Session) -> None:
    user = _user(db)
    account = _account(db, user, opening=1_000_00)

    before = [p.total_cents for p in net_worth(db, user.id, today=TODAY).points]
    db.add(
        transaction(
            user_id=user.id,
            account_id=account.id,
            kind="expense",
            amount_cents=100_00,
            description="forgotten",
            occurred_on=dt.date(2026, 4, 15),
        )
    )
    db.flush()
    after = [p.total_cents for p in net_worth(db, user.id, today=TODAY).points]

    # April onward is 100 lower; anything before April is untouched.
    assert after != before
    assert all(a <= b for a, b in zip(after, before, strict=True))
    assert after[-1] == before[-1] - 100_00


# --- what counts, and when ---------------------------------------------------


def test_an_account_contributes_nothing_before_it_opened(db: Session) -> None:
    """Otherwise opening an account today would invent wealth last March."""
    user = _user(db)
    _account(db, user, opening=500_00, opened_on=dt.date(2026, 7, 1))

    assert _at(db, user, dt.date(2026, 6, 30)) == 0
    assert _at(db, user, dt.date(2026, 7, 1)) == 500_00


def test_an_asset_holds_its_last_stated_value_until_restated(db: Session) -> None:
    user = _user(db)
    car = _asset(db, user)
    _value(db, car, 10_000_00, dt.date(2026, 1, 15))
    _value(db, car, 8_000_00, dt.date(2026, 6, 1))

    assert _at(db, user, dt.date(2026, 5, 31)) == 10_000_00
    assert _at(db, user, dt.date(2026, 6, 30)) == 8_000_00


def test_archiving_drops_an_asset_without_erasing_its_past(db: Session) -> None:
    """Selling needs no special case — the trend falls on the day it goes."""
    user = _user(db)
    car = _asset(db, user)
    _value(db, car, 8_000_00, dt.date(2026, 1, 15))
    car.archived_at = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
    db.flush()

    assert _at(db, user, dt.date(2026, 6, 30)) == 8_000_00
    assert _at(db, user, dt.date(2026, 7, 31)) == 0


def test_accounts_and_assets_are_added_together(db: Session) -> None:
    user = _user(db)
    _account(db, user, opening=1_200_00)
    car = _asset(db, user)
    _value(db, car, 8_000_00, OPENED)

    point = net_worth(db, user.id, today=TODAY).points[-1]
    assert (point.accounts_cents, point.assets_cents) == (1_200_00, 8_000_00)
    assert point.total_cents == 9_200_00


def test_moving_money_never_moves_net_worth_at_any_point(db: Session) -> None:
    """Conservation from 2a, now across the whole series rather than at one instant."""
    user = _user(db)
    a = _account(db, user, opening=1_000_00)
    b = _account(db, user, opening=0)
    before = [p.total_cents for p in net_worth(db, user.id, today=TODAY).points]

    db.add(
        transaction(
            user_id=user.id,
            account_id=a.id,
            counter_account_id=b.id,
            kind="transfer",
            amount_cents=400_00,
            description="to savings",
            occurred_on=dt.date(2026, 5, 5),
        )
    )
    db.flush()

    assert [p.total_cents for p in net_worth(db, user.id, today=TODAY).points] == before


# --- the honesty flag --------------------------------------------------------


def test_complete_from_is_none_with_nothing_on_file(db: Session) -> None:
    assert net_worth(db, _user(db).id, today=TODAY).complete_from is None


def test_complete_from_marks_where_the_line_becomes_comparable(db: Session) -> None:
    """Value a car today and net worth rises by a car — nothing was gained.

    Before this date the line is missing something now on file, so a screen must not
    let that stretch read as a trend.
    """
    user = _user(db)
    _account(db, user, opening=1_000_00, opened_on=dt.date(2026, 1, 1))
    car = _asset(db, user)
    _value(db, car, 8_000_00, dt.date(2026, 6, 1))

    assert net_worth(db, user.id, today=TODAY).complete_from == dt.date(2026, 6, 1)


def test_an_archived_asset_does_not_hold_complete_from_hostage(db: Session) -> None:
    """Something sold is no longer missing from the past — it is accounted for."""
    user = _user(db)
    _account(db, user, opening=1_000_00, opened_on=dt.date(2026, 1, 1))
    sold = _asset(db, user, name="Old bike")
    _value(db, sold, 300_00, dt.date(2026, 7, 20))
    sold.archived_at = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    db.flush()

    assert net_worth(db, user.id, today=TODAY).complete_from == dt.date(2026, 1, 1)


# --- through the API ---------------------------------------------------------


def test_asset_round_trip_and_staleness(client: TestClient) -> None:
    token = register(client, "asset@example.com")
    made = client.post(
        "/assets",
        headers=_h(token),
        json={"name": "Car", "group": "physical", "value_cents": 8_000_00},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["value_cents"] == 8_000_00
    assert body["days_since_valued"] == 0

    old = client.post(
        f"/assets/{body['id']}/valuations",
        headers=_h(token),
        json={"value_cents": 7_000_00, "valued_on": "2026-01-01"},
    )
    assert old.status_code == 200
    # The newest statement still governs "what is it worth now".
    assert old.json()["value_cents"] == 8_000_00


def test_restating_the_same_day_replaces_rather_than_duplicates(client: TestClient) -> None:
    token = register(client, "twice@example.com")
    made = client.post(
        "/assets", headers=_h(token), json={"name": "Flat", "value_cents": 100_00}
    ).json()

    on = made["last_valued_on"]
    fixed = client.post(
        f"/assets/{made['id']}/valuations",
        headers=_h(token),
        json={"value_cents": 250_00, "valued_on": on},
    )
    assert fixed.status_code == 200
    assert fixed.json()["value_cents"] == 250_00


def test_net_worth_endpoint_returns_a_series(client: TestClient) -> None:
    token = register(client, "nw@example.com")
    client.post(
        "/accounts",
        headers=_h(token),
        json={"name": "Everyday", "type": "current", "opening_balance_cents": 1_000_00},
    )
    client.post("/assets", headers=_h(token), json={"name": "Car", "value_cents": 8_000_00})

    body = client.get("/assets/net-worth", headers=_h(token)).json()
    assert len(body["points"]) == 12
    assert body["points"][-1]["total_cents"] == 9_000_00
    assert body["complete_from"] is not None


def test_assets_are_scoped_to_the_owner(client: TestClient) -> None:
    mine = register(client, "amine@example.com")
    theirs = register(client, "atheirs@example.com")
    other = client.post(
        "/assets", headers=_h(theirs), json={"name": "Car", "value_cents": 100}
    ).json()

    assert (
        client.post(
            f"/assets/{other['id']}/valuations", headers=_h(mine), json={"value_cents": 1}
        ).status_code
        == 404
    )
    assert client.get("/assets", headers=_h(mine)).json() == []


def test_duplicate_asset_names_are_refused(client: TestClient) -> None:
    token = register(client, "dupe-asset@example.com")
    payload = {"name": "Car", "value_cents": 100}
    assert client.post("/assets", headers=_h(token), json=payload).status_code == 201
    assert (
        client.post("/assets", headers=_h(token), json={**payload, "name": "car"}).status_code
        == 409
    )
