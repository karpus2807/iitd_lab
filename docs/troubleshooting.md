# Troubleshooting

## API will not start

- Check `DATABASE_URL`. For Docker it must point at service `db`.
- `LABWATCH_SECRET_KEY` must be at least 32 bytes for production JWT.
- Logs: `docker compose logs -f api`

## Dashboard shows 401 / empty data

- Sign in again; access tokens expire (default 8 hours).
- Confirm Nginx `/api/` proxies to the API container.
- CORS is only needed for a separately hosted frontend. The bundled Nginx origin is same-host.

## Agent stays NEVER_CONNECTED

- `labwatch-agent status` (Linux) or `scripts/windows/status.ps1`
- Confirm `server.url` is reachable from the client (`curl https://server/health`)
- Registration token expired, exhausted, or revoked
- Clock skew is rarely an issue; heartbeats use server time

## Agent is ONLINE but RAM slots are unknown

This is expected without SMBIOS access.

Linux: install `dmidecode` and run the agent as root/systemd so it can read DMI.  
Windows: WMI must be healthy; empty slots often lack locators — LabWatch will still show occupied modules and a derived free count when `MemoryDevices` is present.

Never treat missing DMI as “1 slot” or “max RAM = installed RAM”.

## NVIDIA temperature/power missing

`nvidia-smi` must be on `PATH` (or default NVSMI directory on Windows). Without it, the GPU still appears from PCI/WMI with metrics marked unknown.

## PCIe GPU slot map empty

Most laptops and many desktops do not expose System Slot records. The UI will say **Physical slot topology not exposed by firmware/OS** and still list GPUs from PCI. x16 width is **not** used as proof the slot is GPU-capable.

## Duplicate machines after disk clone

Cloned images share system UUID. Either:

- Generate a new agent UUID / clear `state.toml` on the clone, or
- Revoke the old agent and let an administrator approve the new host after changing SMBIOS UUID if the firmware allows it.

## Machine marked OFFLINE while it is running

- Process not running (`systemctl status labwatch-agent`)
- Host can reach the internet but not the monitoring server
- `OFFLINE_AFTER_SECONDS` shorter than agent interval plus jitter (keep ≥ 3× heartbeat)

Offline events are not repeated until the host has been ONLINE again.

## Email notifications not sent

`SMTP_ENABLED=true` and valid `SMTP_*` settings are required. Dashboard notifications still work with SMTP off. Channels are pluggable; webhook URL is configured under Admin notification settings.

## Disk growth from metrics

Lower `METRIC_INTERVAL`, shorten `METRICS_RAW_RETENTION_DAYS`, or confirm the hourly rollup loop is running (API logs `retention`). Hardware snapshots are permanent by design.

## Permission denied on Linux collectors

The agent continues with partial inventory. `dmidecode` and `smartctl` typically need root. systemd unit runs as root by default.

## Windows scheduled task not starting

Task `LabWatchAgent` must exist, run as SYSTEM, and point at `venv\Scripts\python.exe`. Execution policy does not apply to that interpreter. Check Task Scheduler history and `%ProgramData%\LabWatch`.

## Upgrade left API on old schema

Run `alembic upgrade head` inside the API container / `server` directory. The current baseline also calls `create_all` on startup for empty databases.
