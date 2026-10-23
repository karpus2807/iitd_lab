#!/bin/sh
# Apply a LabWatch GitHub tag on the HOST (git fetch/checkout + docker compose).
# Invoked by the privileged helper container (chroot /host) or systemd.
set -eu

TAG="${1:-${LABWATCH_TARGET_TAG:-}}"
REPO="${LABWATCH_REPO_DIR:-}"

if [ -z "$REPO" ]; then
  HERE=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
  REPO=$HERE
fi

DATA="$REPO/data"
mkdir -p "$DATA"
STATUS="$DATA/update-status.json"
LOG="$DATA/update-apply.log"

# write_status <state> <message> [progress 0-100] [step]
write_status() {
  state=$1
  message=$2
  progress=${3:-}
  step=${4:-}
  python3 - "$STATUS" "$state" "$TAG" "$message" "$progress" "$step" <<'PY'
import json, sys
from datetime import datetime, timezone
path, state, tag, message, progress, step = sys.argv[1:7]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
data = {}
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    pass
data.update({"state": state, "tag": tag, "message": message, "updated_at": now})
if progress != "":
    try:
        data["progress"] = int(progress)
    except ValueError:
        pass
if step:
    data["step"] = step
if state in ("ok", "error"):
    data["finished_at"] = now
    if state == "ok":
        data["progress"] = 100
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

if [ -z "$TAG" ] && [ -f "$DATA/update-request.json" ]; then
  TAG=$(python3 -c "import json; print(json.load(open('$DATA/update-request.json'))['tag'])")
fi

if [ -z "$TAG" ]; then
  echo "usage: $0 <tag>" >&2
  exit 2
fi

cd "$REPO"
touch "$LOG"
exec >>"$LOG" 2>&1

echo "===== $(date -u) apply $TAG in $REPO ====="
write_status running "Fetching $TAG from GitHub" 20 fetch

if [ ! -d "$REPO/.git" ]; then
  write_status error "Not a git checkout: $REPO" 0 error
  exit 1
fi

echo ">> git fetch origin --tags --force"
git fetch origin --tags --force
write_status running "Resolving tag $TAG" 35 resolve

if ! git rev-parse "refs/tags/$TAG" >/dev/null 2>&1; then
  write_status error "Unknown git tag $TAG after fetch" 0 error
  exit 1
fi

# Keep untracked runtime files (.env, data/, wheels).
echo ">> git checkout -f refs/tags/$TAG"
git checkout -f "refs/tags/$TAG"
write_status running "Checked out $TAG — rebuilding Docker services" 50 rebuild

if ! command -v docker >/dev/null 2>&1; then
  write_status error "docker not found on PATH" 0 error
  exit 1
fi

echo ">> docker compose up -d --build --pull never"
write_status running "docker compose build/up in progress for $TAG" 60 compose
if docker compose up -d --build --pull never; then
  write_status running "Compose finished — verifying" 90 verify
else
  write_status error "docker compose failed for $TAG (see log)" 0 error
  exit 1
fi

rm -f "$DATA/update-request.json"
write_status ok "Now running $TAG" 100 done
echo "===== $(date -u) done $TAG ====="
