"""Auth: register, verify, login, refresh, logout, password reset.

Three things shape the code here.

**Nothing is issued before the address is proven.** Registering creates the
account and emails a code; it does not return a token and does not start a
session. The gate is therefore that no credential exists yet, rather than a check
bolted onto every request — there is no state in which an unverified account
holds something it could present. Logging in to an unverified account sends a
fresh code and says so, instead of letting it in.

**Sessions are real.** The refresh cookie carries an opaque token backed by a row
in `refresh_sessions`, so logout, logout-all and "a password was just reset"
actually withdraw access. Every refresh rotates the token; presenting a retired
one is treated as theft.

**Existence is not a public fact.** `/auth/forgot-password` and `/auth/resend-code`
answer identically for an address that exists and one that doesn't — same status,
same body, same constant `retry_after_seconds`. Email goes out on a background
task, which keeps the response quick and, usefully, keeps its duration
independent of whether anything was sent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.deps import CurrentUser, DbSession
from app.email import password_reset_code_email, queue_email, verification_code_email
from app.limits import AUTH_LIMIT, RESET_LIMIT, limiter
from app.models import AuthToken, User
from app.schemas import (
    ForgotPasswordIn,
    LoginIn,
    MessageOut,
    RegisterIn,
    ResendCodeIn,
    ResetPasswordIn,
    TicketOut,
    TokenOut,
    UserOut,
    UserUpdate,
    VerifyCodeIn,
)
from app.seed import seed_default_categories
from app.services import auth_tokens, sessions
from app.services.auth_tokens import CodeResult
from app.services.sessions import RotationOutcome

log = logging.getLogger("frankly")
router = APIRouter(tags=["auth"])

#: One sentence, used for every outcome of the endpoints that must not confirm
#: whether an address is registered.
_NEUTRAL = "If that address has an account, I've sent a code to it."
_CODE_REJECTED = "That code is wrong or has expired."


def _set_refresh_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    """Write the refresh cookie.

    Read settings at call time, not import time — same reason as
    `features.ai_enabled`: a module-level binding freezes the cookie policy at
    first import, so COOKIE_SAMESITE would silently never apply.

    Only `max_age` varies, and only with "remember me". `httponly`, `secure`,
    `samesite` and `path` are untouched — cross-site auth depends on that exact
    combination and it is not this feature's business to renegotiate it.
    """
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.is_prod,
        samesite=settings.cookie_samesite,
        max_age=max_age_seconds,
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.is_prod,
        samesite=settings.cookie_samesite,
        path="/auth",
    )


def _clear_cookie_headers() -> dict[str, str]:
    """The same deletion, as headers that can ride on an HTTPException.

    Setting a cookie on the injected `Response` only reaches the client on the
    success path: raising `HTTPException` builds a fresh response and the
    injected one is discarded, header and all. A rejected refresh therefore left
    the dead cookie in the browser, to be re-sent on every subsequent request
    until it aged out on its own.
    """
    probe = Response()
    _clear_refresh_cookie(probe)
    return {"set-cookie": probe.headers["set-cookie"]}


def start_session(db: DbSession, response: Response, user_id: uuid.UUID, remember: bool) -> str:
    """Issue a refresh session, set the cookie, return an access token.

    Shared with the OAuth router so there is exactly one place a session begins.
    """
    token, expires_at = sessions.issue(db, user_id, remember=remember)
    _set_refresh_cookie(
        response, token, max_age_seconds=int((expires_at - datetime.now(UTC)).total_seconds())
    )
    return create_access_token(user_id)


def _send_code(db: DbSession, background: BackgroundTasks, user: User, purpose: str) -> None:
    settings = get_settings()
    code = auth_tokens.issue_code(db, user.id, purpose)
    message = (
        verification_code_email(code, settings.otp_ttl_minutes)
        if purpose == AuthToken.EMAIL_VERIFY_CODE
        else password_reset_code_email(code, settings.otp_ttl_minutes)
    )
    queue_email(background, message, to=user.email, user_id=user.id, purpose=purpose)


@router.post("/auth/register", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(AUTH_LIMIT)
def register(
    request: Request, body: RegisterIn, db: DbSession, background: BackgroundTasks
) -> MessageOut:
    """Create the account and email a code. Deliberately returns no token.

    202 rather than 201: the account exists but is not yet usable, and the
    caller's next step is to prove the address, not to start using it.
    """
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc
    seed_default_categories(db, user.id)
    _send_code(db, background, user, AuthToken.EMAIL_VERIFY_CODE)
    db.commit()
    log.info('{"event":"registered","user_id":"%s"}', user.id)
    return MessageOut(
        detail="Check your email for a code.",
        retry_after_seconds=get_settings().email_resend_cooldown_seconds,
    )


@router.post("/auth/verify-code", response_model=TokenOut)
@limiter.limit(AUTH_LIMIT)
def verify_code(
    request: Request, body: VerifyCodeIn, response: Response, db: DbSession
) -> TokenOut:
    """Redeem a signup code. This is the only way an email account gets in."""
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        # Same answer as a wrong code: whether the address exists is not
        # something this endpoint is willing to say.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _CODE_REJECTED)

    if user.email_verified_at is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That address is already confirmed. Sign in instead."
        )

    check = auth_tokens.check_code(db, user.id, AuthToken.EMAIL_VERIFY_CODE, body.code)
    if check.result is CodeResult.TOO_MANY_ATTEMPTS:
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Too many wrong tries. Ask for a new code.",
        )
    if check.result is not CodeResult.OK:
        db.commit()  # the failed attempt must persist, or the cap means nothing
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _CODE_REJECTED)

    user.email_verified_at = datetime.now(UTC)
    access = start_session(db, response, user.id, remember=False)
    db.commit()
    log.info('{"event":"email_verified","user_id":"%s"}', user.id)
    return TokenOut(access_token=access)


@router.post("/auth/resend-code", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
def resend_code(
    request: Request, body: ResendCodeIn, db: DbSession, background: BackgroundTasks
) -> MessageOut:
    """Send another code.

    Unauthenticated by necessity — a gated account has no token to present — so
    the response must be identical whether or not the address is registered, and
    whether or not it was already confirmed.
    """
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == body.email))
    purpose = (
        AuthToken.EMAIL_VERIFY_CODE if body.purpose == "verify" else AuthToken.PASSWORD_RESET_CODE
    )

    eligible = user is not None and (
        purpose == AuthToken.PASSWORD_RESET_CODE or user.email_verified_at is None
    )
    if (
        user is not None
        and eligible
        and auth_tokens.seconds_until_resend(db, user.id, purpose) == 0
    ):
        _send_code(db, background, user, purpose)
        db.commit()

    # Constant, not computed: a real remaining cooldown would differ between a
    # registered address and an unknown one, which is the leak this avoids.
    return MessageOut(detail=_NEUTRAL, retry_after_seconds=settings.email_resend_cooldown_seconds)


@router.post("/auth/login", response_model=TokenOut)
@limiter.limit(AUTH_LIMIT)
def login(request: Request, body: LoginIn, response: Response, db: DbSession) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email))
    # A null hash means the account only ever used Google. Answered as an
    # ordinary failure rather than "this address uses Google", which would
    # confirm the account exists to anyone who guessed the address.
    if user is None or user.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    if user.email_verified_at is None:
        # Correct password, unproven address. Deliberately does *not* send the
        # code from here: background tasks are attached to a response, and this
        # path raises, so anything queued would be discarded silently. The client
        # asks `/auth/resend-code` next, which is the one place that sends them
        # and already carries the cooldown and the enumeration-safe response.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm your email to sign in.",
            headers={"x-verification-required": "1"},
        )

    sessions.purge_dead(db, user.id)
    access = start_session(db, response, user.id, remember=body.remember_me)
    db.commit()
    return TokenOut(access_token=access)


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(
    db: DbSession,
    response: Response,
    frankly_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenOut:
    if frankly_refresh is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")

    result = sessions.rotate(db, frankly_refresh)
    if result.outcome is not RotationOutcome.OK:
        db.commit()  # a reuse detection revoked rows; that must persist
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid refresh token",
            headers=_clear_cookie_headers(),
        )

    assert result.token is not None and result.expires_at is not None
    _set_refresh_cookie(
        response,
        result.token,
        max_age_seconds=int((result.expires_at - datetime.now(UTC)).total_seconds()),
    )
    db.commit()
    assert result.user_id is not None
    return TokenOut(access_token=create_access_token(result.user_id))


@router.post("/auth/logout", response_model=MessageOut)
def logout(
    db: DbSession,
    response: Response,
    frankly_refresh: Annotated[str | None, Cookie()] = None,
) -> MessageOut:
    """Revoke this session and clear the cookie.

    Unauthenticated on purpose: the cookie is the credential, and someone whose
    access token has expired must still be able to sign out. Always answers the
    same way, so a missing or stale cookie doesn't look like a failure.
    """
    if frankly_refresh:
        sessions.revoke_one(db, frankly_refresh)
        db.commit()
    _clear_refresh_cookie(response)
    return MessageOut(detail="Signed out.")


@router.post("/auth/logout-all", response_model=MessageOut)
def logout_all(user: CurrentUser, db: DbSession, response: Response) -> MessageOut:
    revoked = sessions.revoke_all(db, user.id)
    db.commit()
    _clear_refresh_cookie(response)
    log.info('{"event":"logout_all","user_id":"%s","sessions":%d}', user.id, revoked)
    return MessageOut(detail="Signed out everywhere.")


@router.post("/auth/forgot-password", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
def forgot_password(
    request: Request, body: ForgotPasswordIn, db: DbSession, background: BackgroundTasks
) -> MessageOut:
    """Always the same answer. Never confirms whether the address is registered."""
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == body.email))

    if user is not None:
        if auth_tokens.seconds_until_resend(db, user.id, AuthToken.PASSWORD_RESET_CODE) == 0:
            _send_code(db, background, user, AuthToken.PASSWORD_RESET_CODE)
            log.info('{"event":"password_reset_requested","user_id":"%s"}', user.id)
        db.commit()

    return MessageOut(detail=_NEUTRAL, retry_after_seconds=settings.email_resend_cooldown_seconds)


@router.post("/auth/verify-reset-code", response_model=TicketOut)
@limiter.limit(AUTH_LIMIT)
def verify_reset_code(request: Request, body: VerifyCodeIn, db: DbSession) -> TicketOut:
    """Exchange a reset code for a ticket.

    Two steps rather than one so a wrong code is discovered *before* the person
    has typed a new password. The ticket is a random single-use secret with a
    life of its own, so the code can be consumed here and cannot be replayed.
    """
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _CODE_REJECTED)

    check = auth_tokens.check_code(db, user.id, AuthToken.PASSWORD_RESET_CODE, body.code)
    if check.result is CodeResult.TOO_MANY_ATTEMPTS:
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Too many wrong tries. Ask for a new code."
        )
    if check.result is not CodeResult.OK:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _CODE_REJECTED)

    ticket = auth_tokens.issue_secret(db, user.id, AuthToken.PASSWORD_RESET_TICKET)
    db.commit()
    return TicketOut(ticket=ticket)


@router.post("/auth/reset-password", response_model=MessageOut)
def reset_password(body: ResetPasswordIn, db: DbSession, response: Response) -> MessageOut:
    """Set a new password, then invalidate everything that came before it.

    Deliberately does not sign the user in. Whoever redeemed the code proved they
    can read the inbox, which is not the same as proving they are the account
    holder — so they go to the login form like anyone else.
    """
    token = auth_tokens.consume_secret(db, body.ticket, AuthToken.PASSWORD_RESET_TICKET)
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reset has expired. Start again.")

    user = db.get(User, token.user_id)
    if user is None:  # pragma: no cover — the FK makes this unreachable
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reset is no longer valid.")

    user.password_hash = hash_password(body.password)
    # Someone resetting a password may be doing it *because* of an intruder, and
    # a session issued before the change would outlive it by up to thirty days.
    sessions.revoke_all(db, user.id)
    auth_tokens.invalidate_outstanding(db, user.id, AuthToken.PASSWORD_RESET_CODE)
    auth_tokens.invalidate_outstanding(db, user.id, AuthToken.PASSWORD_RESET_TICKET)
    # A reset also proves the address, so an account gated on verification is
    # unblocked by it — otherwise it could be reset but never entered.
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    db.commit()

    _clear_refresh_cookie(response)
    log.info('{"event":"password_reset_completed","user_id":"%s"}', user.id)
    return MessageOut(detail="Your password is set. Sign in with it.")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: UserUpdate, user: CurrentUser, db: DbSession) -> User:
    data = body.model_dump(exclude_unset=True)
    if data.get("currency") is not None:
        user.currency = str(data["currency"]).upper()
    if "monthly_income_cents" in data:
        user.monthly_income_cents = data["monthly_income_cents"]
    db.commit()
    return user
