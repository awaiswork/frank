"""what gets emailed, and when it last was

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-10

One row per user per kind of message. `last_sent_at` lives here rather than on `users`
because it is per-kind by nature, and it is the thing that makes a double send
impossible: the sender claims a week by updating this column and acting on what the
update returned, so two overlapping cron runs cannot both pick up the same person.

Rows are created on demand. No row means the default, which is on — a weekly summary of
your own money is what this app is for, not something to be sold on.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
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
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('weekly_digest')", name="ck_notification_kind"),
        sa.UniqueConstraint("user_id", "kind", name="uq_notification_user_kind"),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
