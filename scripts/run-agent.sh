#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/agent"
export LABWATCH_CONFIG="${LABWATCH_CONFIG:-$ROOT/agent/config.toml}"
export LABWATCH_STATE_DIR="${LABWATCH_STATE_DIR:-$ROOT/agent/state}"
mkdir -p "$LABWATCH_STATE_DIR"
exec "$ROOT/.venv/bin/python" -m labwatch_agent "$@"
