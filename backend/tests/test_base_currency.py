"""Reports read the base amount, not the amount as it happened.

Nothing user-facing changes here: every row still records the same money, because a
single-currency ledger really was in that currency at a rate of exactly one. What
changes is *which column* every figure adds up — and until a row exists where the two
differ, that swap is unverifiable by the rest of the suite, which is what these are for.

The rule underneath: `base_amount_cents` is stored, never recomputed. A report that
multiplied by a rate at read time would move last March's spending because the euro
moved this morning.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction, User
from app.services.accounts import balances
from app.services.aggregates import daily_burn_rate, safe_to_spend, spend_by_category
from app.services.networth import net_worth
from tests.conftest import transaction

JUNE = dt.date(2026, 6, 1)
TODAY = dt.date(2026, 6, 15)

# $45.00 that cost €41.20 — the numbers a card statement actually shows.
FOREIGN_CENTS = 45_00
BASE_CENTS = 41_20


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


def _account(db: Session, user: User) -> Account:
    account = Account(
        user_id=user.id,
        name="Everyday",
        type="current",
        currency="EUR",
        opening_balance_cents=1_000_00,
        opened_on=dt.date(2026, 1, 1),
    )
    db.add(account)
    db.flush()
    return account


def _foreign(db: Session, user: User, account: Account, category: Category) -> Transaction:
    """One dinner in New York, recorded as both numbers."""
    tx = transaction(
        user_id=user.id,
        account_id=account.id,
        category_id=category.id,
        kind="expense",
        amount_cents=FOREIGN_CENTS,
        currency="USD",
        base_amount_cents=BASE_CENTS,
        fx_rate=Decimal(BASE_CENTS) / Decimal(FOREIGN_CENTS),
        description="dinner",
        occurred_on=dt.date(2026, 6, 10),
    )
    db.add(tx)
    db.flush()
    return tx


def _category(db: Session, user: User) -> Category:
    category = Category(user_id=user.id, name="Eating out", kind="expense", color="#fff")
    db.add(category)
    db.flush()
    return category


def test_spending_counts_what_it_cost_you_not_what_it_said(db: Session) -> None:
    """The whole sweep in one assertion: 41,20 € of spending, not 45,00."""
    user = _user(db)
    account = _account(db, user)
    category = _category(db, user)
    _foreign(db, user, account, category)

    assert spend_by_category(db, user.id, JUNE)[0].spent_cents == BASE_CENTS
    assert (
        safe_to_spend(db, user.id, user.monthly_income_cents, JUNE, today=TODAY).spent_cents
        == BASE_CENTS
    )
    assert daily_burn_rate(db, user.id, today=TODAY).total_spent_cents == BASE_CENTS


def test_the_balance_falls_by_what_left_the_account(db: Session) -> None:
    """The card was charged in euros — the account moved by the euro figure."""
    user = _user(db)
    account = _account(db, user)
    _foreign(db, user, account, _category(db, user))

    assert balances(db, user.id)[0].balance_cents == 1_000_00 - BASE_CENTS


def test_net_worth_uses_the_base_figure_too(db: Session) -> None:
    user = _user(db)
    account = _account(db, user)
    _foreign(db, user, account, _category(db, user))

    assert net_worth(db, user.id, today=TODAY).points[-1].total_cents == 1_000_00 - BASE_CENTS


def test_the_original_amount_survives_untouched(db: Session) -> None:
    """Both numbers are kept: what was paid, and what it came to.

    Losing the foreign figure would mean the row could never say "$45" again — the app
    would remember only its own translation of an event, not the event.
    """
    user = _user(db)
    tx = _foreign(db, user, _account(db, user), _category(db, user))

    stored = db.scalar(select(Transaction).where(Transaction.id == tx.id))
    assert stored is not None
    assert (stored.amount_cents, stored.currency) == (FOREIGN_CENTS, "USD")
    assert stored.base_amount_cents == BASE_CENTS


def test_a_rate_change_cannot_move_a_recorded_total(db: Session) -> None:
    """The reason the converted figure is stored rather than derived.

    Rewriting `fx_rate` to something absurd — as a later rate revision would — leaves
    every reported figure exactly where it was, because nothing multiplies at read time.
    """
    user = _user(db)
    account = _account(db, user)
    tx = _foreign(db, user, account, _category(db, user))
    before = spend_by_category(db, user.id, JUNE)[0].spent_cents

    tx.fx_rate = Decimal("99.5")
    db.flush()

    assert spend_by_category(db, user.id, JUNE)[0].spent_cents == before
    assert balances(db, user.id)[0].balance_cents == 1_000_00 - BASE_CENTS


def test_everything_already_recorded_is_unchanged(db: Session) -> None:
    """The backfill is the truth about those rows, not a stand-in for it."""
    user = _user(db)
    account = _account(db, user)
    category = _category(db, user)
    db.add(
        transaction(
            user_id=user.id,
            account_id=account.id,
            category_id=category.id,
            kind="expense",
            amount_cents=30_00,
            description="domestic",
            occurred_on=dt.date(2026, 6, 5),
        )
    )
    db.flush()

    stored = db.scalar(select(Transaction).where(Transaction.user_id == user.id))
    assert stored is not None
    assert stored.currency == "EUR"
    assert stored.base_amount_cents == stored.amount_cents
    assert stored.fx_rate == Decimal(1)
    assert spend_by_category(db, user.id, JUNE)[0].spent_cents == 30_00
