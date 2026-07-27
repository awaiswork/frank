"""allow the 'unknown' daily-note mood

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27

A user with no monthly income on file has no meaningful safe-to-spend, so Frankly
must not read them as 'go' (which claimed they were "within their means" off the
back of a 0 income fallback). 'unknown' is the honest fourth state.

Existing 'go' rows written while income was unknown are re-moods to 'unknown' so
history matches what those notes should have said.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_daily_notes_mood", "daily_notes", type_="check")
    op.create_check_constraint(
        "ck_daily_notes_mood",
        "daily_notes",
        "mood IN ('go','wait','over','unknown')",
    )
    # Backfill: the snapshot records the income we had at the time, so we can tell
    # which past notes were written with nothing to go on. Rewrite the text too —
    # re-mooding alone would leave "On track" sitting under an 'unknown' row, and
    # the endpoint only rewrites when the live mood *differs* from the stored one.
    op.execute(
        """
        UPDATE daily_notes
           SET mood = 'unknown',
               headline = 'Tell me what you earn',
               note = 'I''m logging what you spend, but I can''t tell you what''s '
                      'safe until I know your monthly income. Add it in Settings '
                      'and I''ll do the maths.'
         WHERE mood = 'go'
           AND (context_snapshot->>'monthly_income_eur') IS NULL
        """
    )


def downgrade() -> None:
    op.execute("UPDATE daily_notes SET mood = 'go' WHERE mood = 'unknown'")
    op.drop_constraint("ck_daily_notes_mood", "daily_notes", type_="check")
    op.create_check_constraint(
        "ck_daily_notes_mood",
        "daily_notes",
        "mood IN ('go','wait','over')",
    )
