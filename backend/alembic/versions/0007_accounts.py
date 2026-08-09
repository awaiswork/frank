"""accounts, and the account a transaction belongs to

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-10

The change under this one is semantic, not structural. Until now a transaction was a
*log entry*: a record that spending happened, allowed to be incomplete because nothing
was derived from its completeness. An account makes it a *ledger entry*, and a balance
computed from an incomplete log is confidently wrong — the failure `income_known`
exists to prevent, one level down.

Which is why `account_id` is nullable and nothing is backfilled. Transactions logged
before accounts existed were captured under the old contract; assigning them to an
account nobody can verify would bake a wrong balance into the app permanently, and a
wrong balance is indistinguishable from a right one on screen. They stay unassigned,
keep counting toward spending analysis (which never needed an account), and contribute
nothing to any balance.

Each account instead carries `opened_on` and the balance it held at the *start* of that
day. Balance is `opening_balance_cents` plus signed entries from `opened_on` onward —
correct from day one, and never reconstructed from a past the app never saw.

`ON DELETE RESTRICT`, deliberately unlike `categories`' SET NULL: an orphaned category
loses a label, an orphaned entry loses money out of a balance with nothing on screen to
say so. An account with entries is archived, never deleted.

`currency` is NOT NULL from the start even though only one value is accepted for now.
An account's currency is part of its identity, and adding the column after a dozen
queries have been written assuming every amount is comparable means auditing all of
them. This is the one piece of multi-currency groundwork that has to land early.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("opening_balance_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        # Only things with a ledger. A car or an apartment has no entries to sum, only a
        # value someone states — that is an asset with valuations, and a different table.
        sa.CheckConstraint(
            "type IN ('current','savings','cash','liability')", name="ck_accounts_type"
        ),
    )
    op.create_index("ix_accounts_user", "accounts", ["user_id"])
    op.create_index(
        "uq_accounts_user_lower_name",
        "accounts",
        ["user_id", sa.text("lower(name)")],
        unique=True,
    )

    op.add_column("transactions", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_account_id_accounts",
        "transactions",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_transactions_account", "transactions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_account", table_name="transactions")
    op.drop_constraint("fk_transactions_account_id_accounts", "transactions", type_="foreignkey")
    op.drop_column("transactions", "account_id")
    op.drop_index("uq_accounts_user_lower_name", table_name="accounts")
    op.drop_index("ix_accounts_user", table_name="accounts")
    op.drop_table("accounts")
