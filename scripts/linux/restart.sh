#!/usr/bin/env bash
set -euo pipefail
systemctl restart labwatch-agent
echo "restarted"
