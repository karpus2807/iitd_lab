#!/usr/bin/env bash
# Prefetch agent pip wheels onto the LabWatch server (hobbit) so lab installs
# never need campus proxy / PyPI. Output: agent/wheels/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/agent/wheels"
REQ="$ROOT/agent/requirements.txt"
mkdir -p "$DEST"

export HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}"
export HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-}}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY"

PIP="$(command -v pip3 || command -v pip || true)"
if [[ -x "$ROOT/.venv/bin/pip" ]]; then
  PIP="$ROOT/.venv/bin/pip"
fi
if [[ -z "$PIP" ]]; then
  echo "pip not found" >&2
  exit 1
fi

echo "Downloading agent wheels into $DEST"
download() {
  local plat="$1" py="$2" abi="$3"
  echo "=== $plat py$py $abi ==="
  "$PIP" download -r "$REQ" -d "$DEST" \
    --platform "$plat" --python-version "$py" --implementation cp --abi "$abi" \
    --only-binary=:all: || echo "WARN: failed $plat py$py (continuing)"
}

for py_abi in 38:cp38 39:cp39 310:cp310 311:cp311 312:cp312 313:cp313 314:cp314; do
  py="${py_abi%%:*}"
  abi="${py_abi##*:}"
  download manylinux2014_x86_64 "$py" "$abi"
  download manylinux2014_aarch64 "$py" "$abi"
  download win_amd64 "$py" "$abi"
done

"$PIP" download pip setuptools wheel tomli exceptiongroup "pysqlite3-binary>=0.5.4" -d "$DEST" || true
"$PIP" download -r "$REQ" -d "$DEST" --only-binary=:all: || true

if [[ ! -f "$DEST/get-pip.py" ]]; then
  echo "Fetching get-pip.py for offline venv bootstrap"
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$DEST/get-pip.py"
fi

# Drop accidental host-only oddballs that confuse older pip resolvers.
rm -f "$DEST"/tomli-*-cp314-*.whl 2>/dev/null || true

count="$(find "$DEST" -maxdepth 1 \( -name '*.whl' -o -name 'get-pip.py' \) | wc -l)"
size="$(du -sh "$DEST" | awk '{print $1}')"
echo "Ready: $count files ($size) in $DEST"
echo "Lab installs use these via /agent-pack.tgz (no PyPI / no campus proxy)."
