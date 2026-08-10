"""Recurring templates: when they fall due, and turning what is due into real rows.

Two halves, kept apart on purpose. `occurrences` is pure date arithmetic and is where
the bugs in a feature like this actually live — month ends, leap years, the turn of the
year — so it is testable without a database. `materialise_due` is the part that writes.

Nothing here forecasts. Occurrences whose date has not arrived are not stored and not
counted; a future rent payment is a plan, not a transaction, and the app must not
report money as spent before it leaves.
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RecurringSkip, RecurringTemplate, Transaction, User
from app.services.money import SAME_CURRENCY_RATE

# A runaway guard, not a product limit. A template backdated years generates its whole
# history on first read; this caps one pass so a single request cannot spiral, and the
# next read carries on from where it stopped.
MAX_PER_PASS = 400


def _add_months(anchor: dt.date, months: int) -> dt.date:
    """``anchor`` shifted by whole months, clamped to the length of the target month.

    A template anchored on the 31st lands on the 28th in February and returns to the
    31st in March — it tracks the anchor rather than drifting down to the 28th for
    ever, which is what repeatedly adding "one month" to the previous result would do.
    """
    # `calendar`, deliberately not `aggregates.days_in_period`. That helper answers
    # "how long is the budgeting period", which happens to equal a calendar month today
    # and would not if periods were ever anchored to a payday. A monthly recurrence
    # clamps to the end of a *calendar month* whatever a budgeting period turns out to
    # be, and the two questions only look like one right now.
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def occurrences(
    *,
    cadence: str,
    start_on: dt.date,
    end_on: dt.date | None,
    through: dt.date,
    after: dt.date | None = None,
) -> Iterator[dt.date]:
    """Every occurrence date in ``(after, through]``, oldest first.

    ``after`` is exclusive so a caller can pass the last date it already handled.
    """
    index = 0
    while True:
        if cadence == "weekly":
            occurs_on = start_on + dt.timedelta(weeks=index)
        elif cadence == "monthly":
            occurs_on = _add_months(start_on, index)
        elif cadence == "yearly":
            occurs_on = _add_months(start_on, 12 * index)
        else:  # pragma: no cover — the CHECK constraint admits nothing else
            raise ValueError(f"unknown cadence {cadence!r}")

        if occurs_on > through or (end_on is not None and occurs_on > end_on):
            return
        if after is None or occurs_on > after:
            yield occurs_on
        index += 1


def _skips(db: Session, template_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[dt.date]]:
    """Dates the user has said will not happen, per template.

    Read here rather than folded into `occurrences`, which stays pure date arithmetic —
    a schedule and an exception to it are different things.
    """
    if not template_ids:
        return {}
    out: dict[uuid.UUID, set[dt.date]] = {}
    for row in db.scalars(select(RecurringSkip).where(RecurringSkip.template_id.in_(template_ids))):
        out.setdefault(row.template_id, set()).add(row.skip_on)
    return out


def due_templates(db: Session, user_id: uuid.UUID, today: dt.date) -> list[RecurringTemplate]:
    """Live templates that might owe a row, cheaply.

    The common case is nothing at all: `last_materialised_on` has already reached today
    for every template, so this returns empty without touching a transaction.
    """
    return list(
        db.scalars(
            select(RecurringTemplate).where(
                RecurringTemplate.user_id == user_id,
                RecurringTemplate.archived_at.is_(None),
                RecurringTemplate.start_on <= today,
                (RecurringTemplate.last_materialised_on.is_(None))
                | (RecurringTemplate.last_materialised_on < today),
            )
        )
    )


def materialise_due(db: Session, user: User, today: dt.date) -> int:
    """Write the occurrences that have arrived. Returns how many rows were created.

    Only up to and including ``today``. Generation resumes from
    ``last_materialised_on``, never from "does a row already exist" — the latter would
    resurrect a row the user deleted, on their next page load, for ever.
    """
    templates = due_templates(db, user.id, today)
    skipped = _skips(db, [t.id for t in templates])

    created = 0
    for template in templates:
        due = list(
            occurrences(
                cadence=template.cadence,
                start_on=template.start_on,
                end_on=template.end_on,
                through=today,
                after=template.last_materialised_on,
            )
        )[:MAX_PER_PASS]
        skips = skipped.get(template.id, set())
        # A skipped date still counts as reached: generation must move past it, or the
        # same date would be reconsidered on every read for ever.
        reached = due[-1] if due else None
        due = [d for d in due if d not in skips]
        if not due:
            if reached is not None:
                template.last_materialised_on = reached
                continue
            # Nothing owed, but the template has been checked as far as today: record
            # that so the next read skips it instead of re-deriving the same nothing.
            template.last_materialised_on = today
            continue

        for occurs_on in due:
            db.add(
                Transaction(
                    user_id=user.id,
                    recurring_template_id=template.id,
                    account_id=template.account_id,
                    category_id=template.category_id,
                    kind=template.kind,
                    amount_cents=template.amount_cents,
                    # Templates are in the reporting currency until foreign recurring
                    # exists, so the conversion is exactly one rather than assumed.
                    currency=user.currency.upper(),
                    base_amount_cents=template.amount_cents,
                    fx_rate=SAME_CURRENCY_RATE,
                    description=template.name,
                    occurred_on=occurs_on,
                    source="recurring",
                )
            )
            created += 1
        template.last_materialised_on = reached or due[-1]

    if created == 0:
        db.commit()
        return 0

    try:
        db.commit()
    except IntegrityError:
        # Another request materialised the same occurrences between our read of
        # `last_materialised_on` and this write. The unique index is what makes that
        # safe rather than duplicated; there is nothing left to do.
        db.rollback()
        return 0
    return created


def forecast(
    db: Session,
    user_id: uuid.UUID,
    *,
    today: dt.date,
    through: dt.date,
) -> dict[uuid.UUID | None, int]:
    """Expense occurrences still to come, per category, in ``(today, through]``.

    **Strictly after today**, because everything up to and including today has already
    been materialised and is counted as spent — overlapping the two would charge the
    same rent twice.

    **Expenses only.** A recurring salary and ``users.monthly_income_cents`` are the
    same statement made twice; counting an upcoming salary as income would inflate the
    month by a month's pay for anyone who has stated both.
    """
    templates = list(
        db.scalars(
            select(RecurringTemplate).where(
                RecurringTemplate.user_id == user_id,
                RecurringTemplate.archived_at.is_(None),
                RecurringTemplate.kind == "expense",
            )
        )
    )
    skipped = _skips(db, [t.id for t in templates])

    out: dict[uuid.UUID | None, int] = {}
    for template in templates:
        skips = skipped.get(template.id, set())
        upcoming = [
            occurs_on
            for occurs_on in occurrences(
                cadence=template.cadence,
                start_on=template.start_on,
                end_on=template.end_on,
                through=through,
                after=today,
            )
            if occurs_on not in skips
        ]
        if upcoming:
            out[template.category_id] = out.get(
                template.category_id, 0
            ) + template.amount_cents * len(upcoming)
    return out
