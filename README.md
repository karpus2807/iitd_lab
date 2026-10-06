# LabWatch

Lab PC monitoring: hardware inventory, live metrics, alerts, history.

Hosts are matched by hardware IDs, not IP. Linux and Windows.

**Live server:** http://hobbit2.cse.iitd.ac.in:8080  
**Latest release:** [v1.1.23](https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.23)

## Agent install (lab PC)

Always use **port 8080**. Port 80 will fail with Connection refused.

```bash
curl -fsSL http://hobbit2.cse.iitd.ac.in:8080/install-agent.sh -o /tmp/labwatch-install.sh
sudo bash /tmp/labwatch-install.sh
```

- Login with a LabWatch **admin** or **operator** account
- Password typing is invisible (no dots)
- On reinstall/update, Enter keeps machine ID and lab
- After enroll, the agent uses its own secret — changing the admin password does **not** disconnect agents

```bash
labwatch-agent status
sudo systemctl status labwatch-agent
```

Remove agent:

```bash
sudo systemctl disable --now labwatch-agent
sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent
sudo rm -rf /opt/labwatch-agent /etc/labwatch-agent /var/lib/labwatch-agent
```

Then **Machines → Remove from LabWatch** on the website.

Windows (admin PowerShell, from this repo):

```powershell
.\scripts\windows\install.ps1 -ServerUrl http://hobbit2.cse.iitd.ac.in:8080 -RegistrationToken <token>
```

## Website

| Page | Use |
| --- | --- |
| Dashboard | fleet counts |
| Machines | search, assign lab, delete |
| Machine | CPU / RAM / GPU / disks / charts / history / events / logs |
| Alerts | open alerts; Resolve / Clear |
| Admin | users (admin only) |

SoC boards (Jetson): unified RAM + on-package GPU. Unsupported DIMM/PCIe fields are hidden.

Roles: `ADMIN`, `OPERATOR`, `VIEWER`.

## Update server (hobbit2)

Postgres volume and `.env` are kept.

```bash
cd ~/iitd_lab
git fetch origin --tags
git checkout -f v1.1.23
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
