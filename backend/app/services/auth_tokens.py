"""Issuing and redeeming the single-use secrets we email people.

Both kinds work the same way: mint a random token, store only its SHA-256, put
the plaintext in a link, and accept it exactly once before its expiry. Issuing a
new one retires whatever was outstanding, so a user can never hold two live reset
links — the most recent email is always the one that works, which is also what
people expect after clicking "send it again".
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.tokens import generate_token, hash_token
from app.models import AuthToken

log = logging.getLogger("frankly")


def _now() -> datetime:
    return datetime.now(UTC)


def _ttl(purpose: str) -> timedelta:
    settings = get_settings()
    if purpose == AuthToken.PASSWORD_RESET:
        return timedelta(minutes=settings.password_reset_ttl_minutes)
    return timedelta(hours=settings.email_verify_ttl_hours)


def issue(db: Session, user_id: uuid.UUID, purpose: str) -> str:
    """Mint a token, retiring any the user already had for this purpose.

    That invalidation is the cap on outstanding tokens: one per user per purpose,
    enforced by construction rather than by counting rows.
    """
    invalidate_outstanding(db, user_id, purpose)
    token = generate_token()
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=_now() + _ttl(purpose),
        )
    )
    db.flush()
    return token


def invalidate_outstanding(db: Session, user_id: uuid.UUID, purpose: str) -> int:
    """Consume every live token of this purpose without redeeming it."""
    result = cast(
        "CursorResult[Any]",
        db.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user_id,
                AuthToken.purpose == purpose,
                AuthToken.consumed_at.is_(None),
            )
            .values(consumed_at=_now())
        ),
    )
    db.flush()
    return int(result.rowcount or 0)


def last_issued_at(db: Session, user_id: uuid.UUID, purpose: str) -> datetime | None:
    """When this user last asked for one of these — the basis of the cooldown.

    Per-user throttling has to come from the database. The in-process limiter
    resets whenever the free-tier instance is culled for being idle, which is
    every fifteen minutes, so anything held in memory is not a limit.
    """
    return db.scalar(
        select(AuthToken.created_at)
        .where(AuthToken.user_id == user_id, AuthToken.purpose == purpose)
        .order_by(AuthToken.created_at.desc())
        .limit(1)
    )


def consume(db: Session, raw_token: str, purpose: str) -> uuid.UUID | None:
    """Redeem a token, returning its owner. ``None`` if it isn't good.

    Lookup is by hash, so a wrong token matches no row — there is no point at
    which two secrets are compared byte by byte, and nothing to time.

    Failure is deliberately undifferentiated here: unknown, expired, already
    used and wrong-purpose all return ``None``. The caller does not get to tell
    a stranger which of those it was.
    """
    token = db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(raw_token),
            AuthToken.purpose == purpose,
        )
    )
    if token is None or token.consumed_at is not None or token.expires_at <= _now():
        return None
    token.consumed_at = _now()
    db.flush()
    return token.user_id
