"""Sign in with Google.

Why this exists: Resend delivers only to the account owner's address until a
domain is verified, so a hard gate on emailed codes means nobody else can
register. Google's basic scopes are non-sensitive — no review, no domain — so
this is the path that actually works for other people.

Authorization Code flow with PKCE. State and the PKCE verifier live in
`oauth_states`, server-side, rather than in a cookie: the cross-site refresh
cookie is fragile and deliberately untouched (CLAUDE.md), and a second cookie
crossing the same boundary would need the same `SameSite=None; Secure` care.
Server-side state sidesteps the question entirely.

The access token is never put in a redirect URL — URLs reach history, `Referer`
headers and server logs. The callback sets the refresh cookie and the app
exchanges it through the existing `/auth/refresh` when it lands.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import get_settings
from app.core.tokens import generate_token, hash_token
from app.deps import DbSession
from app.models import OAuthAccount, OAuthState, User
from app.routers.auth import start_session
from app.seed import seed_default_categories

log = logging.getLogger("frankly")
router = APIRouter(tags=["auth"])

_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]
#: Non-sensitive, so the consent screen needs no Google review. Anything beyond
#: these three drags this into verification and a domain requirement.
_SCOPES = "openid email profile"
_TIMEOUT = 10.0

# Reused so Google's signing keys are fetched once rather than per sign-in.
_jwks_client = jwt.PyJWKClient(_JWKS, cache_keys=True)


def google_configured() -> bool:
    """False when no client is set up — the routes 404 and the button hides.

    Read at call time so a test, or a deploy that adds the credentials later,
    doesn't need a restart to be noticed.
    """
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def _require_configured() -> None:
    if not google_configured():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")


def _redirect_uri(request: Request) -> str:
    """Where Google returns the browser. Must match the console entry exactly.

    Derived from the request so localhost and production each get their own,
    which works because uvicorn runs with `--proxy-headers`; without that,
    Render's TLS termination would make this http:// and Google would reject it.
    """
    return str(request.url_for("google_callback"))


def _app_url(path: str) -> str:
    return f"{get_settings().app_base_url}{path}"


@router.get("/auth/google/start")
def google_start(request: Request, db: DbSession) -> RedirectResponse:
    """Begin sign-in. Redirects to Google's consent screen."""
    _require_configured()
    settings = get_settings()

    state = generate_token()
    verifier = generate_token()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )

    db.add(
        OAuthState(
            state_hash=hash_token(state),
            code_verifier=verifier,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.oauth_state_ttl_minutes),
        )
    )
    db.commit()

    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": _redirect_uri(request),
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Show the account chooser rather than silently reusing whichever
            # Google session the browser happens to be holding.
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"{_AUTHORIZE}?{query}", status_code=status.HTTP_302_FOUND)


@router.get("/auth/google/callback", name="google_callback")
def google_callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google returns the browser here. Ends in a session, or back at login."""
    _require_configured()

    # Cancelled at the consent screen, or refused. Not an error worth a trace.
    if error or not code or not state:
        return RedirectResponse(_app_url("/login?oauth=cancelled"), status_code=302)

    pending = _consume_state(db, state)
    if pending is None:
        # Unknown, expired, or already spent. Single use is what stops a captured
        # callback URL being replayed.
        return RedirectResponse(_app_url("/login?oauth=expired"), status_code=302)

    try:
        claims = _exchange_and_verify(code, pending, _redirect_uri(request))
    except Exception as exc:  # noqa: BLE001 — every failure here means "not signed in"
        log.warning('{"event":"oauth_failed","provider":"google","error":"%s"}', type(exc).__name__)
        return RedirectResponse(_app_url("/login?oauth=failed"), status_code=302)

    user = _link_or_create(db, str(claims["sub"]), str(claims["email"]))

    # The cookie is written onto the redirect itself. Setting it on an injected
    # Response would be dropped the moment we return a different Response —
    # the same way a rejected refresh used to lose its cookie deletion.
    redirect = RedirectResponse(_app_url("/auth/callback"), status_code=302)
    start_session(db, redirect, user.id, remember=True)
    db.commit()
    log.info('{"event":"oauth_signin","provider":"google","user_id":"%s"}', user.id)
    return redirect


def _consume_state(db: DbSession, state: str) -> str | None:
    """Redeem the state, returning its PKCE verifier. Single use."""
    row = db.scalar(select(OAuthState).where(OAuthState.state_hash == hash_token(state)))
    if row is None or row.consumed_at is not None or row.expires_at <= datetime.now(UTC):
        db.commit()
        return None
    row.consumed_at = datetime.now(UTC)
    db.commit()
    return row.code_verifier


def _exchange_and_verify(code: str, verifier: str, redirect_uri: str) -> dict[str, object]:
    """Swap the authorization code for an id_token, and check it properly.

    Every check matters. Without `aud` the token could have been minted for a
    different app; without `iss` it could come from anywhere; without
    `email_verified` a Google account carrying an unproven address could claim
    someone else's — and because we link by email, that is account takeover.
    """
    settings = get_settings()
    token_response = httpx.post(
        _TOKEN,
        timeout=_TIMEOUT,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    token_response.raise_for_status()
    id_token = str(token_response.json()["id_token"])

    signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
    claims: dict[str, object] = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.google_client_id,
        issuer=_ISSUERS,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )
    if claims.get("email_verified") is not True:
        raise ValueError("google account has an unverified email")
    if not claims.get("email"):
        raise ValueError("google account returned no email")
    return claims


def _link_or_create(db: DbSession, subject: str, email: str) -> User:
    """Find the account this Google identity belongs to, creating one if needed.

    Matched on the provider's `sub`, which is stable, falling back to the email —
    which people change — only for the first link. That fallback is safe solely
    because `_exchange_and_verify` refused anything without `email_verified`, so
    Google has asserted the same fact our own emailed code proves.
    """
    link = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == OAuthAccount.GOOGLE,
            OAuthAccount.provider_account_id == subject,
        )
    )
    if link is not None:
        user = db.get(User, link.user_id)
        assert user is not None  # the FK cascade guarantees it
        return user

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # No password: this account has never had one. `login` treats a null hash
        # as an ordinary failure rather than revealing how the account signs in.
        user = User(email=email, password_hash=None)
        db.add(user)
        db.flush()
        seed_default_categories(db, user.id)

    db.add(OAuthAccount(user_id=user.id, provider=OAuthAccount.GOOGLE, provider_account_id=subject))
    # Google proved the address, which is exactly what the emailed code proves.
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    db.flush()
    return user
