"""Frank's daily note (the retention hook).

Once a day, Frank looks at the user's real aggregates and says *one* human thing.
The day's **mood** is computed deterministically here (so it can also drive the
client's ambient interface), and the model writes the note *in that mood's tone* —
never inventing numbers, never shaming. Falls back to a sensible hand-written line
if the model call fails, so the home screen never breaks.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyNote
from app.services import llm

DAILY_MODEL = "claude-sonnet-4-6"
DAILY_TOOL_NAME = "daily_note"

Mood = Literal["go", "wait", "over", "unknown"]


class DailyError(Exception):
    """The model failed to return a usable note."""


class _Note(BaseModel):
    headline: str
    note: str


def compute_mood(context: dict[str, Any], today: dt.date) -> Mood:
    """The day's read, from the numbers alone — shared with the client's ambient field.

    unknown = we have no income to reason from, so we owe the user a setup prompt
    rather than a verdict; over = past safe-to-spend for the month; wait = on current
    burn the remaining days would blow it, or a budget is running ahead of pace;
    go = comfortably on track.
    """
    # Without income, safe-to-spend is just negative spend. Claiming someone is
    # "within their means" off the back of that is a fabrication, so refuse to judge.
    if not context.get("income_known", False):
        return "unknown"

    sts = context.get("safe_to_spend_eur")
    if sts is None:
        return "go"
    if sts < 0:
        return "over"

    burn = context.get("daily_burn_eur") or 0
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = max(days_in_month - today.day, 0)
    projected_spend = burn * days_left
    budgets = context.get("budgets") or []
    running_hot = any(not b.get("on_track", True) for b in budgets)

    if sts - projected_spend < 0 or running_hot:
        return "wait"
    return "go"


_DAILY_SYSTEM = (
    "You are Frank, a candid but warm spending companion. Each day you greet the user with ONE "
    "short check-in about their money — like a sharp friend who has seen their account and is on "
    "their side. Use ONLY the numbers in the provided context; ground the note in a specific "
    "figure when it helps, but never recite a list of stats. Never shame: an over-budget day gets "
    "a calm, constructive nudge, not a telling-off. The day's mood has already been decided for "
    "you — match its tone exactly:\n"
    "- go: comfortably on track. Be light, affirming, maybe permission to enjoy something.\n"
    "- wait: trending tight for the days left. Be a gentle 'ease off this week'.\n"
    "- over: past their safe-to-spend. Be reassuring and forward-looking about recovery; no "
    "drama.\n"
    "- unknown: their monthly income isn't set, so you do NOT know whether they can afford "
    "anything. Never imply they are on track or overspending. Say what you can see (what "
    "they've logged so far) and invite them to add their income so you can do the real "
    "maths.\n"
    "Call the `daily_note` tool exactly once. Do NOT include a greeting, the date, or the word "
    "'good morning' — the app shows those. "
    "headline: 2-4 words, a glanceable read (e.g. 'Comfortably ahead', 'Ease off a touch', "
    '"Let\'s recover"). '
    "note: 1-2 sentences, max ~35 words, second person, in Frank's voice, ideally with one "
    "concrete forward-looking suggestion. "
    "Format money with a comma decimal and trailing € (e.g. 40,00 €; negatives like −29,90 €)."
)

DAILY_TOOL: dict[str, Any] = {
    "name": DAILY_TOOL_NAME,
    "description": "Return Frank's daily check-in note.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["headline", "note"],
    },
}


def _user_message(mood: Mood, context: dict[str, Any]) -> str:
    return (
        f"Today's mood read is: {mood}.\n\n"
        f"Here is the user's financial context (all amounts already in their currency):\n"
        f"{json.dumps(context, ensure_ascii=False)}"
    )


async def generate(context: dict[str, Any], mood: Mood) -> tuple[str, str, dict[str, Any]]:
    """Ask the model for the day's note; returns (headline, note, usage)."""
    message = await llm.call_tool(
        model=DAILY_MODEL,
        system=_DAILY_SYSTEM,
        messages=[{"role": "user", "content": _user_message(mood, context)}],
        tools=[DAILY_TOOL],
        tool_name=DAILY_TOOL_NAME,
        max_tokens=llm.DAILY_MAX_TOKENS,
    )
    for block in getattr(message, "content", []) or []:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == DAILY_TOOL_NAME
            and isinstance(block.input, dict)
        ):
            try:
                parsed = _Note.model_validate(block.input)
            except ValidationError as exc:
                raise DailyError(str(exc)) from exc
            usage = getattr(message, "usage", None)
            return (
                parsed.headline,
                parsed.note,
                {
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                },
            )
    raise DailyError("model did not return a note")


_FALLBACK: dict[Mood, tuple[str, str]] = {
    "go": (
        "On track",
        "Nothing to flag today — you're spending within your means. Keep it rolling.",
    ),
    "wait": (
        "Ease off a touch",
        "You're trending a little hot for the days left this month. Worth taking it easy "
        "this week.",
    ),
    "over": (
        "Let's recover",
        "You're past your safe-to-spend for the month. No drama — a few small days from here "
        "brings it back.",
    ),
    # No income on file: state only what we actually know, and ask for the one number
    # that unlocks the rest. Never a verdict.
    "unknown": (
        "Tell me what you earn",
        "I'm logging what you spend, but I can't tell you what's safe until I know your "
        "monthly income. Add it in Settings and I'll do the maths.",
    ),
}


def fallback(mood: Mood) -> tuple[str, str]:
    return _FALLBACK[mood]


def current_streak(db: Session, user_id: uuid.UUID, today: dt.date) -> int:
    """Consecutive days, ending today, that the user has a note (i.e. checked in)."""
    dates = set(
        db.scalars(
            select(DailyNote.note_date)
            .where(DailyNote.user_id == user_id, DailyNote.note_date <= today)
            .order_by(DailyNote.note_date.desc())
            .limit(366)
        ).all()
    )
    streak = 0
    cursor = today
    while cursor in dates:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak
