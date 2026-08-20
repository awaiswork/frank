"""The weekly digest: who is due one, and what it is allowed to say.

Two halves, and the first is the one that can go wrong quietly.

**Choosing who to send to** claims the week before sending it. The selection is an
``UPDATE ... RETURNING`` with the "not sent recently" predicate inside it, so two
overlapping cron runs cannot both pick up the same person: the second update matches no
rows. If delivery then fails, the claim stands and that person misses a week. That is
the deliberate trade — a missed digest is a disappointment, a duplicate one is the app
looking broken, and only one of the two can be avoided at a time.

**Building the content** goes through the same aggregates every screen uses. There are
no numbers here that are not already on a screen somewhere, which is the point: a digest
is the easiest place in the app to assert something nobody is watching, so it is given
nothing new to assert. `income_known` gates safe-to-spend here exactly as it does on
Home.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import NotificationSetting, User
from app.services import recurring
from app.services.aggregates import (
    _is_spend,
    _spent,
    parse_month,
    safe_to_spend,
    spend_by_category,
)

#: What a reader gets before they choose otherwise, and what everyone got when the
#: schedule was fixed. Monday is 0, matching `date.weekday()`.
DEFAULT_WEEKDAY = 0
DEFAULT_HOUR = 8

#: How long after its appointed hour a digest may still go out.
#:
#: This is the slack that absorbs the scheduler. GitHub's cron is best-effort and skews
#: under load — an hour is routinely late and occasionally never arrives at all — so a
#: window exactly one hour wide would drop a reader's week with nothing in any log to
#: say why.
#:
#: It replaces a check that read `weekday == SEND_WEEKDAY and hour >= SEND_HOUR`. That
#: gave the same protection *by accident*: with the hour fixed at 08:00 the digest
#: stayed eligible until midnight, sixteen hours later. The slack was a property of the
#: chosen hour rather than a decision, and the moment a reader picked 23:00 it silently
#: became one hour. Stating it as a duration is what makes every hour equally safe.
#:
#: It also bounds catching up, which the cooldown it replaces did not: a day after the
#: fact is a late digest, whereas Friday's news on Sunday is just wrong.
CATCH_UP = dt.timedelta(hours=24)


@dataclass(frozen=True)
class DigestContent:
    week_start: dt.date
    spent_cents: int
    previous_spent_cents: int
    top_categories: list[tuple[str, int]]
    upcoming_cents: int
    upcoming_count: int
    safe_to_spend_cents: int | None  # None when there is no income to reason from
    streak: int


def _local_now(user: User, now: dt.datetime) -> dt.datetime:
    """`now` in the user's own zone. Unusable zones fall back to UTC, never raise."""
    if user.timezone:
        try:
            return now.astimezone(ZoneInfo(user.timezone))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return now.astimezone(dt.UTC)


def _appointment(local_now: dt.datetime, weekday: int, hour: int) -> dt.datetime:
    """The most recent local ``weekday`` at ``hour``:00, at or before ``local_now``.

    Arithmetic in wall time, then converted by the caller, so a reader who asked for
    08:00 gets 08:00 on both sides of a daylight-saving change rather than 07:00 for
    half the year. The hour that does not exist on a spring-forward Sunday resolves to
    a real instant rather than raising — a digest an hour off is a digest; an exception
    on that one day a year would take out every reader in that zone.
    """
    days_back = (local_now.weekday() - weekday) % 7
    appointment = (local_now - dt.timedelta(days=days_back)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    # `days_back == 0` on the day itself, where the hour may not have come round yet.
    if appointment > local_now:
        appointment -= dt.timedelta(days=7)
    return appointment


def due_now(db: Session, now: dt.datetime, *, claim: bool = True) -> list[User]:
    """Everyone whose chosen day and hour has arrived and who has not had one.

    Due means three things at once: the appointment has passed, it passed recently
    enough to still be worth sending (`CATCH_UP`), and nothing has been sent since it.

    That last clause is what makes the schedule editable. It compares against *this
    week's appointment* rather than against a fixed number of days, so moving from
    Monday to Thursday takes effect on the Thursday instead of waiting out a cooldown
    measured from a send that answered a different question.

    Enabling on a Wednesday still sends nothing until the chosen day comes round: the
    most recent appointment is then days old, and `CATCH_UP` has long since closed.

    ``claim=False`` answers the same question without taking anyone's week, so a run
    that is not going to send anything can be repeated freely and leaves no trace.
    """
    candidates = list(
        db.execute(
            select(User, NotificationSetting)
            .join(
                NotificationSetting,
                (NotificationSetting.user_id == User.id)
                & (NotificationSetting.kind == NotificationSetting.WEEKLY_DIGEST),
                isouter=True,
            )
            .where(User.email_verified_at.is_not(None))
        )
    )

    due: list[User] = []
    for user, setting in candidates:
        # No row means the defaults, which are on, Monday, 08:00.
        if setting is not None and not setting.enabled:
            continue
        weekday = setting.send_weekday if setting else DEFAULT_WEEKDAY
        hour = setting.send_hour if setting else DEFAULT_HOUR

        appointment = _appointment(_local_now(user, now), weekday, hour).astimezone(dt.UTC)
        if not appointment <= now < appointment + CATCH_UP:
            continue
        if not claim:
            due.append(user)
        elif _claim(db, user.id, now, since=appointment):
            due.append(user)
    return due


def _claim(db: Session, user_id: uuid.UUID, now: dt.datetime, *, since: dt.datetime) -> bool:
    """Take this appointment's slot for one user, atomically. True if we got it.

    The "not sent yet" test lives inside the UPDATE rather than in a read before it.
    Read-then-write would let two overlapping runs both see an old timestamp and both
    send.

    ``since`` is the appointment being claimed, not a rolling cooldown. Comparing to a
    fixed point rather than to "less than N days ago" is what lets a reader move their
    day without either losing a week or getting two.
    """
    claimed = db.execute(
        update(NotificationSetting)
        .where(
            NotificationSetting.user_id == user_id,
            NotificationSetting.kind == NotificationSetting.WEEKLY_DIGEST,
            (NotificationSetting.last_sent_at.is_(None))
            | (NotificationSetting.last_sent_at < since),
        )
        .values(last_sent_at=now)
        .returning(NotificationSetting.id)
    ).first()
    if claimed is not None:
        return True

    # No row to claim yet. Inserting one *is* the claim — and if a concurrent run
    # inserted first, the unique constraint refuses this one, which is the same answer.
    exists = db.scalar(
        select(NotificationSetting.id).where(
            NotificationSetting.user_id == user_id,
            NotificationSetting.kind == NotificationSetting.WEEKLY_DIGEST,
        )
    )
    if exists is not None:
        return False  # a row exists and was sent recently
    db.add(
        NotificationSetting(
            user_id=user_id,
            kind=NotificationSetting.WEEKLY_DIGEST,
            enabled=True,
            last_sent_at=now,
        )
    )
    db.flush()
    return True


def build(db: Session, user: User, today: dt.date) -> DigestContent:
    """What the week looked like — using only figures a screen already shows."""
    week_start = today - dt.timedelta(days=7)
    previous_start = today - dt.timedelta(days=14)

    spent = _sum_spend(db, user.id, week_start, today)
    previous = _sum_spend(db, user.id, previous_start, week_start)

    month_start = parse_month(None, today=today)
    categories = [
        (row.category_name or "Uncategorised", row.spent_cents)
        for row in spend_by_category(db, user.id, month_start)
        if row.spent_cents > 0
    ][:3]

    upcoming = recurring.forecast(db, user.id, today=today, through=today + dt.timedelta(days=7))
    sts = safe_to_spend(db, user.id, user.monthly_income_cents, month_start, today=today)

    from app.services.daily import current_streak

    return DigestContent(
        week_start=week_start,
        spent_cents=spent,
        previous_spent_cents=previous,
        top_categories=categories,
        upcoming_cents=sum(upcoming.values()),
        upcoming_count=len(upcoming),
        # The same gate as every other surface: with no income on file there is no
        # meaningful safe-to-spend, and an email is the last place to start inventing
        # one, because nobody is looking at the screen when it is written.
        safe_to_spend_cents=sts.safe_to_spend_cents if sts.income_known else None,
        streak=current_streak(db, user.id, today),
    )


def _sum_spend(db: Session, user_id: uuid.UUID, start: dt.date, end: dt.date) -> int:
    """Spending in ``[start, end)`` — the same allow-list every other figure uses."""
    from app.models import Transaction

    total = db.scalar(
        select(_spent()).where(
            Transaction.user_id == user_id,
            _is_spend(),
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
    )
    return int(total or 0)
