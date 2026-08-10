"""assets, and the values someone states for them

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-10

A car has no ledger. Nothing transacts against it — there is only what someone says it
is worth, and when they said so. That is a different shape from an account, which is why
it is a different table rather than another account type.

Valuations are **append-only**, one per asset per day, and net worth at any past date is
computed as the accounts' balances plus each asset's most recent valuation on or before
that date. Nothing is snapshotted.

That is the whole argument for this design: adding a valuation dated three months ago
correctly rewrites the trend from that point, and a table of frozen snapshots cannot —
it would sit there disagreeing with the ledger it came from, with no way to tell which
was right.

Selling needs no special case either. Archiving an asset makes it contribute its last
stated value up to `archived_at` and nothing after, so the trend falls on the day of the
sale by itself.

`value_cents` is signed, unlike every other money column here, because an asset can be
worth less than nothing — a thing owned against a debt with no ledger of its own.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("group", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("\"group\" IN ('physical','investment')", name="ck_assets_group"),
    )
    op.create_index("ix_assets_user", "assets", ["user_id"])
    op.create_index(
        "uq_assets_user_lower_name", "assets", ["user_id", sa.text("lower(name)")], unique=True
    )

    op.create_table(
        "asset_valuations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("valued_on", sa.Date(), nullable=False),
        # Signed on purpose — see the module docstring.
        sa.Column("value_cents", sa.BigInteger(), nullable=False),
        # One statement of worth per day. Saying it twice on the same day means the
        # second replaces the first, not that both are true.
        sa.UniqueConstraint("asset_id", "valued_on", name="uq_asset_valuation_day"),
    )
    op.create_index("ix_asset_valuations_asset", "asset_valuations", ["asset_id", "valued_on"])


def downgrade() -> None:
    op.drop_index("ix_asset_valuations_asset", table_name="asset_valuations")
    op.drop_table("asset_valuations")
    op.drop_index("uq_assets_user_lower_name", table_name="assets")
    op.drop_index("ix_assets_user", table_name="assets")
    op.drop_table("assets")
