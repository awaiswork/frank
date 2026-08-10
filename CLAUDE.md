# CLAUDE.md — Frankly

Rules for working in this repo. Read before making changes. These encode hard-won
deployment invariants — breaking them takes production down in ways that produce
no error in the logs.

## What this is

Frankly is a personal-finance app. Monorepo:
- `frontend/` — React 19 + TypeScript + Vite (deployed on **Vercel**)
- `backend/` — FastAPI + Python 3.12, managed with **uv** (deployed on **Render**, Docker from `backend/Dockerfile`, config in root `render.yaml`)
- Database: **Neon** Postgres (direct / non-pooler endpoint, `eu-central-1`)
- AI features exist in code but **ship OFF in production** (`LLM_ENABLED=false`, no Anthropic key)

Public endpoints: API `https://frankly-api-8d2s.onrender.com`, app `https://frank-coral.vercel.app`.

Hosting history, so it isn't re-litigated: Railway removed its free tier, Koyeb closed
free signups after Mistral acquired it (Feb 2026), Fly.io dropped free allowances for new
accounts. **Do not propose any of the three.** The Dockerfile is deliberately
host-agnostic — it honours `$PORT` and `config.py` rewrites the bare `postgresql://`
scheme managed providers hand out — which is why each move cost only documentation.

## How deploys happen

- Pushing to `main` auto-deploys **both**: Vercel rebuilds the frontend, Render rebuilds the API and runs `alembic upgrade head` on boot.
- There is no separate release step; migrations run on every container boot.
- **Render only rebuilds when `backend/**` or `render.yaml` changes** (`buildFilter` in `render.yaml`) — a frontend-only commit no longer restarts the live API. The filter is exhaustive because `dockerContext` is `./backend`, so nothing outside it can affect the image. If you add a backend input somewhere else, add it to the filter or that change won't deploy.
- Filters apply to autodeploys and PR previews only. A **manual deploy** from the Render dashboard always builds, which is the escape hatch if the filter is ever wrong.
- **Vercel still rebuilds on every push**, including backend-only commits — no Ignored Build Step is configured. Harmless (static builds are fast and free) but don't mistake it for path filtering.
- Free tier quotas: ~750 instance-hours/month and 500 build minutes/month. This image builds in roughly 2–3 minutes, so build minutes are not usually the binding constraint — instance-hours are, because keep-warm holds the service awake.

## IMPORTANT — invariants that silently break production

- **Never hardcode the API URL in the frontend.** Always read `import.meta.env.VITE_API_URL`. It is baked in at *build* time, so changing that env var requires a Vercel **redeploy**, not just a save.
- **Do not change the CORS / cookie setup without understanding it.** Auth uses an httpOnly refresh cookie across two different sites (`*.vercel.app` ↔ `*.onrender.com`). It only works because: backend CORS uses an explicit `FRONTEND_ORIGIN` (never `*`) with `allow_credentials=True`; the cookie is `SameSite=None; Secure`; and the frontend sends `credentials: 'include'`. Removing any one of these logs users out on reload with no error. `FRONTEND_ORIGIN` must match the Vercel origin **exactly** — scheme included, no trailing slash. It is comma-separated if several origins are needed.
- **`COOKIE_SAMESITE` stays `none`** while frontend and API are on different domains. Only switch to `lax` after a custom domain makes them same-site (`askfrankly.app` + `api.askfrankly.app` — the domain is owned, but nothing is pointed at it yet). `none` requires `ENV=prod` (the Secure flag follows `ENV`).
- **Read settings at call time, not import time.** `_set_refresh_cookie` calls `get_settings()` *inside* the function, and `features.ai_enabled()` does the same. A module-level `settings = get_settings()` in a router freezes config at first import, which once made `COOKIE_SAMESITE` silently inert and untestable. `app/db.py` is the one deliberate exception (engine creation genuinely is import-time).
- **Money is always integer cents** (`amount_cents`, BIGINT). Never use floats for money, anywhere — not in models, not in the API, not in the frontend. Format for display only at the edge.
- **Keep AI features OFF in prod.** Do not add `ANTHROPIC_API_KEY` to production or flip `LLM_ENABLED` without being explicitly asked — it costs money. `GET /features` returning all-false is a guarantee, not a placeholder. The gate is enforced at three depths in `app/features.py`; don't route around it.
- **`/healthz` must not touch the database.** It is the platform liveness check; a DB query there fails deploys during cold starts. (It currently returns a static dict — keep it that way.)
- **`EMAIL_FROM` decides who can *receive* mail, not just what the From header says.** This one shipped broken and took a release to spot. On the shared `onboarding@resend.dev` sender, Resend delivers *only* to the address on our own Resend account and refuses every other recipient with `403 validation_error` — so signup worked for the one person testing it and silently failed for everybody else. Production now sends from `noreply@askfrankly.app`, a domain verified in Resend (eu-west-1, matching Render frankfurt / Neon eu-central-1). Never log the provider's error `message`; it quotes the recipient's address back at you. `SendFailed` (`app/email/sender.py`) exists to strip it — status and error `name` only.
- **Email config lives in `render.yaml`, not only in the dashboard.** That is the real reason the above went unnoticed: `EMAIL_PROVIDER`, `EMAIL_API_KEY` and `EMAIL_FROM` were set by hand on Render and appeared nowhere in the repo, so no review ever saw that the sender was the shared throwaway. All three are declared now (`EMAIL_API_KEY` as `sync: false`, since it is a secret). Keep it that way — config you cannot read in a diff is config nobody checks.
- **Email that isn't configured fails silently, by design.** `EMAIL_PROVIDER` defaults to `console`, and `get_sender()` also falls back to the console when a provider is named with no `EMAIL_API_KEY`. Neither is fatal (on purpose — email must not take budgets and transactions down with it), so a deployment missing them boots clean, passes its health check, answers `/auth/register` with 202 *"Check your email for a code"*, and prints every OTP into the server log. If mail stops arriving, read these three variables before debugging anything else.
- **Don't "finish" the frank → frankly rename.** The Postgres role, password and database are still `frank`, as is the repo directory. Renaming them needs a dump-and-restore, not a find-and-replace, and buys nothing a user can see.

## Product invariants — these are correctness, not preference

- **The daily note must never claim what it can't know.** With no `monthly_income_cents` on file there is no meaningful safe-to-spend, so `SafeToSpend.income_known` gates it and the mood becomes `'unknown'` rather than a verdict. Any new surface reading `safe_to_spend_cents` must check `income_known` first. Fabricated financial reassurance is the worst failure this product can have.
- **One mood source.** The mood chip and `AmbientField` both read the server mood from `useDailyNote()`. A second client-side computation existed once and drifted from it on screen. Don't add another.
- **"Today" is the user's, never the server's.** No router calls `dt.date.today()` — they take the `Today` dependency (`app/deps.py`), which resolves `users.timezone` (IANA name, NULL → UTC). The daily note's date, the streak, the trailing burn window and the default month all pivot on it, so a server-clock date hands anyone far enough east or west yesterday's or tomorrow's numbers labelled as today's. Validation happens at the write edge (`UserUpdate`); a zone the tz database no longer recognises degrades to UTC on read rather than raising, because a bad row must not 500 every request that user makes. `seed_demo.py` is the one deliberate exception — a script with no user in scope.
- **All period arithmetic comes from `services/aggregates.py`.** `month_bounds` / `parse_month` / `days_in_period`, and nothing computes a month boundary of its own — it was written six ways once. `Budget.month` stores the *period's start date*, not "a month", which is what keeps re-anchoring periods (a payday month, 25th to 24th) a change to one helper instead of a migration against every stored row and the unique constraint over them. `days_in_period` derives from `month_bounds` for the same reason. Also: `days_left` in `compute_mood` excludes today on purpose — today's spend is already inside the burn rate, and the obvious rewrite double-counts it and flips moods from `go` to `wait`.
- **The code screen must not claim an email it can't know was sent.** Same rule as the daily note, on a different surface. `/auth/resend-code` and `/auth/forgot-password` answer *identically* whether they sent a code or dropped it on the per-user cooldown — that sameness is what stops the endpoint confirming which addresses are registered, so the server can never tell the client which happened. The client therefore starts the countdown from the one send it witnessed: whoever routes to `/verify` passes `retryAfter` in router state, and `VerifyCode` seeds its cooldown from it. Absent means nothing was sent and the button must be live. The notice after a resend shows the server's `detail`, never client-authored copy asserting delivery. Anything new that routes to `/verify` has to pass `retryAfter` or it reintroduces the lie.
- **`/auth/login` sends no code, so its caller must.** The 403 path raises, and a background task attached to a raised response is discarded silently — hence the deliberate omission in `routers/auth.py`. `Login.tsx` calls `resendCode` before routing to `/verify`; without it the screen announced a code over an inbox where none had been sent.
- **A transfer is one row, and every aggregate must stay blind to it.** `kind = 'transfer'` with `counter_account_id`, guarded by `ck_transactions_transfer_shape` — both ends present, different, and no category, so it can never reach a budget however the row is written. It costs nothing to exclude because every aggregate filters `kind` with an **allow-list** — `IN ('expense','refund')` for spending, `== 'income'` for income — never a deny-list. `!= 'income'` selects the same rows today and diverges the moment a kind is added, sweeping in transfers, corrections and whatever comes next; an allow-list leaves an unconsidered kind outside every figure by default. `test_spend_signs_are_an_allow_list` holds the line. Two tests hold this: conservation (`Σ(balances)` cannot move when money is moved between your own accounts) and aggregate invariance (every spending figure identical with transfers present).
- **A balance sign is a pair, not a sign.** `services/accounts.LEG_SIGNS` maps each kind to what it does to *its own* account and to a *counter* account, because a transfer leaves one and arrives at another. The flat `{kind: sign}` map this replaced could not express that, and its obvious fix — `"transfer": -1` — produces a half transfer, money leaving with nowhere to land, which reads as handled and is worse than the omission. `test_balance_signs_cover_every_kind` reads the permitted kinds out of the CHECK constraint, so widening it forces a decision here. The client's counterpart is `lib/net.ts`, where `Record<TransactionKind, number>` makes the compiler do the same job.
- **Never remove a logging path without replacing it.** `Capture` was once the only way to create a transaction, which is why turning the AI off required `ManualCapture`. Logging spend by hand must work with every AI feature disabled.
- **Overlays render through `Portal`, never inline.** An element holding a transform becomes the containing block for `position: fixed`, and every page root animates one. A sheet left inside a page centres on that page's column and gets clipped by its height — wrong on screen, silent everywhere else. `Portal` (`components/ui.tsx`) puts overlays on `<body>`; `useModal` (`lib/useModal.ts`) carries the scroll lock, Escape, and the `inert` focus trap that makes `aria-modal="true"` true rather than merely claimed. For the same reason, a keyframe that ends where the element already is uses `backwards`, not `forwards`/`both` — `animate-stamp` is the one that genuinely needs `both`.
- **One capture sheet, owned by `Layout`.** Screens open it with `useCapture()`. When pages mounted their own `<QuickAdd>`, ⌘K opened Layout's on top of it — two backdrops, two dialogs, and a stale form left behind after saving.

## Migrations

- Alembic runs on every boot, so a bad migration takes the API down on deploy.
- Make migrations **backward-compatible**: add a column in one deploy, start requiring it in the next. Old and new code overlap briefly during rollout.
- **Never edit a migration that has already run in production.** Write a new one.
- Test locally against a scratch DB before pushing: `cd backend && uv run alembic upgrade head`.

## Testing

- `tests/conftest.py` has an autouse fixture that forces `LLM_ENABLED=false` **and** `RATE_LIMIT_ENABLED=false`. Any test that drives a model must request the `ai_on` fixture; anything asserting on throttling must re-enable it explicitly (see `tests/test_deploy_config.py`).
- Tests run inside a rolled-back outer transaction, so they never see each other's data. Don't add manual cleanup.
- Deployment-critical config (driver rewrite, cookie policy, CORS list, fail-fast guards) is covered by `tests/test_deploy_config.py`. Extend it rather than trusting a manual check.
- Frontend component tests opt into jsdom per file with a `// @vitest-environment jsdom` docblock, so the pure `lib/` tests keep running on node. Vitest runs without globals here, which means testing-library never registers its automatic cleanup — call `cleanup()` in `afterEach` yourself or each test will query the previous test's DOM.

## Cost / free-tier awareness

- Render free tier gives ~750 instance-hours/month; the keep-warm cron in `.github/workflows/keep-warm.yml` uses most of it. Avoid triggering unnecessary redeploys, and do not marathon-deploy near month-end — crossing 750 suspends the service until reset.
- Keep-warm is free only because this repo is **public** (unmetered Actions). If it ever goes private, that cron would exhaust the 2,000 free minutes — move to an external pinger instead.
- Neon and Render both sleep when idle. `pool_pre_ping` in `app/db.py` is what survives a connection dropped while the database slept — don't remove it.
- Never commit `.env`. Never print or log `DATABASE_URL`, `SECRET_KEY`, or any secret.
- This repo is public. Keep commit messages clean and professional (recruiters read them).
- **Never add `Co-Authored-By: Claude` or any Claude/Anthropic attribution** to commits or PR bodies. `awais` is the sole author.

## Requires my approval before you do it

- Push to `main` / trigger any production deploy
- **Open a pull request.** Branching, committing and pushing need no permission — `gh pr create` does. A PR notifies people, invites review, and builds a Vercel preview, so filing one is my call rather than something to find already done. Push the branch, then say it's ready with a title and summary drafted, so approving it is one word.
- Add or change a migration
- Change any environment variable (state which platform needs a redeploy after)
- Add, remove, or upgrade a dependency
- Touch anything in the auth / cookie / CORS path
- Change `render.yaml`, `vercel.json`, or the Dockerfile

## Preferred workflow

Work on a short branch and open a PR — Vercel builds a preview URL per PR, so changes can be checked on a real deployment before merging. Merge to `main` only when it looks right. Straight-to-`main` is fine for copy tweaks; use the preview loop for migrations or anything risky.

Note: a Vercel preview points at whatever `VITE_API_URL` is configured, i.e. **production**. Treat preview writes as real data, and don't test migrations through one.

## Commands

Whole stack (from repo root) — creates missing `.env` files, applies migrations, starts everything:
- `./dev.sh` (Postgres + API on :8000 + web on :5173; `API_PORT=8001 WEB_PORT=5174 ./dev.sh` to move them)

Backend (from `backend/`):
- Dev by hand: `docker compose up -d db` then `uv run uvicorn app.main:app --reload` — note local Postgres is on host port **5433**, not 5432, to avoid colliding with a system install
- Test / lint / types: `uv run pytest` · `uv run ruff check .` · `uv run mypy app tests`
- **`uv run ruff format --check .`** — CI runs this and the README's check list omits it; it is the usual cause of a green local run and a red CI
- New migration: `uv run alembic revision --autogenerate -m "message"`
- Seed demo account: `uv run --no-dev python -m app.seed_demo` (idempotent; works locally with `DATABASE_URL` pointed at Neon). Creates `demo@frankly.app` with two months of deterministic data.

Frontend (from `frontend/`):
- Dev: `npm run dev`
- Build / test / lint / format: `npm run build` · `npm run test` · `npm run lint` · `npm run format:check`
- **Typecheck is `npm run build`** (it runs `tsc -b`). Do **not** use `npx tsc --noEmit` — `tsconfig.json` is solution-style (`"files": []` plus references), so that command checks zero files and always exits 0. It is a false green.
