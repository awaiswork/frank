"""allow the oauth_handoff purpose in auth_tokens

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-11

Widens `ck_auth_tokens_purpose` by one value. Google's callback now issues an
`oauth_handoff` — a single-use secret the browser exchanges for an access token —
because the refresh cookie it also sets is a third-party cookie, and Safari,
Firefox and Chrome's incognito windows refuse to send one back. See
`routers/oauth` for the whole reason.

Backward-compatible in the direction that matters: widening a CHECK rejects
nothing that used to be accepted, so the code running during a rollout is
unaffected either way — old code never writes the new value, and new code cannot
run before this migration has, because migrations run on boot.

`downgrade` deletes the handoff rows before narrowing the constraint back. They
are unreferenced by anything and live for two minutes, so there is nothing to
preserve; leaving them would make the constraint fail to be created at all.
"""

from __future__ import annotations

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None

_WITH_HANDOFF = (
    "purpose IN ('email_verify_code','password_reset_code','password_reset_ticket','oauth_handoff')"
)
_WITHOUT_HANDOFF = "purpose IN ('email_verify_code','password_reset_code','password_reset_ticket')"


def upgrade() -> None:
    op.drop_constraint("ck_auth_tokens_purpose", "auth_tokens", type_="check")
    op.create_check_constraint("ck_auth_tokens_purpose", "auth_tokens", _WITH_HANDOFF)


def downgrade() -> None:
    op.execute("DELETE FROM auth_tokens WHERE purpose = 'oauth_handoff'")
    op.drop_constraint("ck_auth_tokens_purpose", "auth_tokens", type_="check")
    op.create_check_constraint("ck_auth_tokens_purpose", "auth_tokens", _WITHOUT_HANDOFF)
