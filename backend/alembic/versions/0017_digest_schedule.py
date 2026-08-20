"""Let each reader choose the day and hour their digest arrives.

Additive, with defaults that reproduce the previous fixed schedule exactly — Monday
at 08:00, which is what `digest.SEND_WEEKDAY` / `SEND_HOUR` meant before this. Every
existing row therefore keeps the behaviour it already had, and old code running beside
new during a rollout simply ignores two columns it does not read.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("send_weekday", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "notification_settings",
        sa.Column("send_hour", sa.SmallInteger(), nullable=False, server_default=sa.text("8")),
    )
    # A range no application bug can write around. Monday is 0, matching
    # `date.weekday()`; a Sunday-first convention arriving from somewhere else would
    # silently shift everyone's digest by a day rather than fail.
    op.create_check_constraint(
        "ck_notification_weekday", "notification_settings", "send_weekday BETWEEN 0 AND 6"
    )
    op.create_check_constraint(
        "ck_notification_hour", "notification_settings", "send_hour BETWEEN 0 AND 23"
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_hour", "notification_settings", type_="check")
    op.drop_constraint("ck_notification_weekday", "notification_settings", type_="check")
    op.drop_column("notification_settings", "send_hour")
    op.drop_column("notification_settings", "send_weekday")
