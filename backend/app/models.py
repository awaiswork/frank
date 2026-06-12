"""SQLAlchemy models — mirrors technical-plan.md §5 (PostgreSQL schema).

Money is always integer cents (BIGINT), never floats. Every user-owned table has a
``user_id`` FK with ``ON DELETE CASCADE``; every query must filter by ``user_id``
(enforced by the shared dependency in ``app.deps``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Timestamped, UUIDPk


class User(UUIDPk, Timestamped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="EUR")
    monthly_income_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Category(UUIDPk, Timestamped, Base):
    __tablename__ = "categories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('expense','income')", name="ck_categories_kind"),
        Index(
            "uq_categories_user_lower_name",
            "user_id",
            text("lower(name)"),
            unique=True,
        ),
    )


class Transaction(UUIDPk, Timestamped, Base):
    __tablename__ = "transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('expense','income')", name="ck_transactions_kind"),
        CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("source IN ('manual','nl_parse')", name="ck_transactions_source"),
        Index("ix_transactions_user_occurred", "user_id", text("occurred_on DESC")),
        Index("ix_transactions_user_category", "user_id", "category_id"),
    )


class Budget(UUIDPk, Timestamped, Base):
    __tablename__ = "budgets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[dt.date] = mapped_column(Date, nullable=False)  # always first of month
    limit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "month", name="uq_budgets_user_cat_month"),
        Index("ix_budgets_user_month", "user_id", "month"),
    )


class SavingsGoal(UUIDPk, Timestamped, Base):
    __tablename__ = "savings_goals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    target_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    archived_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)


class GoalContribution(UUIDPk, Timestamped, Base):
    __tablename__ = "goal_contributions"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("savings_goals.id", ondelete="CASCADE"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_on: Mapped[dt.date] = mapped_column(Date, nullable=False)


class AdviceRequest(UUIDPk, Timestamped, Base):
    __tablename__ = "advice_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Any] = mapped_column(JSONB, nullable=False)
    context_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_followed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        CheckConstraint("verdict IN ('go','wait','skip','your_call')", name="ck_advice_verdict"),
        Index("ix_advice_user_created", "user_id", text("created_at DESC")),
    )
