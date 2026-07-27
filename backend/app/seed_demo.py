"""Seed a populated demo account for the public deployment.

A visitor who lands on an empty app sees empty states, which shows none of the
§6 aggregate work (safe-to-spend, budget pace, month-over-month). This writes a
realistic two-month history so Home, Budgets and Insight all have something to
say the moment someone logs in.

Idempotent: it exits if the demo user already exists. Run once after deploy:

    uv run --no-dev python -m app.seed_demo

Deterministic — a fixed RNG seed means the same data every time, so the demo
account doesn't drift between environments.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import Budget, Category, GoalContribution, SavingsGoal, Transaction, User
from app.seed import seed_default_categories

DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@frankly.app")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "frankly-demo-2026")
MONTHLY_INCOME_CENTS = 320_000

RNG_SEED = 20260727

# category name -> (times per month, min cents, max cents, [(description, merchant)])
SPEND_PLAN: list[tuple[str, int, int, int, list[tuple[str, str]]]] = [
    (
        "Groceries",
        9,
        1_800,
        7_400,
        [("Weekly shop", "K-Market"), ("Groceries", "Lidl"), ("Top-up shop", "S-Market")],
    ),
    (
        "Eating out",
        8,
        850,
        3_600,
        [("Lunch", "Hesburger"), ("Coffee", "Kaffa Roastery"), ("Dinner out", "Momotoko")],
    ),
    (
        "Transport",
        5,
        320,
        4_800,
        [("Tram ticket", "HSL"), ("Monthly pass", "HSL"), ("Taxi home", "Bolt")],
    ),
    (
        "Fun",
        4,
        1_200,
        4_500,
        [("Cinema", "Finnkino"), ("Bouldering", "Salmisaari"), ("Records", "Levykauppa Äx")],
    ),
    (
        "Health",
        2,
        1_500,
        6_000,
        [("Pharmacy", "Yliopiston Apteekki"), ("Physio", "Fysios")],
    ),
]

# Fixed monthly commitments — the things that make safe-to-spend realistic.
BILLS: list[tuple[int, int, str, str]] = [
    (3, 95_000, "Rent", "Kojamo"),
    (8, 7_400, "Electricity", "Helen"),
    (8, 2_290, "Internet", "Elisa"),
    (12, 1_190, "Phone", "DNA"),
]

# Tuned against the generated spend so the demo shows a healthy month with one
# category running hot — "Eating out" — which is the story Insight's
# where-the-creep-is callout and the Advisor's evidence rows are built to tell.
# A demo where everything is over budget just reads as alarming.
BUDGETS_EUR: dict[str, int] = {
    "Groceries": 500,
    "Eating out": 180,
    "Transport": 110,
    "Fun": 140,
    "Bills": 1_100,
    "Health": 110,
}


def _month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def _previous_month_start(day: dt.date) -> dt.date:
    return (day.replace(day=1) - dt.timedelta(days=1)).replace(day=1)


def _days_in_month(month: dt.date) -> int:
    nxt = (month.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
    return (nxt - month).days


def _build_month(
    rng: random.Random,
    user_id: object,
    categories: dict[str, Category],
    month: dt.date,
    last_day: int,
) -> list[Transaction]:
    """One month of activity, truncated at `last_day` for the in-progress month."""
    rows: list[Transaction] = []

    def add(category: str, day: int, cents: int, description: str, merchant: str | None) -> None:
        if day > last_day:
            return
        rows.append(
            Transaction(
                user_id=user_id,
                category_id=categories[category].id,
                kind="expense",
                amount_cents=cents,
                description=description,
                merchant=merchant,
                occurred_on=month.replace(day=day),
            )
        )

    # Salary lands on the 1st.
    if last_day >= 1:
        rows.append(
            Transaction(
                user_id=user_id,
                category_id=categories["Income"].id,
                kind="income",
                amount_cents=MONTHLY_INCOME_CENTS,
                description="Salary",
                merchant=None,
                occurred_on=month.replace(day=1),
            )
        )

    for day, cents, description, merchant in BILLS:
        add("Bills", day, cents, description, merchant)

    span = _days_in_month(month)
    for name, count, low, high, labels in SPEND_PLAN:
        for _ in range(count):
            day = rng.randint(1, span)
            description, merchant = labels[rng.randrange(len(labels))]
            add(name, day, rng.randint(low, high), description, merchant)

    return rows


def seed_demo(db: Session) -> bool:
    """Create the demo user and its history. Returns False if it already existed."""
    if db.scalar(select(User).where(User.email == DEMO_EMAIL)) is not None:
        return False

    user = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        monthly_income_cents=MONTHLY_INCOME_CENTS,
    )
    db.add(user)
    db.flush()

    seed_default_categories(db, user.id)
    db.flush()
    categories = {
        c.name: c for c in db.scalars(select(Category).where(Category.user_id == user.id))
    }

    today = dt.date.today()
    this_month = _month_start(today)
    last_month = _previous_month_start(today)

    rng = random.Random(RNG_SEED)
    db.add_all(_build_month(rng, user.id, categories, last_month, _days_in_month(last_month)))
    db.add_all(_build_month(rng, user.id, categories, this_month, today.day))

    for month in (last_month, this_month):
        for name, euros in BUDGETS_EUR.items():
            db.add(
                Budget(
                    user_id=user.id,
                    category_id=categories[name].id,
                    month=month,
                    limit_cents=euros * 100,
                )
            )

    goal = SavingsGoal(
        user_id=user.id,
        name="Japan trip",
        target_cents=250_000,
        due_date=today + dt.timedelta(days=210),
    )
    db.add(goal)
    db.flush()
    for offset, cents in ((60, 40_000), (30, 35_000), (2, 25_000)):
        db.add(
            GoalContribution(
                goal_id=goal.id,
                amount_cents=cents,
                occurred_on=today - dt.timedelta(days=offset),
            )
        )

    db.commit()
    return True


def main() -> int:
    with SessionLocal() as db:
        created = seed_demo(db)
    if created:
        print(f"Seeded demo account: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        return 0
    print(f"Demo account {DEMO_EMAIL} already exists — nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
