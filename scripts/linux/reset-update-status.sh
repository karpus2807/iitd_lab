#!/bin/sh
# Emergency unlock when Admin → Updates is stuck (queued/running forever).
# Run on the LabWatch host (hobbit), from the repo checkout.
set -eu
REPO="${LABWATCH_REPO_DIR:-}"
if [ -z "$REPO" ]; then
  HERE=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
  REPO=$HERE
fi
DATA="$REPO/data"
mkdir -p "$DATA"
echo "Resetting update status in $DATA"
rm -f "$DATA/update-request.json"
docker rm -f labwatch-apply 2>/dev/null || true
python3 - "$DATA/update-status.json" <<'PY'
import json, sys
from datetime import datetime, timezone
path = sys.argv[1]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
data = {
    "state": "cancelled",
    "tag": None,
    "message": "Reset on host — Updates UI unlocked",
    "updated_at": now,
    "finished_at": now,
    "progress": 0,
    "step": "cancelled",
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
print("Wrote", path)
PY
echo "Done. Refresh Admin → Updates and apply again."
