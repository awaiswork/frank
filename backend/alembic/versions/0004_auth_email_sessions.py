"""auth: email verification, one-time tokens, refresh sessions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29

Backward-compatible in both directions of a rolling deploy:

- `users.email_verified_at` is nullable with no default, so the currently
  running code — which has never heard of it — keeps inserting rows happily.
- The two new tables are additive. Nothing already deployed reads or writes
  them, and nothing existing gains a constraint.

No backfill. There are no real accounts yet, so every user starts unverified
and sees the (dismissible) confirm-your-email banner, which is the correct
default for an address nobody has proved they can read. The seeded demo
account is verified in `app/seed_demo.py` instead of here, because that is
fixture data rather than a schema concern.

One-way door worth stating: existing refresh cookies are JWTs and this deploy
stops honouring them, because the refresh token is now an opaque string looked
up in `refresh_sessions`. Everyone signed in at deploy time is signed out once.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def _pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "refresh_sessions",
        _pk(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        # SHA-256 hex. The plaintext lives in the cookie and nowhere else.
        sa.Column("token_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        # Deliberately no ip / user_agent column. See app/models.RefreshSession.
    )
    op.create_index("ix_refresh_sessions_user", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_family", "refresh_sessions", ["family_id"])

    op.create_table(
        "auth_tokens",
        _pk(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('password_reset','email_verify')",
            name="ck_auth_tokens_purpose",
        ),
    )
    op.create_index("ix_auth_tokens_user_purpose", "auth_tokens", ["user_id", "purpose"])


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_user_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("ix_refresh_sessions_family", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_user", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
    op.drop_column("users", "email_verified_at")
