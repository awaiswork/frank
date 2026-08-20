"""Notification preferences, the scheduled digest, and unsubscribing without a login.

Two of these three are the first surfaces in this app that are not either public and
read-only or behind a bearer token belonging to a signed-in person, so they get more
care than their size suggests.

`POST /internal/digest/run` is guarded by a shared secret and **fails closed**: with no
secret configured it refuses every request. That is deliberately the opposite of how
email degrades to the console sender when unconfigured. An email provider that quietly
does nothing is a graceful fallback; an unauthenticated route that emails every user is
not.

`POST /notifications/unsubscribe` takes a signed capability instead of a session,
because an unsubscribe link has to work from a six-month-old email on a device that has
never signed in. It answers identically whether or not the token names anyone, for the
same reason `/auth/forgot-password` does.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.core.signing import sign, verify
from app.core.tokens import tokens_equal
from app.deps import CurrentUser, DbSession
from app.email import queue_email
from app.email.templates import weekly_digest_email
from app.models import NotificationSetting, User
from app.schemas import MessageOut, NotificationsOut, NotificationsUpdate, UnsubscribeIn
from app.services import digest, fx

log = logging.getLogger("frankly")

router = APIRouter(tags=["notifications"])

KIND = NotificationSetting.WEEKLY_DIGEST


def _setting(db: DbSession, user: User) -> NotificationSetting | None:
    return db.scalar(
        select(NotificationSetting).where(
            NotificationSetting.user_id == user.id, NotificationSetting.kind == KIND
        )
    )


def _out(setting: NotificationSetting | None) -> NotificationsOut:
    """One place that says what "no row" means, so GET and PATCH cannot disagree."""
    if setting is None:
        return NotificationsOut(
            weekly_digest=True,
            send_weekday=digest.DEFAULT_WEEKDAY,
            send_hour=digest.DEFAULT_HOUR,
        )
    return NotificationsOut(
        weekly_digest=setting.enabled,
        send_weekday=setting.send_weekday,
        send_hour=setting.send_hour,
    )


@router.get("/notifications", response_model=NotificationsOut)
def get_notifications(user: CurrentUser, db: DbSession) -> NotificationsOut:
    # No row means the defaults — on, and the same Monday morning everyone had before
    # the schedule was theirs to set.
    return _out(_setting(db, user))


@router.patch("/notifications", response_model=NotificationsOut)
def update_notifications(
    body: NotificationsUpdate, user: CurrentUser, db: DbSession
) -> NotificationsOut:
    """Change any of the three; the ones left out keep their value.

    A row is created on first change with the defaults filled in, so setting only the
    hour cannot quietly move someone's day as a side effect.
    """
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        return _out(_setting(db, user))

    setting = _setting(db, user)
    if setting is None:
        setting = NotificationSetting(
            user_id=user.id,
            kind=KIND,
            enabled=True,
            send_weekday=digest.DEFAULT_WEEKDAY,
            send_hour=digest.DEFAULT_HOUR,
        )
        db.add(setting)
    if "weekly_digest" in fields:
        setting.enabled = fields["weekly_digest"]
    if "send_weekday" in fields:
        setting.send_weekday = fields["send_weekday"]
    if "send_hour" in fields:
        setting.send_hour = fields["send_hour"]
    db.commit()
    return _out(setting)


@router.post("/notifications/unsubscribe", response_model=MessageOut)
def unsubscribe(body: UnsubscribeIn, db: DbSession) -> MessageOut:
    """Turn weekly summaries off from a link, with no session involved.

    A POST rather than a GET on the emailed URL: mail scanners and clients prefetch
    links, and a GET that unsubscribes would fire on its own. The email points at the
    app, which shows a button that calls this.

    The answer never varies with whether the token names a real person — a differing
    response would turn this into an oracle for which addresses have accounts.
    """
    said = MessageOut(detail="Weekly summaries are off. Nothing else about your account changed.")

    user_id = verify(body.token, KIND)
    if user_id is None:
        return said

    setting = db.scalar(
        select(NotificationSetting).where(
            NotificationSetting.user_id == user_id, NotificationSetting.kind == KIND
        )
    )
    if setting is None:
        if db.get(User, user_id) is None:
            return said
        db.add(NotificationSetting(user_id=user_id, kind=KIND, enabled=False))
    else:
        setting.enabled = False
    db.commit()
    return said


def _require_cron_secret(authorization: str) -> None:
    """Shared by every scheduled route. Refuses when no secret is configured."""
    settings = get_settings()
    if not settings.cron_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Not configured")
    if not tokens_equal(authorization.removeprefix("Bearer ").strip(), settings.cron_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authorised")


@router.post("/internal/fx/refresh", response_model=MessageOut)
def refresh_rates(db: DbSession, authorization: str = Header(default="")) -> MessageOut:
    """Pull today's published rates for every currency someone actually reports in.

    Deliberately **not** guarded by `ENV = prod`, unlike the digest. That guard exists
    because the digest *contacts people*; this writes exchange rates to a table, which is
    harmless and useful to run locally. Guarding everything named `/internal` by reflex
    would make the digest's guard read as ceremony rather than as a fix for something
    that actually went wrong.
    """
    _require_cron_secret(authorization)
    bases = [code for (code,) in db.execute(select(User.currency).distinct()) if code]
    written = fx.refresh(db, bases)
    return MessageOut(detail=f"Stored {written} rates.")


@router.post("/internal/digest/run", response_model=MessageOut)
def run_digest(
    db: DbSession,
    background: BackgroundTasks,
    authorization: str = Header(default=""),
    dry: bool = False,
) -> MessageOut:
    """Send to everyone whose local Monday morning has arrived. Hit by a cron.

    Returns a count and nothing about who — an endpoint reachable with a shared secret
    should not hand back a list of a service's users.

    **Nothing is sent outside production.** This route's entire job is to email every
    user who is due one, so pointed at a development machine that happens to hold real
    mail credentials it will mail real people — which is exactly what happened while
    this was being built. A comment saying "be careful" would not have stopped that;
    refusing to send unless `ENV=prod` does. Locally it reports who *would* receive one
    and takes nobody's week, so it stays repeatable.

    `?dry=true` does the same in production, for checking without sending.
    """
    _require_cron_secret(authorization)
    settings = get_settings()

    now = dt.datetime.now(dt.UTC)
    # Claiming is what marks a week as spent. A run that will not send must not take it.
    live = settings.is_prod and not dry
    recipients = digest.due_now(db, now, claim=live)

    if not live:
        db.rollback()
        reason = "dry run" if dry else f"ENV is {settings.env!r}, not 'prod'"
        log.info('{"event":"digest_run_skipped","would_send":%d}', len(recipients))
        return MessageOut(detail=f"Would have queued {len(recipients)} — not sending ({reason}).")

    sent = 0
    for user in recipients:
        content = digest.build(db, user, now.date())
        message = weekly_digest_email(
            spent_cents=content.spent_cents,
            previous_spent_cents=content.previous_spent_cents,
            top_categories=content.top_categories,
            upcoming_cents=content.upcoming_cents,
            upcoming_count=content.upcoming_count,
            safe_to_spend_cents=content.safe_to_spend_cents,
            streak=content.streak,
            unsubscribe_url=f"{settings.app_base_url}/unsubscribe?token={sign(user.id, KIND)}",
        )
        queue_email(background, message, to=user.email, user_id=user.id, purpose="weekly_digest")
        sent += 1

    db.commit()
    log.info('{"event":"digest_run","sent":%d}', sent)
    return MessageOut(detail=f"Queued {sent}.")
