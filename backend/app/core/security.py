"""Password hashing (bcrypt) and JWT access/refresh tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

# bcrypt only uses the first 72 bytes; truncate so longer inputs don't raise.
_BCRYPT_MAX_BYTES = 72

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(pw, password_hash.encode("utf-8"))


def _create_token(subject: uuid.UUID, token_type: str, expires: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: uuid.UUID) -> str:
    return _create_token(subject, ACCESS, timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(subject: uuid.UUID) -> str:
    return _create_token(subject, REFRESH, timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str) -> uuid.UUID:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return uuid.UUID(str(payload["sub"]))
