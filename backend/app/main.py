import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.features import ai_enabled
from app.limits import limiter, rate_limit_handler
from app.routers import (
    advisor,
    auth,
    budgets,
    categories,
    goals,
    insights,
    nl,
    oauth,
    transactions,
)
from app.schemas import FeaturesOut


def _configure_logging() -> None:
    """Emit the app's structured JSON logs (e.g. per-call LLM usage, §7a/§12) to stdout.

    Scoped to the ``frankly`` logger with ``propagate=False`` so it doesn't disturb
    uvicorn's own loggers.
    """
    logger = logging.getLogger("frankly")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()
    app = FastAPI(title="Frankly API", version="0.1.0")

    # Toggled per-environment rather than at import, so the test suite (which
    # registers many accounts a minute) can switch it off.
    limiter.enabled = settings.rate_limit_enabled
    limiter.reset()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/features", response_model=FeaturesOut)
    def features() -> FeaturesOut:
        """Which optional features are on. Unauthenticated: the client needs it
        before it can render anything, and it reveals nothing user-specific."""
        on = ai_enabled()
        return FeaturesOut(ai_enabled=on, nl_capture=on, advisor=on, ai_daily_note=on)

    app.include_router(auth.router)
    app.include_router(oauth.router)
    app.include_router(categories.router)
    app.include_router(transactions.router)
    app.include_router(budgets.router)
    app.include_router(goals.router)
    app.include_router(insights.router)
    app.include_router(nl.router)
    app.include_router(advisor.router)
    return app


app = create_app()
