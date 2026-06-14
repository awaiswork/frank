"""Advisor routes (§8): POST /advisor/ask (SSE), GET /advisor/history, PATCH /advisor/{id}."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import AdviceRequest, DailyNote
from app.schemas import AdviceHistoryOut, AdvisorAskIn, AdvisorFollowedIn, DailyNoteOut
from app.services import advisor, daily

router = APIRouter(prefix="/advisor", tags=["advisor"])


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def ask(body: AdvisorAskIn, user: CurrentUser, db: DbSession) -> StreamingResponse:
    context = advisor.build_context(db, user, dt.date.today())

    async def gen() -> AsyncIterator[str]:
        verdict: advisor.Verdict | None = None
        usage: dict[str, object] = {}
        try:
            async for kind, payload in advisor.stream_verdict(
                body.question, body.amount_cents, context
            ):
                if kind == "delta":
                    yield _sse("delta", {"partial": payload["partial"]})
                elif kind == "final":
                    verdict = payload["verdict"]
                    usage = payload
        except advisor.AdvisorError:
            yield _sse("error", {"detail": "Frank couldn't form a verdict. Try rephrasing."})
            return

        assert verdict is not None
        record = AdviceRequest(
            user_id=user.id,
            question=body.question,
            amount_cents=body.amount_cents,
            verdict=verdict.verdict,
            reasoning=verdict.reasoning,
            evidence=[e.model_dump() for e in verdict.evidence],
            context_snapshot=context,
            model=advisor.ADVISOR_MODEL,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        db.add(record)
        db.commit()

        yield _sse(
            "verdict",
            {
                "id": str(record.id),
                "verdict": verdict.verdict,
                "headline": verdict.headline,
                "evidence": [e.model_dump() for e in verdict.evidence],
                "reasoning": verdict.reasoning,
                "disclaimer": advisor.DISCLAIMER,
            },
        )
        yield _sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/daily", response_model=DailyNoteOut)
async def get_daily(user: CurrentUser, db: DbSession) -> DailyNoteOut:
    """Frank's check-in for today — generated once per day, then served from cache."""
    today = dt.date.today()
    row = db.scalar(
        select(DailyNote).where(DailyNote.user_id == user.id, DailyNote.note_date == today)
    )
    if row is None:
        context = advisor.build_context(db, user, today)
        mood = daily.compute_mood(context, today)
        try:
            headline, note, usage = await daily.generate(context, mood)
            model: str | None = daily.DAILY_MODEL
        except daily.DailyError:
            headline, note = daily.fallback(mood)
            usage = {}
            model = None
        row = DailyNote(
            user_id=user.id,
            note_date=today,
            mood=mood,
            headline=headline,
            note=note,
            context_snapshot=context,
            model=model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        db.add(row)
        db.commit()

    return DailyNoteOut(
        date=row.note_date,
        mood=row.mood,  # type: ignore[arg-type]
        headline=row.headline,
        note=row.note,
        streak=daily.current_streak(db, user.id, today),
    )


@router.get("/history", response_model=list[AdviceHistoryOut])
def history(user: CurrentUser, db: DbSession) -> list[AdviceRequest]:
    stmt = (
        select(AdviceRequest)
        .where(AdviceRequest.user_id == user.id)
        .order_by(AdviceRequest.created_at.desc())
        .limit(50)
    )
    return list(db.scalars(stmt))


@router.patch("/{advice_id}", response_model=AdviceHistoryOut)
def set_followed(
    advice_id: uuid.UUID, body: AdvisorFollowedIn, user: CurrentUser, db: DbSession
) -> AdviceRequest:
    record = db.get(AdviceRequest, advice_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Advice not found")
    record.user_followed = body.user_followed
    db.commit()
    return record
