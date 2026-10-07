# LabWatch

Lab PC monitoring: hardware inventory, live metrics, alerts, history.

Hosts are matched by hardware IDs, not IP. Linux and Windows.

**Live server:** http://hobbit2.cse.iitd.ac.in:8080  
**Latest release:** [v1.1.33](https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.33)

## Agent install (lab PC)

In the portal: **Install** (copy-paste commands). Always use **port 8080**. Commands do not pin a version number.

**Linux**

```bash
curl -fsSL http://hobbit2.cse.iitd.ac.in:8080/install-agent.sh -o /tmp/labwatch-install.sh
sudo bash /tmp/labwatch-install.sh
```

**Windows 10 / 11 — primary (LabWatch / hobbit2)** — Admin PowerShell, one command at a time. Do not paste `PS C:\…>` or `>>`. Best for lab PCs with campus proxy.

```powershell
Remove-Item $env:TEMP\labwatch-install.ps1 -ErrorAction SilentlyContinue
```

```powershell
Invoke-WebRequest -Uri http://hobbit2.cse.iitd.ac.in:8080/install-agent.ps1 -OutFile $env:TEMP\labwatch-install.ps1
```

```powershell
Get-Content $env:TEMP\labwatch-install.ps1 -TotalCount 3
```

```powershell
Select-String -Path $env:TEMP\labwatch-install.ps1 -Pattern "ConvertTo-ObjectArray|agent-pack.tgz" | Select-Object -First 5
```

```powershell
powershell -ExecutionPolicy Bypass -File $env:TEMP\labwatch-install.ps1
```

Agent pack comes from the same server (`/agent-pack.tgz`). Login → machine ID → lab number.

**Windows — optional GitHub** (only if GitHub works; always latest release):

```powershell
Invoke-WebRequest -Uri https://github.com/karpus2807/iitd_lab/releases/latest/download/install-agent.ps1 -OutFile $env:TEMP\labwatch-install.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File $env:TEMP\labwatch-install.ps1 -FromGitHub
```

- Login with a LabWatch **admin** or **operator** account (not SSH)
- Password typing is invisible
- Enter keeps machine ID and lab on reinstall
- After enroll, the agent secret is independent of the website password

```bash
labwatch-agent status
sudo systemctl status labwatch-agent
```

### Uninstall (Linux) — one command at a time

```bash
sudo systemctl disable --now labwatch-agent
```

```bash
sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo rm -rf /opt/labwatch-agent
```

```bash
sudo rm -rf /etc/labwatch-agent /var/lib/labwatch-agent
```

(Last line optional — wipes saved machine ID / lab.)

### Uninstall (Windows) — Admin PowerShell, one at a time

```powershell
Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
```

```powershell
Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue
```

```powershell
Remove-Item -Recurse -Force "$env:ProgramFiles\LabWatch Agent" -ErrorAction SilentlyContinue
```

```powershell
Remove-Item -Recurse -Force "$env:ProgramData\LabWatch" -ErrorAction SilentlyContinue
```

(Last line optional — wipes saved machine ID / lab.)

Then on the website: machine page → **Remove from LabWatch**.

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
git checkout -f v1.1.33
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
