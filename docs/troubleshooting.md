# Troubleshooting

## Login is Bad Gateway

Nginx is up; the API is not.

```bash
cd ~/iitd_lab
sudo docker compose ps
sudo docker compose logs api --tail 80
curl -sS http://127.0.0.1/health
```

Health must return JSON with `"status":"ok"`. Then:

```bash
sudo docker compose up -d --force-recreate --no-deps api
```

In `.env`, `NO_PROXY` must include `db` so Postgres is not sent through the campus proxy.

## Agent install looks stuck after username

It is waiting for the **password**. Nothing is printed while you type. Press Enter when done.

Prefer:

```bash
curl -fsSL http://hobbit2.cse.iitd.ac.in/install-agent.sh -o /tmp/labwatch-install.sh
sudo bash /tmp/labwatch-install.sh
```

Same admin login can be used on many PCs.

## UI did not change after git checkout

Recreate **web** and hard-refresh the browser:

```bash
sudo docker compose up -d --force-recreate --no-deps web
```

Installer / agent pack: recreate **api**.

## Campus proxy breaks pip / npm

Keep proxy login alive. In `.env`:

```
HTTP_PROXY=http://10.10.78.21:3128/
HTTPS_PROXY=http://10.10.78.21:3128/
NO_PROXY=localhost,127.0.0.1,db,web,api
```

Optional: `./scripts/linux/prefetch-pypi-wheels.sh` then `docker compose up -d --build`.

## Agent is NEVER_CONNECTED or enrolled=no

```bash
labwatch-agent status
curl -sS http://hobbit2.cse.iitd.ac.in/health
sudo journalctl -u labwatch-agent -n 50 --no-pager
```

Check `server.url`, campus proxy (`NO_PROXY` for hobbit), and that enroll finished.

## RAM / GPU fields empty

Missing tools or a board that has no DIMM/PCIe map (Jetson). Install `dmidecode`, `lspci`, `smartctl` as needed. The agent should run as root (systemd does).

The UI hides fields the device cannot report.

## Duplicate hosts after cloning a disk

Clear `/var/lib/labwatch-agent` on the clone, or remove the old host in the UI and reinstall.

## Host is ON but marked OFFLINE

Agent not running, or the PC cannot reach the server. Offline delay should be at least 3× the heartbeat (default 30s).

## Email not sent

Set `SMTP_ENABLED=true` and `SMTP_*` in `.env`. The website still works without email.
