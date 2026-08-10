"""skipping one occurrence of something that repeats

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-10

The gym is closed in August; the rent is not paid this month because it was paid in
advance. The template is still right — one occurrence is not.

A row here suppresses that date in both places it would otherwise appear: it is never
materialised when the day comes, and it is never counted in the forecast before then.
Both, or skipping would quietly stop reserving money for something that still happens.

Deleting a generated row already covers "this one did not happen" after the fact. This
covers saying so in advance, which is the half that matters once the forecast exists —
which is why it landed with the forecast rather than with materialisation.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_skips",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("recurring_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skip_on", sa.Date(), nullable=False),
        # Skipping twice is the same as skipping once.
        sa.UniqueConstraint("template_id", "skip_on", name="uq_recurring_skip"),
    )


def downgrade() -> None:
    op.drop_table("recurring_skips")
