"""published exchange rates, kept so a conversion can be looked up

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-10

`rate` is **base units per one quote unit**, so `base_amount = amount * rate` — the same
direction as `transactions.fx_rate`, deliberately, because two conventions in one
codebase is how a figure ends up inverted with nobody noticing. Frankfurter publishes
the inverse (1 EUR = 1.1535 USD), so it is flipped once at the edge where it arrives.

One row per (base, quote, day). The ECB publishes on working days only: ask for a
Saturday and the answer carries Friday's date, which is what gets stored — so a lookup
of "the most recent rate at or before this date" gives the weekend and holiday fallback
without a special case, and matches what a bank would have used anyway.

Nothing here is ever used to recompute a transaction. `transactions.base_amount_cents` is
frozen when the row is written; this table only exists so that *new* rows have something
honest to be converted with.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("base", sa.CHAR(3), nullable=False),
        sa.Column("quote", sa.CHAR(3), nullable=False),
        sa.Column("rate_on", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.CheckConstraint("rate > 0", name="ck_fx_rates_positive"),
        sa.CheckConstraint("base <> quote", name="ck_fx_rates_distinct"),
        sa.UniqueConstraint("base", "quote", "rate_on", name="uq_fx_rate_day"),
    )
    # The lookup is always "most recent at or before a date", for one pair.
    op.create_index("ix_fx_rates_pair_day", "fx_rates", ["base", "quote", "rate_on"])


def downgrade() -> None:
    op.drop_index("ix_fx_rates_pair_day", table_name="fx_rates")
    op.drop_table("fx_rates")
