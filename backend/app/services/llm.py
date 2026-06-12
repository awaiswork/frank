"""Shared Anthropic client wrapper (technical-plan.md §7a).

The API key lives only on the server (§10). The wrapper centralises the model
call: a 20s timeout, 2 automatic retries with backoff on 429/5xx (handled by the
SDK), and a structured JSON log line per call with model + token usage + latency.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, ToolChoiceToolParam, ToolParam

from app.config import get_settings

logger = logging.getLogger("frank.llm")
settings = get_settings()

# Hard caps (§7a) — keep cost bounded.
PARSER_MAX_TOKENS = 1000
ADVISOR_MAX_TOKENS = 1200

_TIMEOUT_SECONDS = 20.0
_MAX_RETRIES = 2

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """Lazily build a shared async client (so tests that mock calls never need a key)."""
    global _client
    if _client is None:
        _client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=_TIMEOUT_SECONDS,
            max_retries=_MAX_RETRIES,
        )
    return _client


async def call_tool(
    *,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_name: str,
    max_tokens: int,
) -> Message:
    """Call the model forcing it to invoke ``tool_name``; log usage + latency."""
    client = get_client()
    tool_choice: ToolChoiceToolParam = {"type": "tool", "name": tool_name}
    started = time.monotonic()
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system,
        messages=cast("list[MessageParam]", messages),
        tools=cast("list[ToolParam]", tools),
        tool_choice=tool_choice,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    usage = getattr(message, "usage", None)
    logger.info(
        json.dumps(
            {
                "event": "llm_call",
                "model": model,
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "latency_ms": latency_ms,
            }
        )
    )
    return message
