"""Recurring templates: the date arithmetic, and turning what is due into real rows.

The arithmetic gets tested on its own because that is where a feature like this
actually breaks — month ends, leap years, the turn of the year — and none of it needs
a database to be wrong.

The rest is about one rule: **generation only ever moves forward.** Asking the
transactions table "is there a row for this date?" would resurrect an entry the user
deleted, on their next page load, for ever.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import RecurringTemplate, Transaction, User
from app.services.recurring import materialise_due, occurrences
from tests.conftest import create_account as register


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _dates(**kw: object) -> list[dt.date]:
    return list(occurrences(**kw))  # type: ignore[arg-type]


# --- the arithmetic ----------------------------------------------------------


def test_monthly_tracks_the_anchor_across_short_months() -> None:
    """The 31st becomes the 28th in February and goes *back* to the 31st in March.

    Adding a month to the previous result instead would drift down to the 28th and stay
    there — rent would silently move three days earlier for the rest of time.
    """
    assert _dates(
        cadence="monthly",
        start_on=dt.date(2026, 1, 31),
        end_on=None,
        through=dt.date(2026, 5, 31),
    ) == [
        dt.date(2026, 1, 31),
        dt.date(2026, 2, 28),
        dt.date(2026, 3, 31),
        dt.date(2026, 4, 30),
        dt.date(2026, 5, 31),
    ]


def test_monthly_handles_a_leap_february() -> None:
    assert dt.date(2028, 2, 29) in _dates(
        cadence="monthly",
        start_on=dt.date(2028, 1, 31),
        end_on=None,
        through=dt.date(2028, 3, 1),
    )


def test_weekly_and_yearly_roll_over_the_year() -> None:
    assert _dates(
        cadence="weekly",
        start_on=dt.date(2026, 12, 21),
        end_on=None,
        through=dt.date(2027, 1, 11),
    ) == [
        dt.date(2026, 12, 21),
        dt.date(2026, 12, 28),
        dt.date(2027, 1, 4),
        dt.date(2027, 1, 11),
    ]
    assert _dates(
        cadence="yearly",
        start_on=dt.date(2024, 2, 29),
        end_on=None,
        through=dt.date(2026, 3, 1),
    ) == [dt.date(2024, 2, 29), dt.date(2025, 2, 28), dt.date(2026, 2, 28)]


def test_end_on_and_after_bound_the_walk() -> None:
    common = {"cadence": "monthly", "start_on": dt.date(2026, 1, 15)}
    assert _dates(**common, end_on=dt.date(2026, 3, 1), through=dt.date(2026, 6, 1)) == [
        dt.date(2026, 1, 15),
        dt.date(2026, 2, 15),
    ]
    # `after` is exclusive, so a caller can pass the last date it already handled.
    assert _dates(
        **common, end_on=None, through=dt.date(2026, 4, 1), after=dt.date(2026, 2, 15)
    ) == [dt.date(2026, 3, 15)]


def test_nothing_is_generated_before_it_is_due() -> None:
    """A rent payment due next month is a plan, not money that has left."""
    assert (
        _dates(
            cadence="monthly",
            start_on=dt.date(2026, 9, 1),
            end_on=None,
            through=dt.date(2026, 8, 10),
        )
        == []
    )


# --- materialising -----------------------------------------------------------


def _user(db: Session) -> User:
    user = User(email=f"{uuid.uuid4().hex}@ex.com", password_hash="x", currency="EUR")
    db.add(user)
    db.flush()
    return user


def _template(db: Session, user: User, **kw: object) -> RecurringTemplate:
    template = RecurringTemplate(
        user_id=user.id,
        name=kw.pop("name", "Rent"),
        kind=kw.pop("kind", "expense"),
        amount_cents=kw.pop("amount_cents", 800_00),
        cadence=kw.pop("cadence", "monthly"),
        start_on=kw.pop("start_on", dt.date(2026, 6, 1)),
        **kw,
    )
    db.add(template)
    db.flush()
    return template


def _rows(db: Session, user: User) -> list[Transaction]:
    return list(
        db.scalars(
            select(Transaction)
            .where(Transaction.user_id == user.id)
            .order_by(Transaction.occurred_on)
        )
    )


def test_materialising_writes_what_is_due_and_stops_at_today(db: Session) -> None:
    user = _user(db)
    _template(db, user, start_on=dt.date(2026, 6, 1))

    created = materialise_due(db, user, dt.date(2026, 8, 10))
    assert created == 3  # June, July, August — not September
    assert [r.occurred_on for r in _rows(db, user)] == [
        dt.date(2026, 6, 1),
        dt.date(2026, 7, 1),
        dt.date(2026, 8, 1),
    ]
    assert all(r.source == "recurring" for r in _rows(db, user))


def test_reading_twice_materialises_once(db: Session) -> None:
    user = _user(db)
    _template(db, user)
    today = dt.date(2026, 8, 10)

    assert materialise_due(db, user, today) == 3
    assert materialise_due(db, user, today) == 0
    assert len(_rows(db, user)) == 3


def test_a_deleted_occurrence_does_not_come_back(db: Session) -> None:
    """The rule the whole design turns on.

    Generation resumes from `last_materialised_on`, never from "does a row exist", so
    removing a payment that did not actually happen makes it stay gone.
    """
    user = _user(db)
    _template(db, user)
    today = dt.date(2026, 8, 10)
    materialise_due(db, user, today)

    july = next(r for r in _rows(db, user) if r.occurred_on == dt.date(2026, 7, 1))
    db.delete(july)
    db.flush()
    assert len(_rows(db, user)) == 2

    assert materialise_due(db, user, today) == 0
    assert len(_rows(db, user)) == 2


def test_an_archived_template_stops_generating(db: Session) -> None:
    user = _user(db)
    template = _template(db, user)
    template.archived_at = dt.datetime.now(dt.UTC)
    db.flush()

    assert materialise_due(db, user, dt.date(2026, 8, 10)) == 0
    assert _rows(db, user) == []


def test_end_on_stops_generation(db: Session) -> None:
    user = _user(db)
    _template(db, user, start_on=dt.date(2026, 6, 1), end_on=dt.date(2026, 7, 5))

    assert materialise_due(db, user, dt.date(2026, 8, 10)) == 2
    assert [r.occurred_on for r in _rows(db, user)] == [
        dt.date(2026, 6, 1),
        dt.date(2026, 7, 1),
    ]


def test_generated_rows_are_ordinary_spending(db: Session) -> None:
    """Nothing downstream should need to know a row was generated."""
    from app.services.aggregates import safe_to_spend

    user = _user(db)
    user.monthly_income_cents = 300_000
    _template(db, user, amount_cents=800_00, start_on=dt.date(2026, 8, 1))
    materialise_due(db, user, dt.date(2026, 8, 10))

    assert (
        safe_to_spend(db, user.id, user.monthly_income_cents, dt.date(2026, 8, 1)).spent_cents
        == 800_00
    )


def test_a_second_pass_cannot_duplicate_a_row(db: Session) -> None:
    """The unique index, not the service, is what makes concurrency safe.

    Simulated by winding `last_materialised_on` back — the state two requests would see
    if they read it at the same moment.
    """
    user = _user(db)
    template = _template(db, user)
    today = dt.date(2026, 8, 10)
    materialise_due(db, user, today)

    template.last_materialised_on = None
    db.flush()
    assert materialise_due(db, user, today) == 0  # the index refuses the duplicates
    assert len(_rows(db, user)) == 3


# --- the routes that must be up to date --------------------------------------


def test_every_money_route_is_up_to_date() -> None:
    """Every route that reports money must generate what is due before counting it.

    Four routers is three places to forget, so this asserts the dependency rather than
    trusting a convention. A money-reading route added without it fails here.
    """
    app = create_app()
    money_reads = {
        ("GET", "/transactions"),
        ("GET", "/insights/summary"),
        ("GET", "/budgets"),
        ("GET", "/accounts"),
        # Reports no totals, but `next_on` is derived from how far generation has
        # reached — without this it could name a date after one that had not been
        # written yet.
        ("GET", "/recurring"),
    }
    seen = set()
    for route in app.routes:
        methods: set[str] = getattr(route, "methods", set())
        path: str = getattr(route, "path", "")
        for method in methods:
            if (method, path) not in money_reads:
                continue
            seen.add((method, path))
            names = [d.dependency.__name__ for d in getattr(route, "dependencies", [])]
            assert "bring_ledger_up_to_date" in names, (
                f"{method} {path} reports money without generating what is due first — "
                "a recurring payment would be missing from it until some other screen "
                "was opened."
            )
    assert seen == money_reads, f"never checked: {money_reads - seen}"


# --- through the API ---------------------------------------------------------


def test_recurring_crud_and_next_date(client: TestClient) -> None:
    token = register(client, "rec@example.com")
    made = client.post(
        "/recurring",
        headers=_h(token),
        json={"name": "Rent", "amount_cents": 800_00, "cadence": "monthly"},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["next_on"] is not None

    listed = client.get("/recurring", headers=_h(token)).json()
    assert [r["name"] for r in listed] == ["Rent"]

    raised = client.patch(
        f"/recurring/{body['id']}", headers=_h(token), json={"amount_cents": 850_00}
    )
    assert raised.status_code == 200
    assert raised.json()["amount_cents"] == 850_00


def test_editing_a_template_leaves_generated_rows_alone(client: TestClient) -> None:
    """A rent rise does not change what last month cost."""
    token = register(client, "raise@example.com")
    made = client.post(
        "/recurring",
        headers=_h(token),
        json={
            "name": "Rent",
            "amount_cents": 800_00,
            "cadence": "monthly",
            "start_on": "2026-01-01",
        },
    ).json()

    before = client.get("/transactions", headers=_h(token)).json()
    assert before and all(t["amount_cents"] == 800_00 for t in before)

    client.patch(f"/recurring/{made['id']}", headers=_h(token), json={"amount_cents": 900_00})
    after = client.get("/transactions", headers=_h(token)).json()
    assert [t["amount_cents"] for t in after] == [t["amount_cents"] for t in before]


def test_deleting_a_template_keeps_the_money_that_moved(client: TestClient) -> None:
    token = register(client, "keep@example.com")
    made = client.post(
        "/recurring",
        headers=_h(token),
        json={
            "name": "Rent",
            "amount_cents": 800_00,
            "cadence": "monthly",
            "start_on": "2026-01-01",
        },
    ).json()
    generated = client.get("/transactions", headers=_h(token)).json()
    assert generated

    assert client.delete(f"/recurring/{made['id']}", headers=_h(token)).status_code == 204
    after = client.get("/transactions", headers=_h(token)).json()
    assert len(after) == len(generated)
    assert all(t["recurring_template_id"] is None for t in after)


def test_a_template_cannot_borrow_someone_elses_category(client: TestClient) -> None:
    mine = register(client, "rmine@example.com")
    theirs = register(client, "rtheirs@example.com")
    other_category = client.get("/categories", headers=_h(theirs)).json()[0]

    res = client.post(
        "/recurring",
        headers=_h(mine),
        json={"name": "X", "amount_cents": 100, "category_id": other_category["id"]},
    )
    assert res.status_code == 422


@pytest.mark.parametrize("field", ["amount_cents", "cadence"])
def test_bad_templates_are_refused(client: TestClient, field: str) -> None:
    token = register(client, f"bad{field}@example.com")
    body: dict[str, object] = {"name": "X", "amount_cents": 100, "cadence": "monthly"}
    body[field] = 0 if field == "amount_cents" else "hourly"
    assert client.post("/recurring", headers=_h(token), json=body).status_code == 422
