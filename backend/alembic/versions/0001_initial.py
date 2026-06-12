"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-12

Hand-written to match technical-plan.md §5. Money is integer cents (BIGINT).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _pk() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        _pk(),
        _created(),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="EUR"),
        sa.Column("monthly_income_cents", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "categories",
        _pk(),
        _created(),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('expense','income')", name="ck_categories_kind"),
    )
    op.create_index(
        "uq_categories_user_lower_name",
        "categories",
        ["user_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "transactions",
        _pk(),
        _created(),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("merchant", sa.Text(), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column("llm_confidence", sa.Numeric(3, 2), nullable=True),
        sa.CheckConstraint("kind IN ('expense','income')", name="ck_transactions_kind"),
        sa.CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint("source IN ('manual','nl_parse')", name="ck_transactions_source"),
    )
    op.create_index(
        "ix_transactions_user_occurred",
        "transactions",
        ["user_id", sa.text("occurred_on DESC")],
    )
    op.create_index("ix_transactions_user_category", "transactions", ["user_id", "category_id"])

    op.create_table(
        "budgets",
        _pk(),
        _created(),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("limit_cents", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("user_id", "category_id", "month", name="uq_budgets_user_cat_month"),
    )
    op.create_index("ix_budgets_user_month", "budgets", ["user_id", "month"])

    op.create_table(
        "savings_goals",
        _pk(),
        _created(),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("target_cents", sa.BigInteger(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "goal_contributions",
        _pk(),
        _created(),
        sa.Column(
            "goal_id",
            sa.Uuid(),
            sa.ForeignKey("savings_goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
    )

    op.create_table(
        "advice_requests",
        _pk(),
        _created(),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("user_followed", sa.Boolean(), nullable=True),
        sa.CheckConstraint("verdict IN ('go','wait','skip','your_call')", name="ck_advice_verdict"),
    )
    op.create_index(
        "ix_advice_user_created",
        "advice_requests",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("advice_requests")
    op.drop_table("goal_contributions")
    op.drop_table("savings_goals")
    op.drop_table("budgets")
    op.drop_table("transactions")
    op.drop_table("categories")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS citext")
