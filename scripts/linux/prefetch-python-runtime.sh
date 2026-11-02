#!/usr/bin/env bash
# Prefetch Astral python-build-standalone (install_only_stripped) for lab PCs
# that ship only Python 2 / 3.5–3.7 (e.g. Ubuntu 16.04 / 18.04).
# Run on the LabWatch server (hobbit), then recreate api so /python-runtime.tgz works.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/agent/python-runtime"
TAG="${LABWATCH_PBS_TAG:-20250409}"
PY_VER="${LABWATCH_PBS_PY:-3.12.10}"
BASE="https://github.com/astral-sh/python-build-standalone/releases/download/${TAG}"

mkdir -p "$OUT"
cd "$OUT"

_fetch() {
  local arch="$1" triple="$2" dest="$3"
  local name="cpython-${PY_VER}+${TAG}-${triple}-install_only_stripped.tar.gz"
  local url="${BASE}/${name}"
  echo "Fetching ${arch} → ${dest}"
  if command -v curl >/dev/null; then
    curl -fL --retry 3 --retry-delay 2 -o "${dest}.partial" "$url"
  else
    wget -O "${dest}.partial" "$url"
  fi
  mv -f "${dest}.partial" "$dest"
  ls -lh "$dest"
}

# Ubuntu 16.04+ x86_64 (glibc 2.23 ≥ manylinux2014 / PBS gnu builds)
_fetch x86_64 "x86_64-unknown-linux-gnu" "linux-x86_64.tgz"
# aarch64 lab boards / Jetson-class hosts on newer Ubuntu; still useful
_fetch aarch64 "aarch64-unknown-linux-gnu" "linux-aarch64.tgz" || {
  echo "WARN: aarch64 runtime fetch failed (optional)."
  rm -f linux-aarch64.tgz.partial
}

cat > README.md <<EOF
# Bundled CPython for old lab OS

Downloaded by \`scripts/linux/prefetch-python-runtime.sh\`.

- \`linux-x86_64.tgz\` / \`linux-aarch64.tgz\` — Astral python-build-standalone
  CPython ${PY_VER} (tag ${TAG}), install_only_stripped.
- Served as \`GET /python-runtime.tgz?arch=x86_64|aarch64\`.
- Installer unpacks to \`/opt/labwatch-agent/python\` when the host has no Python 3.8+.

Do not commit these \`.tgz\` files to git (large binaries). Prefetch on hobbit after deploy.
EOF

echo "Done. Recreate api: sudo docker compose up -d --force-recreate --no-deps api"
