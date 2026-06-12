"""Insights — the §6 aggregate bundle consumed by Home and the Insights screen."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.schemas import (
    BurnRateOut,
    CategoryMoMOut,
    CategorySpendOut,
    InsightsSummaryOut,
    SafeToSpendOut,
)
from app.services.aggregates import (
    daily_burn_rate,
    month_over_month_by_category,
    parse_month,
    safe_to_spend,
    spend_by_category,
)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/summary", response_model=InsightsSummaryOut)
def summary(
    user: CurrentUser,
    db: DbSession,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> InsightsSummaryOut:
    today = dt.date.today()
    month_start = parse_month(month, today=today)

    safe = safe_to_spend(db, user.id, user.monthly_income_cents, month_start)
    spend = spend_by_category(db, user.id, month_start)
    burn = daily_burn_rate(db, user.id, today=today)
    mom = month_over_month_by_category(db, user.id, month_start)

    return InsightsSummaryOut(
        month=month_start.strftime("%Y-%m"),
        safe_to_spend=SafeToSpendOut.model_validate(safe),
        spend_by_category=[CategorySpendOut.model_validate(r) for r in spend],
        daily_burn=BurnRateOut.model_validate(burn),
        month_over_month=[CategoryMoMOut.model_validate(r) for r in mom],
    )
