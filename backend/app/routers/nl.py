"""Natural-language capture — POST /nl/parse returns drafts, never persists (§7b, §8)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Category
from app.schemas import NlParseIn, ParsedTransactionOut
from app.services.parser import ParseError, parse_transactions

router = APIRouter(prefix="/nl", tags=["nl"])


@router.post("/parse", response_model=list[ParsedTransactionOut])
async def parse(body: NlParseIn, user: CurrentUser, db: DbSession) -> list[ParsedTransactionOut]:
    categories = list(db.scalars(select(Category).where(Category.user_id == user.id)))
    today = dt.date.today()

    try:
        drafts = await parse_transactions(
            body.text,
            category_names=[c.name for c in categories],
            currency=user.currency,
            today=today,
        )
    except ParseError as exc:
        # Friendly message the UI maps to the correction flow (§7b).
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            'Frank couldn\'t read that. Try rephrasing, e.g. "lunch 12,50 at Hesburger".',
        ) from exc

    by_lower = {c.name.lower(): c for c in categories}
    out: list[ParsedTransactionOut] = []
    for d in drafts:
        match = by_lower.get(d.category_name.lower()) if d.category_name else None
        out.append(
            ParsedTransactionOut(
                kind=d.kind,
                amount_cents=d.amount_cents,
                description=d.description,
                merchant=d.merchant,
                occurred_on=d.occurred_on or today,
                category_id=match.id if match else None,
                category_name=match.name if match else d.category_name,
                confidence=d.confidence,
            )
        )
    return out
