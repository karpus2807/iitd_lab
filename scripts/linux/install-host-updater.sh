#!/usr/bin/env bash
# Install a systemd path watcher so Admin → Updates can apply GitHub tags
# even if the API container cannot spawn Docker.
set -euo pipefail
if [[ ${EUID:-0} -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
APPLY="$SCRIPT_DIR/apply-requested-update.sh"
UNIT_DIR=/etc/systemd/system
REQUEST="$REPO/data/update-request.json"

mkdir -p "$REPO/data" /usr/local/lib/labwatch
install -m 0755 "$APPLY" /usr/local/lib/labwatch/apply-requested-update.sh

cat > "$UNIT_DIR/labwatch-updater.service" <<EOF
[Unit]
Description=LabWatch apply GitHub build from Admin UI
After=docker.service network-online.target

[Service]
Type=oneshot
Environment=LABWATCH_REPO_DIR=$REPO
WorkingDirectory=$REPO
ExecStart=/usr/local/lib/labwatch/apply-requested-update.sh
EOF

cat > "$UNIT_DIR/labwatch-updater.path" <<EOF
[Unit]
Description=Watch LabWatch Admin update requests

[Path]
PathModified=$REQUEST
PathChanged=$REQUEST
Unit=labwatch-updater.service

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now labwatch-updater.path
echo "Host updater enabled for $REPO"
echo "Admin GUI: Updates page can now upgrade/downgrade GitHub releases."
