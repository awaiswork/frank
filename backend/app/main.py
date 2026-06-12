import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, budgets, categories, goals, insights, nl, transactions


def _configure_logging() -> None:
    """Emit the app's structured JSON logs (e.g. per-call LLM usage, §7a/§12) to stdout.

    Scoped to the ``frank`` logger with ``propagate=False`` so it doesn't disturb
    uvicorn's own loggers.
    """
    logger = logging.getLogger("frank")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()
    app = FastAPI(title="Frank API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(categories.router)
    app.include_router(transactions.router)
    app.include_router(budgets.router)
    app.include_router(goals.router)
    app.include_router(insights.router)
    app.include_router(nl.router)
    return app


app = create_app()
