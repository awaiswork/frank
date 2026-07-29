"""Password hashing (bcrypt) and the JWT access token.

The refresh token is deliberately *not* here any more. It used to be a second
JWT, which made it unrevokable — a signed statement stays true until it expires,
whatever the server later wishes. It is now an opaque random string checked
against `refresh_sessions`; see `services.sessions`.

The access token stays a JWT because it is verified on every request and a
database lookup per call would be a poor trade for a credential that lives
fifteen minutes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

# bcrypt only uses the first 72 bytes; truncate so longer inputs don't raise.
_BCRYPT_MAX_BYTES = 72

ACCESS = "access"


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(pw, password_hash.encode("utf-8"))


def create_access_token(subject: uuid.UUID) -> str:
    # Settings read here rather than at import: a module-level binding freezes
    # config at first import, which is the failure CLAUDE.md calls out for
    # COOKIE_SAMESITE and would make the TTL untestable.
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str) -> uuid.UUID:
    settings = get_settings()
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return uuid.UUID(str(payload["sub"]))
