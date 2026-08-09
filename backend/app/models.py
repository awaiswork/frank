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
    SmallInteger,
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
    # NULL for an account that only ever signed in with Google. Every read has to
    # cope with that: `login` treats a null hash as a failed password rather than
    # announcing "this address uses Google", which would confirm the account
    # exists to anyone who asked.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="EUR")
    # IANA name, e.g. "Europe/Helsinki". NULL means they have never told us, which is
    # deliberately not the same as being in UTC — reads fall back to UTC either way, but
    # only NULL says we are entitled to ask. Validated on write in `UserUpdate`; a value
    # the tz database no longer recognises degrades to UTC rather than raising.
    timezone: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_income_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # NULL means unverified, and unverified means no session is ever issued — the
    # gate is that a token doesn't exist yet, not a check on each request. A
    # timestamp rather than a boolean because "when" answers questions later that
    # "whether" cannot, at the same storage cost.
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
    """A short-lived single-use secret, of one of four kinds.

    One table because the mechanics are identical — a secret, a hash at rest, an
    expiry, consumed once — and only the lifetime and the effect of redeeming it
    differ. What varies is the *shape* of the secret, and that changes the hash:

    - the two ``*_code`` purposes hold a six-digit OTP, which is guessable, so
      the hash is bcrypt and the row is found by ``(user_id, purpose)``;
    - ``password_reset_ticket`` holds 32 random bytes, which are not, so the hash
      is SHA-256 and the row is found *by the hash*.

    ``secret_hash`` is therefore not uniquely indexed: two users could in
    principle hold bcrypt hashes that collide in no meaningful way, and more to
    the point a bcrypt hash of the same code differs every time.
    """

    __tablename__ = "auth_tokens"

    EMAIL_VERIFY_CODE = "email_verify_code"
    PASSWORD_RESET_CODE = "password_reset_code"
    PASSWORD_RESET_TICKET = "password_reset_ticket"

    #: The purposes whose secret is a six-digit code rather than a random string.
    CODE_PURPOSES = (EMAIL_VERIFY_CODE, PASSWORD_RESET_CODE)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A six-digit code is one of a million, which is guessable at machine speed.
    # Without a ceiling on wrong answers that million collapses to a few thousand
    # tries, and the code would be materially weaker than the link it replaced.
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verify_code','password_reset_code','password_reset_ticket')",
            name="ck_auth_tokens_purpose",
        ),
        Index("ix_auth_tokens_user_purpose", "user_id", "purpose"),
        Index("ix_auth_tokens_secret_hash", "secret_hash"),
    )


class OAuthState(UUIDPk, Base):
    """One half-finished Google sign-in.

    Its own table rather than a row in ``auth_tokens`` because it belongs to a
    browser mid-flow, not to a user — there may not be an account yet, and
    ``auth_tokens.user_id`` is NOT NULL for good reason. Forcing it in would have
    meant either a nullable FK on every other purpose or a reserved sentinel user,
    both of which are worse than one small table.

    Living here also keeps OAuth out of the cookie jar entirely: the state and the
    PKCE verifier are server-side, so the flow adds no cookie and cannot disturb
    the cross-site refresh cookie, which is fragile and deliberately untouched.
    """

    __tablename__ = "oauth_states"

    state_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    #: PKCE verifier. Binds the authorization code to the browser that started
    #: the flow, so a code intercepted in the redirect cannot be redeemed alone.
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthAccount(UUIDPk, Base):
    """A third-party identity attached to one of our users.

    Keyed on the provider's stable subject id, never on the email — people change
    the address on a Google account, and matching on a mutable field would hand
    the wrong account to whoever inherits an old one.
    """

    __tablename__ = "oauth_accounts"

    GOOGLE = "google"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),
        Index("ix_oauth_accounts_user", "user_id"),
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


class Account(UUIDPk, Timestamped, Base):
    """Somewhere money sits, with a ledger that moves it.

    Only things you can transact against live here — `type` is deliberately narrow.
    A car or an apartment has no entries to sum, only a value someone states; that is
    an asset with valuations, which is a different shape and a different table.

    The balance is **always derived** (`services/accounts.balances`), never stored:
    ``opening_balance_cents`` plus every signed entry from ``opened_on`` onward. A
    stored balance rots the first time anything is edited, deleted or backdated, and it
    rots silently, which is the worst way for a money figure to be wrong.
    """

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    # NOT NULL from the start though only the user's own currency is accepted for now.
    # An account's currency is part of its identity, so adding it later would mean
    # auditing every query written in the meantime that assumed all amounts compare.
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    # The balance at the **start** of `opened_on` — entries on that day count on top of
    # it. Stated the other way round, they would be counted twice.
    opening_balance_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    opened_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('current','savings','cash','liability')", name="ck_accounts_type"
        ),
        Index("ix_accounts_user", "user_id"),
        Index("uq_accounts_user_lower_name", "user_id", text("lower(name)"), unique=True),
    )


class Transaction(UUIDPk, Timestamped, Base):
    __tablename__ = "transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    # RESTRICT, not SET NULL as above: an orphaned category costs a label, an orphaned
    # entry costs money out of a balance with nothing on screen to say so. NULL means
    # the entry predates the ledger (see migration 0007) — it counts toward spending,
    # never toward a balance.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
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
        Index("ix_transactions_account", "account_id"),
    )


class Budget(UUIDPk, Timestamped, Base):
    __tablename__ = "budgets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    # The *start of the budgeting period*, which today is always the first of a calendar
    # month. Read it as a period id rather than as "a month": every boundary in the app
    # comes from ``aggregates.month_bounds``, so anchoring periods elsewhere (a payday
    # month, 25th to 24th) stays a change to that one helper instead of a migration
    # against the rows stored here and the unique constraint over them.
    month: Mapped[dt.date] = mapped_column(Date, nullable=False)
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
    # Explicitly tz-aware. Left implicit, SQLAlchemy infers a naive DateTime() from the
    # annotation, which is *not* what migration 0001 created (timestamptz) — and since
    # tests build their schema from this metadata while production builds it from the
    # migrations, the two disagreed silently. `test_schema_drift` now catches that class
    # of divergence; this column was the one that proved it was possible.
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
