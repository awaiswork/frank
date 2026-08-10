"""Recording an amount in the currency it happened in, and in the user's own.

One helper rather than three columns to remember at four call sites. Everything written
while there is a single currency goes in at a rate of exactly one — which is not a
placeholder, it is what the conversion actually is.

The rate is stored beside the converted figure and never used to recompute it. A report
adds up `base_amount_cents`; nothing multiplies at read time, so no historical total can
move because a rate moved today.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import User

#: Recorded when a transaction is already in the reporting currency. Exact, not a stand-in.
SAME_CURRENCY_RATE = Decimal(1)


def in_base(
    user: User,
    amount_cents: int,
    *,
    currency: str | None = None,
    base_amount_cents: int | None = None,
) -> tuple[str, int, Decimal]:
    """``(currency, base_amount_cents, fx_rate)`` for one amount.

    ``base_amount_cents`` given wins: a bank statement showing both the foreign amount
    and what actually left the account is better evidence than any published rate, and
    the rate is then derived from what really happened.
    """
    code = (currency or user.currency).upper()
    if code == user.currency.upper():
        return code, amount_cents, SAME_CURRENCY_RATE
    if base_amount_cents is None:
        # No lookup yet — foreign entry arrives with the rates table, and until then
        # nothing can reach here without saying what it came to.
        raise ValueError("a foreign amount needs its value in the reporting currency")
    rate = (
        Decimal(base_amount_cents) / Decimal(amount_cents) if amount_cents else SAME_CURRENCY_RATE
    )
    return code, base_amount_cents, rate
