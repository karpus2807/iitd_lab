#!/usr/bin/env bash
set -euo pipefail
# LabWatch Linux agent installer
# Usage: sudo ./install-linux.sh https://labwatch.example.edu lw_token_here

PREFIX="${PREFIX:-/opt/labwatch-agent}"
CONFIG_DIR="${CONFIG_DIR:-/etc/labwatch-agent}"
STATE_DIR="${STATE_DIR:-/var/lib/labwatch-agent}"
SERVER_URL="${1:-${SERVER_URL:-}}"
REGISTRATION_TOKEN="${2:-${REGISTRATION_TOKEN:-}}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0 <SERVER_URL> <REGISTRATION_TOKEN>"
  exit 1
fi
if [[ -z "$SERVER_URL" ]]; then
  echo "Usage: $0 <SERVER_URL> <REGISTRATION_TOKEN>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_SRC="${SCRIPT_DIR}/agent"
if [[ ! -d "$AGENT_SRC/labwatch_agent" ]]; then
  AGENT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../agent" && pwd)"
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
from labwatch_agent.service import main
if __name__ == "__main__":
    raise SystemExit(main())
PY
# Make the package importable
echo "$PREFIX" > "$PREFIX/venv/lib/python3.*/site-packages/labwatch.pth" 2>/dev/null || true
PY_SITE="$("$PREFIX/venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
echo "$PREFIX" > "$PY_SITE/labwatch.pth"

if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
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
fi

cat > /usr/local/bin/labwatch-agent <<EOF
#!/usr/bin/env bash
export LABWATCH_CONFIG="${CONFIG_DIR}/config.toml"
export LABWATCH_STATE_DIR="${STATE_DIR}"
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
echo "Installed. Commands: labwatch-agent status|once ; systemctl status labwatch-agent"
