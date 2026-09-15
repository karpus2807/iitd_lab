# Troubleshooting

## Login shows Bad Gateway

The login form is static Nginx. Password submit calls `/api/auth/login`. **502** means Nginx cannot reach the API container (`api` is restarting, crashed, or still installing packages).

```bash
cd ~/iitd_lab
sudo docker compose ps
sudo docker compose logs api --tail 80
curl -sS http://127.0.0.1/health
```

`health` must return `{"status":"ok",...}`. If `api` is `Exit` or **Up Less than a second**, the API is crash-looping and Nginx will always return 502.

```bash
sudo docker inspect iitd_lab-api-1 --format 'restarts={{.RestartCount}} exit={{.State.ExitCode}} err={{.State.Error}}'
sudo docker compose logs api --tail 200
```

Rebuild is not required for this Python fix if the API image already exists. After `git checkout v1.1.7`:

```bash
sudo docker compose up -d --force-recreate --no-deps api
sudo docker compose logs -f api
```

Also confirm `.env` has `NO_PROXY` including `db` so Postgres is not sent through the campus HTTP proxy.

## Admin Updates page cannot apply a GitHub tag

The API lists the last 3 releases from GitHub. Apply needs the git checkout path (`LABWATCH_REPO_DIR`) and Docker. From the repo root:

```bash
sudo ./scripts/linux/install-host-updater.sh
```

Compose bind-mounts the git checkout at `/opt/labwatch` and Docker socket into `api`. `.env` is not overwritten by `git checkout`.

Sidebar, Labs, Updates, and Admin all come from the bind-mounted SPA in `docker/web-static`. After `git checkout`, recreate **web** (no npm/image rebuild):

```bash
sudo docker compose up -d --force-recreate --no-deps web
```

## Docker / pip: IITD proxy CONNECT drops

`Establishing a new connection` during `pip`/`npm` is **squid**, not SSH. Each wheel hits `pypi.org` then `files.pythonhosted.org`; squid 3.1 closes the CONNECT tunnel, the client opens another, and if the `proxy.cgi` session expired you get `302` again.

Keep a `proxy.cgi` **Refresh every 30s** on that same host for the whole download. One login only (a second login kicks the first).

Put proxy URLs in `.env` so Compose build args reach `pip`/`npm`:

```
HTTP_PROXY=http://10.10.78.21:3128/
HTTPS_PROXY=http://10.10.78.21:3128/
NO_PROXY=localhost,127.0.0.1,::1,db,web,api
```

Prefetch wheels with retries (survives CONNECT drops), then build without PyPI:

```bash
./scripts/linux/prefetch-pypi-wheels.sh
sudo docker compose up -d --build
```

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
