#!/usr/bin/env bash
# =============================================================================
# Olympus Engine v9 — Quick start (development)
# =============================================================================
# Builds and starts the dev stack. Reads `.env` (copy from `.env.example`).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# --- helpers ----------------------------------------------------------------

log()  { printf '\033[1;34m[dev-start]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dev-start]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[dev-start]\033[0m %s\n' "$*" >&2; exit 1; }

require() {
    command -v "$1" >/dev/null 2>&1 || err "$1 is required but not installed"
}

require docker
require curl

# --- .env -------------------------------------------------------------------

if [ ! -f .env ]; then
    log "creating .env from .env.example"
    cp .env.example .env
fi

# --- docker compose ---------------------------------------------------------

COMPOSE="docker compose"

$COMPOSE --version >/dev/null 2>&1 || err "docker compose is not available"

log "pulling base images"
$COMPOSE pull --ignore-pull-failures || warn "some images could not be pulled (offline?)"

log "building backend + frontend"
$COMPOSE build backend frontend

log "starting core stack (postgres, pgbouncer, redis, sentinel, backend, frontend, openresty)"
$COMPOSE up -d postgres pgbouncer redis redis-sentinel backend frontend openresty

log "waiting for backend to be ready…"
for i in $(seq 1 60); do
    if curl -fsS http://localhost:8000/api/v1/ready >/dev/null 2>&1; then
        log "backend is ready (after ${i}s)"
        break
    fi
    sleep 1
done

if ! curl -fsS http://localhost:8000/api/v1/ready >/dev/null 2>&1; then
    err "backend did not become ready in 60s; check 'docker compose logs backend'"
fi

# --- summary ----------------------------------------------------------------

cat <<EOF

\033[1;32m=========================================\033[0m
\033[1;32m Olympus Engine v9 — dev stack is up\033[0m
\033[1;32m=========================================\033[0m

  Frontend:    http://localhost:8080
  Backend:     http://localhost:8000
  OpenResty:   http://localhost:80  (HTTPS on 443 — dev certs)
  PostgreSQL:  localhost:5432  (user/pass: olympus/olympus)
  PgBouncer:   localhost:6432
  Redis:       localhost:6379
  Sentinel:    localhost:26379

  Health:  curl http://localhost:8000/api/v1/health
  Ready:   curl http://localhost:8000/api/v1/ready
  Docs:    http://localhost:8000/docs

  Tail logs:   docker compose logs -f
  Stop:        docker compose down
  Reset:       docker compose down -v

EOF

log "done"
