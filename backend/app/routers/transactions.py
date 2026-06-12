"""Transactions CRUD — every query scoped by the authenticated user (§8, §10)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession
from app.models import Category, Transaction
from app.schemas import TransactionCreate, TransactionOut, TransactionUpdate

router = APIRouter(prefix="/transactions", tags=["transactions"])

PAGE_SIZE = 50


def _month_range(month: str) -> tuple[dt.date, dt.date]:
    year, mon = (int(part) for part in month.split("-"))
    start = dt.date(year, mon, 1)
    end = dt.date(year + 1, 1, 1) if mon == 12 else dt.date(year, mon + 1, 1)
    return start, end


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


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    user: CurrentUser,
    db: DbSession,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    category_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> list[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == user.id)
    if month is not None:
        start, end = _month_range(month)
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
    tx = Transaction(
        user_id=user.id,
        category_id=body.category_id,
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
    for field, value in data.items():
        setattr(tx, field, value)
    db.commit()
    return tx


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(tx_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    tx = _owned_transaction(db, user.id, tx_id)
    db.delete(tx)
    db.commit()
