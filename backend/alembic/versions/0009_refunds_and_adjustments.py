"""refunds, and the corrections a ledger needs when it drifts

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10

Three kinds, for two problems.

**refund** — a returned purchase is not income. Counting it as income inflates what
someone earned and corrupts safe-to-spend; not logging it at all lets the balance
drift. It is a *negative expense*: it gives back the category's spend, the budget's
allowance and the burn rate, and leaves income alone. Stored as a positive magnitude
with the direction in the kind, exactly as income and expense already are — the
alternative, negative-amount expenses, would relax `amount_cents > 0` for every row
and let any expense go negative by accident.

**adjustment_up / adjustment_down** — the app and the bank will disagree eventually,
and the difference has to go somewhere. Two kinds rather than one signed amount for
the same reason as above: the positivity constraint is worth more than the extra enum
value, and this is how the schema already expresses direction.

Deliberately *not* how reconcile works: quietly changing `opening_balance_cents`. That
column means "the balance at the start of `opened_on`", so absorbing today's drift
into it makes the statement false, rewrites every past balance, and leaves no record
that a correction happened. A correction the user cannot see is the failure this app
exists to avoid, so it is a transaction and it shows up in their activity.

None of the three reaches a spending figure by accident: every aggregate filters kind
with an allow-list, so a kind nobody has considered is outside all of them.

Backward-compatible — widening a CHECK accepts every existing row, and
`ck_transactions_transfer_shape` already reads `kind <> 'transfer' -> counter IS NULL`,
which the new kinds satisfy without being mentioned.
"""

from __future__ import annotations

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

KINDS = "'expense','income','transfer','refund','adjustment_up','adjustment_down'"
SOURCES = "'manual','nl_parse','reconcile'"


def upgrade() -> None:
    op.drop_constraint("ck_transactions_kind", "transactions", type_="check")
    op.create_check_constraint("ck_transactions_kind", "transactions", f"kind IN ({KINDS})")

    # `source` is provenance, not meaning — no aggregate reads it. A reconciliation row
    # was derived from a balance the user stated rather than typed as a transaction,
    # and that is worth being able to tell apart later.
    op.drop_constraint("ck_transactions_source", "transactions", type_="check")
    op.create_check_constraint("ck_transactions_source", "transactions", f"source IN ({SOURCES})")


def downgrade() -> None:
    op.execute(
        "DELETE FROM transactions WHERE kind IN ('refund','adjustment_up','adjustment_down')"
    )
    op.drop_constraint("ck_transactions_source", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_source", "transactions", "source IN ('manual','nl_parse')"
    )
    op.drop_constraint("ck_transactions_kind", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_kind", "transactions", "kind IN ('expense','income','transfer')"
    )
