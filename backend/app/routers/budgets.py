"""Budgets — monthly per-category limits with budget-vs-actual pace (§6.2, §8).

``GET /budgets?month=`` returns the pace-aware aggregate; ``PUT /budgets/{cat}``
upserts a limit for a month. Every query is scoped to the authenticated user.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession
from app.models import Budget, Category
from app.schemas import BudgetActualOut, BudgetUpsertIn
from app.services.aggregates import budget_vs_actual, parse_month

router = APIRouter(prefix="/budgets", tags=["budgets"])

MonthParam = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")]


def _owned_category(db: Session, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    cat = db.get(Category, category_id)
    if cat is None or cat.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return cat


@router.get("", response_model=list[BudgetActualOut])
def list_budgets(
    user: CurrentUser, db: DbSession, month: MonthParam = None
) -> list[BudgetActualOut]:
    today = dt.date.today()
    month_start = parse_month(month, today=today)
    rows = budget_vs_actual(db, user.id, month_start, today=today)
    return [BudgetActualOut.model_validate(row) for row in rows]


@router.put("/{category_id}", response_model=BudgetActualOut)
def upsert_budget(
    category_id: uuid.UUID,
    body: BudgetUpsertIn,
    user: CurrentUser,
    db: DbSession,
    month: MonthParam = None,
) -> BudgetActualOut:
    today = dt.date.today()
    month_start = parse_month(month, today=today)
    _owned_category(db, user.id, category_id)

    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category_id == category_id,
            Budget.month == month_start,
        )
    )
    if budget is None:
        budget = Budget(
            user_id=user.id,
            category_id=category_id,
            month=month_start,
            limit_cents=body.limit_cents,
        )
        db.add(budget)
    else:
        budget.limit_cents = body.limit_cents
    db.commit()

    rows = budget_vs_actual(db, user.id, month_start, today=today)
    match = next(row for row in rows if row.category_id == category_id)
    return BudgetActualOut.model_validate(match)
