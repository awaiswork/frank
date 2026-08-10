"""Recording an amount in the currency it happened in, and in the user's own.

One helper rather than three columns to remember at four call sites. Everything written
while there is a single currency goes in at a rate of exactly one — which is not a
placeholder, it is what the conversion actually is.

The rate is stored beside the converted figure and never used to recompute it. A report
adds up `base_amount_cents`; nothing multiplies at read time, so no historical total can
move because a rate moved today.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import User
from app.services import fx

#: Recorded when a transaction is already in the reporting currency. Exact, not a stand-in.
SAME_CURRENCY_RATE = Decimal(1)


class NoRate(Exception):
    """No published rate covers this date, and no converted amount was supplied."""


def in_base(
    user: User,
    amount_cents: int,
    *,
    currency: str | None = None,
    base_amount_cents: int | None = None,
    db: Session | None = None,
    on: dt.date | None = None,
) -> tuple[str, int, Decimal]:
    """``(currency, base_amount_cents, fx_rate)`` for one amount.

    ``base_amount_cents`` given wins, and is the path to prefer. A statement showing both
    the foreign amount and what actually left the account is better evidence than any
    mid-market rate — it is what the money did, rather than what the ECB thought that
    morning — so the rate is derived from it rather than the other way round.

    Failing that, the published rate for the day is used. If there is none, this raises
    rather than inventing one: a date from before rates were collected has no honest
    conversion available, and a guess would enter every total that reads it looking
    exactly like a real figure.
    """
    code = (currency or user.currency).upper()
    base = user.currency.upper()
    if code == base:
        return code, amount_cents, SAME_CURRENCY_RATE

    if base_amount_cents is not None:
        rate = (
            Decimal(base_amount_cents) / Decimal(amount_cents)
            if amount_cents
            else SAME_CURRENCY_RATE
        )
        return code, base_amount_cents, rate

    if db is None or on is None:  # pragma: no cover — every caller passes both
        raise NoRate(code)
    found = fx.rate_for(db, base=base, quote=code, on=on)
    if found is None:
        raise NoRate(code)
    rate, _published_on = found
    # Rounded once, here, and then frozen on the row. Nothing multiplies again later.
    return code, int((Decimal(amount_cents) * rate).quantize(Decimal(1))), rate
