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
    - ``password_reset_ticket`` and ``oauth_handoff`` hold 32 random bytes, which
      are not, so the hash is SHA-256 and the row is found *by the hash*.

    ``secret_hash`` is therefore not uniquely indexed: two users could in
    principle hold bcrypt hashes that collide in no meaningful way, and more to
    the point a bcrypt hash of the same code differs every time.
    """

    __tablename__ = "auth_tokens"

    EMAIL_VERIFY_CODE = "email_verify_code"
    PASSWORD_RESET_CODE = "password_reset_code"
    PASSWORD_RESET_TICKET = "password_reset_ticket"
    #: Redeemed once, seconds after it is issued, for the access token that ends
    #: a Google sign-in. See ``routers/oauth`` for why the flow needs one.
    OAUTH_HANDOFF = "oauth_handoff"

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
            "purpose IN ('email_verify_code','password_reset_code',"
            "'password_reset_ticket','oauth_handoff')",
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
            "type IN ('current','savings','cash','liability','person')",
            name="ck_accounts_type",
        ),
        Index("ix_accounts_user", "user_id"),
        Index("uq_accounts_user_lower_name", "user_id", text("lower(name)"), unique=True),
    )


class NotificationSetting(UUIDPk, Timestamped, Base):
    """Whether a kind of message is wanted, and when it last went out.

    `last_sent_at` is what makes a double send impossible. The sender claims a week by
    updating this column with a predicate and acting only on the rows the update
    returned, so two overlapping cron runs cannot both pick up the same person. If
    delivery then fails the claim stands and they miss a week — worse than a perfect
    send, and much better than being emailed the same digest twice.
    """

    __tablename__ = "notification_settings"

    WEEKLY_DIGEST = "weekly_digest"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('weekly_digest')", name="ck_notification_kind"),
        UniqueConstraint("user_id", "kind", name="uq_notification_user_kind"),
    )


class FxRate(UUIDPk, Timestamped, Base):
    """A published rate, kept so a new transaction has something honest to convert with.

    ``rate`` is **base units per one quote unit** — `base_amount = amount * rate`, the
    same direction as `Transaction.fx_rate`. Two conventions in one codebase is how a
    figure ends up inverted with nobody noticing, so there is only one.

    Never used to recompute anything already recorded: `base_amount_cents` is frozen
    when its row is written, and this table has no say over it afterwards.
    """

    __tablename__ = "fx_rates"

    base: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    quote: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    rate_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)

    __table_args__ = (
        CheckConstraint("rate > 0", name="ck_fx_rates_positive"),
        CheckConstraint("base <> quote", name="ck_fx_rates_distinct"),
        UniqueConstraint("base", "quote", "rate_on", name="uq_fx_rate_day"),
        Index("ix_fx_rates_pair_day", "base", "quote", "rate_on"),
    )


class Asset(UUIDPk, Timestamped, Base):
    """Something owned that has no ledger — a car, a flat, a fund held elsewhere.

    Nothing transacts against it. There is only what someone says it is worth and when
    they said so, which is why this is not an account: an account is opening balance
    plus entries, and there are no entries here.
    """

    __tablename__ = "assets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    group: Mapped[str] = mapped_column(Text, nullable=False)
    # Selling needs no special case: an archived asset counts its last stated value up
    # to this moment and nothing after, so the trend falls on the day of the sale.
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("\"group\" IN ('physical','investment')", name="ck_assets_group"),
        Index("ix_assets_user", "user_id"),
        Index("uq_assets_user_lower_name", "user_id", text("lower(name)"), unique=True),
    )


class AssetValuation(UUIDPk, Timestamped, Base):
    """What an asset was said to be worth, on a day. Append-only.

    Net worth at a past date reads the most recent valuation on or before it, so a
    valuation entered late but dated correctly rewrites the trend from that point. A
    table of snapshots could not — it would disagree with the ledger and offer no way
    to tell which was right.
    """

    __tablename__ = "asset_valuations"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    valued_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Signed, unlike every other money column: a thing can be worth less than nothing.
    value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "valued_on", name="uq_asset_valuation_day"),
        Index("ix_asset_valuations_asset", "asset_id", "valued_on"),
    )


class RecurringTemplate(UUIDPk, Timestamped, Base):
    """A thing that repeats — rent, a salary, a subscription.

    The template describes the schedule; occurrences whose date has arrived become
    ordinary transactions, so every figure downstream sees them without knowing they
    were generated. Future occurrences are not stored at all.

    ``last_materialised_on`` is the occurrence date generation has reached, and it is
    what makes deleting a generated row stick: asking the transactions table "is there
    one for this date?" would recreate a row the user removed, silently, on the next
    page load. Generation only ever moves forward from here.
    """

    __tablename__ = "recurring_templates"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    cadence: Mapped[str] = mapped_column(Text, nullable=False)
    start_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    last_materialised_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('expense','income')", name="ck_recurring_kind"),
        CheckConstraint("amount_cents > 0", name="ck_recurring_amount_positive"),
        CheckConstraint("cadence IN ('weekly','monthly','yearly')", name="ck_recurring_cadence"),
        CheckConstraint("end_on IS NULL OR end_on >= start_on", name="ck_recurring_end_after"),
        Index("ix_recurring_user", "user_id"),
    )


class RecurringSkip(UUIDPk, Timestamped, Base):
    """One occurrence of a template that should not happen.

    Suppresses the date in both places it would otherwise appear — materialisation and
    the forecast. Only one of the two would be a bug in opposite directions: skipping
    without suppressing the forecast reserves money for something cancelled, and the
    other way round pays out for something the user said would not.
    """

    __tablename__ = "recurring_skips"

    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recurring_templates.id", ondelete="CASCADE"), nullable=False
    )
    skip_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("template_id", "skip_on", name="uq_recurring_skip"),)


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
    # The far side of a transfer, and NULL for everything else — enforced by
    # ``ck_transactions_transfer_shape``. A transfer is deliberately *one* row: the
    # matched-pair alternative needs application code to keep "both legs exist and sum
    # to zero" true forever, and gives every future aggregate somewhere to forget it.
    # One row makes half a transfer unrepresentable instead.
    counter_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    # Set on rows a recurring template generated. SET NULL rather than the RESTRICT
    # used for accounts: deleting a template must not delete the rent you actually
    # paid — that money moved. The rows stay and stop being attributed to a template.
    recurring_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_templates.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # What the transaction was, in the currency it happened in.
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    # The same money in the user's reporting currency, **frozen when it was recorded**.
    # Every report reads this and never a rate: converting at read time would move last
    # March's spending because the euro moved this morning.
    base_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # What was actually used to get there — published, stale, or typed off a statement.
    # Kept for the audit trail; never used to recompute the amount beside it.
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('expense','income','transfer','refund','adjustment_up','adjustment_down')",
            name="ck_transactions_kind",
        ),
        # A transfer needs both ends, they must differ, and it carries no category — so
        # it can never reach a budget however the row is written. Enforced here rather
        # than trusted to the router, because a constraint cannot be forgotten.
        CheckConstraint(
            "(kind = 'transfer'"
            " AND account_id IS NOT NULL"
            " AND counter_account_id IS NOT NULL"
            " AND counter_account_id <> account_id"
            " AND category_id IS NULL)"
            " OR (kind <> 'transfer' AND counter_account_id IS NULL)",
            name="ck_transactions_transfer_shape",
        ),
        CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("fx_rate > 0", name="ck_transactions_fx_rate_positive"),
        CheckConstraint("base_amount_cents > 0", name="ck_transactions_base_amount_positive"),
        CheckConstraint(
            "source IN ('manual','nl_parse','reconcile','recurring')",
            name="ck_transactions_source",
        ),
        Index("ix_transactions_user_occurred", "user_id", text("occurred_on DESC")),
        Index("ix_transactions_user_category", "user_id", "category_id"),
        Index("ix_transactions_account", "account_id"),
        Index("ix_transactions_counter_account", "counter_account_id"),
        # Partial: only generated rows are constrained. This is the backstop against
        # two concurrent reads both materialising the same occurrence.
        Index(
            "uq_transactions_recurrence",
            "recurring_template_id",
            "occurred_on",
            unique=True,
            postgresql_where=text("recurring_template_id IS NOT NULL"),
        ),
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
