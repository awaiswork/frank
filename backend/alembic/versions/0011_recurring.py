"""recurring templates, and the rows they generate

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-10

Rent does not need typing in every month. A template describes the thing that repeats;
occurrences whose date has arrived are written as ordinary transactions, so everything
downstream — spending, budgets, balances, the daily note — sees them without knowing
they were generated. Occurrences still in the future are not stored at all.

**`last_materialised_on` is what makes deleting one stick.** Asking "does a row exist
for this date?" would bring a deleted rent entry back on the next page load, silently,
for ever. Generation only moves forward from this column, so a row you removed stays
removed. It is also what keeps this cheap: the ordinary case is one indexed read that
returns nothing.

The partial unique index is a different concern — two requests reading the same stale
`last_materialised_on` would both insert. The database refuses the second and the
service treats that as "somebody else got there first".

`ON DELETE SET NULL` on the new column, deliberately unlike `account_id`'s RESTRICT:
deleting a template must not delete the rent you actually paid. That money moved. The
rows stay and simply stop being attributed to a template.

Additive — a new table and a nullable column, nothing to backfill.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None

SOURCES = "'manual','nl_parse','reconcile','recurring'"


def upgrade() -> None:
    op.create_table(
        "recurring_templates",
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
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cadence", sa.Text(), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=True),
        # The last occurrence date generation has reached. NULL means nothing yet.
        sa.Column("last_materialised_on", sa.Date(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        # Only what repeats on its own. A transfer needs a far account and a refund
        # undoes something specific, so neither belongs on a schedule yet.
        sa.CheckConstraint("kind IN ('expense','income')", name="ck_recurring_kind"),
        sa.CheckConstraint("amount_cents > 0", name="ck_recurring_amount_positive"),
        sa.CheckConstraint("cadence IN ('weekly','monthly','yearly')", name="ck_recurring_cadence"),
        sa.CheckConstraint("end_on IS NULL OR end_on >= start_on", name="ck_recurring_end_after"),
    )
    op.create_index("ix_recurring_user", "recurring_templates", ["user_id"])

    op.add_column("transactions", sa.Column("recurring_template_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_recurring_template",
        "transactions",
        "recurring_templates",
        ["recurring_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Partial: only generated rows are constrained, and NULLs would not conflict anyway.
    op.create_index(
        "uq_transactions_recurrence",
        "transactions",
        ["recurring_template_id", "occurred_on"],
        unique=True,
        postgresql_where=sa.text("recurring_template_id IS NOT NULL"),
    )

    op.drop_constraint("ck_transactions_source", "transactions", type_="check")
    op.create_check_constraint("ck_transactions_source", "transactions", f"source IN ({SOURCES})")


def downgrade() -> None:
    op.execute("DELETE FROM transactions WHERE source = 'recurring'")
    op.drop_constraint("ck_transactions_source", "transactions", type_="check")
    op.create_check_constraint(
        "ck_transactions_source",
        "transactions",
        "source IN ('manual','nl_parse','reconcile')",
    )
    op.drop_index("uq_transactions_recurrence", table_name="transactions")
    op.drop_constraint("fk_transactions_recurring_template", "transactions", type_="foreignkey")
    op.drop_column("transactions", "recurring_template_id")
    op.drop_index("ix_recurring_user", table_name="recurring_templates")
    op.drop_table("recurring_templates")
