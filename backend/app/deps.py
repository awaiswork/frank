"""Shared FastAPI dependencies — DB session, the authenticated user, and their date.

`get_current_user` is the single choke point through which `user_id` enters every
request; routers must scope all queries by `user.id` (technical-plan.md §10).
`get_today` is the equivalent for dates: no router calls `date.today()` itself, because
that is the *server's* today and the app has opinions that only make sense in the
user's — which day the note belongs to, whether a streak survived, how much of the
month is left.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import ACCESS, decode_token
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        user_id = decode_token(creds.credentials, ACCESS)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def today_in(tz: str | None, *, now: dt.datetime | None = None) -> dt.date:
    """The calendar date it currently is in ``tz``. ``None`` or unusable -> UTC.

    Never raises. A timezone the tz database does not recognise — a stale IANA name,
    a hand-edited row — must not take down budgets and transactions along with it, and
    UTC is the same answer the app gave before anyone could set one. ``now`` is
    injectable so the interesting cases are testable without freezing the clock.
    """
    moment = now if now is not None else dt.datetime.now(dt.UTC)
    if tz:
        try:
            return moment.astimezone(ZoneInfo(tz)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return moment.astimezone(dt.UTC).date()


def get_today(user: CurrentUser) -> dt.date:
    return today_in(user.timezone)


Today = Annotated[dt.date, Depends(get_today)]


def bring_ledger_up_to_date(user: CurrentUser, db: DbSession, today: Today) -> None:
    """Write any recurring occurrence whose date has arrived, before anything is read.

    Every money figure — spend, budgets, balances, the daily note — is computed from
    the transactions table, so a generated row has to exist before any of them are
    asked. There is no scheduler on this stack, so the read is the trigger.

    Cheap when there is nothing to do: `last_materialised_on` means the usual case is
    one indexed query returning no templates at all.

    Declared as a dependency rather than called from each handler because four routers
    is three places to forget. `test_recurring.test_every_money_route_is_up_to_date`
    asserts the money-reading routes all carry it.
    """
    from app.services.recurring import materialise_due

    materialise_due(db, user, today)


#: Money-reading routes depend on this so generated rows exist before they are counted.
LedgerUpToDate = Depends(bring_ledger_up_to_date)
