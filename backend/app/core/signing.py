"""Signed capabilities that travel in a URL and outlive every session.

Deliberately a separate module from `core.tokens`, which is about *one-time* secrets:
generated once, hashed at rest, burned on use, expiring in minutes. An unsubscribe link
is the opposite of all four. It has to work from an email opened six months later, on a
device that has never signed in, after the account's sessions are long gone — so there
is nothing to store and nothing to expire.

That makes it a bearer capability, and the whole design is about keeping the blast
radius of holding one as small as possible:

* it is scoped to a single user *and* a single kind of message, so it cannot be widened;
* it carries no session and unlocks no data — the only thing it can do is stop email;
* it is verified in constant time against a signature, never by fetching a row and
  comparing secrets;
* and it is derived from ``SECRET_KEY``, so rotating that key invalidates every
  outstanding link at once.

The worst outcome if one leaks — someone forwards a digest and the recipient
unsubscribes them — is an annoyance, not a breach. That is the trade being made, and it
is a far better one than putting anything session-shaped in an email.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.config import get_settings

_SEP = "."


def _signature(payload: str) -> str:
    # get_settings() at call time, never at import: a module-level read freezes the
    # key at first import and makes the whole thing untestable and silently stale.
    key = get_settings().secret_key.encode("utf-8")
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign(user_id: uuid.UUID, kind: str) -> str:
    """A URL-safe capability naming exactly one user and one kind of message."""
    payload = f"{user_id}{_SEP}{kind}"
    return f"{payload}{_SEP}{_signature(payload)}"


def verify(token: str, kind: str) -> uuid.UUID | None:
    """The user this token speaks for, or None if it does not speak for anyone.

    Returns None for every kind of failure — malformed, wrong kind, bad signature,
    unparseable id. The caller cannot tell them apart, and neither can an attacker.
    """
    parts = token.split(_SEP)
    if len(parts) != 3:
        return None
    raw_id, token_kind, signature = parts
    if token_kind != kind:
        # A digest link must not silently work for some other kind of message.
        return None
    if not hmac.compare_digest(signature, _signature(f"{raw_id}{_SEP}{token_kind}")):
        return None
    try:
        return uuid.UUID(raw_id)
    except ValueError:  # pragma: no cover — a valid signature over a non-uuid
        return None
