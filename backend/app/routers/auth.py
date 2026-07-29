"""Auth: register, login, refresh, logout, password reset, email verification.

Two things shape most of the code here.

**Sessions are real.** The refresh cookie carries an opaque token backed by a row
in `refresh_sessions`, so logout, logout-all and "a password was just reset"
actually withdraw access instead of hoping the browser cooperates. Every refresh
rotates the token; presenting a retired one is treated as theft.

**Existence is not a public fact.** `/auth/forgot-password` answers identically
for an address that exists and one that doesn't — same status, same body, same
constant `retry_after_seconds`, and the work is arranged so the timings sit on
top of each other. The email goes out on a background task, which is what keeps
the response quick and, usefully, keeps its duration independent of whether we
sent anything at all.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.deps import CurrentUser, DbSession
from app.email import password_reset_email, queue_email, verification_email
from app.limits import AUTH_LIMIT, RESET_LIMIT, limiter
from app.models import AuthToken, User
from app.schemas import (
    ForgotPasswordIn,
    LoginIn,
    MessageOut,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
    UserUpdate,
    VerifyEmailIn,
)
from app.seed import seed_default_categories
from app.services import auth_tokens, sessions
from app.services.sessions import RotationOutcome

log = logging.getLogger("frankly")
router = APIRouter(tags=["auth"])

# One sentence, used for every outcome of /auth/forgot-password.
_FORGOT_RESPONSE = "If that address has an account, I've sent a link to reset the password."


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


def _start_session(db: DbSession, response: Response, user_id: uuid.UUID, remember: bool) -> None:
    token, expires_at = sessions.issue(db, user_id, remember=remember)
    _set_refresh_cookie(
        response, token, max_age_seconds=int((expires_at - datetime.now(UTC)).total_seconds())
    )


def _send_verification(db: DbSession, background: BackgroundTasks, user: User) -> None:
    settings = get_settings()
    token = auth_tokens.issue(db, user.id, AuthToken.EMAIL_VERIFY)
    url = f"{settings.app_base_url}/verify-email?token={token}"
    queue_email(
        background,
        verification_email(url, settings.email_verify_ttl_hours),
        to=user.email,
        user_id=user.id,
        purpose=AuthToken.EMAIL_VERIFY,
    )


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(AUTH_LIMIT)
def register(
    request: Request,
    body: RegisterIn,
    response: Response,
    db: DbSession,
    background: BackgroundTasks,
) -> TokenOut:
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc
    seed_default_categories(db, user.id)
    _send_verification(db, background, user)
    _start_session(db, response, user.id, remember=False)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/auth/login", response_model=TokenOut)
@limiter.limit(AUTH_LIMIT)
def login(request: Request, body: LoginIn, response: Response, db: DbSession) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    sessions.purge_dead(db, user.id)
    _start_session(db, response, user.id, remember=body.remember_me)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id))


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
    request: Request,
    body: ForgotPasswordIn,
    db: DbSession,
    background: BackgroundTasks,
) -> MessageOut:
    """Always the same answer. Never confirms whether the address is registered."""
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == body.email))

    if user is not None:
        last = auth_tokens.last_issued_at(db, user.id, AuthToken.PASSWORD_RESET)
        cooling = last is not None and datetime.now(UTC) - last < timedelta(
            seconds=settings.email_resend_cooldown_seconds
        )
        if not cooling:
            token = auth_tokens.issue(db, user.id, AuthToken.PASSWORD_RESET)
            url = f"{settings.app_base_url}/reset-password?token={token}"
            queue_email(
                background,
                password_reset_email(url, settings.password_reset_ttl_minutes),
                to=user.email,
                user_id=user.id,
                purpose=AuthToken.PASSWORD_RESET,
            )
            log.info('{"event":"password_reset_requested","user_id":"%s"}', user.id)
        db.commit()

    # Constant, not computed: a real remaining-cooldown would differ between a
    # registered address and an unknown one, which is the leak this endpoint
    # exists to avoid.
    return MessageOut(
        detail=_FORGOT_RESPONSE,
        retry_after_seconds=settings.email_resend_cooldown_seconds,
    )


@router.post("/auth/reset-password", response_model=MessageOut)
def reset_password(body: ResetPasswordIn, db: DbSession, response: Response) -> MessageOut:
    """Set a new password, then invalidate everything that came before it.

    Deliberately does not sign the user in. Whoever just used this link proved
    they can read the inbox, which is not the same as proving they are the
    account holder — so they go to the login form like anyone else.
    """
    user_id = auth_tokens.consume(db, body.token, AuthToken.PASSWORD_RESET)
    if user_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That reset link is invalid or has expired."
        )

    user = db.get(User, user_id)
    if user is None:  # pragma: no cover — FK makes this unreachable
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reset link is no longer valid.")

    user.password_hash = hash_password(body.password)
    # Anyone still holding a session got it before the password changed, which is
    # exactly the situation a reset is meant to end.
    sessions.revoke_all(db, user.id)
    auth_tokens.invalidate_outstanding(db, user.id, AuthToken.PASSWORD_RESET)
    db.commit()

    _clear_refresh_cookie(response)
    log.info('{"event":"password_reset_completed","user_id":"%s"}', user.id)
    return MessageOut(detail="Your password is set. Sign in with it.")


@router.post("/auth/verify-email", response_model=MessageOut)
def verify_email(body: VerifyEmailIn, db: DbSession) -> MessageOut:
    user_id = auth_tokens.consume(db, body.token, AuthToken.EMAIL_VERIFY)
    if user_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That confirmation link is invalid or has expired."
        )
    user = db.get(User, user_id)
    if user is None:  # pragma: no cover — FK makes this unreachable
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That confirmation link is no longer valid."
        )
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    db.commit()
    return MessageOut(detail="Your email is confirmed.")


@router.post("/auth/resend-verification", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
def resend_verification(
    request: Request, user: CurrentUser, db: DbSession, background: BackgroundTasks
) -> MessageOut:
    """Send the confirmation email again.

    Authenticated, which sidesteps enumeration entirely — you can only ask for
    your own address, and you already had to know the password to get here.
    """
    settings = get_settings()
    cooldown = settings.email_resend_cooldown_seconds

    if user.email_verified_at is not None:
        return MessageOut(detail="That address is already confirmed.")

    last = auth_tokens.last_issued_at(db, user.id, AuthToken.EMAIL_VERIFY)
    if last is not None:
        elapsed = datetime.now(UTC) - last
        if elapsed < timedelta(seconds=cooldown):
            remaining = int((timedelta(seconds=cooldown) - elapsed).total_seconds()) + 1
            return MessageOut(
                detail="I've already sent one. Give it a moment.",
                retry_after_seconds=remaining,
            )

    _send_verification(db, background, user)
    db.commit()
    return MessageOut(detail="Sent. Check your inbox.", retry_after_seconds=cooldown)


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
