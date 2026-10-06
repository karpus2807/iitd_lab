# Troubleshooting

## Windows install downloads HTML (`<!doctype html>`)

nginx was falling through to the website. Update to **v1.1.28+** and recreate **web**. Verify:

```powershell
(Get-Content $env:TEMP\labwatch-install.ps1 -TotalCount 2)
# must start with #Requires or # LabWatch — not <!doctype html>
```

## Connection refused on agent install

LabWatch listens on **8080**, not 80. Re-download the script:

```bash
curl -fsSL http://hobbit2.cse.iitd.ac.in:8080/install-agent.sh -o /tmp/labwatch-install.sh
sudo bash /tmp/labwatch-install.sh
```

The login line must show `…:8080`.

## Login is Bad Gateway

UI is up; API is down.

```bash
cd ~/iitd_lab
sudo docker compose ps
sudo docker compose logs api --tail 80
curl -sS http://127.0.0.1:8080/health
sudo docker compose up -d --force-recreate --no-deps api
```

`.env`: `NO_PROXY` must include `db`.

## Install looks stuck after username

It is waiting for the **password** (nothing is printed). Type it and press Enter.

## Admin password changed — agents still OK?

Yes. Agents use `agent_id` + `agent_secret` after enroll. Admin login is only for the website and new installs.

## UI / installer not updating after git checkout

```bash
sudo docker compose up -d --force-recreate --no-deps api web
```

Then hard-refresh the browser (`Ctrl+Shift+R`).

## Campus proxy / Docker build

Keep `iitd-proxy` logged in. Prefetch wheels if needed:

```bash
./scripts/linux/prefetch-pypi-wheels.sh
sudo docker compose up -d --build
```

API needs `greenlet` (in `server/requirements.txt`).

## Agent NEVER_CONNECTED / enrolled=no

```bash
labwatch-agent status
curl -sS http://hobbit2.cse.iitd.ac.in:8080/health
sudo journalctl -u labwatch-agent -n 50 --no-pager
```

Check `server.url` includes `:8080` and hobbit is reachable (set `NO_PROXY` for the hostname if needed).

## Empty RAM / GPU fields

Install `dmidecode` / `lspci` / `smartctl` as needed. Jetson has no DIMM/PCIe map — that is expected; the UI hides those fields.

## Cloned disk → duplicate host

Wipe `/var/lib/labwatch-agent` on the clone, or remove the old host in the UI and reinstall.

## Online PC shows OFFLINE

Agent not running, or PC cannot reach `:8080`. Offline timeout should be ≥ 3× heartbeat (default 30s).
