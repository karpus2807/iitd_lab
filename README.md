# LabWatch

Lab PC monitoring: hardware inventory, live metrics, alerts, history.

Hosts are matched by hardware IDs, not IP. Linux and Windows.

**Live server:** http://hobbit2.cse.iitd.ac.in:8080  
**Latest release:** [v1.1.25](https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.25)

## Agent install (lab PC)

In the portal: **Install** (copy-paste commands). Always use **port 8080**.

**Linux**

```bash
curl -fsSL http://hobbit2.cse.iitd.ac.in:8080/install-agent.sh -o /tmp/labwatch-install.sh
sudo bash /tmp/labwatch-install.sh
```

**Windows** (Admin PowerShell, Python 3.8+ on PATH)

```powershell
irm http://hobbit2.cse.iitd.ac.in:8080/install-agent.ps1 | iex
```

- Login with a LabWatch **admin** or **operator** account (not SSH)
- Password typing is invisible
- Enter keeps machine ID and lab on reinstall
- After enroll, the agent secret is independent of the website password

```bash
labwatch-agent status
sudo systemctl status labwatch-agent
```

## Website

| Page | Use |
| --- | --- |
| Dashboard | fleet counts |
| Machines | search, assign lab, delete |
| Machine | CPU / RAM / GPU / disks / charts / history / events / logs |
| Alerts | open alerts; Resolve / Clear |
| Install | Linux / Windows agent commands |
| Admin | users (admin only) |

SoC boards (Jetson): unified RAM + on-package GPU. Unsupported DIMM/PCIe fields are hidden.

Roles: `ADMIN`, `OPERATOR`, `VIEWER`.

## Update server (hobbit2)

Postgres volume and `.env` are kept.

```bash
cd ~/iitd_lab
git fetch origin --tags
git checkout -f v1.1.25
sudo docker compose up -d --force-recreate --no-deps api web
curl -sS http://127.0.0.1:8080/health
```

Hard-refresh the browser. Recreate **api** for installer/agent pack; **web** for UI.

`LABWATCH_PUBLIC_URL` in `.env` must be `http://hobbit2.cse.iitd.ac.in:8080`.

## First-time server

```bash
cp .env.example .env   # SECRET_KEY, ADMIN_PASSWORD, PUBLIC_URL=:8080
docker compose up -d --build
```

Compose maps host **8080 →** nginx. Health: `http://127.0.0.1:8080/health`.

## Layout

```
server/     FastAPI
agent/      Python agent (3.8+)
frontend/   React UI → docker/web-static
scripts/    installers
docs/       troubleshooting, hardware
```

Optional Linux tools: `dmidecode`, `lspci`, `lsblk`, `smartctl`, `nvidia-smi`.

## Backup / tests

```bash
./scripts/backup.sh ./backups
cd server && ../.venv/bin/python -m pytest
cd agent && PYTHONPATH=. ../.venv/bin/python -m pytest
```

## Docs

- [Troubleshooting](docs/troubleshooting.md)
- [Hardware](docs/hardware.md)
