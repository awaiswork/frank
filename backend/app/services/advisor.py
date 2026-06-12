"""The Advisor (technical-plan.md §7c) — grounded "should I buy…" verdicts.

The context builder sends compact *aggregates* (never raw rows), targeting well
under 1,500 input tokens; the exact dict is stored as ``context_snapshot`` for
reproducibility. The model returns a tool-forced structured verdict; we stream the
tool's partial JSON over SSE so the card + reasoning render progressively.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any, Literal, cast

from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AdviceRequest, GoalContribution, SavingsGoal, User
from app.services import llm
from app.services.aggregates import budget_vs_actual, daily_burn_rate, safe_to_spend

ADVISOR_MODEL = "claude-sonnet-4-6"
TOOL_NAME = "give_verdict"
DISCLAIMER = "Frank gives opinions based on your data, not professional financial advice."

VerdictKind = Literal["go", "wait", "skip", "your_call"]


class Evidence(BaseModel):
    label: str
    value: str


class Verdict(BaseModel):
    verdict: VerdictKind
    headline: str
    evidence: list[Evidence]
    reasoning: str


class AdvisorError(Exception):
    """The model failed to return a usable verdict."""


def _eur(cents: int) -> float:
    return round(cents / 100, 2)


def build_context(db: Session, user: User, today: dt.date) -> dict[str, Any]:
    """Compact aggregates for the model — the §7c context (also the stored snapshot)."""
    month_start = today.replace(day=1)

    budgets = budget_vs_actual(db, user.id, month_start, today=today)
    sts = safe_to_spend(db, user.id, user.monthly_income_cents, month_start)
    burn = daily_burn_rate(db, user.id, today=today)

    contributed = (
        select(
            GoalContribution.goal_id.label("goal_id"),
            func.coalesce(func.sum(GoalContribution.amount_cents), 0).label("total"),
        )
        .group_by(GoalContribution.goal_id)
        .subquery()
    )
    goal_rows = db.execute(
        select(SavingsGoal, func.coalesce(contributed.c.total, 0))
        .join(contributed, contributed.c.goal_id == SavingsGoal.id, isouter=True)
        .where(SavingsGoal.user_id == user.id, SavingsGoal.archived_at.is_(None))
        .order_by(SavingsGoal.due_date.nulls_last())
    ).all()

    recent = db.scalars(
        select(AdviceRequest)
        .where(AdviceRequest.user_id == user.id)
        .order_by(AdviceRequest.created_at.desc())
        .limit(3)
    ).all()

    return {
        "today": today.isoformat(),
        "currency": user.currency,
        "monthly_income_eur": _eur(user.monthly_income_cents)
        if user.monthly_income_cents
        else None,
        "safe_to_spend_eur": _eur(sts.safe_to_spend_cents),
        "spent_this_month_eur": _eur(sts.spent_cents),
        "daily_burn_eur": _eur(burn.daily_burn_cents),
        "budgets": [
            {
                "category": b.category_name,
                "limit_eur": _eur(b.limit_cents),
                "spent_eur": _eur(b.spent_cents),
                "on_track": b.on_track,
            }
            for b in budgets
        ],
        "goals": [
            {
                "name": g.name,
                "target_eur": _eur(g.target_cents),
                "saved_eur": _eur(int(total)),
                "due": g.due_date.isoformat() if g.due_date else None,
            }
            for g, total in goal_rows
        ],
        "recent_decisions": [
            {"question": r.question, "verdict": r.verdict, "followed": r.user_followed}
            for r in recent
        ],
    }


_SYSTEM = (
    "You are Frank, a candid but kind spending advisor. Answer the user's purchase "
    "question using ONLY the numbers in the provided context — never invent data, and "
    "ground every claim in a specific figure. Call the `give_verdict` tool exactly once.\n"
    "Verdicts: 'go' = comfortably within their means; 'wait' = fine but better after "
    "payday or once a budget resets; 'skip' = a supportive no (not a judgement); "
    "'your_call' = it's genuinely their decision, OR the question isn't a purchase "
    "decision — in that case say what information is missing. Keep the headline short "
    "(a few words). Provide 2-4 evidence rows as {label, value} drawn from the context "
    "(e.g. label 'Safe to spend', value '120,00 €'). Keep reasoning to 2-4 sentences. "
    "Format every money value with a comma decimal and a trailing € (e.g. 1234,56 €; "
    "negatives like −29,90 €)."
)

_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
    "required": ["label", "value"],
}

VERDICT_TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Return Frank's verdict on the purchase question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["go", "wait", "skip", "your_call"]},
            "headline": {"type": "string"},
            "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
            "reasoning": {"type": "string"},
        },
        "required": ["verdict", "headline", "evidence", "reasoning"],
    },
}


def _build_user_message(question: str, amount_cents: int | None, context: dict[str, Any]) -> str:
    import json

    amount = (
        f"\nApproximate amount: {_eur(amount_cents)} {context['currency']}." if amount_cents else ""
    )
    return (
        f'Question: "{question}".{amount}\n\n'
        f"Here is the user's financial context (all amounts already in their currency):\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )


def _extract_verdict(message: Any) -> Verdict:
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            if isinstance(block.input, dict):
                return Verdict.model_validate(block.input)
    raise AdvisorError("model did not return a verdict")


async def stream_verdict(
    question: str, amount_cents: int | None, context: dict[str, Any]
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ('delta', {partial}) chunks as the tool JSON streams, then ('final', {...})."""
    client = llm.get_client()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_user_message(question, amount_cents, context)}
    ]
    tool_choice: ToolChoiceToolParam = {"type": "tool", "name": TOOL_NAME}

    async with client.messages.stream(
        model=ADVISOR_MODEL,
        max_tokens=llm.ADVISOR_MAX_TOKENS,
        temperature=0,
        system=_SYSTEM,
        messages=cast("list[MessageParam]", messages),
        tools=cast("list[ToolParam]", [VERDICT_TOOL]),
        tool_choice=tool_choice,
    ) as stream:
        async for event in stream:
            delta = getattr(event, "delta", None)
            if getattr(event, "type", "") == "content_block_delta" and (
                getattr(delta, "type", "") == "input_json_delta"
            ):
                yield ("delta", {"partial": getattr(delta, "partial_json", "")})
        final = await stream.get_final_message()

    try:
        verdict = _extract_verdict(final)
    except ValidationError as exc:
        raise AdvisorError(str(exc)) from exc

    usage = getattr(final, "usage", None)
    yield (
        "final",
        {
            "verdict": verdict,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )
