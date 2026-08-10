"""The forecast, and the double count it exists to avoid.

A budget and a recurring template are two ways of describing the same commitment. Add
them and the rent is reserved twice, so safe-to-spend reads a month's rent lower than
it should — quietly, and in the direction that makes someone spend less than they can.

`_reserved` takes the **larger** of the two per category rather than the sum, which is
right in every shape this comes in and needs no rule telling people how to budget.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Budget, Category, RecurringSkip, RecurringTemplate, User
from app.services.aggregates import SafeToSpend, safe_to_spend
from app.services.recurring import forecast, materialise_due
from tests.conftest import create_account as register

AUGUST = dt.date(2026, 8, 1)
TODAY = dt.date(2026, 8, 10)
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


def _category(db: Session, user: User, name: str = "Bills") -> Category:
    category = Category(user_id=user.id, name=name, kind="expense", color="#fff")
    db.add(category)
    db.flush()
    return category


def _template(db: Session, user: User, **kw: object) -> RecurringTemplate:
    template = RecurringTemplate(
        user_id=user.id,
        name=kw.pop("name", "Rent"),
        kind=kw.pop("kind", "expense"),
        amount_cents=kw.pop("amount_cents", 800_00),
        cadence=kw.pop("cadence", "monthly"),
        # The 25th, so it is still to come relative to TODAY.
        start_on=kw.pop("start_on", dt.date(2026, 8, 25)),
        **kw,
    )
    db.add(template)
    db.flush()
    return template


def _sts(db: Session, user: User) -> SafeToSpend:
    return safe_to_spend(db, user.id, user.monthly_income_cents, AUGUST, today=TODAY)


# --- the landmine ------------------------------------------------------------


def test_a_budget_covering_the_rent_reserves_it_once(db: Session) -> None:
    """The bug this phase exists to prevent.

    Bills is budgeted at 900 and the 800 rent comes out of it. Reserving both would
    hold back 1700 for 900 of commitments and read a month's rent too low.
    """
    user = _user(db)
    bills = _category(db, user)
    db.add(Budget(user_id=user.id, category_id=bills.id, month=AUGUST, limit_cents=900_00))
    _template(db, user, category_id=bills.id, amount_cents=800_00)
    db.flush()

    result = _sts(db, user)
    assert result.remaining_budgets_cents == 900_00  # not 1_700_00
    assert result.upcoming_cents == 800_00
    assert result.safe_to_spend_cents == INCOME - 900_00


def test_rent_with_no_budget_is_still_reserved(db: Session) -> None:
    """Nothing said it was coming before this phase — the money simply vanished later."""
    user = _user(db)
    bills = _category(db, user)
    _template(db, user, category_id=bills.id, amount_cents=800_00)
    db.flush()

    result = _sts(db, user)
    assert result.remaining_budgets_cents == 800_00
    assert result.safe_to_spend_cents == INCOME - 800_00


def test_a_budget_set_too_low_does_not_shrink_the_rent(db: Session) -> None:
    """The rent does not care what limit was written down."""
    user = _user(db)
    bills = _category(db, user)
    db.add(Budget(user_id=user.id, category_id=bills.id, month=AUGUST, limit_cents=100_00))
    _template(db, user, category_id=bills.id, amount_cents=800_00)
    db.flush()

    assert _sts(db, user).remaining_budgets_cents == 800_00


def test_budgets_without_templates_are_unchanged(db: Session) -> None:
    """The behaviour everyone already has must not move."""
    user = _user(db)
    groceries = _category(db, user, "Groceries")
    db.add(Budget(user_id=user.id, category_id=groceries.id, month=AUGUST, limit_cents=400_00))
    db.flush()

    result = _sts(db, user)
    assert result.remaining_budgets_cents == 400_00
    assert result.upcoming_cents == 0


def test_separate_categories_add_up_normally(db: Session) -> None:
    """Only the *same* category competes; different ones are genuinely both."""
    user = _user(db)
    bills = _category(db, user, "Bills")
    groceries = _category(db, user, "Groceries")
    db.add(Budget(user_id=user.id, category_id=groceries.id, month=AUGUST, limit_cents=400_00))
    _template(db, user, category_id=bills.id, amount_cents=800_00)
    db.flush()

    assert _sts(db, user).remaining_budgets_cents == 1_200_00


def test_an_uncategorised_template_is_reserved_on_its_own(db: Session) -> None:
    user = _user(db)
    _template(db, user, category_id=None, amount_cents=50_00)
    db.flush()

    assert _sts(db, user).remaining_budgets_cents == 50_00


# --- what the forecast counts ------------------------------------------------


def test_what_has_already_posted_is_not_forecast_as_well(db: Session) -> None:
    """Materialised occurrences are spending; forecasting them too pays the rent twice."""
    user = _user(db)
    bills = _category(db, user)
    _template(db, user, category_id=bills.id, start_on=dt.date(2026, 8, 1), amount_cents=800_00)
    materialise_due(db, user, TODAY)  # the 1st has arrived

    result = _sts(db, user)
    assert result.spent_cents == 800_00
    assert result.upcoming_cents == 0  # September's is outside August
    assert result.safe_to_spend_cents == INCOME - 800_00


def test_income_templates_are_never_forecast(db: Session) -> None:
    """A recurring salary and `monthly_income_cents` are the same thing said twice."""
    user = _user(db)
    _template(db, user, kind="income", name="Salary", amount_cents=2_000_00, category_id=None)
    db.flush()

    result = _sts(db, user)
    assert result.upcoming_cents == 0
    assert result.income_cents == INCOME


def test_a_skipped_occurrence_is_neither_forecast_nor_written(db: Session) -> None:
    user = _user(db)
    bills = _category(db, user)
    template = _template(db, user, category_id=bills.id, start_on=dt.date(2026, 8, 25))
    db.add(RecurringSkip(template_id=template.id, skip_on=dt.date(2026, 8, 25)))
    db.flush()

    assert _sts(db, user).upcoming_cents == 0
    # And when the day comes it is not written either.
    assert materialise_due(db, user, dt.date(2026, 8, 26)) == 0


def test_the_forecast_stops_at_the_end_of_the_month(db: Session) -> None:
    user = _user(db)
    _template(db, user, category_id=None, start_on=dt.date(2026, 9, 5), amount_cents=99_00)
    db.flush()

    assert _sts(db, user).upcoming_cents == 0
    assert forecast(db, user.id, today=TODAY, through=dt.date(2026, 9, 30)) != {}


def test_a_past_month_forecasts_nothing(db: Session) -> None:
    """Nothing is "still to come" in a month already lived through."""
    user = _user(db)
    _template(db, user, category_id=None, start_on=dt.date(2026, 8, 25))
    db.flush()

    july = safe_to_spend(db, user.id, user.monthly_income_cents, dt.date(2026, 7, 1), today=TODAY)
    assert july.upcoming_cents == 0


# --- through the API ---------------------------------------------------------


def test_upcoming_lists_what_is_still_to_come(client: TestClient) -> None:
    token = register(client, "up@example.com")
    made = client.post(
        "/recurring",
        headers=_h(token),
        json={"name": "Netflix", "amount_cents": 12_00, "cadence": "monthly"},
    ).json()

    rows = client.get("/recurring/upcoming", headers=_h(token)).json()
    assert rows, "a live monthly template should have something ahead of it"
    assert all(r["template_id"] == made["id"] for r in rows)
    assert all(r["skipped"] is False for r in rows)
    # Strictly after today — today's has already been written as a real transaction.
    assert all(r["occurs_on"] > dt.date.today().isoformat() for r in rows)


def test_skipping_and_unskipping_round_trip(client: TestClient) -> None:
    token = register(client, "skip@example.com")
    made = client.post(
        "/recurring",
        headers=_h(token),
        json={"name": "Gym", "amount_cents": 30_00, "cadence": "monthly"},
    ).json()
    first = client.get("/recurring/upcoming", headers=_h(token)).json()[0]

    skipped = client.post(
        f"/recurring/{made['id']}/skips",
        headers=_h(token),
        json={"skip_on": first["occurs_on"]},
    )
    assert skipped.status_code == 204
    rows = {
        r["occurs_on"]: r["skipped"]
        for r in client.get("/recurring/upcoming", headers=_h(token)).json()
    }
    assert rows[first["occurs_on"]] is True

    # Saying it twice means the same thing, not an error.
    assert (
        client.post(
            f"/recurring/{made['id']}/skips",
            headers=_h(token),
            json={"skip_on": first["occurs_on"]},
        ).status_code
        == 204
    )

    undone = client.delete(f"/recurring/{made['id']}/skips/{first['occurs_on']}", headers=_h(token))
    assert undone.status_code == 204
    rows = {
        r["occurs_on"]: r["skipped"]
        for r in client.get("/recurring/upcoming", headers=_h(token)).json()
    }
    assert rows[first["occurs_on"]] is False


@pytest.mark.parametrize("offset", [0, -1])
def test_skipping_a_past_date_is_refused(client: TestClient, offset: int) -> None:
    """By then the row exists — delete it — or generation has moved past it."""
    token = register(client, f"past{offset}@example.com")
    made = client.post(
        "/recurring", headers=_h(token), json={"name": "X", "amount_cents": 100}
    ).json()

    res = client.post(
        f"/recurring/{made['id']}/skips",
        headers=_h(token),
        json={"skip_on": (dt.date.today() + dt.timedelta(days=offset)).isoformat()},
    )
    assert res.status_code == 422
    assert "already passed" in res.json()["detail"]


def test_next_on_steps_over_a_skipped_date(client: TestClient) -> None:
    """Naming a skipped date as "next" asserts a payment the user just cancelled."""
    token = register(client, "nexton@example.com")
    made = client.post(
        "/recurring",
        headers=_h(token),
        json={"name": "Gym", "amount_cents": 30_00, "cadence": "monthly"},
    ).json()
    first = client.get("/recurring/upcoming", headers=_h(token)).json()[0]
    assert made["next_on"] == first["occurs_on"]

    client.post(
        f"/recurring/{made['id']}/skips",
        headers=_h(token),
        json={"skip_on": first["occurs_on"]},
    )
    after = client.get("/recurring", headers=_h(token)).json()[0]
    assert after["next_on"] != first["occurs_on"]


def test_skips_are_scoped_to_the_owner(client: TestClient) -> None:
    mine = register(client, "smine@example.com")
    theirs = register(client, "stheirs@example.com")
    other = client.post(
        "/recurring", headers=_h(theirs), json={"name": "X", "amount_cents": 100}
    ).json()

    res = client.post(
        f"/recurring/{other['id']}/skips",
        headers=_h(mine),
        json={"skip_on": (dt.date.today() + dt.timedelta(days=40)).isoformat()},
    )
    assert res.status_code == 404
