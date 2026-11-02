# Bundled CPython for old lab OS

Downloaded by `scripts/linux/prefetch-python-runtime.sh`.

- `linux-x86_64.tgz` / `linux-aarch64.tgz` — Astral python-build-standalone
  CPython 3.12.10 (tag 20250409), install_only_stripped.
- Served as `GET /python-runtime.tgz?arch=x86_64|aarch64`.
- Installer unpacks to `/opt/labwatch-agent/python` when the host has no Python 3.8+.

Do not commit these `.tgz` files to git (large binaries). Prefetch on hobbit after deploy.
