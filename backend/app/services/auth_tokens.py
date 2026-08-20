"""Issuing and redeeming the short-lived secrets that gate the auth flows.

Four kinds, two shapes, and the shape decides the hash.

**Six-digit codes** (`email_verify_code`, `password_reset_code`) are what we
email. A million possibilities is guessable at machine speed, so they get bcrypt
— deliberately slow — plus a ten-minute life and a cap on wrong answers. That is
the exact inverse of the rule for the link tokens, and correct for the same
reason: bcrypt buys nothing against a full-entropy secret and everything against
a short one. It works here only because the row is found by ``(user_id,
purpose)`` and the code is then *verified* against the hash. We never search by
the secret, which we couldn't anyway — bcrypt salts every hash differently.

**Random strings** (`password_reset_ticket`, `oauth_handoff`) are 32 bytes from
the CSPRNG, never seen by a person. Nothing to guess, so SHA-256 and a lookup by
hash, which is inherently constant-time with respect to the secret.
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
from app.core.security import hash_password, verify_password
from app.core.tokens import generate_code, generate_token, hash_token
from app.models import AuthToken

log = logging.getLogger("frankly")


class CodeResult(enum.Enum):
    OK = "ok"
    #: Wrong, expired, already used, or no code outstanding. Undifferentiated on
    #: purpose — the caller must not tell a stranger which.
    INVALID = "invalid"
    #: Too many wrong answers. The code is dead; a new one must be requested.
    TOO_MANY_ATTEMPTS = "too_many_attempts"


@dataclass(frozen=True)
class CodeCheck:
    result: CodeResult
    attempts_left: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


def _ttl(purpose: str) -> timedelta:
    settings = get_settings()
    if purpose in AuthToken.CODE_PURPOSES:
        return timedelta(minutes=settings.otp_ttl_minutes)
    if purpose == AuthToken.OAUTH_HANDOFF:
        return timedelta(seconds=settings.oauth_handoff_ttl_seconds)
    return timedelta(minutes=settings.reset_ticket_ttl_minutes)


def invalidate_outstanding(db: Session, user_id: uuid.UUID, purpose: str) -> int:
    """Consume every live secret of this purpose without redeeming it."""
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


def issue_code(db: Session, user_id: uuid.UUID, purpose: str) -> str:
    """Mint a six-digit code, retiring any the user already had.

    That invalidation is the cap on outstanding codes — one per user per purpose,
    enforced by construction rather than by counting rows — and it is also what
    people expect from "send it again": the newest code is the one that works.
    """
    invalidate_outstanding(db, user_id, purpose)
    code = generate_code()
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            secret_hash=hash_password(code),
            expires_at=_now() + _ttl(purpose),
        )
    )
    db.flush()
    return code


def check_code(db: Session, user_id: uuid.UUID, purpose: str, code: str) -> CodeCheck:
    """Verify a code and consume it on success.

    A wrong answer costs an attempt. Running out burns the code outright rather
    than merely refusing this try, so an attacker cannot keep the same target
    alive while working through the space.
    """
    settings = get_settings()
    token = db.scalar(
        select(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose,
            AuthToken.consumed_at.is_(None),
        )
        .order_by(AuthToken.created_at.desc())
        .limit(1)
    )
    if token is None or token.expires_at <= _now():
        return CodeCheck(CodeResult.INVALID)

    if token.attempts >= settings.otp_max_attempts:
        token.consumed_at = _now()
        db.flush()
        return CodeCheck(CodeResult.TOO_MANY_ATTEMPTS)

    if not verify_password(code, token.secret_hash):
        token.attempts += 1
        remaining = settings.otp_max_attempts - token.attempts
        if remaining <= 0:
            token.consumed_at = _now()
            db.flush()
            log.info('{"event":"otp_burned","user_id":"%s","purpose":"%s"}', user_id, purpose)
            return CodeCheck(CodeResult.TOO_MANY_ATTEMPTS)
        db.flush()
        return CodeCheck(CodeResult.INVALID, attempts_left=remaining)

    token.consumed_at = _now()
    db.flush()
    return CodeCheck(CodeResult.OK)


def issue_secret(db: Session, user_id: uuid.UUID, purpose: str) -> str:
    """Mint a random single-use secret — the reset ticket, or an OAuth handoff."""
    invalidate_outstanding(db, user_id, purpose)
    secret = generate_token()
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            secret_hash=hash_token(secret),
            expires_at=_now() + _ttl(purpose),
        )
    )
    db.flush()
    return secret


def consume_secret(db: Session, raw: str, purpose: str) -> AuthToken | None:
    """Redeem a random secret, returning its row. ``None`` if it isn't good.

    Lookup is by hash, so a wrong secret matches nothing and there is no point at
    which two secrets are compared byte by byte. Failure is undifferentiated:
    unknown, expired, already used and wrong-purpose all return ``None``.
    """
    token = db.scalar(
        select(AuthToken).where(
            AuthToken.secret_hash == hash_token(raw),
            AuthToken.purpose == purpose,
        )
    )
    if token is None or token.consumed_at is not None or token.expires_at <= _now():
        return None
    token.consumed_at = _now()
    db.flush()
    return token


def last_issued_at(db: Session, user_id: uuid.UUID, purpose: str) -> datetime | None:
    """When this user last asked for one — the basis of the cooldown.

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


def seconds_until_resend(db: Session, user_id: uuid.UUID, purpose: str) -> int:
    """0 when a new send is allowed, else how long the caller must wait."""
    cooldown = timedelta(seconds=get_settings().email_resend_cooldown_seconds)
    last = last_issued_at(db, user_id, purpose)
    if last is None:
        return 0
    elapsed = _now() - last
    if elapsed >= cooldown:
        return 0
    return int((cooldown - elapsed).total_seconds()) + 1
