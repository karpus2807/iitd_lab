# LabWatch

Monitor lab PCs from one website: hardware, live stats, alerts, and history.

Linux and Windows. A machine is identified by hardware IDs, not its IP. DHCP changes do not create a new host.

**Server:** [hobbit2.cse.iitd.ac.in](http://hobbit2.cse.iitd.ac.in)

## Install an agent (lab PC)

```bash
curl -fsSL http://hobbit2.cse.iitd.ac.in/install-agent.sh -o /tmp/labwatch-install.sh
sudo bash /tmp/labwatch-install.sh
```

Sign in with a LabWatch admin/operator account. Enter keeps the old machine ID and lab on reinstall or update.

Password typing is invisible. If `curl | sudo bash` looks stuck, use the two-line form above.

```bash
labwatch-agent status
sudo systemctl status labwatch-agent
```

Remove the agent:

```bash
sudo systemctl disable --now labwatch-agent
sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent
sudo rm -rf /opt/labwatch-agent /etc/labwatch-agent /var/lib/labwatch-agent
```

Then delete the host in **Machines → Remove from LabWatch**.

Windows (admin PowerShell), from this repo:

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\scripts\windows\install.ps1 -ServerUrl http://hobbit2.cse.iitd.ac.in -RegistrationToken <token>
```

## Use the site

Sign in at `http://hobbit2.cse.iitd.ac.in`.

| Page | What it shows |
| --- | --- |
| Dashboard | counts and recent hardware changes |
| Machines | list, search, assign lab, delete |
| Machine | CPU, RAM, GPU, disks, charts, history, events, logs |
| Alerts | open issues; Resolve / Clear |
| Admin | users (admin only) |

SoC boards (Jetson) show soldered RAM and an on-package GPU. DIMM/PCIe fields that do not exist are hidden.

Roles: `ADMIN`, `OPERATOR`, `VIEWER`.

## Update the server

Postgres data stays in Docker. `.env` is not in git.

```bash
cd ~/iitd_lab
git fetch origin --tags
git checkout -f v1.1.21
sudo docker compose up -d --force-recreate --no-deps api web
curl -sS http://127.0.0.1/health
```

Then refresh the browser (`Ctrl+Shift+R`). Recreate **api** for the installer/agent pack; **web** for the UI.

## First-time server install

```bash
cp .env.example .env   # set LABWATCH_SECRET_KEY and ADMIN_PASSWORD
docker compose up -d --build
```

Open `http://<server>/`. API docs: `/api/docs`. Health: `/health`.

If login is **Bad Gateway**, the UI is up but `api` is not: `sudo docker compose logs api --tail 80`.

Local run without Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
cp .env.example .env
./scripts/run-api.sh
cd frontend && npm install && npm run dev
```

## Layout

```
server/     API
agent/      Linux + Windows agent (Python 3.8+)
frontend/   dashboard
docker/     containers + static UI
scripts/    installers
docs/       extra notes
```

Linux extras (optional): `dmidecode`, `lspci`, `lsblk`, `smartctl`, `nvidia-smi`.

## Backup

```bash
./scripts/backup.sh ./backups
./scripts/restore.sh ./backups/<file>.sql.gz
```

## Tests

```bash
cd server && ../.venv/bin/python -m pytest
cd agent && PYTHONPATH=. ../.venv/bin/python -m pytest
```

## More

- [Troubleshooting](docs/troubleshooting.md)
- [Hardware sources](docs/hardware.md)
