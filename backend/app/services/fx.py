"""Fetching published rates, and finding the one that applied on a day.

Rates come from Frankfurter, which serves ECB reference data, needs no key and is not
metered. One request returns every quote against a base, so a refresh is one call per
distinct reporting currency rather than one per pair.

Two things here are easy to get wrong and expensive to notice:

**Direction.** Everything in this codebase stores *base units per one quote unit*, so
``base_amount = amount * rate``. Frankfurter publishes the inverse — its ``?from=EUR``
answer says how many dollars a euro buys. It is flipped once, here, at the edge. An
inverted rate produces a number that looks like money and is wrong by a factor of about
1.3, which no total would flag.

**Weekends.** The ECB publishes on working days. Ask Frankfurter for a Saturday and it
answers with Friday's date and Friday's rate — so the response's own ``date`` is what
gets stored, never the date that was asked for. Lookups then ask for the most recent rate
at or before a day, which gives weekends, holidays and "we have not fetched yet" the same
sensible answer, and is what a bank would have used too.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import FxRate

log = logging.getLogger("frankly")

# The .dev host, not the documented .app one: that now answers 301, and httpx does not
# follow redirects by default — so the old URL fails quietly rather than loudly.
FRANKFURTER = "https://api.frankfurter.dev/v1"
TIMEOUT_SECONDS = 15.0


def rate_for(db: Session, *, base: str, quote: str, on: dt.date) -> tuple[Decimal, dt.date] | None:
    """The rate that applied on ``on``, and the day it was actually published.

    "At or before" rather than "on": there is no Sunday rate anywhere, and the last
    published one is the honest answer rather than a gap.
    """
    if base.upper() == quote.upper():
        return Decimal(1), on
    row = db.scalar(
        select(FxRate)
        .where(
            FxRate.base == base.upper(),
            FxRate.quote == quote.upper(),
            FxRate.rate_on <= on,
        )
        .order_by(FxRate.rate_on.desc())
        .limit(1)
    )
    return (row.rate, row.rate_on) if row else None


def fetch(base: str, *, client: httpx.Client | None = None) -> tuple[dt.date, dict[str, Decimal]]:
    """Every quote against ``base``, already inverted into our direction.

    Returns the date the data is *for*, which is not necessarily today.
    """
    owned = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.get(f"{FRANKFURTER}/latest", params={"from": base.upper()})
        response.raise_for_status()
        payload = response.json()
    finally:
        if owned:
            http.close()

    published = dt.date.fromisoformat(str(payload["date"]))
    quotes: dict[str, Decimal] = {}
    for code, value in payload["rates"].items():
        published_rate = Decimal(str(value))
        if published_rate <= 0:  # pragma: no cover — the ECB does not publish these
            continue
        # Flip: they say "1 EUR buys 1.15 USD", we store "1 USD is worth 0.87 EUR".
        quotes[code.upper()] = Decimal(1) / published_rate
    return published, quotes


def refresh(db: Session, bases: list[str], *, client: httpx.Client | None = None) -> int:
    """Store the latest rates for each base currency. Returns rows written or updated.

    Idempotent by day: running it hourly stores one row per pair per published day, and
    a re-run of the same day overwrites with the same numbers rather than accumulating.
    """
    written = 0
    for base in {code.upper() for code in bases}:
        try:
            published, quotes = fetch(base, client=client)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # One base failing must not stop the others, and a missed refresh is
            # survivable — the previous day's rate stays the most recent one.
            log.warning(
                '{"event":"fx_refresh_failed","base":"%s","error":"%s"}', base, type(exc).__name__
            )
            continue

        for quote, rate in quotes.items():
            if quote == base:
                continue
            db.execute(
                insert(FxRate)
                .values(base=base, quote=quote, rate_on=published, rate=rate)
                .on_conflict_do_update(constraint="uq_fx_rate_day", set_={"rate": rate})
            )
            written += 1
    db.commit()
    return written
