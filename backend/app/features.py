"""Feature gating for the model-backed features — the only ones that cost API usage.

Three features call Anthropic and therefore bill: natural-language capture (§7b),
the Advisor (§7c) and Frank's AI-written daily note. They ship **off** — marked
"coming soon" in the UI — and are switched on together with ``LLM_ENABLED=true``
plus a real ``ANTHROPIC_API_KEY``.

The gate is enforced at three depths so nothing can quietly bill:
  * ``GET /features`` tells the client what to render (presentation only);
  * ``Depends`` guards reject the routed calls with 503 before any model call;
  * ``llm.get_client()`` refuses to build an Anthropic client at all, which
    catches any future code path that forgets the route guard.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.config import get_settings


class AiFeature(StrEnum):
    """The billable features, keyed the same way ``GET /features`` reports them."""

    NL_CAPTURE = "nl_capture"
    ADVISOR = "advisor"
    DAILY_NOTE = "ai_daily_note"


LABELS: dict[AiFeature, str] = {
    AiFeature.NL_CAPTURE: "Natural-language capture",
    AiFeature.ADVISOR: "Ask Frank",
    AiFeature.DAILY_NOTE: "Frank's daily note",
}


class AiDisabledError(RuntimeError):
    """A service tried to reach the model while the AI features are switched off."""


def ai_enabled() -> bool:
    """True only when the flag is on *and* a key is configured.

    Read at call time (not import time) so the flag can be flipped without a
    rebuild, and so tests can toggle it via the settings cache.
    """
    settings = get_settings()
    return settings.llm_enabled and bool(settings.anthropic_api_key.strip())


def coming_soon_detail(feature: AiFeature) -> str:
    return (
        f"{LABELS[feature]} is coming soon — Frank's AI features are switched off "
        "in this build. Everything else works as normal."
    )


def require_ai(feature: AiFeature) -> Callable[[], None]:
    """Build a dependency that 503s a billable route while the features are off."""

    def guard() -> None:
        if not ai_enabled():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, coming_soon_detail(feature))

    return guard


# Declare these *after* `CurrentUser` in a signature so auth still answers first.
NlCaptureGate = Annotated[None, Depends(require_ai(AiFeature.NL_CAPTURE))]
AdvisorGate = Annotated[None, Depends(require_ai(AiFeature.ADVISOR))]
