"""daily notes (Frankly's daily check-in)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14

One row per user per day; the row also records that the user checked in that day
(the streak is derived from consecutive note_dates).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_notes",
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
        sa.Column("note_date", sa.Date(), nullable=False),
        sa.Column("mood", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.CheckConstraint("mood IN ('go','wait','over')", name="ck_daily_notes_mood"),
        sa.UniqueConstraint("user_id", "note_date", name="uq_daily_notes_user_date"),
    )
    op.create_index(
        "ix_daily_notes_user_date",
        "daily_notes",
        ["user_id", sa.text("note_date DESC")],
    )


def downgrade() -> None:
    op.drop_table("daily_notes")
