# Technical Plan — "Frank", the AI Spending Advisor

> **How to use this document:** This is the complete technical specification for building Frank end to end. It is written to be handed to Claude Code together with the design screens. Decisions are already made — follow them unless something is impossible, in which case flag it and propose the closest alternative. Build in the milestone order in §13.

---

## 1. Goals and explicit non-goals

**Goals (v1):**
- A deployed, working web app: React + TypeScript frontend, Python + FastAPI backend, PostgreSQL database, hosted in cloud infrastructure.
- Two AI features as the product core: (1) natural-language transaction capture, (2) the spending advisor that reasons over the user's real data.
- Clean, demonstrable engineering at every layer — this is a portfolio piece for a role requiring end-to-end web development with TypeScript, Python, and PostgreSQL.

**Non-goals (v1 — do not build):**
- Bank account integration / open banking, loans, investments, multi-currency conversion, shared/household accounts, mobile native apps, receipt image scanning, recurring-transaction automation. These are explicitly out of scope to protect delivery.

## 2. Architecture overview

```
Browser (React + TS, Vite)
   │  HTTPS / JSON, JWT bearer auth
   ▼
FastAPI (Python 3.12)
   │  ├── REST endpoints (CRUD + aggregates)
   │  ├── /nl/parse  ──► Anthropic API (claude-haiku-4-5) ─► Pydantic validation
   │  └── /advisor/ask ─► context builder (SQL aggregates) ─► Anthropic API (claude-sonnet-4-6, streaming)
   ▼
PostgreSQL 16 (SQLAlchemy 2.0 ORM, Alembic migrations)
```

Single deployable API; the Anthropic API key lives **only** on the server, never in the frontend.

## 3. Repository layout (monorepo)

```
frank/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app factory, CORS, routers
│   │   ├── config.py            # pydantic-settings, reads env vars
│   │   ├── db.py                # engine, session dependency
│   │   ├── models/              # SQLAlchemy models (one file per table)
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── routers/             # auth.py, transactions.py, budgets.py, goals.py, nl.py, advisor.py, insights.py
│   │   ├── services/
│   │   │   ├── llm.py           # Anthropic client wrapper, retries, usage logging
│   │   │   ├── parser.py        # NL → transaction drafts
│   │   │   ├── advisor.py       # context builder + verdict generation
│   │   │   └── aggregates.py    # the SQL aggregate queries (§6)
│   │   └── security.py          # password hashing, JWT
│   ├── alembic/                 # migrations
│   ├── tests/                   # pytest
│   ├── pyproject.toml           # managed with uv
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/                 # typed client, generated or hand-written per §8
│   │   ├── components/          # per design component sheet
│   │   ├── pages/               # Home, Capture, Advisor, Transactions, Budgets, Goals, Insights, Settings
│   │   ├── hooks/
│   │   └── lib/
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml           # local dev: postgres + api
└── .github/workflows/ci.yml
```

## 4. Stack decisions (final)

| Layer | Choice | Why |
|---|---|---|
| Backend language | Python 3.12 | Role requirement; modern typing |
| Web framework | FastAPI | Async (LLM calls), OpenAPI for free, Pydantic-native |
| ORM / migrations | SQLAlchemy 2.0 (typed, `Mapped[]` style) + Alembic | Industry standard; migrations prove schema discipline |
| Validation | Pydantic v2 | One model chain: LLM JSON → Pydantic → DB |
| Package mgmt (BE) | uv | Fast, lockfile, modern |
| Database | PostgreSQL 16 | Role requirement |
| LLM | Anthropic API via official `anthropic` Python SDK | Parsing: `claude-haiku-4-5` (fast/cheap, temperature 0). Advisor: `claude-sonnet-4-6` (better reasoning, streamed). Verify current model IDs and pricing at https://docs.claude.com/en/docs/about-claude/models/overview before pinning. |
| Frontend | React 18 + TypeScript (strict) + Vite | Role requirement |
| Server state | TanStack Query | Caching, optimistic updates for CRUD |
| Styling | Tailwind CSS, design tokens from the design doc as CSS variables | Fast to match redlines |
| Charts | Recharts | Covers bars/lines/donuts in the designs |
| Forms/local state | React hook form only where needed; avoid global state libs | v1 doesn't need Redux/Zustand |
| Auth | Email + password, bcrypt (passlib), JWT access token (24h) in memory + refresh via httpOnly cookie | Simple, demonstrable, sufficient for single-user portfolio app |
| Testing | pytest + httpx (BE), Vitest + React Testing Library (FE) | |
| Lint/format | ruff + mypy (BE), eslint + prettier + `tsc --noEmit` (FE) | |
| CI | GitHub Actions | Lint, typecheck, test, build on every push |
| Hosting | Backend + Postgres on **Railway** (managed Postgres addon); frontend on **Vercel** | Fastest path to "running in cloud infrastructure"; can mention RDS/containers as a discussed upgrade path in the README |
| Containerization | Dockerfile for the API + docker-compose for local dev | Demonstrates container fluency even if Railway builds from Dockerfile |

## 5. Database schema (PostgreSQL)

All money is stored as **integer cents** (`amount_cents BIGINT`) — never floats. All tables have `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `created_at timestamptz DEFAULT now()`. Every user-owned table has `user_id` FK with `ON DELETE CASCADE`, and **every query filters by user_id** (enforce in a shared dependency).

```sql
users           (id, email CITEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                 currency CHAR(3) NOT NULL DEFAULT 'EUR', monthly_income_cents BIGINT)

categories      (id, user_id FK, name TEXT NOT NULL, kind TEXT CHECK (kind IN ('expense','income')),
                 color TEXT, UNIQUE (user_id, lower(name)))

transactions    (id, user_id FK, category_id FK NULL, kind TEXT CHECK (kind IN ('expense','income')),
                 amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
                 description TEXT NOT NULL, merchant TEXT,
                 occurred_on DATE NOT NULL,
                 source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','nl_parse')),
                 raw_input TEXT,            -- the original NL sentence, for the audit trail
                 llm_confidence NUMERIC(3,2))

budgets         (id, user_id FK, category_id FK, month DATE NOT NULL,   -- always first of month
                 limit_cents BIGINT NOT NULL, UNIQUE (user_id, category_id, month))

savings_goals   (id, user_id FK, name TEXT NOT NULL, target_cents BIGINT NOT NULL,
                 due_date DATE, archived_at timestamptz)

goal_contributions (id, goal_id FK, amount_cents BIGINT NOT NULL, occurred_on DATE NOT NULL)

advice_requests (id, user_id FK, question TEXT NOT NULL, amount_cents BIGINT,
                 verdict TEXT CHECK (verdict IN ('go','wait','skip','your_call')),
                 reasoning TEXT NOT NULL,
                 evidence JSONB NOT NULL,        -- the evidence rows shown on the card
                 context_snapshot JSONB NOT NULL, -- exact aggregates sent to the model (reproducibility)
                 model TEXT, input_tokens INT, output_tokens INT,
                 user_followed BOOLEAN)           -- set later from the "did you buy it?" follow-up
```

**Indexes:** `transactions (user_id, occurred_on DESC)`, `transactions (user_id, category_id)`, `budgets (user_id, month)`, `advice_requests (user_id, created_at DESC)`.

Seed migration: 6 default expense categories + 1 income category created at registration.

## 6. The aggregate queries (the SQL showcase — implement as real SQL/SQLAlchemy Core, not ORM loops)

1. **Spend by category for a month** — `SUM(amount_cents) GROUP BY category` filtered to month, joined to categories.
2. **Budget vs. actual with pace** — budgets LEFT JOIN the aggregate above; compute `spent / limit` and `day_of_month / days_in_month` so the API returns pace, not just percentage.
3. **Safe to spend** — income this month − fixed budgets remaining − goal contributions planned − spent so far; one CTE-based query.
4. **Daily burn rate (trailing 30 days)** and **month-over-month delta per category** (window function `LAG()` over monthly sums) for the Insights screen.

These four queries are interview material — keep them readable, commented, and covered by tests with seeded fixtures.

## 7. LLM integration (the core of the project)

### 7a. Shared client (`services/llm.py`)
- Official `anthropic` SDK, async client. API key from `ANTHROPIC_API_KEY` env var.
- Wrapper handles: timeout (20s), 2 retries with backoff on 429/5xx, and logging of `model, input_tokens, output_tokens, latency_ms` per call to stdout (structured JSON logs).
- Hard limits: parser `max_tokens=1000`; advisor `max_tokens=1200`. Reject NL inputs > 500 characters and advisor questions > 300 characters at the API layer (cost + abuse control).

### 7b. NL parser (`POST /nl/parse`)
- Model: `claude-haiku-4-5`, temperature 0.
- **Use tool-use / structured output to force the schema** (define a `record_transactions` tool whose input schema mirrors the Pydantic model below; instruct the model it must call it). This is more reliable than "respond only with JSON" prompting — see https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview.
- Output schema (Pydantic): `ParsedTransaction { kind, amount_cents, description, merchant?, category_name?, occurred_on?, confidence: float }`, returned as `list[ParsedTransaction]` (one sentence can contain several transactions).
- Prompt content: today's date, the user's category names (so it maps to *their* categories, not invented ones), currency, and 4–5 few-shot examples including a multi-transaction example and an ambiguous one.
- **Parse never writes to the DB.** It returns drafts; the client confirms via the normal `POST /transactions` endpoint (the confirm-before-commit pattern from the design doc). Validation failures → one retry with the validation error appended; second failure → 422 with a friendly message the UI maps to the correction flow.

### 7c. Advisor (`POST /advisor/ask`)
- Model: `claude-sonnet-4-6`, streamed (SSE) to the frontend so the reasoning renders progressively.
- **Context builder** (`services/advisor.py`): never send raw transaction rows. Send compact aggregates: current month budget-vs-actual per category (from §6.2), safe-to-spend (§6.3), goals with progress and due dates, last 3 advice requests + verdicts, and the trailing-30-day burn rate. Target < 1,500 input tokens. Store the exact context in `context_snapshot` for reproducibility.
- Output: tool-forced structured response `{ verdict: go|wait|skip|your_call, headline: str, evidence: list[{label, value}], reasoning: str }` mapping 1:1 to the verdict card in the design.
- System prompt rules: ground every claim in the provided numbers; never invent data; be candid but kind; if the question is not a purchase decision, use `your_call` and say what info is missing; always include the static disclaimer field (UI renders it small): *Frank gives opinions based on your data, not professional financial advice.*
- Follow-up endpoint `PATCH /advisor/{id}` sets `user_followed` — powers the "you asked / Frank said / you did" history.

## 8. API surface (FastAPI routers; OpenAPI auto-generated — frontend consumes the generated types via `openapi-typescript`)

```
POST   /auth/register            POST   /auth/login            POST  /auth/refresh
GET    /me                       PATCH  /me

GET    /transactions?month=YYYY-MM&category_id=&q=     (paginated, 50/page)
POST   /transactions             PATCH  /transactions/{id}     DELETE /transactions/{id}

POST   /nl/parse                 # → list of drafts, not persisted

GET    /budgets?month=           PUT    /budgets/{category_id}?month=    # upsert
GET    /goals                    POST   /goals                 PATCH /goals/{id}
POST   /goals/{id}/contributions

POST   /advisor/ask              # SSE stream
GET    /advisor/history          PATCH  /advisor/{id}          # user_followed

GET    /insights/summary?month=  # aggregates for the Insights screen
GET    /healthz
```

Conventions: all errors as RFC-7807-style JSON `{type, title, detail}`; request-id middleware adds `X-Request-ID` and includes it in logs; rate limit `/nl/parse` and `/advisor/ask` to 20/min/user (slowapi).

## 9. Frontend plan

- Routing: React Router. Pages map 1:1 to design screens; the NL capture input is a shared layout component present on Home and Transactions.
- TanStack Query keys per resource; optimistic updates for transaction edit/delete; invalidate budgets + home summary after any transaction write (the "Groceries: 64% → 71%" moment comes from refetching the budget aggregate).
- Advisor streaming: consume SSE with `EventSource`/fetch-streams; render headline + evidence as soon as the structured prefix arrives, stream the reasoning paragraph after.
- Money handling: a single `formatMoney(cents, currency)` util; never do float math on the client.
- Implement design tokens (colors, type scale, spacing, motion durations) as Tailwind theme extensions taken directly from the design doc's redlines; `prefers-reduced-motion` respected globally.

## 10. Security checklist

API key server-side only; bcrypt password hashing; JWT signed with `SECRET_KEY` env var; httpOnly+Secure+SameSite refresh cookie; CORS locked to the frontend origin; every DB query scoped by `user_id` from the token (single shared dependency — write a test that proves cross-user access fails); input length limits (§7a); no PII in logs; SQL only via parameterized SQLAlchemy.

## 11. Testing strategy

- **Backend (pytest, ephemeral Postgres via docker-compose in CI):** auth flow; CRUD per resource; the four aggregate queries against seeded fixtures (known totals); parser service with the Anthropic client **mocked** (valid parse, multi-transaction, malformed-then-retry, length rejection); advisor context builder output shape and token-size budget; cross-user isolation test.
- **Frontend (Vitest + RTL):** money formatting; draft-card field correction; budget pace component logic; advisor card renders all 4 verdicts from fixture payloads.
- One smoke E2E (Playwright, optional stretch): register → NL-capture a transaction → see budget move.

## 12. Environments, config, deployment

- Env vars: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SECRET_KEY`, `FRONTEND_ORIGIN`, `ENV`. Local dev: `docker-compose up` (postgres) + `uvicorn --reload` + `vite dev`; `.env` files git-ignored, `.env.example` committed.
- Migrations: `alembic upgrade head` runs as the release step on deploy.
- **Railway:** API service built from `backend/Dockerfile`, managed Postgres addon, env vars in dashboard. **Vercel:** frontend, `VITE_API_URL` pointing at Railway. Custom domain optional.
- CI (GitHub Actions): on push → ruff + mypy + pytest (with services: postgres) for backend; eslint + tsc + vitest + `vite build` for frontend. Merge to `main` deploys (Railway/Vercel git integration).
- Observability v1: structured JSON logs + request IDs + per-call LLM token/cost log lines. A `/healthz` endpoint checked by Railway.

## 13. Build order (milestones — finish each before starting the next)

1. **M0 — Skeleton (½ day):** repo, docker-compose Postgres, FastAPI hello + healthz, Vite app, CI green.
2. **M1 — Data layer (1–2 days):** models, migrations, auth, categories seed, transactions CRUD + tests.
3. **M2 — Core UI (2–3 days):** design tokens, Home, Transactions, Budgets, Goals pages against real API; aggregate queries §6 wired to Home/Budgets.
4. **M3 — NL capture (1–2 days):** parser service + endpoint + draft-card flow with confirm/correct; mocked tests; the parsing loading moment per design.
5. **M4 — Advisor (2 days):** context builder, streaming endpoint, verdict card ×4, history + user_followed.
6. **M5 — Polish + deploy (1–2 days):** empty/error states, dark mode, rate limits, deploy to Railway+Vercel, seed a demo account.
7. **M6 — Portfolio assets (½ day):** README with architecture diagram + the §6 queries highlighted, 60-second demo GIF of NL capture and a verdict, LinkedIn post.

**Definition of done (v1):** a stranger can register, log "spent 12.50 lunch at Hesburger" in natural language, confirm the draft, watch the Groceries budget move, ask "should I buy 240€ headphones?", and receive a streamed verdict grounded in their own numbers — on a public URL, with CI green.

## 14. Known risks and mitigations

- **LLM output drift / malformed JSON** → tool-forced schemas + Pydantic + one corrective retry (§7b).
- **API cost surprises** → Haiku for parsing, aggregate-only advisor context, token logging, per-user rate limits, max_tokens caps.
- **Scope creep** → §1 non-goals are binding; new ideas go to a `LATER.md`, not the codebase.
- **Model deprecation** → model IDs in config, not code; check the models page before pinning.
