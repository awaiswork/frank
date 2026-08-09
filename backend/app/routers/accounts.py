"""Accounts CRUD — every query scoped by the authenticated user (§8, §10).

Balances are never stored, so there is nothing to keep in step here: every response
recomputes from the ledger (`services/accounts.balances`).
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, Today
from app.models import Account, User
from app.schemas import AccountCreate, AccountOut, AccountsOut, AccountUpdate
from app.services.accounts import balances, earliest_opened_on, has_entries

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _owned_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        # 404 rather than 403, so we never confirm another user's rows exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


def _require_own_currency(user: User, currency: str | None) -> str:
    """Only the user's own currency, until true multi-currency lands.

    The column exists from the start because an account's currency is part of its
    identity, but accepting a second one now would create rows every balance and total
    in the app would silently add together as though they were comparable.
    """
    if currency is None or currency.upper() == user.currency.upper():
        return user.currency.upper()
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        f"Accounts are in {user.currency.upper()} for now — more currencies are coming.",
    )


def _payload(db: Session, user_id: uuid.UUID, *, include_archived: bool) -> AccountsOut:
    rows = balances(db, user_id, include_archived=include_archived)
    return AccountsOut(
        accounts=[
            AccountOut(
                id=r.account.id,
                name=r.account.name,
                type=r.account.type,
                currency=r.account.currency,
                opening_balance_cents=r.account.opening_balance_cents,
                opened_on=r.account.opened_on,
                archived_at=r.account.archived_at,
                balance_cents=r.balance_cents,
                entry_count=r.entry_count,
            )
            for r in rows
        ],
        # Archived accounts still hold money, so they count toward the total whenever
        # they are being shown; excluding them from a list they appear in would make
        # the total disagree with the rows above it.
        total_cents=sum(r.balance_cents for r in rows),
        ledger_starts_on=earliest_opened_on(db, user_id),
    )


@router.get("", response_model=AccountsOut)
def list_accounts(
    user: CurrentUser,
    db: DbSession,
    include_archived: bool = Query(default=False),
) -> AccountsOut:
    return _payload(db, user.id, include_archived=include_archived)


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountCreate, user: CurrentUser, db: DbSession, today: Today
) -> AccountOut:
    account = Account(
        user_id=user.id,
        name=body.name.strip(),
        type=body.type,
        currency=_require_own_currency(user, body.currency),
        opening_balance_cents=body.opening_balance_cents,
        # Defaults to today rather than to some earlier date: an opening balance is only
        # trustworthy for a day the user can actually check.
        opened_on=body.opened_on or today,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have an account with that name"
        ) from exc
    return _one(db, user.id, account.id)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: uuid.UUID, body: AccountUpdate, user: CurrentUser, db: DbSession
) -> AccountOut:
    account = _owned_account(db, user.id, account_id)
    data = body.model_dump(exclude_unset=True)

    if "archived" in data and data["archived"] is not None:
        account.archived_at = dt.datetime.now(dt.UTC) if data["archived"] else None
    for field in ("name", "type", "opening_balance_cents", "opened_on"):
        if data.get(field) is not None:
            setattr(account, field, data[field].strip() if field == "name" else data[field])

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have an account with that name"
        ) from exc
    return _one(db, user.id, account_id)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Only an empty account can be deleted; anything with history is archived.

    Mirrors the RESTRICT on the foreign key rather than relying on it, so the user gets
    an explanation instead of a 500 from the database.
    """
    account = _owned_account(db, user.id, account_id)
    if has_entries(db, account_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This account has transactions. Archive it instead so its history stays put.",
        )
    db.delete(account)
    db.commit()


def _one(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> AccountOut:
    """Re-read through the balance query so a write answers with the derived figure."""
    payload = _payload(db, user_id, include_archived=True)
    match = next((a for a in payload.accounts if a.id == account_id), None)
    if match is None:  # pragma: no cover — the row was just written in this transaction
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return match
