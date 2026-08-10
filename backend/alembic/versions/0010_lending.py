"""accounts: a person you have lent to or borrowed from

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-10

One new account type, and that is the whole change. An IOU is a transfer between one
of your accounts and a person's, so conservation, the transfer shape constraint and
the exclusion from every spending figure all arrive already built.

**One type rather than a receivable/payable pair.** The direction is the sign of the
balance: positive means they owe you, negative means you owe them. Two types cannot
represent having lent Sam 50 and borrowed 80 from Sam — that is one relationship
worth −30, and a pair would leave two accounts for one person that ought to net.
Grouping by sign is also more truthful than grouping by a label chosen when the
account was created, because the label can go stale and the balance cannot.

**No counterparty column.** The account's `name` is the person. A second field for it
would be a column that has to agree with the one beside it forever.

Already owed when you started? An opening balance says so: create "Sam" opening at 50
and Sam already owes you 50, from a date you can point at.

Backward-compatible — widening a CHECK accepts every existing row.
"""

from __future__ import annotations

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None

TYPES = "'current','savings','cash','liability','person'"


def upgrade() -> None:
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint("ck_accounts_type", "accounts", f"type IN ({TYPES})")


def downgrade() -> None:
    # Their transfers reference real accounts, so the rows have to go before the
    # accounts they point at can.
    op.execute(
        "DELETE FROM transactions WHERE account_id IN "
        "(SELECT id FROM accounts WHERE type = 'person') "
        "OR counter_account_id IN (SELECT id FROM accounts WHERE type = 'person')"
    )
    op.execute("DELETE FROM accounts WHERE type = 'person'")
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type", "accounts", "type IN ('current','savings','cash','liability')"
    )
