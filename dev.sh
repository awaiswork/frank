#!/usr/bin/env bash
#
# Start Frankly's whole local dev stack with one command: Postgres, the FastAPI
# backend, and the Vite frontend. Ctrl-C stops the backend and frontend; the db
# container is left running (stop it with `docker compose down`).
#
# Usage: ./dev.sh
#
# Ports default to 8000 (backend) and 5173 (frontend); override either with:
#   API_PORT=8001 WEB_PORT=5174 ./dev.sh
# The two are threaded through to CORS (FRONTEND_ORIGIN) and the frontend's
# VITE_API_URL, so they stay in sync without editing any .env. Process env wins
# over .env in both pydantic-settings and Vite, so those overrides take effect.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

api_pid=""
web_pid=""

log() { printf '\033[1;35m→\033[0m %s\n' "$1"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$1" >&2; exit 1; }

cleanup() {
  trap - INT TERM EXIT
  printf '\n'
  log "shutting down…"
  # Kill the reloader children too — uvicorn --reload and vite both fork.
  for pid in "$api_pid" "$web_pid"; do
    if [ -n "$pid" ]; then
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  log "stopped. Postgres is still up — \`docker compose down\` to stop it too."
}
trap cleanup INT TERM EXIT

port_busy() { lsof -iTCP:"$1" -sTCP:LISTEN -n -P >/dev/null 2>&1; }

# --- preflight -------------------------------------------------------------
port_busy "$API_PORT" && die "port $API_PORT is in use. Free it, or: API_PORT=$((API_PORT + 1)) ./dev.sh"
port_busy "$WEB_PORT" && die "port $WEB_PORT is in use. Free it, or: WEB_PORT=$((WEB_PORT + 1)) ./dev.sh"

command -v uv >/dev/null || die "uv is not installed: https://docs.astral.sh/uv/"
command -v npm >/dev/null || die "npm is not installed (need Node 22+)."
docker info >/dev/null 2>&1 || die "the Docker daemon isn't responding — start Docker Desktop."

[ -f backend/.env ] || { log "creating backend/.env from .env.example"; cp backend/.env.example backend/.env; }
[ -f frontend/.env ] || { log "creating frontend/.env from .env.example"; cp frontend/.env.example frontend/.env; }

# --- database --------------------------------------------------------------
log "starting Postgres on host port 5433…"
docker compose up -d --wait db

# --- backend ---------------------------------------------------------------
log "syncing backend deps…"
(cd backend && uv sync --quiet)

log "applying migrations…"
(cd backend && uv run alembic upgrade head)

# --- frontend deps ---------------------------------------------------------
if [ ! -d frontend/node_modules ]; then
  log "installing frontend deps…"
  (cd frontend && npm install)
fi

# --- serve -----------------------------------------------------------------
# Keep CORS and the frontend's API base pointed at whatever ports we settled on.
export FRONTEND_ORIGIN="http://localhost:$WEB_PORT"
export VITE_API_URL="http://localhost:$API_PORT"

log "starting backend  → http://localhost:$API_PORT"
(cd backend && exec uv run uvicorn app.main:app --reload --port "$API_PORT") \
  > >(sed $'s/^/\033[36m[api]\033[0m /') 2>&1 &
api_pid=$!

log "starting frontend → http://localhost:$WEB_PORT"
# --strictPort so Vite fails loudly instead of silently drifting to another port,
# which would leave it on an origin the backend's CORS doesn't allow.
(cd frontend && exec npm run dev -- --port "$WEB_PORT" --strictPort) \
  > >(sed $'s/^/\033[32m[web]\033[0m /') 2>&1 &
web_pid=$!

printf '\n'
log "Frankly is up. Ctrl-C to stop."
printf '\n'

# Exit as soon as either server dies, so a crash doesn't leave a half-up stack.
# (A poll rather than `wait -n`, which macOS's stock bash 3.2 doesn't have.)
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
log "a server exited — tearing down the rest."
