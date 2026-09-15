#!/usr/bin/env bash
set -euo pipefail
# Backup LabWatch Postgres volume or local sqlite file.
# Usage: ./scripts/backup.sh [output-dir]

OUT="${1:-./backups}"
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if command -v docker >/dev/null && docker compose ps db >/dev/null 2>&1; then
  docker compose exec -T db pg_dump -U labwatch labwatch | gzip > "$OUT/labwatch-$STAMP.sql.gz"
  echo "Wrote $OUT/labwatch-$STAMP.sql.gz"
elif [[ -f server/labwatch.db ]]; then
  cp server/labwatch.db "$OUT/labwatch-$STAMP.db"
  echo "Wrote $OUT/labwatch-$STAMP.db"
else
  echo "No running Postgres service or server/labwatch.db found."
  exit 1
fi
