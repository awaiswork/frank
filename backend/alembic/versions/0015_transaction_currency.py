"""what a transaction was in, and what it came to in your own money

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-10

Groundwork only: after this every row still says exactly what it said before, because
the backfill is not a guess. Everything captured while there was one currency really was
in that currency, at a rate of exactly one — so `currency = users.currency`,
`fx_rate = 1`, `base_amount_cents = amount_cents` is the truth about those rows rather
than an assumption stood in for it.

`amount_cents` keeps meaning **what the transaction was in its own currency** (one-way
door 2, decided before accounts existed). `base_amount_cents` is what that came to in the
user's reporting currency, **frozen at the moment it was recorded**.

That freezing is the whole point. Converting at read time would mean every historical
total moved whenever a rate moved — last March's spending changing because the euro did
something this morning. Reports read `base_amount_cents` and never a rate.

`fx_rate` is stored alongside for the audit trail: it is what *was* used, whether that
came from a published rate, a stale one, or a figure typed off a bank statement. It is
never used to recompute the amount beside it.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("currency", sa.CHAR(3), nullable=True))
    op.add_column("transactions", sa.Column("base_amount_cents", sa.BigInteger(), nullable=True))
    op.add_column("transactions", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))

    # Not a guess: a single-currency ledger really was in that currency at a rate of 1.
    op.execute(
        """
        UPDATE transactions t
        SET currency = u.currency,
            base_amount_cents = t.amount_cents,
            fx_rate = 1
        FROM users u
        WHERE u.id = t.user_id
        """
    )

    op.alter_column("transactions", "currency", nullable=False)
    op.alter_column("transactions", "base_amount_cents", nullable=False)
    op.alter_column("transactions", "fx_rate", nullable=False)
    op.create_check_constraint("ck_transactions_fx_rate_positive", "transactions", "fx_rate > 0")
    # Signed like `amount_cents` is: a magnitude, with direction carried by `kind`.
    op.create_check_constraint(
        "ck_transactions_base_amount_positive", "transactions", "base_amount_cents > 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_base_amount_positive", "transactions", type_="check")
    op.drop_constraint("ck_transactions_fx_rate_positive", "transactions", type_="check")
    op.drop_column("transactions", "fx_rate")
    op.drop_column("transactions", "base_amount_cents")
    op.drop_column("transactions", "currency")
