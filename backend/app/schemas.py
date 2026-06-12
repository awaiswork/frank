"""Pydantic v2 request/response models."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Kind = Literal["expense", "income"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    currency: str
    monthly_income_cents: int | None


class UserUpdate(BaseModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    monthly_income_cents: int | None = Field(default=None, ge=0)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: Kind
    color: str | None


class TransactionCreate(BaseModel):
    kind: Kind = "expense"
    amount_cents: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    occurred_on: dt.date
    category_id: uuid.UUID | None = None


class TransactionUpdate(BaseModel):
    kind: Kind | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    occurred_on: dt.date | None = None
    category_id: uuid.UUID | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    amount_cents: int
    description: str
    merchant: str | None
    occurred_on: dt.date
    category_id: uuid.UUID | None
    source: str
    created_at: dt.datetime


# --- Budgets -----------------------------------------------------------------


class BudgetUpsertIn(BaseModel):
    limit_cents: int = Field(gt=0)


class BudgetActualOut(BaseModel):
    """Budget vs. actual with pace (§6.2) — built from the aggregate dataclass."""

    model_config = ConfigDict(from_attributes=True)

    category_id: uuid.UUID
    category_name: str
    color: str | None
    limit_cents: int
    spent_cents: int
    spent_fraction: float
    elapsed_fraction: float
    on_track: bool


# --- Goals -------------------------------------------------------------------


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_cents: int = Field(gt=0)
    due_date: dt.date | None = None


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_cents: int | None = Field(default=None, gt=0)
    due_date: dt.date | None = None
    archived: bool | None = None


class GoalContributionIn(BaseModel):
    amount_cents: int = Field(gt=0)
    occurred_on: dt.date | None = None


class GoalContributionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount_cents: int
    occurred_on: dt.date
    created_at: dt.datetime


class GoalOut(BaseModel):
    id: uuid.UUID
    name: str
    target_cents: int
    due_date: dt.date | None
    archived_at: dt.datetime | None
    contributed_cents: int
    progress_fraction: float


# --- Insights / Home aggregates ----------------------------------------------


class CategorySpendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: uuid.UUID | None
    category_name: str | None
    color: str | None
    spent_cents: int


class SafeToSpendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    income_cents: int
    spent_cents: int
    remaining_budgets_cents: int
    goal_contributions_cents: int
    safe_to_spend_cents: int


class BurnRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trailing_days: int
    total_spent_cents: int
    daily_burn_cents: int


class CategoryMoMOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: uuid.UUID | None
    category_name: str | None
    color: str | None
    this_month_cents: int
    prev_month_cents: int
    delta_cents: int


class InsightsSummaryOut(BaseModel):
    month: str  # YYYY-MM
    safe_to_spend: SafeToSpendOut
    spend_by_category: list[CategorySpendOut]
    daily_burn: BurnRateOut
    month_over_month: list[CategoryMoMOut]


# --- NL capture (M3) ---------------------------------------------------------


class NlParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)  # §7a input limit


class ParsedTransactionOut(BaseModel):
    """A draft returned by /nl/parse — never persisted; the client confirms it."""

    kind: Kind
    amount_cents: int
    description: str
    merchant: str | None
    occurred_on: dt.date
    category_id: uuid.UUID | None
    category_name: str | None
    confidence: float
