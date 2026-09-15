#!/usr/bin/env bash
set -euo pipefail
systemctl status labwatch-agent --no-pager || true
labwatch-agent status 2>/dev/null || true
