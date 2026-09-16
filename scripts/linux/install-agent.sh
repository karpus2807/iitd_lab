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

_pkg_install() {
  local pkgs=("$@")
  ((${#pkgs[@]})) || return 0
  if command -v apt-get >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}" || true
  elif command -v dnf >/dev/null; then
    dnf install -y "${pkgs[@]}" || true
  elif command -v yum >/dev/null; then
    yum install -y "${pkgs[@]}" || true
  elif command -v zypper >/dev/null; then
    zypper --non-interactive install "${pkgs[@]}" || true
  elif command -v pacman >/dev/null; then
    pacman -Sy --noconfirm "${pkgs[@]}" || true
  else
    echo "Install these packages by hand if fields are empty: ${pkgs[*]}"
  fi
}

_ensure_host_tools() {
  local pkgs=()
  command -v python3 >/dev/null || pkgs+=(python3 python3-venv python3-pip)
  command -v curl >/dev/null || pkgs+=(curl)
  command -v dmidecode >/dev/null || pkgs+=(dmidecode)
  command -v lspci >/dev/null || pkgs+=(pciutils)
  command -v lsblk >/dev/null || pkgs+=(util-linux)
  command -v lscpu >/dev/null || pkgs+=(util-linux)
  command -v ip >/dev/null || pkgs+=(iproute2)
  command -v smartctl >/dev/null || pkgs+=(smartmontools)
  if ((${#pkgs[@]} == 0)); then
    echo "Host collector tools already present."
    return 0
  fi
  echo "Installing missing collector tools: ${pkgs[*]}"
  _pkg_install "${pkgs[@]}"
}

_python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null
}

_find_python() {
  local c
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$c" >/dev/null && _python_ok "$(command -v "$c")"; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

_ensure_python() {
  local found
  found="$(_find_python || true)"
  if [[ -n "$found" ]]; then
    echo "$found"
    return 0
  fi
  echo "Python 3.8+ not found. Trying to install a newer interpreter…"
  if command -v apt-get >/dev/null; then
    _pkg_install python3 python3-venv python3-pip python3.10 python3.10-venv python3.12 python3.12-venv || true
  elif command -v dnf >/dev/null; then
    _pkg_install python3 python3-pip python3-virtualenv || true
  fi
  found="$(_find_python || true)"
  if [[ -n "$found" ]]; then
    echo "$found"
    return 0
  fi
  echo "Need Python 3.8 or newer for the agent (Ubuntu 18.04+, Debian 10+, or Python 3.10 from deadsnakes)."
  return 1
}

_ensure_host_tools
PYTHON_BIN="$(_ensure_python)" || {
  echo "python3 3.8+ is required."
  exit 1
}
echo "Using $($PYTHON_BIN -V)"
if ! command -v curl >/dev/null; then
  echo "curl is required."
  exit 1
fi

TTY=""
if [[ -c /dev/tty && -r /dev/tty && -w /dev/tty ]]; then
  TTY="/dev/tty"
fi
REPLY_TTY=""

_say() {
  if [[ -n "$TTY" ]]; then
    printf '%s\n' "$*" >"$TTY"
  else
    printf '%s\n' "$*" >&2
  fi
}

_ask() {
  # Read from the real keyboard, not from `curl | sudo` stdin (that is the script).
  # Do not run this inside $(...) — a subshell + stty/read on /dev/tty can hang.
  local prompt="$1" silent="${2:-0}"
  REPLY_TTY=""
  if [[ -z "$TTY" ]]; then
    _say "No terminal attached (curl | sudo bash needs a real TTY)."
    _say "Save the script first:"
    _say "  curl -fsSL ${SERVER_URL}/install-agent.sh -o /tmp/labwatch-install.sh"
    _say "  sudo bash /tmp/labwatch-install.sh"
    _say "Or set LABWATCH_USER, LABWATCH_PASSWORD, LABWATCH_INVENTORY_ID, LABWATCH_LAB."
    return 1
  fi
  printf '%s' "$prompt" >"$TTY"
  if [[ "$silent" == "1" ]]; then
    if ! IFS= read -r -s -t 180 REPLY_TTY <"$TTY"; then
      printf '\n' >"$TTY"
      _say "No password entered (timeout). Run again, or: sudo bash /tmp/labwatch-install.sh"
      return 1
    fi
    printf '\n' >"$TTY"
  else
    if ! IFS= read -r -t 180 REPLY_TTY <"$TTY"; then
      _say "No input entered (timeout). Run again, or: sudo bash /tmp/labwatch-install.sh"
      return 1
    fi
  fi
  return 0
}

if systemctl is-active --quiet labwatch-agent 2>/dev/null || [[ -f "${CONFIG_DIR}/config.toml" ]]; then
  _say "Existing LabWatch agent found. Enter keeps the current machine ID and lab."
  systemctl stop labwatch-agent 2>/dev/null || true
fi

_toml_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  python3 - "$file" "$key" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
key = sys.argv[2]
m = re.search(r"^" + re.escape(key) + r'\s*=\s*"(.*)"', text, re.M)
print(m.group(1) if m else "", end="")
PY
}

USERNAME="${LABWATCH_USER:-}"
PASSWORD="${LABWATCH_PASSWORD:-}"
INVENTORY_ID="${LABWATCH_INVENTORY_ID:-${2:-}}"
LAB_ID="${LABWATCH_LAB_ID:-}"
LAB_NAME="${LABWATCH_LAB:-}"
EXISTING_INVENTORY="$(_toml_get "${CONFIG_DIR}/config.toml" inventory_id)"
EXISTING_LAB_ID="${LAB_ID:-$(_toml_get "${CONFIG_DIR}/config.toml" lab_id)}"
EXISTING_LAB_NAME="${LAB_NAME:-$(_toml_get "${CONFIG_DIR}/config.toml" lab)}"
if [[ -z "$INVENTORY_ID" && -n "$EXISTING_INVENTORY" ]]; then
  INVENTORY_ID="$EXISTING_INVENTORY"
fi

_say ""
_say "Login for ${SERVER_URL}"
_say "Multiple devices can use the same admin login. That does not block install."
if [[ -z "$USERNAME" ]]; then
  _ask "Username: " || exit 1
  USERNAME="$REPLY_TTY"
fi
if [[ -z "$PASSWORD" ]]; then
  _say "Type the LabWatch password now. Nothing will appear (no dots). Then press Enter."
  _ask "Password: " 1 || exit 1
  PASSWORD="$REPLY_TTY"
  if [[ -z "$PASSWORD" ]]; then
    _say "Password was empty. Run the installer again."
    exit 1
  fi
  _say "Password received. Asking for machine ID next…"
fi
if [[ -z "${LABWATCH_INVENTORY_ID:-}" && -z "${2:-}" ]]; then
  _ask "Machine ID [${EXISTING_INVENTORY:-example 12345/2012/12}]: " || exit 1
  if [[ -n "$REPLY_TTY" ]]; then
    INVENTORY_ID="$REPLY_TTY"
  fi
fi

if [[ -z "$USERNAME" || -z "$PASSWORD" || -z "$INVENTORY_ID" ]]; then
  echo "Username, password, and machine ID are required (Enter keeps the previous machine ID if one exists)."
  exit 1
fi

if [[ -z "$LAB_ID" ]]; then
  _say "Fetching labs from ${SERVER_URL} (direct, 20s timeout)…"
  LABS_JSON="$(
    SERVER_URL="$SERVER_URL" USERNAME="$USERNAME" PASSWORD="$PASSWORD" INVENTORY_ID="$INVENTORY_ID" EXISTING_LAB_ID="$EXISTING_LAB_ID" EXISTING_LAB_NAME="$EXISTING_LAB_NAME" python3 - <<'PY'
import json, os, sys, urllib.error, urllib.parse, urllib.request

def call(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    raw = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(os.environ["SERVER_URL"] + path, data=raw, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"Request failed ({exc.code}): {body}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach {os.environ['SERVER_URL']}: {exc}")

sys.stderr.write("Logging in…\n")
sys.stderr.flush()
login = call("POST", "/api/auth/login", {"username": os.environ["USERNAME"], "password": os.environ["PASSWORD"]})
token = login["access_token"]
sys.stderr.write("Loading lab list…\n")
sys.stderr.flush()
labs = call("GET", "/api/labs", token=token)
if not isinstance(labs, list) or not labs:
    raise SystemExit("No labs found. Create labs in Admin first.")
labs.sort(key=lambda row: (str(row.get("name") or "").strip().lower() == "unassigned", str(row.get("name") or "").lower()))
by_id = {str(row["id"]): row for row in labs}
unassigned = next((row for row in labs if str(row.get("name") or "").strip().lower() == "unassigned"), labs[0])

current = None
inv = (os.environ.get("INVENTORY_ID") or "").strip()
if inv:
    q = urllib.parse.quote(inv)
    listed = call("GET", f"/api/machines?inventory_id={q}", token=token)
    if isinstance(listed, list) and listed:
        lid = str(listed[0].get("lab_id") or "")
        current = by_id.get(lid)
if current is None:
    lid = (os.environ.get("EXISTING_LAB_ID") or "").strip()
    current = by_id.get(lid)
if current is None:
    name = (os.environ.get("EXISTING_LAB_NAME") or "").strip().lower()
    if name:
        current = next((row for row in labs if str(row.get("name") or "").lower() == name), None)

print(json.dumps({
    "labs": [{"id": row["id"], "name": row["name"], "machine_count": row.get("machine_count") or 0} for row in labs],
    "current_id": current["id"] if current else unassigned["id"],
    "current_name": current["name"] if current else unassigned["name"],
}))
PY
  )" || {
    echo "Could not fetch labs. Check username/password and that ${SERVER_URL} is reachable."
    exit 1
  }
  python3 - "$LABS_JSON" <<'PY' >"${TTY:-/dev/stderr}"
import json, sys
data = json.loads(sys.argv[1])
print("\nLabs:")
for i, lab in enumerate(data["labs"], 1):
    extra = "  (%s hosts)" % lab.get("machine_count", 0)
    mark = "  [current]" if lab["id"] == data.get("current_id") else ""
    print("  %s) %s%s%s" % (i, lab["name"], extra, mark))
print("Select lab number (Enter keeps %s): " % data["current_name"], end="")
sys.stdout.flush()
PY
  if [[ -n "${LABWATCH_LAB:-}" ]]; then
    CHOICE="$LABWATCH_LAB"
    _say "$CHOICE"
  else
    _ask "" || exit 1
    CHOICE="$REPLY_TTY"
  fi
  LAB_PICK="$(
    CHOICE="$CHOICE" python3 - "$LABS_JSON" <<'PY'
import json, os, sys
data = json.loads(sys.argv[1])
labs = data["labs"]
raw = (os.environ.get("CHOICE") or "").strip()
preset = (os.environ.get("LABWATCH_LAB") or "").strip()
if preset.isdigit():
    raw = preset
elif preset:
    match = next((i for i, lab in enumerate(labs, 1) if lab["name"].lower() == preset.lower()), None)
    if match is None:
        raise SystemExit("Unknown lab '%s'" % preset)
    raw = str(match)
if not raw:
    chosen = next(lab for lab in labs if lab["id"] == data["current_id"])
    print(json.dumps({"lab_id": chosen["id"], "lab": chosen["name"], "kept": True}))
    raise SystemExit
if not raw.isdigit():
    raise SystemExit("Select a lab by number, for example 1")
choice = int(raw)
if choice < 1 or choice > len(labs):
    raise SystemExit("Lab number must be between 1 and %s" % len(labs))
chosen = labs[choice - 1]
print(json.dumps({"lab_id": chosen["id"], "lab": chosen["name"], "kept": False, "n": choice}))
PY
  )" || {
    echo "Invalid lab choice."
    exit 1
  }
  LAB_ID="$(printf '%s' "$LAB_PICK" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lab_id"])')"
  LAB_NAME="$(printf '%s' "$LAB_PICK" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lab"])')"
  if printf '%s' "$LAB_PICK" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("kept") else 1)'; then
    _say "Keeping ${LAB_NAME}"
  else
    _say "Selected ${LAB_NAME}"
  fi
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
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(req, timeout=20) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    raise SystemExit(f"Enroll failed ({exc.code}): {body}")
except urllib.error.URLError as exc:
    raise SystemExit(f"Enroll failed: {exc}")
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
systemctl stop labwatch-agent 2>/dev/null || true
mkdir -p "$PREFIX" "$CONFIG_DIR" "$STATE_DIR"
"$PYTHON_BIN" -m venv --without-pip "$PREFIX/venv" 2>/dev/null || "$PYTHON_BIN" -m venv "$PREFIX/venv"
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

LAB_TOML="$(printf '%s' "$LAB_NAME" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
cat > "$CONFIG_DIR/config.toml" <<EOF
[server]
url = "${SERVER_URL}"
registration_token = "${TOKEN}"
inventory_id = "${INVENTORY_ID}"
lab_id = "${LAB_ID}"
lab = ${LAB_TOML}

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
rm -f "$STATE_DIR/state.toml"

cat > /usr/local/bin/labwatch-agent <<EOF
#!/usr/bin/env bash
export LABWATCH_CONFIG="${CONFIG_DIR}/config.toml"
export LABWATCH_STATE_DIR="${STATE_DIR}"
export PYTHONPATH="${PREFIX}"
export HTTP_PROXY=""
export HTTPS_PROXY=""
export ALL_PROXY=""
export http_proxy=""
export https_proxy=""
export all_proxy=""
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
Environment=HTTP_PROXY=
Environment=HTTPS_PROXY=
Environment=ALL_PROXY=
Environment=http_proxy=
Environment=https_proxy=
Environment=all_proxy=
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
echo "Installed ${INVENTORY_ID} (${LAB_NAME:-lab}) → ${SERVER_URL}"
echo -n "Collector tools:"
for t in dmidecode lspci lsblk smartctl nvidia-smi; do
  if command -v "$t" >/dev/null; then echo -n " $t"; else echo -n " NO-$t"; fi
done
echo
echo "Update later with the same curl command; Enter keeps this machine ID and lab."
echo "Commands: labwatch-agent status|once ; systemctl status labwatch-agent"
