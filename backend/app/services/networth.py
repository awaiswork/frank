"""Net worth over time, derived — never snapshotted.

    net worth on D = Σ(account balances on D)
                   + Σ(per asset: the most recent valuation with valued_on <= D)

Both halves are recomputed from what is stored, so a valuation entered late but dated
correctly rewrites the trend from that date, and a backdated transaction moves every
point after it. A table of periodic snapshots cannot do either: it would sit there
disagreeing with the ledger it came from, with no way to tell which was right.

**What this deliberately does not do** is pretend to know things before it was told
them. Value a car for the first time today and net worth rises by the car — not because
anything was gained, but because Frankly learned something. `complete_from` marks the
earliest date at which every account and asset currently on file was already known, so
a screen can show the earlier part of the line without letting it read as a trend.
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Asset, AssetValuation
from app.services.accounts import _legs

#: Points on the trend. Net worth is a slow number; monthly is the honest resolution.
DEFAULT_MONTHS = 12


@dataclass(frozen=True)
class NetWorthPoint:
    on: dt.date
    accounts_cents: int
    assets_cents: int
    total_cents: int


@dataclass(frozen=True)
class NetWorthSeries:
    points: list[NetWorthPoint]
    #: Earliest date the line is comparable — before it, things now on file were not
    #: yet known, so a rise there is Frankly learning rather than the user gaining.
    #: None when there is nothing to be incomplete about.
    complete_from: dt.date | None


def _month_end(year: int, month: int) -> dt.date:
    """Last day of a *calendar* month.

    `calendar`, deliberately not `aggregates.days_in_period`: that answers how long a
    budgeting period is, which equals a calendar month today and would not if periods
    were ever anchored to a payday. A net-worth trend is plotted on calendar months
    whatever a budgeting period turns out to be.
    """
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def series_dates(today: dt.date, months: int = DEFAULT_MONTHS) -> list[dt.date]:
    """Month ends going back, then today — so the last point is always current."""
    out: list[dt.date] = []
    for back in range(months - 1, 0, -1):
        total = (today.year * 12 + today.month - 1) - back
        out.append(_month_end(total // 12, total % 12 + 1))
    out.append(today)
    return out


def net_worth(
    db: Session, user_id: uuid.UUID, *, today: dt.date, months: int = DEFAULT_MONTHS
) -> NetWorthSeries:
    """The trend, in two queries and a fold.

    Not one windowed statement. The constraint that matters on this stack is round
    trips behind a cold start, and an as-of join plus a running total in a single
    statement is materially harder to verify than the arithmetic it would replace.
    """
    dates = series_dates(today, months)

    # Accounts: everything about them is small except their movement.
    accounts = list(
        db.execute(
            select(Account.id, Account.opening_balance_cents, Account.opened_on).where(
                Account.user_id == user_id
            )
        )
    )
    legs = _legs(user_id)
    movement = list(
        db.execute(
            select(legs.c.occurred_on, func.sum(legs.c.delta))
            .join(Account, Account.id == legs.c.account_id)
            .where(legs.c.occurred_on >= Account.opened_on)
            .group_by(legs.c.occurred_on)
            .order_by(legs.c.occurred_on)
        )
    )

    valuations = list(
        db.execute(
            select(
                AssetValuation.asset_id,
                AssetValuation.valued_on,
                AssetValuation.value_cents,
                Asset.archived_at,
            )
            .join(Asset, Asset.id == AssetValuation.asset_id)
            .where(Asset.user_id == user_id)
            .order_by(AssetValuation.asset_id, AssetValuation.valued_on)
        )
    )

    points: list[NetWorthPoint] = []
    for on in dates:
        # An account contributes nothing before it opened: the app knew nothing about
        # it, and pretending otherwise would invent history.
        opening = sum(row.opening_balance_cents for row in accounts if row.opened_on <= on)
        moved = sum(int(delta) for occurred_on, delta in movement if occurred_on <= on)

        latest: dict[uuid.UUID, int] = {}
        for asset_id, valued_on, value_cents, archived_at in valuations:
            if valued_on > on:
                continue
            if archived_at is not None and archived_at.date() <= on:
                # Sold or written off by this date — worth nothing to its owner now,
                # while still counting at every earlier point.
                latest[asset_id] = 0
                continue
            latest[asset_id] = value_cents

        accounts_cents = opening + moved
        assets_cents = sum(latest.values())
        points.append(
            NetWorthPoint(
                on=on,
                accounts_cents=accounts_cents,
                assets_cents=assets_cents,
                total_cents=accounts_cents + assets_cents,
            )
        )

    return NetWorthSeries(
        points=points,
        complete_from=_complete_from(db, user_id, [row.opened_on for row in accounts]),
    )


def _complete_from(db: Session, user_id: uuid.UUID, opened_on: Sequence[dt.date]) -> dt.date | None:
    """The earliest date at which nothing now on file was still unknown.

    The latest of: every account's `opened_on`, and every live asset's first valuation.
    Before that point the line is missing something the user has since told us about,
    so a rise there is not a gain.
    """
    known: list[dt.date] = list(opened_on)
    firsts = db.execute(
        select(func.min(AssetValuation.valued_on))
        .join(Asset, Asset.id == AssetValuation.asset_id)
        .where(Asset.user_id == user_id, Asset.archived_at.is_(None))
        .group_by(AssetValuation.asset_id)
    )
    known.extend(first for (first,) in firsts if first is not None)
    return max(known) if known else None
