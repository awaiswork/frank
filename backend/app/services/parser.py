"""Natural-language → transaction drafts (technical-plan.md §7b).

A tool-forced Haiku call returns structured drafts; we validate them with Pydantic
and, on failure, retry once with the validation error appended. This NEVER writes
to the database — it returns drafts the client confirms via POST /transactions.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.services import llm

Kind = Literal["expense", "income"]

PARSER_MODEL = "claude-haiku-4-5"
TOOL_NAME = "record_transactions"


class ParsedTransaction(BaseModel):
    """One draft the model proposes (not yet persisted)."""

    kind: Kind = "expense"
    amount_cents: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    category_name: str | None = None
    occurred_on: dt.date | None = None
    confidence: float = Field(ge=0, le=1)


class ParseError(Exception):
    """Raised when the model output can't be coerced into valid drafts."""


_TRANSACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["expense", "income"],
            "description": "income only for money received (salary, refund, bonus); else expense",
        },
        "amount_cents": {
            "type": "integer",
            "description": "positive integer cents, e.g. 12.50 euros -> 1250",
        },
        "description": {"type": "string", "description": "short human description"},
        "merchant": {"type": ["string", "null"], "description": "place/vendor if named"},
        "category_name": {
            "type": ["string", "null"],
            "description": "must be one of the user's categories, or null if unclear",
        },
        "occurred_on": {
            "type": ["string", "null"],
            "description": "ISO date YYYY-MM-DD; null means today",
        },
        "confidence": {"type": "number", "description": "0..1 confidence in this draft"},
    },
    "required": ["kind", "amount_cents", "description", "confidence"],
}

TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Record one or more transactions extracted from the user's sentence.",
    "input_schema": {
        "type": "object",
        "properties": {"transactions": {"type": "array", "items": _TRANSACTION_SCHEMA}},
        "required": ["transactions"],
    },
}


def _build_system(category_names: list[str], currency: str, today: dt.date) -> str:
    cats = ", ".join(category_names) if category_names else "(none)"
    return (
        "You extract personal-finance transactions from a short sentence and call the "
        f"`{TOOL_NAME}` tool. Today is {today.isoformat()}. The user's currency is {currency}. "
        f"Their categories are: {cats}. Map each transaction to the closest of THESE category "
        "names (never invent one); use null if nothing fits. Amounts are in the user's currency; "
        "convert to positive integer cents (12,50 -> 1250). A comma or a dot can be the decimal "
        "separator. One sentence may contain several transactions. Resolve relative dates "
        '("yesterday", "on Friday") against today; null means today. Set confidence lower when '
        "the amount, category, or intent is ambiguous.\n"
        "Examples:\n"
        '- "8,40 coffee and croissant" -> one expense, 840, category Eating out, confidence ~0.9\n'
        '- "lunch 12.50 at Hesburger and 3e bus" -> two expenses: 1250 Eating out (merchant '
        "Hesburger), 300 Transport\n"
        '- "got paid 2400 salary" -> one income, 240000, category Income\n'
        '- "spent like 20 on stuff" -> one expense, 2000, category null, confidence ~0.4\n'
        '- "k-market 34,90" -> one expense, 3490, category Groceries (merchant K-Market)'
    )


def _extract_tool_input(message: Any) -> dict[str, Any]:
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            data = block.input
            if isinstance(data, dict):
                return data
    raise ParseError("model did not return a tool call")


def _validate(raw: dict[str, Any]) -> list[ParsedTransaction]:
    rows = raw.get("transactions")
    if not isinstance(rows, list) or not rows:
        raise ParseError("no transactions found")
    return [ParsedTransaction.model_validate(row) for row in rows]


async def parse_transactions(
    text: str,
    *,
    category_names: list[str],
    currency: str,
    today: dt.date,
) -> list[ParsedTransaction]:
    """Parse ``text`` into drafts. One corrective retry, then ParseError → 422 upstream."""
    system = _build_system(category_names, currency, today)
    last_error = ""
    for attempt in range(2):
        content = text
        if attempt == 1:
            content = (
                f"{text}\n\n(Your previous response was invalid: {last_error}. "
                "Return corrected transactions via the tool.)"
            )
        message = await llm.call_tool(
            model=PARSER_MODEL,
            system=system,
            messages=[{"role": "user", "content": content}],
            tools=[TOOL],
            tool_name=TOOL_NAME,
            max_tokens=llm.PARSER_MAX_TOKENS,
        )
        try:
            return _validate(_extract_tool_input(message))
        except (ValidationError, ParseError) as exc:
            last_error = str(exc)
    raise ParseError(last_error or "could not parse")
