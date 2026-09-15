#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$ROOT/server/labwatch.db}"
export LABWATCH_SECRET_KEY="${LABWATCH_SECRET_KEY:-dev-only-change-me-use-32-bytes-min}"
export ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-adminadmin}"
export PYTHONPATH="$ROOT/server"
cd "$ROOT/server"
exec "$ROOT/.venv/bin/python" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
