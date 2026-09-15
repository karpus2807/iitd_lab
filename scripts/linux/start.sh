#!/usr/bin/env bash
set -euo pipefail
systemctl start labwatch-agent
systemctl --no-pager --full status labwatch-agent || true
