"""Per-IP rate limits (technical-plan.md §12).

Only `/auth/register` and `/auth/login` are throttled: on a public URL they are
the only unauthenticated endpoints that write, and an open signup route is the
obvious thing to abuse. The billable AI routes need nothing here — they are
already shut by the gates in ``app.features`` and 503 before doing any work.

Behind the platform's proxy the client IP arrives in ``X-Forwarded-For``, which is
why the container runs uvicorn with ``--forwarded-allow-ips``; without it every
request would look like it came from the proxy and share one bucket.
"""

from __future__ import annotations

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Generous enough that a person fumbling a password never notices.
AUTH_LIMIT = "10/minute"

# The endpoints that cause an email to be sent. Tighter, because the cost of
# abuse is somebody else's inbox and a finite monthly send quota.
#
# Per-IP only, and that is not the whole story: this limiter counts in process
# memory, and the free-tier instance is culled after fifteen idle minutes, so
# these counters reset roughly as often as the app goes quiet. The durable half
# of the throttle is per-user and lives in the database — see
# `services.auth_tokens.last_issued_at`, which is what actually stops one
# address being mailed repeatedly.
RESET_LIMIT = "5/minute"


def rate_limit_handler(request: Request, exc: Exception) -> Response:
    """429 shaped like every other error the API returns.

    slowapi's own handler answers with ``{"error": ...}``, which the frontend
    client doesn't read — it surfaces ``detail`` (see ``api/client.ts:toError``).
    Typed against bare ``Exception`` because that's Starlette's handler
    signature; the app only registers it for ``RateLimitExceeded``.
    """
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Too many attempts. Give it a minute and try again."},
    )
