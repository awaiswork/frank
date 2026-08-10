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

from sqlalchemy import ColumnElement, Integer, case, func, select
from sqlalchemy.orm import Session

from app.models import Account, Transaction

# What each kind of entry does to the balance of the account it belongs to.
#
# This is the only sign-based aggregation on the server, and the only place a new
# transaction kind can be silently mishandled: a `CASE ... ELSE 0` would quietly
# contribute nothing for a kind nobody remembered, so a transfer would move no money
# and the balance would just be wrong. `test_balance_signs_cover_every_kind` reads the
# allowed values straight out of the ck_transactions_kind constraint and fails the
# moment this map stops matching them — so widening that CHECK forces a decision here
# rather than allowing an omission.
BALANCE_SIGNS: dict[str, int] = {"income": 1, "expense": -1}


@dataclass(frozen=True)
class AccountBalance:
    account: Account
    balance_cents: int
    entry_count: int


def _signed_amount() -> ColumnElement[int]:
    """SUM(±amount_cents) built from BALANCE_SIGNS, with no catch-all branch."""
    return func.coalesce(
        func.sum(
            case(
                *(
                    (Transaction.kind == kind, Transaction.amount_cents * sign)
                    for kind, sign in BALANCE_SIGNS.items()
                ),
                else_=None,
            )
        ),
        0,
    )


def balances(
    db: Session, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[AccountBalance]:
    """Every account with its derived balance, ordered by type then name.

    Entries dated before ``opened_on`` are excluded on purpose: the opening balance
    already accounts for everything that happened before the ledger started, so
    counting them again would double them. Such an entry still counts toward spending.
    """
    movement = (
        select(
            Transaction.account_id.label("account_id"),
            _signed_amount().label("delta"),
            func.count(Transaction.id).label("entries"),
        )
        .join(Account, Account.id == Transaction.account_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.occurred_on >= Account.opened_on,
        )
        .group_by(Transaction.account_id)
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
    """Whether anything references this account — deletion is only for empty ones."""
    return db.scalar(
        select(func.count(Transaction.id)).where(Transaction.account_id == account_id)
    ) not in (0, None)


def earliest_opened_on(db: Session, user_id: uuid.UUID) -> dt.date | None:
    """When this user's ledger starts, for the "balances count from…" line."""
    return db.scalar(
        select(func.min(Account.opened_on)).where(
            Account.user_id == user_id, Account.archived_at.is_(None)
        )
    )
