"""Auth + account: register, login, refresh, and /me (technical-plan.md §8)."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Cookie, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.security import (
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut, UserUpdate
from app.seed import seed_default_categories

router = APIRouter(tags=["auth"])
settings = get_settings()


def _set_refresh_cookie(response: Response, user_id: uuid.UUID) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=create_refresh_token(user_id),
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path="/auth",
    )


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, response: Response, db: DbSession) -> TokenOut:
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc
    seed_default_categories(db, user.id)
    db.commit()
    _set_refresh_cookie(response, user.id)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, response: Response, db: DbSession) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    _set_refresh_cookie(response, user.id)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(
    db: DbSession,
    frank_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenOut:
    if frank_refresh is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        user_id = decode_token(frank_refresh, REFRESH)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return TokenOut(access_token=create_access_token(user.id))


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
