# Bundled CPython for any host Python

LabWatch agent needs CPython **3.10+** for its wheels. The **host default Python is never changed**.

- Host may have Python 2, 3.5–3.9, 3.10+, or none.
- Linux installer downloads this standalone CPython 3.12 into `/opt/labwatch-agent/python` only.
- It does **not** run `update-alternatives`, does **not** replace `/usr/bin/python3`, and does **not** alter the user’s default `python` / `python3`.

## Prefetch (LabWatch server / hobbit)

```bash
./scripts/linux/prefetch-python-runtime.sh
sudo docker compose up -d --force-recreate --no-deps api
```

Creates (gitignored): `linux-x86_64.tgz`, `linux-aarch64.tgz`  
Served as `GET /python-runtime.tgz?arch=x86_64|aarch64`.
