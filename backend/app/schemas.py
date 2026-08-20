"""Pydantic v2 request/response models."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Categories and parsed drafts are only ever one of these two — a category cannot be
# a transfer, and its own DB CHECK says so. Kept separate from TransactionKind so
# widening what a *transaction* can be does not quietly widen those.
Kind = Literal["expense", "income"]
TransactionKind = Literal[
    "expense",
    "income",
    "transfer",
    # A returned purchase: gives back spending rather than counting as income.
    "refund",
    # A reconciliation against the real balance. Two kinds so `amount_cents` stays a
    # positive magnitude and the direction keeps living in the kind.
    "adjustment_up",
    "adjustment_down",
]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    # Picks the session lifetime, nothing else. The cookie's security attributes
    # are identical either way.
    remember_me: bool = False


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    ticket: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=8, max_length=128)


class VerifyCodeIn(BaseModel):
    email: EmailStr
    # Exactly six digits. Validated here so a malformed code is rejected before
    # it costs the user one of their five attempts.
    code: str = Field(pattern=r"^\d{6}$")


class ResendCodeIn(BaseModel):
    email: EmailStr
    purpose: Literal["verify", "reset"] = "verify"


class TicketOut(BaseModel):
    """Proof that a reset code was checked, exchanged for a password change."""

    ticket: str


class HandoffIn(BaseModel):
    """The secret Google's callback handed the browser, exchanged for a session."""

    handoff: str = Field(min_length=1, max_length=512)


class MessageOut(BaseModel):
    """The deliberately incurious response.

    `/auth/forgot-password` answers with this whether or not the address belongs
    to anyone, so the shape and the values must not depend on what we found.
    `retry_after_seconds` is a constant from configuration for the same reason —
    a real per-user cooldown would leak existence by varying.
    """

    detail: str
    retry_after_seconds: int | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    currency: str
    timezone: str | None
    monthly_income_cents: int | None
    email_verified: bool


class UserUpdate(BaseModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, max_length=64)
    monthly_income_cents: int | None = Field(default=None, ge=0)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str | None) -> str | None:
        """Reject anything the tz database doesn't know.

        The write edge is the only place this can be checked — Postgres cannot express
        "is a valid IANA name" as a CHECK. Reads deliberately do not validate, so a name
        that is retired from the tz database later degrades to UTC instead of failing
        every request the user makes.
        """
        if v is None:
            return None
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone") from exc
        return v


AccountType = Literal[
    "current",
    "savings",
    "cash",
    "liability",
    # Someone you have lent to or borrowed from. One type, not a receivable/payable
    # pair: the direction is the sign of the balance, so a person you have both lent
    # to and borrowed from stays one relationship with one number.
    "person",
]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: AccountType
    # Balance at the *start* of `opened_on`; entries on that day land on top of it.
    # Signed, unlike a transaction: a liability legitimately opens negative.
    opening_balance_cents: int = 0
    opened_on: dt.date | None = None  # None -> the user's today, in the router
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    type: AccountType | None = None
    opening_balance_cents: int | None = None
    opened_on: dt.date | None = None
    archived: bool | None = None  # maps to archived_at, not a column


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    currency: str
    opening_balance_cents: int
    opened_on: dt.date
    archived_at: dt.datetime | None
    # Derived, never stored — see services/accounts.py.
    balance_cents: int
    entry_count: int


class LendIn(BaseModel):
    """Lend to, or borrow from, someone — in one step so no half-made person survives."""

    person: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0)
    # The account the money actually moves through.
    account_id: uuid.UUID
    # True when they are handing money to you, i.e. you are borrowing.
    borrowing: bool = False
    occurred_on: dt.date | None = None
    description: str | None = Field(default=None, max_length=500)


class ReconcileIn(BaseModel):
    """ "The real balance is X." The difference becomes a visible correction."""

    actual_balance_cents: int
    occurred_on: dt.date | None = None  # None -> the user's today


class AccountsOut(BaseModel):
    accounts: list[AccountOut]
    total_cents: int
    # None until the user has an account. The UI says "balances count from here" so a
    # total is never mistaken for one that covers the whole transaction history.
    ledger_starts_on: dt.date | None


Cadence = Literal["weekly", "monthly", "yearly"]


class RecurringCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "expense"
    amount_cents: int = Field(gt=0)
    cadence: Cadence = "monthly"
    start_on: dt.date | None = None  # None -> the user's today
    end_on: dt.date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None


class RecurringUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount_cents: int | None = Field(default=None, gt=0)
    cadence: Cadence | None = None
    end_on: dt.date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    archived: bool | None = None


class RecurringOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    amount_cents: int
    cadence: str
    start_on: dt.date
    end_on: dt.date | None
    category_id: uuid.UUID | None
    account_id: uuid.UUID | None
    archived_at: dt.datetime | None
    # Computed, not stored: the next date this falls due, or None once it has ended.
    next_on: dt.date | None


class UpcomingOut(BaseModel):
    """One occurrence still to come — computed, never stored."""

    template_id: uuid.UUID
    name: str
    kind: str
    amount_cents: int
    occurs_on: dt.date
    category_id: uuid.UUID | None
    account_id: uuid.UUID | None
    skipped: bool


class SkipIn(BaseModel):
    skip_on: dt.date


AssetGroup = Literal["physical", "investment"]


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    group: AssetGroup = "physical"
    # Signed: a thing can be worth less than nothing.
    value_cents: int
    valued_on: dt.date | None = None  # None -> the user's today


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    group: AssetGroup | None = None
    archived: bool | None = None


class ValuationIn(BaseModel):
    value_cents: int
    valued_on: dt.date | None = None


class AssetOut(BaseModel):
    id: uuid.UUID
    name: str
    group: str
    archived_at: dt.datetime | None
    # The latest stated value, and when it was stated. None before anything is said.
    value_cents: int | None
    last_valued_on: dt.date | None
    # Reported rather than judged: how stale a car and an index fund each are is not
    # the same question, and the answer belongs where it is being shown.
    days_since_valued: int | None


class NetWorthPointOut(BaseModel):
    on: dt.date
    accounts_cents: int
    assets_cents: int
    total_cents: int


class NetWorthOut(BaseModel):
    points: list[NetWorthPointOut]
    # Earliest date the line is comparable. Before it, something now on file was not
    # yet known, so a rise there is Frankly learning rather than the user gaining.
    complete_from: dt.date | None


class NotificationsOut(BaseModel):
    weekly_digest: bool
    #: Monday is 0, matching `date.weekday()` and the CHECK on the column.
    send_weekday: int
    send_hour: int


class NotificationsUpdate(BaseModel):
    weekly_digest: bool | None = None
    # Bounded here as well as in the database. The constraint is what makes a bad value
    # impossible; this is what makes it a 422 with a readable message instead of a 500
    # from a violated CHECK.
    send_weekday: int | None = Field(default=None, ge=0, le=6)
    send_hour: int | None = Field(default=None, ge=0, le=23)


class UnsubscribeIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: Kind
    color: str | None


class TransactionCreate(BaseModel):
    kind: TransactionKind = "expense"
    account_id: uuid.UUID | None = None
    # What it was in, if not your own money. The published rate for the day is used
    # unless `base_amount_cents` says what actually left the account — which a bank
    # statement does, and which is better evidence than any mid-market rate.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    base_amount_cents: int | None = Field(default=None, gt=0)
    # Required for a transfer and rejected otherwise — see `_require_transfer_shape`
    # in the router, and ck_transactions_transfer_shape behind it.
    counter_account_id: uuid.UUID | None = None
    amount_cents: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    occurred_on: dt.date
    category_id: uuid.UUID | None = None


class TransactionUpdate(BaseModel):
    kind: TransactionKind | None = None
    account_id: uuid.UUID | None = None
    counter_account_id: uuid.UUID | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    occurred_on: dt.date | None = None
    category_id: uuid.UUID | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    account_id: uuid.UUID | None
    counter_account_id: uuid.UUID | None
    # What it was in, and what it came to. Equal, with a rate of 1, whenever the two
    # are the same currency.
    currency: str
    base_amount_cents: int
    # Set when a recurring template generated this row; null once the template is gone.
    recurring_template_id: uuid.UUID | None
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
    # Recurring expenses still due this month — what a screen shows to explain why the
    # figure moved, rather than leaving it to drop unexplained.
    upcoming_cents: int
    safe_to_spend_cents: int
    # False -> we have no income to reason from; the client must not present
    # safe_to_spend_cents as a verdict (see aggregates.SafeToSpend).
    income_known: bool


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


# --- Advisor (M4) ------------------------------------------------------------

Verdict = Literal["go", "wait", "skip", "your_call"]


class AdvisorAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)  # §7a input limit
    amount_cents: int | None = Field(default=None, ge=0)


class EvidenceOut(BaseModel):
    label: str
    value: str


class AdviceHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    amount_cents: int | None
    verdict: Verdict | None
    reasoning: str
    evidence: list[EvidenceOut]
    user_followed: bool | None
    created_at: dt.datetime


class AdvisorFollowedIn(BaseModel):
    user_followed: bool


# --- Daily note (the hook) ---------------------------------------------------

Mood = Literal["go", "wait", "over", "unknown"]


class DailyNoteOut(BaseModel):
    date: dt.date
    mood: Mood
    headline: str
    note: str
    streak: int


# --- Feature flags -----------------------------------------------------------


class FeaturesOut(BaseModel):
    """What this deployment has switched on, so the client knows what to render.

    Presentation only — the server enforces the same flags on every billable
    route (app/features.py), so a client that ignores this gets a 503.
    """

    ai_enabled: bool
    nl_capture: bool
    advisor: bool
    ai_daily_note: bool
