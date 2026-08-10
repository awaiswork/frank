"""Account balances — derived on read, never stored.

A balance is ``opening_balance_cents`` plus every signed entry from ``opened_on``
onward. Nothing caches it: editing, deleting or backdating an entry has to move the
balance immediately, and a stored figure that drifts from its own ledger is wrong in
the way that is hardest to notice.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import Integer, case, func, or_, select, union_all
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.models import Account, Transaction

# What one transaction contributes to the balance of each account it touches, as
# (own account, counter account). None means it does not touch that side.
#
# This has to be a *pair* rather than a single sign, and that is the whole reason the
# query below is shaped the way it is. A transfer's effect depends on which account is
# being asked about: it leaves `account_id` and arrives at `counter_account_id`. Under
# the flat {kind: sign} map this started as, the honest-looking fix — "transfer": -1 —
# produces a half transfer, where money leaves the source and never lands anywhere.
# That reads as handled and is worse than the omission it replaces, so the shape of
# this map is what makes it hard to get wrong.
#
# `test_balance_signs_cover_every_kind` reads the permitted values straight out of the
# ck_transactions_kind constraint, so widening that CHECK forces a decision here
# instead of allowing a silent gap.
LEG_SIGNS: dict[str, tuple[int, int | None]] = {
    "income": (1, None),
    "expense": (-1, None),
    "transfer": (-1, 1),
    # Money coming back from a returned purchase. It lands in an account like income
    # does; what makes it a refund rather than income is that it also gives back the
    # spending it undoes — see SPEND_SIGNS in services/aggregates.
    "refund": (1, None),
    # A reconciliation: the difference between what the ledger computed and what the
    # bank actually says. Two kinds rather than one signed amount, so `amount_cents`
    # stays a positive magnitude and direction keeps living in the kind.
    "adjustment_up": (1, None),
    "adjustment_down": (-1, None),
}


@dataclass(frozen=True)
class AccountBalance:
    account: Account
    balance_cents: int
    entry_count: int


def _legs(user_id: uuid.UUID) -> Subquery:
    """One row per (account, signed contribution) — the ledger as double entry.

    A transaction emits a leg for its own account and, when the kind has a counter
    side, a second leg for that. Splitting it this way is what makes conservation a
    property of the shape rather than something to remember: a transfer emits −x and
    +x, so no arrangement of transfers can change the sum of all balances.
    """
    own = select(
        Transaction.account_id.label("account_id"),
        case(
            *(
                # base_amount_cents: while accounts are all in the reporting
                # currency, this is what actually left or arrived in the account.
                (Transaction.kind == kind, Transaction.base_amount_cents * signs[0])
                for kind, signs in LEG_SIGNS.items()
            ),
            else_=None,
        ).label("delta"),
        Transaction.occurred_on.label("occurred_on"),
    ).where(Transaction.user_id == user_id, Transaction.account_id.is_not(None))

    counter_kinds = {k: s[1] for k, s in LEG_SIGNS.items() if s[1] is not None}
    if not counter_kinds:  # pragma: no cover — 'transfer' always has a far side
        return own.subquery()

    counter = select(
        Transaction.counter_account_id.label("account_id"),
        case(
            *(
                (Transaction.kind == kind, Transaction.base_amount_cents * sign)
                for kind, sign in counter_kinds.items()
            ),
            else_=None,
        ).label("delta"),
        Transaction.occurred_on.label("occurred_on"),
    ).where(Transaction.user_id == user_id, Transaction.counter_account_id.is_not(None))

    return union_all(own, counter).subquery()


def balances(
    db: Session, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[AccountBalance]:
    """Every account with its derived balance, ordered by type then name.

    Entries dated before ``opened_on`` are excluded on purpose: the opening balance
    already accounts for everything that happened before the ledger started, so
    counting them again would double them. Such an entry still counts toward spending.
    """
    legs = _legs(user_id)
    movement = (
        select(
            legs.c.account_id.label("account_id"),
            func.coalesce(func.sum(legs.c.delta), 0).label("delta"),
            func.count().label("entries"),
        )
        # Each leg is measured against its *own* account's start date, so a transfer
        # into an account opened last week counts there even if it left an account
        # that has been open for years.
        .join(Account, Account.id == legs.c.account_id)
        .where(legs.c.occurred_on >= Account.opened_on)
        .group_by(legs.c.account_id)
        .subquery()
    )

    stmt = (
        select(
            Account,
            (Account.opening_balance_cents + func.coalesce(movement.c.delta, 0)).label("balance"),
            func.coalesce(movement.c.entries, 0).cast(Integer).label("entries"),
        )
        .join(movement, movement.c.account_id == Account.id, isouter=True)
        .where(Account.user_id == user_id)
        .order_by(Account.type, Account.name)
    )
    if not include_archived:
        stmt = stmt.where(Account.archived_at.is_(None))

    return [
        AccountBalance(
            account=row[0],
            balance_cents=int(row.balance),
            entry_count=int(row.entries),
        )
        for row in db.execute(stmt)
    ]


def has_entries(db: Session, account_id: uuid.UUID) -> bool:
    """Whether anything references this account — deletion is only for empty ones.

    Both sides, deliberately. An account that has only ever been a transfer
    *destination* has no rows naming it as `account_id`, so checking one column would
    call it empty and offer a delete the RESTRICT foreign key then refuses — a 500
    where the user deserved an explanation.
    """
    return db.scalar(
        select(func.count(Transaction.id)).where(
            or_(
                Transaction.account_id == account_id,
                Transaction.counter_account_id == account_id,
            )
        )
    ) not in (0, None)


def earliest_opened_on(db: Session, user_id: uuid.UUID) -> dt.date | None:
    """When this user's ledger starts, for the "balances count from…" line."""
    return db.scalar(
        select(func.min(Account.opened_on)).where(
            Account.user_id == user_id, Account.archived_at.is_(None)
        )
    )
