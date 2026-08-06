"""auth: OTP codes, reset tickets, and Google sign-in

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-29

Not backward-compatible in the rolling sense, and deliberately so: `0004`'s code
is being replaced wholesale, not extended. `auth_tokens.token_hash` becomes
`secret_hash`, its purposes change, and the old link-shaped rows have no meaning
under the new scheme. Because every row in that table is a single-use secret
with a lifetime measured in minutes, the safe move is to delete them rather than
migrate them — the worst case is that someone mid-reset starts again.

`users.password_hash` becomes nullable. An account that only ever signed in with
Google has no password, and storing a placeholder that no bcrypt comparison
could ever match would be a lie the schema tells about itself.

The demo account is verified here. It is the one address published in the README
for people trying the app, nobody can read its inbox, and under the new gate an
unverified account cannot sign in — so without this the demo login simply stops
working. Every other existing account goes through the code flow.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- Google-only accounts have no password ------------------------------
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)

    # --- auth_tokens: from link tokens to codes and tickets ------------------
    # Outstanding secrets are short-lived and single-use; none survives the
    # change of scheme, and keeping them would violate the new CHECK.
    op.execute("DELETE FROM auth_tokens")

    op.alter_column("auth_tokens", "token_hash", new_column_name="secret_hash")
    # bcrypt hashes are 60 characters and salted per row, so the old CHAR(64)
    # and its UNIQUE index no longer fit: two codes hash differently every time.
    op.alter_column(
        "auth_tokens",
        "secret_hash",
        existing_type=sa.CHAR(64),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.drop_constraint("auth_tokens_token_hash_key", "auth_tokens", type_="unique")
    op.create_index("ix_auth_tokens_secret_hash", "auth_tokens", ["secret_hash"])

    op.add_column(
        "auth_tokens",
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
    )

    op.drop_constraint("ck_auth_tokens_purpose", "auth_tokens", type_="check")
    op.create_check_constraint(
        "ck_auth_tokens_purpose",
        "auth_tokens",
        "purpose IN ('email_verify_code','password_reset_code','password_reset_ticket')",
    )

    # --- Google sign-in ------------------------------------------------------
    op.create_table(
        "oauth_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("state_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        # No user_id: this belongs to a browser mid-flow, and there may be no
        # account yet.
    )

    op.create_table(
        "oauth_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        # The provider's stable subject id, never the email — people change the
        # address on a Google account.
        sa.Column("provider_account_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),
    )
    op.create_index("ix_oauth_accounts_user", "oauth_accounts", ["user_id"])

    # --- Keep the published demo login working -------------------------------
    op.execute(
        "UPDATE users SET email_verified_at = now() "
        "WHERE email = 'demo@frankly.app' AND email_verified_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_accounts_user", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.drop_table("oauth_states")

    op.execute("DELETE FROM auth_tokens")
    op.drop_constraint("ck_auth_tokens_purpose", "auth_tokens", type_="check")
    op.create_check_constraint(
        "ck_auth_tokens_purpose",
        "auth_tokens",
        "purpose IN ('password_reset','email_verify')",
    )
    op.drop_column("auth_tokens", "attempts")
    op.drop_index("ix_auth_tokens_secret_hash", table_name="auth_tokens")
    op.alter_column(
        "auth_tokens",
        "secret_hash",
        existing_type=sa.Text(),
        type_=sa.CHAR(64),
        existing_nullable=False,
    )
    op.alter_column("auth_tokens", "secret_hash", new_column_name="token_hash")
    op.create_unique_constraint("auth_tokens_token_hash_key", "auth_tokens", ["token_hash"])

    # Rows with a NULL password cannot exist under the old schema.
    op.execute("DELETE FROM users WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
