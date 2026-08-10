"""transfers: money moving between two of your own accounts

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-10

A transfer is one row, not two. The alternative — a matched pair of rows, one per
side — puts an invariant into application code that has to hold forever ("both legs
exist and sum to zero") and gives every future aggregate somewhere to forget it. One
row makes half a transfer *unrepresentable*, and `ck_transactions_transfer_shape`
below makes the malformed variants unrepresentable too, which is stronger than any
test could be.

It also costs nothing to exclude. Every spend aggregate filters `kind = 'expense'` or
`kind = 'income'` positively — there is not one `!=` or `NOT IN` in the codebase — so
a third value is already outside all six of them, with no query touched. That
property is load-bearing and worth keeping deliberately.

`counter_account_id` gets ON DELETE RESTRICT for the same reason `account_id` did:
an orphaned entry costs money out of a balance with nothing on screen to explain it.
Note it makes an account that is only ever a transfer *destination* non-empty, which
`services/accounts.has_entries` has to agree with, or the app offers a delete the
database will refuse.

Backward-compatible: every existing row is expense or income with a NULL counter, so
it satisfies the second branch of the shape check and nothing needs backfilling. Old
code, which never sets the column, keeps inserting valid rows.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("counter_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_counter_account_id_accounts",
        "transactions",
        "accounts",
        ["counter_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_transactions_counter_account", "transactions", ["counter_account_id"])

    op.drop_constraint("ck_transactions_kind", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_kind", "transactions", "kind IN ('expense','income','transfer')"
    )

    # The shape of a transfer, enforced where it cannot be argued with. A transfer
    # needs both ends, they must differ, and it carries no category — so it can never
    # land in a budget, however it is written.
    op.create_check_constraint(
        "ck_transactions_transfer_shape",
        "transactions",
        """
        (kind = 'transfer'
           AND account_id IS NOT NULL
           AND counter_account_id IS NOT NULL
           AND counter_account_id <> account_id
           AND category_id IS NULL)
        OR (kind <> 'transfer' AND counter_account_id IS NULL)
        """,
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_transfer_shape", "transactions", type_="check")
    op.execute("DELETE FROM transactions WHERE kind = 'transfer'")
    op.drop_constraint("ck_transactions_kind", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_kind", "transactions", "kind IN ('expense','income')"
    )
    op.drop_index("ix_transactions_counter_account", table_name="transactions")
    op.drop_constraint(
        "fk_transactions_counter_account_id_accounts", "transactions", type_="foreignkey"
    )
    op.drop_column("transactions", "counter_account_id")
