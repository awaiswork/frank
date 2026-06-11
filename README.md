# Frank — AI Spending Advisor

A personal finance app with two AI features at its core: natural-language transaction
capture and a spending advisor that reasons over your real data.

**Stack:** React 19 + TypeScript (Vite) · Python 3.12 + FastAPI · PostgreSQL 16 ·
Anthropic API (Claude).

## Local development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22+, Docker.

```sh
# 1. Database
docker compose up -d db

# 2. Backend (http://localhost:8000)
cd backend
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload

# 3. Frontend (http://localhost:5173)
cd frontend
cp .env.example .env
npm install
npm run dev
```

Health check: `curl http://localhost:8000/healthz`

## Checks

```sh
# Backend
cd backend && uv run ruff check . && uv run mypy app tests && uv run pytest

# Frontend
cd frontend && npm run lint && npm run format:check && npm run build
```

CI runs the same checks on every push (`.github/workflows/ci.yml`).
