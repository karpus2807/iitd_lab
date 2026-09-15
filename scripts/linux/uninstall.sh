#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "run as root"; exit 1; fi
systemctl disable --now labwatch-agent || true
rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent
systemctl daemon-reload
rm -rf /opt/labwatch-agent
echo "Uninstalled (config in /etc/labwatch-agent and state in /var/lib/labwatch-agent were kept)."
echo "Remove them manually if desired."
