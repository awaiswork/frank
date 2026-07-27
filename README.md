# Frankly — AI Spending Advisor

A personal finance app with two AI features at its core: natural-language transaction
capture and a spending advisor that reasons over your real data.

**Stack:** React 19 + TypeScript (Vite) · Python 3.12 + FastAPI · PostgreSQL 16 ·
Anthropic API (Claude).

## AI features are off by default

Three features call the Anthropic API and therefore cost money: natural-language
capture, Ask Frankly, and the written daily note. They ship **disabled** and show as
"coming soon" in the UI. Everything else — logging spend by hand, budgets, goals,
safe-to-spend, insights, CSV export — works untouched, and the daily note falls back
to a hand-written line for the day's (still deterministic) mood.

Turn them on with **both** of these in `backend/.env`:

```sh
LLM_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...
```

Either one alone leaves the features off, so a stray key can't start billing. The
gate is enforced server-side — `GET /features` only tells the client what to render,
while the routes themselves return 503 and `llm.get_client()` refuses to build a
client at all. See `backend/app/features.py`.

## Local development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22+, Docker.

```sh
./dev.sh
```

That brings up the whole stack: Postgres, the backend on http://localhost:8000, and the
frontend on http://localhost:5173. It creates any missing `.env` from `.env.example`,
applies migrations, and installs deps on first run. Ctrl-C stops the servers and leaves
the db container up (`docker compose down` to stop that too).

If either port is taken, override it — CORS and the frontend's API base follow along, so
no `.env` edits are needed:

```sh
API_PORT=8001 WEB_PORT=5174 ./dev.sh
```

<details>
<summary>Or start each piece by hand</summary>

```sh
# 1. Database
docker compose up -d db

# 2. Backend (http://localhost:8000)
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 3. Frontend (http://localhost:5173)
cd frontend
cp .env.example .env
npm install
npm run dev
```

</details>

Health check: `curl http://localhost:8000/healthz`

## Checks

```sh
# Backend
cd backend && uv run ruff check . && uv run mypy app tests && uv run pytest

# Frontend
cd frontend && npm run lint && npm run format:check && npm run build
```

CI runs the same checks on every push (`.github/workflows/ci.yml`).

## Deployment

The API runs on Railway from `backend/Dockerfile` (managed Postgres attached); the
frontend is a static Vite build on Vercel. Both deploy from `main` on push. Migrations
run as part of the container's start command, so a deploy can never serve against a
stale schema.

**Railway** — service root directory `backend`, Dockerfile builder.

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — the bare `postgresql://` scheme is rewritten to psycopg3 in `app/config.py` |
| `ENV` | `prod` |
| `SECRET_KEY` | `openssl rand -hex 32` — the app refuses to boot in prod on the dev default |
| `FRONTEND_ORIGIN` | `https://frankly.app,https://www.frankly.app` (comma-separated) |
| `COOKIE_SAMESITE` | `lax` on a shared domain; `none` while on `*.vercel.app` + `*.up.railway.app` |
| `LLM_ENABLED` | `false` |

`ANTHROPIC_API_KEY` stays unset. Both it and `LLM_ENABLED` are required before anything
can bill, so an unset key is a second lock (`app/features.py`).

**Vercel** — root directory `frontend`, framework Vite, `VITE_API_URL` pointing at the
API. Vite inlines that at build time, so changing it needs a redeploy, not a restart.
`frontend/vercel.json` rewrites all paths to `index.html` so client-side routes survive
a refresh.

**Why `COOKIE_SAMESITE` exists:** the refresh token is an httpOnly cookie. A browser
only sends a `SameSite=Lax` cookie on same-site requests — `frankly.app` and
`api.frankly.app` qualify, but `*.vercel.app` and `*.up.railway.app` are different
sites, so on platform subdomains the cookie is silently dropped and every reload logs
the user out. Set `none` until a custom domain is attached, then move it back to `lax`.

**Demo account** — run once after the first deploy, from the Railway shell:

```sh
uv run --no-dev python -m app.seed_demo
```

That creates `demo@frankly.app` with a deterministic two-month history (transactions,
budgets, a savings goal) so the public link opens on a populated app rather than empty
states. It's idempotent — re-running is a no-op.
