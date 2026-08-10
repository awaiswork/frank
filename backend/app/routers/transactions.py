"""Transactions CRUD — every query scoped by the authenticated user (§8, §10)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, LedgerUpToDate, Today
from app.models import Account, Category, Transaction
from app.schemas import TransactionCreate, TransactionOut, TransactionUpdate
from app.services.aggregates import month_bounds, parse_month
from app.services.money import NoRate, in_base

router = APIRouter(prefix="/transactions", tags=["transactions"])

PAGE_SIZE = 50


def _owned_transaction(db: Session, user_id: uuid.UUID, tx_id: uuid.UUID) -> Transaction:
    tx = db.get(Transaction, tx_id)
    if tx is None or tx.user_id != user_id:
        # 404 (not 403) so we never reveal another user's rows exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return tx


def _require_owned_category(db: Session, user_id: uuid.UUID, category_id: uuid.UUID | None) -> None:
    if category_id is None:
        return
    cat = db.get(Category, category_id)
    if cat is None or cat.user_id != user_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown category")


def _require_owned_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID | None) -> None:
    """NULL is allowed and means unassigned — see migration 0007.

    An archived account is refused: it is still owed its history, but nothing new
    should land in a balance the user has put away.
    """
    if account_id is None:
        return
    account = db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown account")
    if account.archived_at is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That account is archived")


def _require_transfer_shape(
    kind: str,
    account_id: uuid.UUID | None,
    counter_account_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
) -> None:
    """The same rules as ck_transactions_transfer_shape, said in words.

    The constraint is what makes a malformed transfer impossible; this exists so the
    user gets a sentence instead of a 500 from a violated CHECK. Deliberately a
    restatement rather than the only guard — a check that lives solely in a router is
    a check the next writer can route around.
    """
    if kind == "transfer":
        if account_id is None or counter_account_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A transfer needs an account at both ends.",
            )
        if account_id == counter_account_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A transfer needs two different accounts.",
            )
        if category_id is not None:
            # Categories are how spend reaches budgets, and moving your own money is
            # not spending. Refusing here keeps that true by construction.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A transfer between your own accounts isn't spending, so it has no category.",
            )
    elif counter_account_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a transfer has a second account.",
        )


@router.get("", response_model=list[TransactionOut], dependencies=[LedgerUpToDate])
def list_transactions(
    user: CurrentUser,
    db: DbSession,
    today: Today,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    category_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> list[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == user.id)
    if month is not None:
        start, end = month_bounds(parse_month(month, today=today))
        stmt = stmt.where(Transaction.occurred_on >= start, Transaction.occurred_on < end)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Transaction.description.ilike(like) | Transaction.merchant.ilike(like))
    stmt = (
        stmt.order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
        .limit(PAGE_SIZE)
        .offset((page - 1) * PAGE_SIZE)
    )
    return list(db.scalars(stmt))


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(body: TransactionCreate, user: CurrentUser, db: DbSession) -> Transaction:
    _require_owned_category(db, user.id, body.category_id)
    _require_owned_account(db, user.id, body.account_id)
    _require_owned_account(db, user.id, body.counter_account_id)
    _require_transfer_shape(body.kind, body.account_id, body.counter_account_id, body.category_id)
    try:
        currency, base_cents, rate = in_base(
            user,
            body.amount_cents,
            currency=body.currency,
            base_amount_cents=body.base_amount_cents,
            db=db,
            on=body.occurred_on,
        )
    except NoRate as exc:
        # Asking rather than guessing. A made-up conversion would enter every total
        # that reads it looking exactly like a real one.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"No {exc.args[0]} rate for {body.occurred_on}. "
            "Enter what it came to in your own currency.",
        ) from exc
    tx = Transaction(
        user_id=user.id,
        currency=currency,
        base_amount_cents=base_cents,
        fx_rate=rate,
        category_id=body.category_id,
        account_id=body.account_id,
        counter_account_id=body.counter_account_id,
        kind=body.kind,
        amount_cents=body.amount_cents,
        description=body.description,
        merchant=body.merchant,
        occurred_on=body.occurred_on,
        source="manual",
    )
    db.add(tx)
    db.commit()
    return tx


@router.patch("/{tx_id}", response_model=TransactionOut)
def update_transaction(
    tx_id: uuid.UUID, body: TransactionUpdate, user: CurrentUser, db: DbSession
) -> Transaction:
    tx = _owned_transaction(db, user.id, tx_id)
    data = body.model_dump(exclude_unset=True)
    if "category_id" in data:
        _require_owned_category(db, user.id, data["category_id"])
    if "account_id" in data:
        _require_owned_account(db, user.id, data["account_id"])
    if "counter_account_id" in data:
        _require_owned_account(db, user.id, data["counter_account_id"])
    for field, value in data.items():
        setattr(tx, field, value)
    # Validated against the row as it will be, not as it arrived: a patch that only
    # changes `kind` still has to produce a legal shape with the fields already there.
    _require_transfer_shape(tx.kind, tx.account_id, tx.counter_account_id, tx.category_id)
    db.commit()
    return tx


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(tx_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    tx = _owned_transaction(db, user.id, tx_id)
    db.delete(tx)
    db.commit()
