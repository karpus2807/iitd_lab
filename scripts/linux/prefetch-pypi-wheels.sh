#!/usr/bin/env bash
# Download PyPI wheels on the host, retrying when IITD squid drops CONNECT.
# Requires: docker (python:3.12-slim), HTTP(S)_PROXY, a live proxy.cgi session.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ROOT/docker/wheels"
export HTTP_PROXY="${HTTP_PROXY:-http://10.10.78.21:3128/}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://10.10.78.21:3128/}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"

echo "Downloading wheels into $ROOT/docker/wheels (PIP_MAX_WORKERS=1)"
n=0
while true; do
  n=$((n + 1))
  echo "=== attempt $n ==="
  if sudo docker run --rm \
    -e HTTP_PROXY -e HTTPS_PROXY -e NO_PROXY \
    -e http_proxy="$HTTP_PROXY" -e https_proxy="$HTTPS_PROXY" -e no_proxy="$NO_PROXY" \
    -e PIP_MAX_WORKERS=1 \
    -e PIP_DEFAULT_TIMEOUT=180 \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
    -v "$ROOT/server/requirements.txt:/r.txt:ro" \
    -v "$ROOT/docker/wheels:/wheels" \
    -v labwatch-pip-cache:/root/.cache/pip \
    python:3.12-slim \
    pip download -r /r.txt -d /wheels --retries 30 --timeout 180
  then
    echo "Wheels ready. Next: sudo docker compose up -d --build"
    exit 0
  fi
  echo "Proxy CONNECT dropped. Retry in 8s (keep proxy.cgi refresh running)."
  sleep 8
done
