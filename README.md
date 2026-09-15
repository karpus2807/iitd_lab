# LabWatch — Lab Hardware Monitoring & Asset Management

LabWatch is a production-oriented system for institute and university computer labs. It combines **asset inventory**, **hardware-change detection**, and **live monitoring** for hundreds of Linux and Windows machines.

It is not a toy CPU/RAM graph. Each host is tracked as a durable asset with RAM slot topology, GPU identity, storage serials, motherboard/BIOS data, historical snapshots, and an audit trail.

## Architecture

```
Client agent (Linux / Windows service)
        |  HTTPS + per-agent credentials + heartbeat
        v
Central API (FastAPI) ── PostgreSQL
        |
        +-- inventory snapshots + hardware diff engine
        +-- metrics + retention
        +-- alert + notification channels
        +-- audit logs
        v
Nginx  →  React dashboard
```

Machine identity is **not** the IP address. The server stores its own machine ID and matches returning hosts using system UUID, motherboard/system serials, and a persistent agent UUID. DHCP address changes do not create a new asset.

Online/offline state is determined by an **authenticated heartbeat**, not ICMP ping.

Statuses:

| Status | Meaning |
| --- | --- |
| ONLINE | Heartbeat within the configured threshold |
| OFFLINE | Heartbeat missed beyond threshold |
| NEVER_CONNECTED | Registered but no heartbeat yet |
| AGENT_UNHEALTHY | Heartbeat present but agent reports degraded collectors |

## Repository layout

```
server/      FastAPI application, Alembic, tests
agent/       Python monitoring agent (Linux + Windows)
frontend/    React + TypeScript dashboard
docker/      API, web, and Nginx Dockerfiles
scripts/     Linux/Windows installers, backup/restore, local runners
docs/        Extra operational guides
```

## Requirements

- Server: Docker with Compose **or** Python 3.10+ and PostgreSQL 14+
- Dashboard build: Node.js 20+
- Agent: Python 3.10+ on each client
- Linux inventory extras (optional but recommended): `dmidecode`, `lsblk`, `lspci`, `smartctl`, `nvidia-smi`
- Windows inventory: PowerShell / CIM (built-in). `nvidia-smi` for NVIDIA telemetry

## Server setup (Docker)

```bash
cp .env.example .env
# set LABWATCH_SECRET_KEY, ADMIN_PASSWORD, and SMTP settings
docker compose up -d --build
```

Services:

- `db` — PostgreSQL 16
- `api` — FastAPI on the internal network
- `web` — Nginx serving the dashboard and proxying `/api`

Open `http://<server>/`. Default admin comes from `.env` (`ADMIN_USERNAME` / `ADMIN_PASSWORD`) and is created only when the user table is empty.

API documentation: `http://<server>/api/docs`

### Server updates (GitHub)

Admins get an **Updates** page that lists the last 3 GitHub releases, marks **Current** vs **Latest**, and can update or downgrade to a selected tag.

Compose bind-mounts the git checkout and Docker socket so Apply can `git checkout` that release and rebuild. On first boot also run:

```bash
sudo ./scripts/linux/install-host-updater.sh
```

That systemd watcher applies the same request if the API container cannot spawn Docker. `.env` is gitignored and is never overwritten.

### Database / migrations

Tables are created on API startup. Alembic is also provided:

```bash
cd server
alembic upgrade head
```

The initial revision uses SQLAlchemy metadata so PostgreSQL and SQLite stay aligned.

### Local development without Docker

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
cp .env.example .env
./scripts/run-api.sh
cd frontend && npm install && npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## Agent installation

Create a registration token in **Admin → tokens**. Each lab can have its own token. Tokens are hashed at rest; the plaintext is shown **once**.

### Linux

```bash
sudo ./scripts/linux/install.sh https://labwatch.example.edu lw_your_token
```

That installs a systemd unit `labwatch-agent` which starts on boot.

| Command | Action |
| --- | --- |
| `sudo ./scripts/linux/start.sh` | start |
| `sudo ./scripts/linux/stop.sh` | stop |
| `sudo ./scripts/linux/restart.sh` | restart |
| `sudo ./scripts/linux/status.sh` | status |
| `sudo ./scripts/linux/uninstall.sh` | remove unit and files |
| `labwatch-agent once` | print a one-shot inventory |
| `labwatch-agent status` | enrollment status |

Config: `/etc/labwatch-agent/config.toml`  
State / credentials: `/var/lib/labwatch-agent/state.toml` (mode 0600)

### Windows

Run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\scripts\windows\install.ps1 -ServerUrl https://labwatch.example.edu -RegistrationToken lw_your_token
```

A scheduled task named `LabWatchAgent` runs as SYSTEM at startup.

Companion scripts: `start.ps1`, `stop.ps1`, `restart.ps1`, `status.ps1`, `uninstall.ps1`.

Config: `C:\ProgramData\LabWatch\config.toml`

### Agent registration

1. Admin creates a registration token (optionally bound to a lab).
2. Agent config contains `SERVER_URL` and `REGISTRATION_TOKEN`.
3. `POST /api/agents/register` returns `machine_id`, `agent_id`, and a unique `agent_secret`.
4. The secret is stored locally and sent as `Authorization: Bearer <agent_id>:<agent_secret>`.
5. Subsequent heartbeat / inventory / metrics / events use that credential.

If the same system UUID / motherboard serial returns later, the server reuses the existing machine row (IP changes do not fork the asset). Revoked agents are rejected until an administrator re-approves or rotates credentials.

### Configuration

See `agent/config.toml.example`. Environment variables override the file:

`SERVER_URL`, `REGISTRATION_TOKEN`, `AGENT_ID`, `HEARTBEAT_INTERVAL`, `METRIC_INTERVAL`, `INVENTORY_INTERVAL`, `LOG_LEVEL`, `TLS_VERIFY`, `TLS_CA_FILE`, `LABWATCH_CONFIG`, `LABWATCH_STATE_DIR`.

Defaults are chosen for hundreds of hosts (30s heartbeat and metrics, 5 minute inventory) with client-side jitter to avoid stampedes.

If the server is unreachable the agent keeps collecting and buffers events/logs in a local SQLite queue, then drains the queue with backoff when connectivity returns.

## Dashboard usage

- **Dashboard** — counts, labs, recent hardware changes
- **Machines** — search and filter by lab, status, OS, GPU, alerts
- **Machine page** — overview, CPU, RAM slots, GPUs, storage, network, motherboard/BIOS, history, charts, events, logs
- **Labs** — create / rename; move a machine from its overview page
- **Alerts** — acknowledge / resolve
- **Admin** (ADMIN role) — users, tokens, agent approve/revoke/rotate, alert thresholds, audit log

Roles: `ADMIN`, `OPERATOR`, `VIEWER`.

Time ranges for graphs: 1h, 6h, 24h, 7d, 30d. Ranges longer than 7 days read hourly aggregates.

## Hardware detection

Collectors **never invent** topology. If firmware/OS does not expose a value, the UI shows `Unknown / Not reported`.

RAM:

- Linux: `dmidecode -t memory` (slot locators, empty slots, max capacity)
- Windows: `Win32_PhysicalMemory` + `Win32_PhysicalMemoryArray`
- Usage still comes from the OS even when DIMM maps are hidden
- Empty slots without locators are counted, not fabricated as fake slot names

GPU:

- NVIDIA: `nvidia-smi` for model, VRAM, util, temp, power, clocks, driver, PCI, serial/UUID
- Other vendors: PCI / Win32_VideoController identity without fake telemetry
- Physical PCIe slot maps come from SMBIOS System Slot records when present
- The system does **not** treat every x16 slot as GPU-capable

Virtual machines are flagged from DMI/hypervisor bits. Virtual DIMM/PCIe layouts are not presented as physical motherboard truth.

The **hardware diff engine** compares successive snapshots and emits durable events such as `RAM_REMOVED`, `GPU_CHANGED`, `DISK_ADDED`. Duplicate ONLINE/OFFLINE storms are suppressed.

## Security

- User passwords: bcrypt
- Agent secrets and registration tokens: SHA-256 at rest, constant-time compare (high-entropy tokens; bcrypt is intentionally not used on the heartbeat path)
- JWT access tokens for the dashboard
- Per-agent credentials; a stolen token can be revoked or rotated
- TLS-ready: put certificates on Nginx and set `tls.verify` / `ca_file` on agents
- Secrets are not written to application logs
- Audit log for login, user changes, token/agent lifecycle, alert actions

## Backup / restore

```bash
./scripts/backup.sh ./backups
./scripts/restore.sh ./backups/labwatch-YYYYMMDDTHHMMSSZ.sql.gz
```

Hardware snapshots, hardware-change events, and (by default) audit logs are retained permanently. Raw metrics default to 30 days; hourly rollups default to 365 days (`METRICS_RAW_RETENTION_DAYS`, `METRICS_HOURLY_RETENTION_DAYS`).

## Upgrade

```bash
git pull
docker compose build
docker compose up -d
cd server && alembic upgrade head   # when a new revision exists
```

Then roll the agent package to clients (`install.sh` / `install.ps1` again, or copy `labwatch_agent` and restart the service). Agents are backward compatible as long as the REST contract is unchanged.

## Tests

```bash
cd server && ../.venv/bin/python -m pytest
cd agent && ../.venv/bin/python -m pytest
```

Covered: authentication, agent register/heartbeat/inventory, RAM/GPU add/remove, disk changes, identity stability across re-register, alert open/resolve, offline event de-duplication, dmidecode/nvidia parsers.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md).

## License

Internal institute use unless you add a license file.
