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

from app.deps import CurrentUser, DbSession, LedgerUpToDate, Today
from app.models import Budget, Category
from app.schemas import BudgetActualOut, BudgetUpsertIn
from app.services.aggregates import budget_vs_actual, effective_budget_month, parse_month

router = APIRouter(prefix="/budgets", tags=["budgets"])

MonthParam = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")]


def _owned_category(db: Session, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    cat = db.get(Category, category_id)
    if cat is None or cat.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return cat


@router.get("", response_model=list[BudgetActualOut], dependencies=[LedgerUpToDate])
def list_budgets(
    user: CurrentUser, db: DbSession, today: Today, month: MonthParam = None
) -> list[BudgetActualOut]:
    month_start = parse_month(month, today=today)
    rows = budget_vs_actual(db, user.id, month_start, today=today)
    return [BudgetActualOut.model_validate(row) for row in rows]


def _settle(db: Session, user_id: uuid.UUID, month_start: dt.date) -> None:
    """Give this month its own budget rows before anything edits one.

    Limits carry forward on read, so a month with no rows of its own is showing last
    month's. Writing a single row into it would make it a month that *has* rows — and
    the carry-forward read would then use only that one, silently dropping every other
    category's budget. So the first write to a month copies the whole inherited set in,
    and the edit lands on top of a complete picture.
    """
    inherited = effective_budget_month(db, user_id, month_start)
    if inherited is None or inherited == month_start:
        return
    for budget in db.scalars(
        select(Budget).where(Budget.user_id == user_id, Budget.month == inherited)
    ):
        db.add(
            Budget(
                user_id=user_id,
                category_id=budget.category_id,
                month=month_start,
                limit_cents=budget.limit_cents,
            )
        )
    db.flush()


@router.put("/{category_id}", response_model=BudgetActualOut)
def upsert_budget(
    category_id: uuid.UUID,
    body: BudgetUpsertIn,
    user: CurrentUser,
    db: DbSession,
    today: Today,
    month: MonthParam = None,
) -> BudgetActualOut:
    month_start = parse_month(month, today=today)
    _owned_category(db, user.id, category_id)
    _settle(db, user.id, month_start)

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


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    category_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    today: Today,
    month: MonthParam = None,
) -> None:
    """Stop budgeting a category.

    This exists because limits now carry forward. While they evaporated every month,
    doing nothing was how you stopped; now a budget you no longer want would follow you
    indefinitely with no way to say so.

    Settles the month first for the same reason the upsert does. Note the one edge: if
    this removes the *last* budget in the month, the month has no rows again and the
    read falls back to the previous one — the old limits reappear. Left deliberately;
    storing "this month was emptied on purpose" is a column, and one deletion edge does
    not earn it.
    """
    month_start = parse_month(month, today=today)
    _owned_category(db, user.id, category_id)
    _settle(db, user.id, month_start)

    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category_id == category_id,
            Budget.month == month_start,
        )
    )
    if budget is not None:
        db.delete(budget)
        db.commit()
