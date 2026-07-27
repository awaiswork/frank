FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# alembic ships in the image so migrations can run on deploy; `alembic` is a
# main dependency, so --no-dev keeps it.
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# Shell form on purpose: exec form doesn't expand ${PORT}, which Railway injects.
# Migrations run first so a deploy can't serve against a stale schema.
#
# --forwarded-allow-ips: behind Railway's proxy the real client IP only arrives
# in X-Forwarded-For; without trusting it, per-IP rate limits would bucket every
# request together.
# `exec` so uvicorn replaces the shell and receives SIGTERM directly — otherwise
# a redeploy waits out the grace period and gets SIGKILLed.
CMD uv run --no-dev alembic upgrade head && \
    exec uv run --no-dev uvicorn app.main:app \
      --host 0.0.0.0 --port ${PORT:-8000} \
      --proxy-headers --forwarded-allow-ips='*'
