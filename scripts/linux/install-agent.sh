#!/usr/bin/env bash
set -euo pipefail
# LabWatch one-command installer (served from hobbit as /install-agent.sh)
# curl -fsSL http://hobbit2.cse.iitd.ac.in/install-agent.sh | sudo bash

PREFIX="${PREFIX:-/opt/labwatch-agent}"
CONFIG_DIR="${CONFIG_DIR:-/etc/labwatch-agent}"
STATE_DIR="${STATE_DIR:-/var/lib/labwatch-agent}"
SERVER_URL="${LABWATCH_SERVER_URL:-${1:-__SERVER_URL__}}"
if [[ "$SERVER_URL" == "__SERVER_URL__" || -z "$SERVER_URL" ]]; then
  SERVER_URL="http://hobbit2.cse.iitd.ac.in"
fi
SERVER_URL="${SERVER_URL%/}"
SERVER_HOST="${SERVER_URL#*://}"
SERVER_HOST="${SERVER_HOST%%/*}"
SERVER_HOST="${SERVER_HOST%%:*}"
export NO_PROXY="${SERVER_HOST},localhost,127.0.0.1"
export no_proxy="${NO_PROXY}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: curl -fsSL ${SERVER_URL}/install-agent.sh | sudo bash"
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo "python3 is required. On Ubuntu: sudo apt-get install -y python3 python3-venv python3-pip curl"
  exit 1
fi
if ! command -v curl >/dev/null; then
  echo "curl is required. On Ubuntu: sudo apt-get install -y curl"
  exit 1
fi

_read_tty() {
  local prompt="$1" silent="${2:-0}" value=""
  if [[ -r /dev/tty ]]; then
    if [[ "$silent" == "1" ]]; then
      read -r -s -p "$prompt" value </dev/tty || true
      echo >/dev/tty
    else
      read -r -p "$prompt" value </dev/tty || true
    fi
  else
    if [[ "$silent" == "1" ]]; then
      read -r -s -p "$prompt" value || true
      echo
    else
      read -r -p "$prompt" value || true
    fi
  fi
  printf '%s' "$value"
}

USERNAME="${LABWATCH_USER:-}"
PASSWORD="${LABWATCH_PASSWORD:-}"
INVENTORY_ID="${LABWATCH_INVENTORY_ID:-${2:-}}"
LAB_ID="${LABWATCH_LAB_ID:-}"
LAB_NAME="${LABWATCH_LAB:-}"

if [[ -z "$USERNAME" ]]; then
  USERNAME="$(_read_tty 'LabWatch username: ')"
fi
if [[ -z "$PASSWORD" ]]; then
  PASSWORD="$(_read_tty 'LabWatch password: ' 1)"
fi
if [[ -z "$INVENTORY_ID" ]]; then
  INVENTORY_ID="$(_read_tty 'Machine ID (example 12345/2012/12): ')"
fi

if [[ -z "$USERNAME" || -z "$PASSWORD" || -z "$INVENTORY_ID" ]]; then
  echo "Username, password, and machine ID are required."
  exit 1
fi

if [[ -z "$LAB_ID" ]]; then
  echo "Fetching labs from ${SERVER_URL}…"
  LAB_PICK="$(
    SERVER_URL="$SERVER_URL" USERNAME="$USERNAME" PASSWORD="$PASSWORD" LABWATCH_LAB="$LAB_NAME" python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request

def call(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    raw = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(os.environ["SERVER_URL"] + path, data=raw, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"Request failed ({exc.code}): {body}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach {os.environ['SERVER_URL']}: {exc}")

tty_out = open("/dev/tty", "w") if os.path.exists("/dev/tty") else sys.stderr
tty_in = open("/dev/tty", "r") if os.path.exists("/dev/tty") else sys.stdin

login = call("POST", "/api/auth/login", {"username": os.environ["USERNAME"], "password": os.environ["PASSWORD"]})
labs = call("GET", "/api/labs", token=login["access_token"])
if not isinstance(labs, list) or not labs:
    raise SystemExit("No labs found. Create labs in Admin first.")
labs.sort(key=lambda row: (str(row.get("name") or "").strip().lower() == "unassigned", str(row.get("name") or "").lower()))
tty_out.write("\nLabs:\n")
for i, lab in enumerate(labs, 1):
    extra = f"  ({lab.get('machine_count') or 0} hosts)" if lab.get("machine_count") is not None else ""
    tty_out.write(f"  {i}) {lab['name']}{extra}\n")
tty_out.flush()
preset = (os.environ.get("LABWATCH_LAB") or "").strip()
choice = None
if preset.isdigit():
    choice = int(preset)
elif preset:
    for i, lab in enumerate(labs, 1):
        if lab["name"].lower() == preset.lower():
            choice = i
            break
    if choice is None:
        raise SystemExit(f"Unknown lab '{preset}'")
else:
    tty_out.write("Select lab number: ")
    tty_out.flush()
    raw = tty_in.readline().strip()
    if not raw.isdigit():
        raise SystemExit("Select a lab by number, for example 1")
    choice = int(raw)
if choice < 1 or choice > len(labs):
    raise SystemExit(f"Lab number must be between 1 and {len(labs)}")
chosen = labs[choice - 1]
tty_out.write(f"Selected {choice}) {chosen['name']}\n")
print(json.dumps({"lab_id": chosen["id"], "lab": chosen["name"]}))
PY
  )"
  LAB_ID="$(printf '%s' "$LAB_PICK" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lab_id"])')"
  LAB_NAME="$(printf '%s' "$LAB_PICK" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lab"])')"
  echo "Using lab: ${LAB_NAME}"
fi

echo "Logging in to ${SERVER_URL} and enrolling ${INVENTORY_ID}…"
ENROLL_JSON="$(
  SERVER_URL="$SERVER_URL" USERNAME="$USERNAME" PASSWORD="$PASSWORD" INVENTORY_ID="$INVENTORY_ID" LAB_ID="$LAB_ID" python3 - <<'PY'
import json, os, urllib.error, urllib.request
payload = {
    "username": os.environ["USERNAME"],
    "password": os.environ["PASSWORD"],
    "inventory_id": os.environ["INVENTORY_ID"],
}
lab_id = os.environ.get("LAB_ID") or ""
if lab_id.strip():
    payload["lab_id"] = lab_id.strip()
req = urllib.request.Request(
    os.environ["SERVER_URL"] + "/api/agents/enroll",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    raise SystemExit(f"Enroll failed ({exc.code}): {body}")
PY
)"
TOKEN="$(printf '%s' "$ENROLL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["registration_token"])')"
REMOTE_URL="$(printf '%s' "$ENROLL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("server_url") or "")')"
if [[ -n "$REMOTE_URL" ]]; then
  SERVER_URL="$REMOTE_URL"
  SERVER_HOST="${SERVER_URL#*://}"
  SERVER_HOST="${SERVER_HOST%%/*}"
  SERVER_HOST="${SERVER_HOST%%:*}"
  export NO_PROXY="${SERVER_HOST},localhost,127.0.0.1"
  export no_proxy="${NO_PROXY}"
fi
unset PASSWORD

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
AGENT_SRC=""
if [[ -n "${SCRIPT_DIR:-}" && -d "${SCRIPT_DIR}/../../agent/labwatch_agent" ]]; then
  AGENT_SRC="$(cd "${SCRIPT_DIR}/../../agent" && pwd)"
fi
if [[ -z "$AGENT_SRC" ]]; then
  WORK="$(mktemp -d)"
  echo "Downloading agent from ${SERVER_URL}/agent-pack.tgz"
  curl -fsSL "${SERVER_URL}/agent-pack.tgz" -o "$WORK/agent-pack.tgz"
  mkdir -p "$WORK/src"
  tar -xzf "$WORK/agent-pack.tgz" -C "$WORK/src"
  AGENT_SRC="$WORK/src"
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
registration_token = "${TOKEN}"
inventory_id = "${INVENTORY_ID}"

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
echo "Installed ${INVENTORY_ID} → ${SERVER_URL}"
echo "Commands: labwatch-agent status|once ; systemctl status labwatch-agent"
