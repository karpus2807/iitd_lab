#!/usr/bin/env bash
set -euo pipefail
# Restore LabWatch Postgres dump created by backup.sh
# Usage: ./scripts/restore.sh backups/labwatch-YYYYMMDDTHHMMSSZ.sql.gz

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Usage: $0 <dump.sql.gz>"
  exit 1
fi
gzip -dc "$FILE" | docker compose exec -T db psql -U labwatch -d labwatch
echo "Restore complete. Restart API if needed: docker compose restart api"
