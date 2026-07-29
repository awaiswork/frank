"""One-time secrets for password reset, email verification and refresh sessions.

Two rules govern everything in this module.

**The plaintext exists once.** It is generated, put in an email or a cookie, and
never written down — not in the database, not in a log line, not in an exception
message. What the database holds is a SHA-256 hash, so a dump of the tokens table
is worth nothing to whoever reads it.

**SHA-256, not bcrypt.** That is the opposite of the rule for passwords, and it is
correct here for the same reason it is wrong there. bcrypt is deliberately slow to
make guessing a *low-entropy human-chosen* secret expensive. These tokens are 32
bytes from the OS CSPRNG — there is nothing to guess, so the slowness would buy
no security and would instead put a deliberate delay on the hot path of every
refresh. Fast hashing of a full-entropy secret is the right trade.
"""

from __future__ import annotations

import hashlib
import secrets

# 32 bytes ≈ 256 bits, URL-safe so it survives being pasted into a mail client
# and back out again.
_TOKEN_BYTES = 32


def generate_token() -> str:
    """A new single-use secret. The only copy — hash it before storing."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The form we persist and query by: 64 hex characters of SHA-256.

    Lookup is by equality on this hash, which is also why there is no
    timing-unsafe comparison anywhere: we never fetch a candidate row and then
    compare secrets byte by byte. We hash what arrived and ask the database for
    that exact hash, so a wrong token simply matches no row.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time compare, for the rare path that can't be a hash lookup."""
    return secrets.compare_digest(a, b)
