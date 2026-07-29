"""Refresh sessions: issuing, rotating, and revoking them for real.

The refresh token used to be a self-contained JWT, which meant it could not be
withdrawn — signing out cleared some state in the browser and left a credential
in the cookie jar that still worked for thirty days. Now the cookie carries an
opaque random string and the database decides whether it is still good, so
"revoke" is a row update rather than a wish.

Rotation: every refresh mints a new token and retires the one presented. A token
that turns up after it was already retired is the signal that a copy exists
somewhere it shouldn't, and the answer is to kill that whole login — see
`RotationResult` for the one exception, which is not a security hole so much as
an acknowledgement of how browsers work.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.tokens import generate_token, hash_token
from app.models import RefreshSession

log = logging.getLogger("frankly")


class RotationOutcome(enum.Enum):
    OK = "ok"
    #: Presented token is unknown, expired, or belongs to a revoked session.
    INVALID = "invalid"
    #: Presented token was rotated long enough ago to be someone else's copy.
    #: The family is dead by the time this is returned.
    REUSE_DETECTED = "reuse_detected"


@dataclass(frozen=True)
class RotationResult:
    outcome: RotationOutcome
    user_id: uuid.UUID | None = None
    token: str | None = None
    expires_at: datetime | None = None


def _now() -> datetime:
    """Timezone-aware UTC, everywhere. A naive datetime compared against an
    aware one raises, and comparing two naive ones silently comes out wrong in
    whichever direction the server's local zone happens to lean."""
    return datetime.now(UTC)


def _lifetime(remember: bool) -> timedelta:
    settings = get_settings()
    return (
        timedelta(days=settings.refresh_token_expire_days)
        if remember
        else timedelta(hours=settings.refresh_session_short_hours)
    )


def issue(db: Session, user_id: uuid.UUID, *, remember: bool) -> tuple[str, datetime]:
    """Start a new session family. Returns the plaintext token and its expiry.

    The plaintext is returned once, to be put straight into the cookie. Only its
    hash is stored, so a leaked database gives an attacker nothing to present.
    """
    token = generate_token()
    expires_at = _now() + _lifetime(remember)
    db.add(
        RefreshSession(
            user_id=user_id,
            family_id=uuid.uuid4(),
            token_hash=hash_token(token),
            expires_at=expires_at,
        )
    )
    db.flush()
    return token, expires_at


def rotate(db: Session, raw_token: str) -> RotationResult:
    """Exchange a refresh token for its successor.

    The expiry is inherited, not extended: a session lives for a fixed window
    from the login that created it. Otherwise an active tab would refresh its way
    to an unbounded session and "remember me for 30 days" would mean forever.
    """
    settings = get_settings()
    now = _now()
    session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw_token))
    )

    if session is None:
        return RotationResult(RotationOutcome.INVALID)

    # Natural expiry is not an attack; let it fail quietly.
    if session.expires_at <= now:
        return RotationResult(RotationOutcome.INVALID)

    if session.revoked_at is not None:
        # Signed out, or already caught up in a family revocation. Either way the
        # credential is dead and re-presenting it earns nothing.
        return RotationResult(RotationOutcome.INVALID)

    if session.rotated_at is not None:
        grace = timedelta(seconds=settings.refresh_rotation_grace_seconds)
        if now - session.rotated_at > grace:
            # A token that was retired a while ago has just been presented. Either
            # it was captured, or a very stale tab woke up — and we cannot tell
            # which, so we assume the worse one and take the family down.
            revoke_family(db, session.family_id)
            log.warning(
                '{"event":"refresh_reuse_detected","user_id":"%s","family_id":"%s"}',
                session.user_id,
                session.family_id,
            )
            return RotationResult(RotationOutcome.REUSE_DETECTED, user_id=session.user_id)
        # Inside the window: two tabs booted together and both sent the cookie
        # they had. Punishing that would sign people out for opening a second tab.
        log.info(
            '{"event":"refresh_replay_within_grace","user_id":"%s"}',
            session.user_id,
        )

    session.rotated_at = now
    session.last_used_at = now

    successor = generate_token()
    db.add(
        RefreshSession(
            user_id=session.user_id,
            family_id=session.family_id,
            token_hash=hash_token(successor),
            expires_at=session.expires_at,
        )
    )
    db.flush()
    return RotationResult(
        RotationOutcome.OK,
        user_id=session.user_id,
        token=successor,
        expires_at=session.expires_at,
    )


def revoke_one(db: Session, raw_token: str) -> bool:
    """Revoke exactly the session behind this token. Used by logout."""
    session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw_token))
    )
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = _now()
    db.flush()
    return True


def revoke_family(db: Session, family_id: uuid.UUID) -> int:
    """Revoke every token descended from one login."""
    result = cast(
        "CursorResult[Any]",
        db.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        ),
    )
    db.flush()
    return int(result.rowcount or 0)


def revoke_all(db: Session, user_id: uuid.UUID) -> int:
    """Revoke every session this user has anywhere.

    Used by logout-all and — not optionally — by a completed password reset. A
    reset that left old sessions alive would hand the person who prompted it a
    thirty-day credential.
    """
    result = cast(
        "CursorResult[Any]",
        db.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        ),
    )
    db.flush()
    return int(result.rowcount or 0)


def purge_dead(db: Session, user_id: uuid.UUID) -> None:
    """Drop this user's finished sessions.

    There is no scheduler on this stack, so cleanup is opportunistic: it happens
    on login, which is both cheap and exactly when a user is most likely to have
    accumulated dead rows. Scoped to one user so it never turns into a table scan.
    """
    db.query(RefreshSession).filter(
        RefreshSession.user_id == user_id,
        RefreshSession.expires_at <= _now(),
    ).delete(synchronize_session=False)
    db.flush()
