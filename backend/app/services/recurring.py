"""Recurring templates: when they fall due, and turning what is due into real rows.

Two halves, kept apart on purpose. `occurrences` is pure date arithmetic and is where
the bugs in a feature like this actually live — month ends, leap years, the turn of the
year — so it is testable without a database. `materialise_due` is the part that writes.

Nothing here forecasts. Occurrences whose date has not arrived are not stored and not
counted; a future rent payment is a plan, not a transaction, and the app must not
report money as spent before it leaves.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RecurringTemplate, Transaction, User
from app.services.aggregates import days_in_period

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
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, days_in_period(dt.date(year, month, 1)))
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
    created = 0
    for template in due_templates(db, user.id, today):
        due = list(
            occurrences(
                cadence=template.cadence,
                start_on=template.start_on,
                end_on=template.end_on,
                through=today,
                after=template.last_materialised_on,
            )
        )[:MAX_PER_PASS]
        if not due:
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
                    description=template.name,
                    occurred_on=occurs_on,
                    source="recurring",
                )
            )
            created += 1
        template.last_materialised_on = due[-1]

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
