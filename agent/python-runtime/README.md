# Bundled CPython (system Python never changed)

Downloaded by `scripts/linux/prefetch-python-runtime.sh`.

- `linux-x86_64.tgz` / `linux-aarch64.tgz` / `windows-x86_64.tgz`
- Astral python-build-standalone CPython 3.12.10 (tag 20250409)
- Served as `GET /python-runtime.tgz?arch=x86_64|aarch64|windows-x86_64`
- Unpacks under `/opt/labwatch-agent/python` (Linux) or
  `%ProgramFiles%\LabWatch Agent\python` (Windows)

Do not commit `.tgz` files to git. Prefetch on hobbit after deploy.
