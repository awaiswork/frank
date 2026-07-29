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

## Auth and email

Email + password, with a short-lived access token held in memory and a refresh
cookie backed by a server-side session row. The session table is what makes
signing out mean something: the refresh cookie is httpOnly and scoped to
`/auth`, so the browser cannot drop it on its own — before sessions existed,
signing out cleared some React state and left a credential in the jar that a
reload would happily reuse.

**Flows**

| Flow | What happens |
|---|---|
| Register | Creates the account, signs you in, emails a confirmation link (24h) |
| Log in | `remember_me` picks the session lifetime: 12 hours, or 30 days |
| Refresh | Rotates the token on every use; a retired token replayed later revokes that whole login |
| Log out | Revokes this session server-side and clears the cookie |
| Log out everywhere | Revokes every session for the account (Settings → Account) |
| Forgot password | Emails a one-hour, single-use link. Identical response whether or not the address exists |
| Reset password | Sets the password, revokes **all** sessions, then sends you to the login form rather than signing you in |
| Verify email | Confirms the address. Unverified accounts are **not** blocked — they see a dismissible banner with a resend button |

Tokens are 32 random bytes; only their SHA-256 is stored. SHA-256 rather than
bcrypt on purpose — these are full-entropy secrets with nothing to guess, so
bcrypt's deliberate slowness would buy no security and would tax every refresh.

**Email**

Sending goes through `EmailSender` (`app/email/sender.py`). Two implementations:

- `console` — the default. Prints the message, including the link, and sends
  nothing. This is the development path, and the test suite pins it so no test
  can reach the network.
- `resend` — posts to Resend's API with a 5-second timeout.

Sends run in a FastAPI background task, after the response is on the wire, so a
slow provider can never turn "reset my password" into a hang. Two consequences
worth knowing: a send that fails is logged and dropped (the resend button is the
recovery path), and because Render's free instance is culled after 15 idle
minutes, a background send still in flight when that happens dies with it.

**Resend without a domain.** Until a custom domain is verified, Resend permits
sending only from `onboarding@resend.dev` and only *to* the address on your
Resend account. Any other recipient is rejected. So: to exercise the real
provider, register with that exact address. For every other address, use
`EMAIL_PROVIDER=console` and copy the link out of the logs.

**Data residency.** Resend's sending region is chosen **per domain**, in the
dashboard, when the domain is added — there is no per-request setting, and no
domain means no choice: mail leaves via the shared `resend.dev` domain in
Resend's default region. Account data, logs and metadata are held in the US
regardless, under a DPA with SCCs. So EU dispatch is something a custom domain
buys, not something this app can request. A known gap rather than an oversight;
`EmailSender` exists partly so a move to an EU-resident provider is one file.

Never logged: tokens, links, email addresses, or anything password-shaped.
Events carry a user id (`password_reset_requested`, `refresh_reuse_detected`).

## Deployment

Three free services, no card required: the API on **Render** from `backend/Dockerfile`,
Postgres on **Neon**, and the frontend as a static Vite build on **Vercel**. All three
deploy from `main` on push. Migrations run as part of the container's start command, so
a deploy can never serve against a stale schema.

**Neon** — create a project in a region near Render's (`frankfurt`) and copy the
connection string. It arrives as `postgresql://…?sslmode=require`; `app/config.py`
rewrites the scheme to psycopg3 and preserves the TLS parameters. Render's own free
Postgres expires after a trial period, which is why the database lives here instead.

**Render** — import `render.yaml` as a Blueprint (New + → Blueprint) rather than
clicking through the dashboard; it declares the Docker build, the `/healthz` health
check, and every environment variable. Render prompts for the two it can't know:

| Variable | Required | Value |
|---|---|---|
| `DATABASE_URL` | yes | the Neon connection string, verbatim |
| `FRONTEND_ORIGIN` | yes | the Vercel URL; comma-separated for several |
| `PUBLIC_APP_URL` | recommended | the one origin emailed links are built from. Must match a `FRONTEND_ORIGIN` entry exactly. Defaults to the first entry, whose order is incidental — set it explicitly once previews exist |
| `EMAIL_PROVIDER` | no | `console` (default, logs and sends nothing) or `resend` |
| `EMAIL_API_KEY` | if provider set | Resend API key. Required whenever `EMAIL_PROVIDER` is not `console`; boot fails without it |
| `EMAIL_FROM` | no | sender address. `Frankly <onboarding@resend.dev>` until a domain is verified |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | default 15. This is the real delay between revoking a session and access actually stopping |
| `REFRESH_TOKEN_EXPIRE_DAYS` | no | "remember me" lifetime, default 30 |
| `REFRESH_SESSION_SHORT_HOURS` | no | lifetime without "remember me", default 12 |
| `PASSWORD_RESET_TTL_MINUTES` | no | default 60 |
| `EMAIL_VERIFY_TTL_HOURS` | no | default 24 |
| `EMAIL_RESEND_COOLDOWN_SECONDS` | no | per-user gap between verification emails, default 60 |

The rest are set by the Blueprint: `ENV=prod`, a generated `SECRET_KEY`,
`LLM_ENABLED=false`, and `COOKIE_SAMESITE=none`. `ANTHROPIC_API_KEY` stays unset — both
it and `LLM_ENABLED` are required before anything can bill, so an absent key is a second
lock (`app/features.py`).

**Vercel** — root directory `frontend`, framework Vite, `VITE_API_URL` pointing at the
API. Vite inlines that at build time, so changing it needs a redeploy, not a restart.
`frontend/vercel.json` rewrites all paths to `index.html` so client-side routes survive
a refresh.

**Why `COOKIE_SAMESITE` exists:** the refresh token is an httpOnly cookie. A browser
only sends a `SameSite=Lax` cookie on same-site requests — `frankly.app` and
`api.frankly.app` qualify, but `*.vercel.app` and `*.onrender.com` are different sites,
so on platform subdomains the cookie is silently dropped and every reload logs the user
out. Set `none` until a custom domain is attached, then move it back to `lax`.

**Cold starts.** A free Render service sleeps after 15 minutes idle and takes 30–60 s to
wake — long enough that a visitor gives up. `.github/workflows/keep-warm.yml` pings
`/healthz` every 10 minutes to prevent it; set the `API_URL` repository variable to
switch it on. Staying awake ~744 h/month fits inside Render's 750 free instance-hours,
with little room for a second free service. Neon sleeps too, but wakes in well under a
second, and `pool_pre_ping` in `app/db.py` handles connections dropped while it slept.

Running `alembic upgrade head` on every boot is a deliberate trade: it costs a second or
two of start-up in exchange for never serving against a stale schema, and free plans
give no separate release step to put it in. Neon is reachable directly, so migrations
can move to a manual step if that ever matters —
`DATABASE_URL=<neon-url> uv run alembic upgrade head` works from any machine.

**Demo account** — run once after the first deploy, from Render's shell (or against the
Neon URL from your machine, since Neon is reachable directly):

```sh
uv run --no-dev python -m app.seed_demo
```

That creates `demo@frankly.app` with a deterministic two-month history (transactions,
budgets, a savings goal) so the public link opens on a populated app rather than empty
states. It's idempotent — re-running is a no-op.
