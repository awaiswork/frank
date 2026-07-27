"""Advisor routes (§8): POST /advisor/ask (SSE), GET /advisor/history, PATCH /advisor/{id}."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.features import AdvisorGate, ai_enabled
from app.models import AdviceRequest, DailyNote
from app.schemas import AdviceHistoryOut, AdvisorAskIn, AdvisorFollowedIn, DailyNoteOut
from app.services import advisor, daily

router = APIRouter(prefix="/advisor", tags=["advisor"])


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask")
async def ask(
    body: AdvisorAskIn, user: CurrentUser, db: DbSession, _gate: AdvisorGate
) -> StreamingResponse:
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
            yield _sse("error", {"detail": "Frankly couldn't form a verdict. Try rephrasing."})
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
    """Frankly's check-in for today — one note a day, rewritten if the day turns.

    The mood is recomputed live on every read, so the note can never contradict the
    numbers on screen: a note written for 'go' this morning is stale once the user
    has spent past their safe-to-spend, and gets replaced. Within a mood the text is
    cached, which is what keeps this to at most a handful of model calls a day (and
    exactly zero while the AI features are off, since the fallback is hand-written).
    """
    today = dt.date.today()
    row = db.scalar(
        select(DailyNote).where(DailyNote.user_id == user.id, DailyNote.note_date == today)
    )
    context = advisor.build_context(db, user, today)
    mood = daily.compute_mood(context, today)

    if row is None or row.mood != mood:
        usage: dict[str, Any] = {}
        model: str | None = None
        if ai_enabled():
            try:
                headline, note, usage = await daily.generate(context, mood)
                model = daily.DAILY_MODEL
            except daily.DailyError:
                headline, note = daily.fallback(mood)
        else:
            headline, note = daily.fallback(mood)

        if row is None:
            # First check-in today — this row is also the streak's "showed up" mark.
            row = DailyNote(user_id=user.id, note_date=today)
            db.add(row)
        row.mood = mood
        row.headline = headline
        row.note = note
        row.context_snapshot = context
        row.model = model
        row.input_tokens = usage.get("input_tokens")
        row.output_tokens = usage.get("output_tokens")
        db.commit()

    return DailyNoteOut(
        date=row.note_date,
        mood=row.mood,
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
