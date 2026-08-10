"""Recurring templates — the schedule, not the rows it produces.

Creating a template does not create anything to spend against: an occurrence becomes a
transaction only once its date arrives (`services/recurring.materialise_due`). A rent
payment due next month is a plan, and reporting a plan as money spent is the kind of
confident wrongness this app exists to avoid.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, LedgerUpToDate, Today
from app.models import Account, Category, RecurringSkip, RecurringTemplate
from app.schemas import RecurringCreate, RecurringOut, RecurringUpdate, SkipIn, UpcomingOut
from app.services.recurring import occurrences

router = APIRouter(prefix="/recurring", tags=["recurring"])


def _owned(db: Session, user_id: uuid.UUID, template_id: uuid.UUID) -> RecurringTemplate:
    template = db.get(RecurringTemplate, template_id)
    if template is None or template.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring item not found")
    return template


def _check_refs(
    db: Session,
    user_id: uuid.UUID,
    category_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
) -> None:
    if category_id is not None:
        category = db.get(Category, category_id)
        if category is None or category.user_id != user_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown category")
    if account_id is not None:
        account = db.get(Account, account_id)
        if account is None or account.user_id != user_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown account")
        if account.type == "person":
            # Lending is a relationship, not a subscription.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Pick an account of your own for something that repeats.",
            )


def _skips_for(db: Session, template_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[dt.date]]:
    if not template_ids:
        return {}
    out: dict[uuid.UUID, set[dt.date]] = {}
    for row in db.scalars(select(RecurringSkip).where(RecurringSkip.template_id.in_(template_ids))):
        out.setdefault(row.template_id, set()).add(row.skip_on)
    return out


def _out(
    template: RecurringTemplate, today: dt.date, skips: set[dt.date] | None = None
) -> RecurringOut:
    """`next_on` is derived, so it can never disagree with the schedule it describes.

    Skipped dates are stepped over. Naming one as "next" would be the screen asserting
    a payment the user has just said will not happen.
    """
    skipped = skips or set()
    upcoming = next(
        (
            occurs_on
            for occurs_on in occurrences(
                cadence=template.cadence,
                start_on=template.start_on,
                end_on=template.end_on,
                # A year ahead is far enough to find the next one for any cadence we
                # support, and bounds the walk for a template that has already ended.
                through=today + dt.timedelta(days=400),
                after=max(today, template.last_materialised_on or today),
            )
            if occurs_on not in skipped
        ),
        None,
    )
    return RecurringOut(
        id=template.id,
        name=template.name,
        kind=template.kind,
        amount_cents=template.amount_cents,
        cadence=template.cadence,
        start_on=template.start_on,
        end_on=template.end_on,
        category_id=template.category_id,
        account_id=template.account_id,
        archived_at=template.archived_at,
        next_on=None if template.archived_at is not None else upcoming,
    )


# Carries the dependency too, though it aggregates nothing: `next_on` is derived from
# how far generation has reached, so a screen that reported it without generating first
# could say "next 1 September" while August's row had not been written yet.
@router.get("", response_model=list[RecurringOut], dependencies=[LedgerUpToDate])
def list_recurring(
    user: CurrentUser,
    db: DbSession,
    today: Today,
    include_archived: bool = Query(default=False),
) -> list[RecurringOut]:
    stmt = select(RecurringTemplate).where(RecurringTemplate.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(RecurringTemplate.archived_at.is_(None))
    rows = list(db.scalars(stmt.order_by(RecurringTemplate.name)))
    skips = _skips_for(db, [row.id for row in rows])
    return [_out(row, today, skips.get(row.id)) for row in rows]


@router.get("/upcoming", response_model=list[UpcomingOut], dependencies=[LedgerUpToDate])
def upcoming(
    user: CurrentUser,
    db: DbSession,
    today: Today,
    days: int = Query(default=60, ge=1, le=400),
) -> list[UpcomingOut]:
    """What is still to come, computed on the fly.

    Strictly after today: everything up to and including today has been written as a
    real transaction already, so listing it here would show it twice.
    """
    through = today + dt.timedelta(days=days)
    templates = list(
        db.scalars(
            select(RecurringTemplate).where(
                RecurringTemplate.user_id == user.id,
                RecurringTemplate.archived_at.is_(None),
            )
        )
    )
    skips: dict[uuid.UUID, set[dt.date]] = {}
    if templates:
        for row in db.scalars(
            select(RecurringSkip).where(RecurringSkip.template_id.in_([t.id for t in templates]))
        ):
            skips.setdefault(row.template_id, set()).add(row.skip_on)

    out: list[UpcomingOut] = []
    for template in templates:
        for occurs_on in occurrences(
            cadence=template.cadence,
            start_on=template.start_on,
            end_on=template.end_on,
            through=through,
            after=today,
        ):
            out.append(
                UpcomingOut(
                    template_id=template.id,
                    name=template.name,
                    kind=template.kind,
                    amount_cents=template.amount_cents,
                    occurs_on=occurs_on,
                    category_id=template.category_id,
                    account_id=template.account_id,
                    # Shown rather than hidden: a skipped rent is a decision the user
                    # made, and it should be visible and reversible, not just absent.
                    skipped=occurs_on in skips.get(template.id, set()),
                )
            )
    return sorted(out, key=lambda item: (item.occurs_on, item.name))


@router.post("/{template_id}/skips", status_code=status.HTTP_204_NO_CONTENT)
def skip_occurrence(
    template_id: uuid.UUID, body: SkipIn, user: CurrentUser, db: DbSession, today: Today
) -> None:
    """Say one occurrence will not happen, before it does.

    Refused for a date already past, because by then the row either exists — delete it
    — or generation has moved beyond it and a skip would change nothing while looking
    as though it had.
    """
    _owned(db, user.id, template_id)
    if body.skip_on <= today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That date has already passed — delete the entry instead.",
        )
    db.add(RecurringSkip(template_id=template_id, skip_on=body.skip_on))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # already skipped; saying so twice means the same thing


@router.delete("/{template_id}/skips/{skip_on}", status_code=status.HTTP_204_NO_CONTENT)
def unskip_occurrence(
    template_id: uuid.UUID, skip_on: dt.date, user: CurrentUser, db: DbSession
) -> None:
    _owned(db, user.id, template_id)
    row = db.scalar(
        select(RecurringSkip).where(
            RecurringSkip.template_id == template_id, RecurringSkip.skip_on == skip_on
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()


@router.post("", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
def create_recurring(
    body: RecurringCreate, user: CurrentUser, db: DbSession, today: Today
) -> RecurringOut:
    _check_refs(db, user.id, body.category_id, body.account_id)
    start_on = body.start_on or today
    if body.end_on is not None and body.end_on < start_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The end date is before the start date."
        )
    template = RecurringTemplate(
        user_id=user.id,
        name=body.name.strip(),
        kind=body.kind,
        amount_cents=body.amount_cents,
        cadence=body.cadence,
        start_on=start_on,
        end_on=body.end_on,
        category_id=body.category_id,
        account_id=body.account_id,
    )
    db.add(template)
    db.commit()
    # Brand new, so nothing can have been skipped yet.
    return _out(template, today)


@router.patch("/{template_id}", response_model=RecurringOut)
def update_recurring(
    template_id: uuid.UUID,
    body: RecurringUpdate,
    user: CurrentUser,
    db: DbSession,
    today: Today,
) -> RecurringOut:
    """Edits apply to occurrences still to come.

    Rows already generated are ordinary transactions and are left exactly alone — they
    record what actually happened, and a rent rise does not change what last month cost.
    Correcting one of those means editing that transaction.
    """
    template = _owned(db, user.id, template_id)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, user.id, data.get("category_id"), data.get("account_id"))

    if "archived" in data and data["archived"] is not None:
        template.archived_at = dt.datetime.now(dt.UTC) if data["archived"] else None
    for field in ("name", "amount_cents", "cadence", "end_on", "category_id", "account_id"):
        if field in data:
            value = data[field]
            setattr(template, field, value.strip() if field == "name" and value else value)

    if template.end_on is not None and template.end_on < template.start_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The end date is before the start date."
        )
    db.commit()
    return _out(template, today, _skips_for(db, [template.id]).get(template.id))


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(template_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """The schedule goes; the rows it already produced stay.

    Those are transactions that really happened — the foreign key is SET NULL, so they
    simply stop being attributed to a template.
    """
    template = _owned(db, user.id, template_id)
    db.delete(template)
    db.commit()
