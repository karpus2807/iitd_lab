#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "run as root"; exit 1; fi
systemctl disable --now labwatch-agent || true
rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent
systemctl daemon-reload
rm -rf /opt/labwatch-agent
echo "Uninstalled the agent from this PC."
echo "Config in /etc/labwatch-agent and state in /var/lib/labwatch-agent were kept so a reinstall can reuse the machine ID and lab."
echo "Remove those directories if you want a blank install."
echo "To remove the host from the LabWatch website, open the machine and click Remove from LabWatch."
