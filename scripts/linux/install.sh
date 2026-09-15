#!/usr/bin/env bash
set -euo pipefail
# LabWatch Linux agent installer
# Usage: sudo ./scripts/linux/install.sh http://hobbit2.cse.iitd.ac.in lw_token_here

PREFIX="${PREFIX:-/opt/labwatch-agent}"
CONFIG_DIR="${CONFIG_DIR:-/etc/labwatch-agent}"
STATE_DIR="${STATE_DIR:-/var/lib/labwatch-agent}"
SERVER_URL="${1:-${SERVER_URL:-}}"
REGISTRATION_TOKEN="${2:-${REGISTRATION_TOKEN:-}}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0 <SERVER_URL> <REGISTRATION_TOKEN>"
  exit 1
fi
if [[ -z "$SERVER_URL" || -z "$REGISTRATION_TOKEN" ]]; then
  echo "Usage: $0 <SERVER_URL> <REGISTRATION_TOKEN>"
  echo "Create a token in LabWatch Admin → tokens, then pass it as the second argument."
  exit 1
fi
SERVER_HOST="${SERVER_URL#*://}"
SERVER_HOST="${SERVER_HOST%%/*}"
SERVER_HOST="${SERVER_HOST%%:*}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_SRC="${REPO_ROOT}/agent"
if [[ ! -d "$AGENT_SRC/labwatch_agent" ]]; then
  echo "Could not find agent sources at $AGENT_SRC"
  echo "Run this from a LabWatch git checkout: sudo ./scripts/linux/install.sh <SERVER_URL> <TOKEN>"
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo "python3 is required. On Ubuntu: sudo apt-get install -y python3 python3-venv python3-pip"
  exit 1
fi

echo "Installing LabWatch agent to $PREFIX"
mkdir -p "$PREFIX" "$CONFIG_DIR" "$STATE_DIR"
python3 -m venv --without-pip "$PREFIX/venv" 2>/dev/null || python3 -m venv "$PREFIX/venv"
if [[ ! -x "$PREFIX/venv/bin/pip" ]]; then
  curl -sS https://bootstrap.pypa.io/get-pip.py | "$PREFIX/venv/bin/python"
fi
"$PREFIX/venv/bin/python" -m pip install -q -U pip
"$PREFIX/venv/bin/python" -m pip install -q -r "$AGENT_SRC/requirements.txt"
mkdir -p "$PREFIX/labwatch_agent"
cp -a "$AGENT_SRC/labwatch_agent/." "$PREFIX/labwatch_agent/"
cat > "$PREFIX/run.py" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from labwatch_agent.service import main

if __name__ == "__main__":
    raise SystemExit(main())
PY
PY_SITE="$("$PREFIX/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
mkdir -p "$PY_SITE"
echo "$PREFIX" > "$PY_SITE/labwatch.pth"

cat > "$CONFIG_DIR/config.toml" <<EOF
[server]
url = "${SERVER_URL}"
registration_token = "${REGISTRATION_TOKEN}"

[agent]
heartbeat_interval = 30
metric_interval = 30
inventory_interval = 300

[tls]
verify = true

[logging]
level = "INFO"
EOF
chmod 600 "$CONFIG_DIR/config.toml"

cat > /usr/local/bin/labwatch-agent <<EOF
#!/usr/bin/env bash
export LABWATCH_CONFIG="${CONFIG_DIR}/config.toml"
export LABWATCH_STATE_DIR="${STATE_DIR}"
export PYTHONPATH="${PREFIX}"
export NO_PROXY="${SERVER_HOST},localhost,127.0.0.1"
export no_proxy="${SERVER_HOST},localhost,127.0.0.1"
exec ${PREFIX}/venv/bin/python ${PREFIX}/run.py "\$@"
EOF
chmod +x /usr/local/bin/labwatch-agent

cat > /etc/systemd/system/labwatch-agent.service <<EOF
[Unit]
Description=LabWatch hardware monitoring agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=LABWATCH_CONFIG=${CONFIG_DIR}/config.toml
Environment=LABWATCH_STATE_DIR=${STATE_DIR}
Environment=PYTHONPATH=${PREFIX}
Environment=NO_PROXY=${SERVER_HOST},localhost,127.0.0.1
Environment=no_proxy=${SERVER_HOST},localhost,127.0.0.1
ExecStart=${PREFIX}/venv/bin/python ${PREFIX}/run.py run
Restart=always
RestartSec=5
User=root
Nice=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable labwatch-agent
systemctl restart labwatch-agent
sleep 2
if ! systemctl is-active --quiet labwatch-agent; then
  echo "Agent failed to stay running. Last logs:"
  journalctl -u labwatch-agent -n 40 --no-pager || true
  exit 1
fi
echo "Installed. Commands: labwatch-agent status|once ; systemctl status labwatch-agent"
