"""users: the timezone their day rolls over in

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-10

Until now "today" meant the API container's today. Every date the app decides for
itself — the daily note's date, the streak, the trailing burn window, the default
month — pivoted on server-local midnight, so a user far enough east or west got
yesterday's or tomorrow's numbers presented as today's.

Nullable rather than NOT NULL DEFAULT 'UTC', because UTC is a fallback and not an
answer. NULL has to keep meaning "never told us", distinct from a user who really
is in UTC: the weekly digest needs that difference to know whether it can pick a
send hour or has to ask. Same reasoning as `email_verified_at` being a timestamp
rather than a boolean.

Backward-compatible: old code ignores the column, new code reads NULL as UTC, and
the container already runs UTC — so nothing changes for anyone until they set one.
IANA names are validated at the write edge (`ZoneInfo` in the Pydantic schema); a
CHECK constraint cannot express them, and an unrecognised value read back falls
through to UTC rather than raising.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "timezone")
