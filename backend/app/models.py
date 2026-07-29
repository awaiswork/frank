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
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
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
    # NULL means unverified. A timestamp rather than a boolean because "when"
    # answers questions later that "whether" cannot, at the same storage cost.
    # Verification is a soft gate: an unverified user keeps full use of the app
    # and sees a banner. Nothing here locks anyone out of their own money.
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class RefreshSession(UUIDPk, Base):
    """One live refresh token. Deleting the row is what makes logout real.

    Deliberately not stored: IP address and user-agent. They are the obvious
    things to put here and the usual reason a table like this becomes a tracking
    log. Nothing in this product needs them, so collecting them would be
    unjustifiable under data minimisation — this is financial data belonging to
    someone in the EU.
    """

    __tablename__ = "refresh_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Every rotation of one login keeps the same family. Reuse of an already
    # rotated token means someone has a copy they shouldn't, so the response is
    # to kill the family — this login on this device — rather than every session
    # the user has everywhere.
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when this token was exchanged for its successor. Distinguishes "rotated
    # a moment ago, probably a second tab" from "revoked", which need different
    # answers. See `refresh_rotation_grace_seconds`.
    rotated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_refresh_sessions_user", "user_id"),
        Index("ix_refresh_sessions_family", "family_id"),
    )


class AuthToken(UUIDPk, Base):
    """A single-use emailed secret: password reset or email verification.

    One table for both because the mechanics are identical — random secret,
    SHA-256 at rest, an expiry, consumed once — and only the lifetime and the
    effect of redeeming it differ. Two tables would be the same code twice.
    """

    __tablename__ = "auth_tokens"

    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFY = "email_verify"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('password_reset','email_verify')", name="ck_auth_tokens_purpose"
        ),
        Index("ix_auth_tokens_user_purpose", "user_id", "purpose"),
    )


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


class DailyNote(UUIDPk, Timestamped, Base):
    """Frankly's once-a-day check-in (the daily hook). One row per user per day; the
    row's existence also *is* the "checked in today" signal the streak is built on."""

    __tablename__ = "daily_notes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    note_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # 'go' | 'wait' | 'over' | 'unknown' (no income on file — see services/daily.py).
    # The note text is written *for* this mood, so if the day's live mood moves away
    # from it the note is stale and gets rewritten.
    mood: Mapped[str] = mapped_column(Text, nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint("mood IN ('go','wait','over','unknown')", name="ck_daily_notes_mood"),
        UniqueConstraint("user_id", "note_date", name="uq_daily_notes_user_date"),
        Index("ix_daily_notes_user_date", "user_id", text("note_date DESC")),
    )


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
