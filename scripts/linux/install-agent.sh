#!/usr/bin/env bash
set -euo pipefail
# LabWatch one-command installer (served from hobbit as /install-agent.sh)
# curl -fsSL http://hobbit2.cse.iitd.ac.in:8080/install-agent.sh | sudo bash

PREFIX="${PREFIX:-/opt/labwatch-agent}"
CONFIG_DIR="${CONFIG_DIR:-/etc/labwatch-agent}"
STATE_DIR="${STATE_DIR:-/var/lib/labwatch-agent}"
# API replaces only the marker below with LABWATCH_PUBLIC_URL (e.g. …:8080).
SERVER_URL="${LABWATCH_SERVER_URL:-${1:-}}"
if [[ -z "$SERVER_URL" ]]; then
  SERVER_URL="__SERVER_URL__"
fi
SERVER_URL="${SERVER_URL%/}"
# Unreplaced marker (git checkout) → default hobbit URL with port.
if [[ "$SERVER_URL" == "__SERVER_URL__" ]]; then
  SERVER_URL="http://hobbit2.cse.iitd.ac.in:8080"
fi
SERVER_HOST="${SERVER_URL#*://}"
SERVER_HOST="${SERVER_HOST%%/*}"
# Keep port in NO_PROXY host list only as hostname (no port).
SERVER_HOST="${SERVER_HOST%%:*}"
export NO_PROXY="${SERVER_HOST},localhost,127.0.0.1"
export no_proxy="${NO_PROXY}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: curl -fsSL --noproxy '*' ${SERVER_URL}/install-agent.sh | sudo bash"
  exit 1
fi

# IITD campus squid (IP session after proxy.cgi login — not HTTP Basic in the URL).
# Proxy is ONLY used when direct internet fails (home / open network needs no proxy).
CAMPUS_PROXY_URL="${LABWATCH_HTTP_PROXY:-http://10.10.78.21:3128}"
CAMPUS_PROXY_CGI="${LABWATCH_PROXY_CGI:-https://proxy21.iitd.ac.in/cgi-bin/proxy.cgi}"
PROXY_READY=0
DIRECT_OK="" # "" unknown, 1 yes, 0 no
PROXY_USER="${LABWATCH_PROXY_USER:-}"
PROXY_PASSWORD="${LABWATCH_PROXY_PASSWORD:-}"

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
  local prompt="$1" silent="${2:-0}"
  REPLY_TTY=""
  if [[ -z "$TTY" ]]; then
    _say "No terminal attached (curl | sudo bash needs a real TTY)."
    _say "Save the script first:"
    _say "  curl -fsSL --noproxy '*' ${SERVER_URL}/install-agent.sh -o /tmp/labwatch-install.sh"
    _say "  head -1 /tmp/labwatch-install.sh   # must be #!/usr/bin/env bash"
    _say "  sudo bash /tmp/labwatch-install.sh"
    _say "Or set LABWATCH_USER, LABWATCH_PASSWORD, LABWATCH_INVENTORY_ID, LABWATCH_LAB,"
    _say "and LABWATCH_PROXY_USER / LABWATCH_PROXY_PASSWORD when campus proxy is required."
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

_campus_proxy_cgi_login() {
  local user="$1" pass="$2"
  if command -v python3 >/dev/null; then
    PROXY_USER="$user" PROXY_PASSWORD="$pass" CAMPUS_PROXY_CGI="$CAMPUS_PROXY_CGI" python3 - <<'PY'
import os, re, ssl, sys, urllib.parse, urllib.request

cgi = os.environ.get("CAMPUS_PROXY_CGI") or "https://proxy21.iitd.ac.in/cgi-bin/proxy.cgi"
user = (os.environ.get("PROXY_USER") or "").strip()
password = os.environ.get("PROXY_PASSWORD") or ""
if not user or not password:
    raise SystemExit("proxy credentials missing")

ctx = ssl._create_unverified_context()
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=ctx),
    urllib.request.HTTPHandler(),
)
html = opener.open(cgi, timeout=30).read().decode("utf-8", "replace")
m = re.search(
    r'sessionid"[^>]*value="([a-zA-Z0-9]{16})"|value="([a-zA-Z0-9]{16})"[^>]*name="sessionid"',
    html,
    re.I,
)
if not m:
    raise SystemExit("could not read proxy.cgi session id")
sid = m.group(1) or m.group(2)
body = urllib.parse.urlencode(
    {"sessionid": sid, "action": "Validate", "userid": user, "pass": password}
).encode()
req = urllib.request.Request(cgi, data=body, method="POST")
text = opener.open(req, timeout=30).read().decode("utf-8", "replace")
low = text.lower()
if "logged in successfully" in low or "already logged in" in low:
    sys.exit(0)
if "does'not match" in low or "does not match" in low:
    raise SystemExit("proxy rejected username/password")
raise SystemExit("proxy.cgi login failed")
PY
    return $?
  fi
  # No python3 yet — use curl (needed to apt-install python after proxy login).
  command -v curl >/dev/null || return 1
  local html sid resp
  html="$(curl -fsSk --noproxy '*' --max-time 30 "$CAMPUS_PROXY_CGI" 2>/dev/null || true)"
  sid="$(printf '%s' "$html" | sed -n 's/.*sessionid" type="hidden" value="\([a-zA-Z0-9]\{16\}\)".*/\1/p' | head -1)"
  [[ -n "$sid" ]] || sid="$(printf '%s' "$html" | sed -n 's/.*name="sessionid"[^>]*value="\([a-zA-Z0-9]\{16\}\)".*/\1/p' | head -1)"
  [[ -n "$sid" ]] || return 1
  resp="$(curl -fsSk --noproxy '*' --max-time 30 -X POST \
    --data-urlencode "sessionid=${sid}" \
    --data-urlencode "action=Validate" \
    --data-urlencode "userid=${user}" \
    --data-urlencode "pass=${pass}" \
    "$CAMPUS_PROXY_CGI" 2>/dev/null || true)"
  printf '%s' "$resp" | grep -qiE 'logged in successfully|already logged in'
}

_probe_direct_internet() {
  # True if this host can reach the public internet without campus proxy.
  if [[ "$DIRECT_OK" == "1" ]]; then
    return 0
  fi
  if [[ "$DIRECT_OK" == "0" ]]; then
    return 1
  fi
  if ! command -v curl >/dev/null; then
    DIRECT_OK=0
    return 1
  fi
  local ok=0
  # Probe without inheriting any proxy env (campus squid would 302).
  if curl -fsSIL --noproxy '*' --connect-timeout 5 --max-time 10 \
      https://pypi.org/simple/pip/ >/dev/null 2>&1; then
    ok=1
  elif curl -fsSIL --noproxy '*' --connect-timeout 5 --max-time 10 \
      http://archive.ubuntu.com/ubuntu/ >/dev/null 2>&1; then
    ok=1
  elif curl -fsS --noproxy '*' --connect-timeout 5 --max-time 10 \
      -o /dev/null https://www.google.com/generate_204 >/dev/null 2>&1; then
    ok=1
  fi
  if [[ "$ok" == "1" ]]; then
    DIRECT_OK=1
    return 0
  fi
  DIRECT_OK=0
  return 1
}

_ensure_campus_proxy() {
  # One-shot: prompt + proxy.cgi login + export HTTP(S)_PROXY for apt/pip.
  # Call only after direct internet has failed.
  if [[ "$PROXY_READY" == "1" ]]; then
    return 0
  fi
  _say ""
  _say "Direct internet is not available. IITD campus proxy login is required for apt/PyPI."
  if [[ -z "$PROXY_USER" ]]; then
    _ask "Proxy username (IITD kerberos id): " || return 1
    PROXY_USER="$REPLY_TTY"
  fi
  if [[ -z "$PROXY_PASSWORD" ]]; then
    _say "Type the proxy password (nothing will appear). Then press Enter."
    _ask "Proxy password: " 1 || return 1
    PROXY_PASSWORD="$REPLY_TTY"
  fi
  if [[ -z "$PROXY_USER" || -z "$PROXY_PASSWORD" ]]; then
    _say "Proxy username and password are required when direct internet is blocked."
    return 1
  fi
  _say "Logging into campus proxy (${CAMPUS_PROXY_CGI})…"
  if ! _campus_proxy_cgi_login "$PROXY_USER" "$PROXY_PASSWORD"; then
    _say "Campus proxy login failed. Check kerberos id/password (proxy21)."
    PROXY_PASSWORD=""
    return 1
  fi
  export http_proxy="$CAMPUS_PROXY_URL"
  export https_proxy="$CAMPUS_PROXY_URL"
  export HTTP_PROXY="$CAMPUS_PROXY_URL"
  export HTTPS_PROXY="$CAMPUS_PROXY_URL"
  export ftp_proxy="$CAMPUS_PROXY_URL"
  export FTP_PROXY="$CAMPUS_PROXY_URL"
  # LabWatch server stays direct (already in NO_PROXY).
  export NO_PROXY="${SERVER_HOST},localhost,127.0.0.1,::1"
  export no_proxy="$NO_PROXY"
  PROXY_READY=1
  _say "Campus proxy OK. Continuing install…"
  return 0
}

_ensure_outer_network() {
  # Prefer direct internet; only ask for campus proxy when direct fails.
  if [[ "$PROXY_READY" == "1" ]]; then
    return 0
  fi
  if _probe_direct_internet; then
    _say "Direct internet OK — installing without campus proxy."
    return 0
  fi
  _ensure_campus_proxy
}

_pkg_install_once() {
  local pkgs=("$@")
  if command -v apt-get >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq || return 1
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}" || return 1
    return 0
  elif command -v dnf >/dev/null; then
    dnf install -y "${pkgs[@]}" || return 1
  elif command -v yum >/dev/null; then
    yum install -y "${pkgs[@]}" || return 1
  elif command -v zypper >/dev/null; then
    zypper --non-interactive install "${pkgs[@]}" || return 1
  elif command -v pacman >/dev/null; then
    pacman -Sy --noconfirm "${pkgs[@]}" || return 1
  else
    echo "Install these packages by hand if fields are empty: ${pkgs[*]}"
    return 1
  fi
}

_pkg_install() {
  local pkgs=("$@")
  ((${#pkgs[@]})) || return 0
  if [[ "$PROXY_READY" == "1" ]]; then
    _pkg_install_once "${pkgs[@]}" || true
    return 0
  fi
  # Try without proxy first (home / open network).
  if _pkg_install_once "${pkgs[@]}" 2>/dev/null; then
    DIRECT_OK=1
    return 0
  fi
  _say "Package install over direct network failed — trying campus proxy…"
  _ensure_campus_proxy || {
    echo "Cannot install packages (no direct internet and proxy login failed): ${pkgs[*]}"
    return 1
  }
  _pkg_install_once "${pkgs[@]}" || true
}

_check_os_supported() {
  # LabWatch agents: Ubuntu 16.04+ (and similar glibc hosts). Older Ubuntu rejected.
  if [[ ! -f /etc/os-release ]]; then
    echo "OS: unknown (no /etc/os-release) — continuing; any host Python is OK (bundled 3.12 if needed)."
    return 0
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  local id="${ID:-}" ver_full="${VERSION_ID:-}" ver_major
  ver_major="${ver_full%%.*}"
  case "$id" in
    ubuntu)
      if [[ -n "$ver_major" && "$ver_major" -lt 16 ]]; then
        echo "Ubuntu ${ver_full} is not supported. LabWatch needs Ubuntu 16.04 or newer."
        exit 1
      fi
      echo "OS: Ubuntu ${ver_full} (supported — 16.04+)"
      ;;
    debian)
      if [[ -n "$ver_major" && "$ver_major" -lt 9 ]]; then
        echo "WARN: Debian ${ver_full} is older than recommended; bundled Python may still work."
      else
        echo "OS: Debian ${ver_full} (supported)"
      fi
      ;;
    *)
      echo "OS: ${PRETTY_NAME:-$id $ver_full} — supported if glibc works with bundled CPython 3.12"
      ;;
  esac
}

_host_arch() {
  local m
  m="$(uname -m 2>/dev/null || echo x86_64)"
  case "$m" in
    x86_64|amd64) echo x86_64 ;;
    aarch64|arm64) echo aarch64 ;;
    *) echo "$m" ;;
  esac
}

_ensure_host_tools() {
  local pkgs=()
  # Distro python3 is nice-to-have; Ubuntu 16 may only have 3.5 — we bootstrap 3.12 later.
  command -v python3 >/dev/null || pkgs+=(python3 python3-venv python3-pip) || true
  if command -v apt-get >/dev/null; then
    pkgs+=(libsqlite3-0)
  fi
  command -v curl >/dev/null || pkgs+=(curl)
  command -v tar >/dev/null || pkgs+=(tar)
  command -v dmidecode >/dev/null || pkgs+=(dmidecode)
  command -v lspci >/dev/null || pkgs+=(pciutils)
  command -v lsblk >/dev/null || pkgs+=(util-linux)
  command -v lscpu >/dev/null || pkgs+=(util-linux)
  command -v ip >/dev/null || pkgs+=(iproute2)
  command -v smartctl >/dev/null || pkgs+=(smartmontools)
  if ((${#pkgs[@]} == 0)); then
    echo "Host collector tools already present."
  else
    echo "Installing missing collector tools: ${pkgs[*]}"
    _pkg_install "${pkgs[@]}" || true
  fi
  local gpu_pkgs=()
  if command -v apt-get >/dev/null; then
    command -v intel_gpu_top >/dev/null || gpu_pkgs+=(intel-gpu-tools)
    command -v glxinfo >/dev/null || gpu_pkgs+=(mesa-utils)
  fi
  if ((${#gpu_pkgs[@]})); then
    echo "Installing optional GPU tools (best-effort): ${gpu_pkgs[*]}"
    _pkg_install "${gpu_pkgs[@]}" || true
  fi
}

_python_ok() {
  # Agent venv needs 3.10+ for current wheels. Host Python may be anything (2.x / 3.5 / 3.8…).
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

_python_has_sqlite() {
  "$1" -c 'import sqlite3; sqlite3.connect(":memory:").close()' 2>/dev/null
}

_host_python_summary() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -V 2>&1 || true
    return 0
  fi
  if command -v python2 >/dev/null 2>&1; then
    python2 -V 2>&1 || true
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    python -V 2>&1 || true
    return 0
  fi
  echo "none"
}

_candidate_bundled() {
  local path
  for path in \
    "${PREFIX}/python/bin/python3" \
    "${PREFIX}/python/bin/python" \
    /opt/labwatch-agent/python/bin/python3 \
    /opt/labwatch-agent/python/bin/python
  do
    [[ -x "$path" ]] && echo "$path"
  done
}

_candidate_system() {
  local c path
  for c in python3.14 python3.13 python3.12 python3.11 python3.10; do
    path="/usr/bin/$c"
    [[ -x "$path" ]] && echo "$path"
  done
  for c in python3.14 python3.13 python3.12 python3.11 python3.10; do
    path="$(command -v "$c" 2>/dev/null || true)"
    [[ -n "$path" ]] || continue
    echo "$path"
  done
  # Generic python3 only if it is already 3.10+
  path="$(command -v python3 2>/dev/null || true)"
  if [[ -n "$path" ]] && _python_ok "$path"; then
    echo "$path"
  fi
}

_pick_python() {
  # stdin: candidate paths; $1=1 require sqlite
  local prefer="${1:-1}" path
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    [[ -x "$path" ]] || continue
    _python_ok "$path" || continue
    if [[ "$prefer" == "1" ]]; then
      _python_has_sqlite "$path" || continue
    fi
    echo "$path"
    return 0
  done
  return 1
}

_bootstrap_bundled_python() {
  local arch dest work tgz pybin
  arch="$(_host_arch)"
  case "$arch" in
    x86_64|aarch64) ;;
    *)
      echo "No LabWatch bundled Python for arch=${arch}." >&2
      return 1
      ;;
  esac
  if ! command -v curl >/dev/null || ! command -v tar >/dev/null; then
    echo "curl and tar are required to download LabWatch's bundled CPython 3.12." >&2
    return 1
  fi
  dest="${PREFIX}/python"
  work="$(mktemp -d)"
  tgz="$work/python-runtime.tgz"
  echo "Downloading LabWatch bundled CPython 3.12 for ${arch} (host Python is left untouched)…" >&2
  if ! curl -fsSL "${SERVER_URL}/python-runtime.tgz?arch=${arch}" -o "$tgz"; then
    echo "ERROR: could not download ${SERVER_URL}/python-runtime.tgz?arch=${arch}" >&2
    echo "On the LabWatch server run: ./scripts/linux/prefetch-python-runtime.sh" >&2
    echo "Then: sudo docker compose up -d --force-recreate --no-deps api" >&2
    rm -rf "$work"
    return 1
  fi
  rm -rf "$dest"
  mkdir -p "$dest"
  tar -xzf "$tgz" -C "$work"
  if [[ -d "$work/python" ]]; then
    cp -a "$work/python/." "$dest/"
  else
    find "$work" -mindepth 1 -maxdepth 1 ! -name 'python-runtime.tgz' -exec cp -a {} "$dest/" \;
  fi
  rm -rf "$work"
  for pybin in "$dest/bin/python3" "$dest/bin/python"; do
    if [[ -x "$pybin" ]] && _python_ok "$pybin"; then
      echo "$pybin"
      return 0
    fi
  done
  echo "ERROR: bundled Python unpack failed under $dest" >&2
  return 1
}

_ensure_python() {
  # Goal: install works no matter what Python the host has (2.x, 3.5, 3.8, none…).
  # Prefer LabWatch's own CPython 3.12 under PREFIX/python — never use host 3.8 for the agent.
  local found host_py
  host_py="$(_host_python_summary)"
  echo "Host Python: ${host_py} — left unchanged. Agent uses LabWatch CPython under ${PREFIX}/python." >&2

  found="$(_pick_python 1 < <(_candidate_bundled) || true)"
  if [[ -n "$found" ]]; then
    echo "Reusing LabWatch bundled runtime: $found" >&2
    echo "$found"
    return 0
  fi

  # Download bundled 3.12 first (Ubuntu 20.04 default python3 is 3.8 — must not be used).
  found="$(_bootstrap_bundled_python || true)"
  if [[ -n "$found" ]]; then
    echo "$found"
    return 0
  fi

  found="$(_pick_python 1 < <(_candidate_system) || true)"
  if [[ -n "$found" ]]; then
    echo "Using system Python 3.10+: $found" >&2
    echo "$found"
    return 0
  fi
  found="$(_pick_python 0 < <(_candidate_system) || true)"
  if [[ -n "$found" ]]; then
    echo "Using system Python 3.10+: $found" >&2
    echo "$found"
    return 0
  fi

  echo "Trying distro Python 3.10/3.12 packages as fallback…" >&2
  if command -v apt-get >/dev/null; then
    _pkg_install libsqlite3-0 python3.10 python3.10-venv python3.12 python3.12-venv || true
  elif command -v dnf >/dev/null; then
    _pkg_install sqlite python3 python3-pip python3-virtualenv || true
  fi
  found="$(_pick_python 1 < <(_candidate_system) || true)"
  if [[ -n "$found" ]]; then
    echo "$found"
    return 0
  fi

  echo "Could not obtain CPython 3.10+ for the agent (bundled download failed)." >&2
  echo "Fix: ensure ${SERVER_URL}/python-runtime.tgz is reachable, then re-run installer." >&2
  return 1
}

_check_os_supported
_ensure_host_tools
if ! command -v curl >/dev/null; then
  echo "curl is required (apt install curl after campus proxy login if needed)."
  _pkg_install curl || exit 1
fi
PYTHON_BIN="$(_ensure_python)" || {
  echo "LabWatch could not install its bundled CPython 3.12. Check network to ${SERVER_URL}/python-runtime.tgz"
  exit 1
}
echo "Using Python for agent: $PYTHON_BIN ($($PYTHON_BIN -V 2>&1))"
if ! _python_has_sqlite "$PYTHON_BIN"; then
  echo "NOTE: $PYTHON_BIN has no stdlib _sqlite3 — will use pysqlite3-binary from LabWatch wheels."
fi

if systemctl is-active --quiet labwatch-agent 2>/dev/null || [[ -f "${CONFIG_DIR}/config.toml" ]]; then
  _say "Existing LabWatch agent found. Enter keeps the current machine ID and lab."
  systemctl stop labwatch-agent 2>/dev/null || true
fi

_toml_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  $PYTHON_BIN - "$file" "$key" <<'PY'
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
EXISTING_PET_NAME="$(_toml_get "${CONFIG_DIR}/config.toml" pet_name)"
EXISTING_LAB_ID="${LAB_ID:-$(_toml_get "${CONFIG_DIR}/config.toml" lab_id)}"
EXISTING_LAB_NAME="${LAB_NAME:-$(_toml_get "${CONFIG_DIR}/config.toml" lab)}"
PET_NAME="${LABWATCH_PET_NAME:-}"
if [[ -z "$INVENTORY_ID" && -n "$EXISTING_INVENTORY" ]]; then
  INVENTORY_ID="$EXISTING_INVENTORY"
fi
if [[ -z "$PET_NAME" && -n "$EXISTING_PET_NAME" ]]; then
  PET_NAME="$EXISTING_PET_NAME"
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

if [[ -z "${LABWATCH_PET_NAME:-}" ]]; then
  _ask "Pet name [${EXISTING_PET_NAME:-optional}]: " || exit 1
  if [[ -n "$REPLY_TTY" ]]; then
    PET_NAME="$REPLY_TTY"
  fi
fi

if [[ -z "$USERNAME" || -z "$PASSWORD" || -z "$INVENTORY_ID" ]]; then
  echo "Username, password, and machine ID are required (Enter keeps the previous machine ID if one exists)."
  exit 1
fi

if [[ -z "$LAB_ID" ]]; then
  _say "Fetching labs from ${SERVER_URL} (direct, 20s timeout)…"
  LABS_JSON="$(
    SERVER_URL="$SERVER_URL" USERNAME="$USERNAME" PASSWORD="$PASSWORD" INVENTORY_ID="$INVENTORY_ID" EXISTING_LAB_ID="$EXISTING_LAB_ID" EXISTING_LAB_NAME="$EXISTING_LAB_NAME" $PYTHON_BIN - <<'PY'
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
  $PYTHON_BIN - "$LABS_JSON" <<'PY' >"${TTY:-/dev/stderr}"
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
    CHOICE="$CHOICE" $PYTHON_BIN - "$LABS_JSON" <<'PY'
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
  LAB_ID="$(printf '%s' "$LAB_PICK" | $PYTHON_BIN -c 'import json,sys; print(json.load(sys.stdin)["lab_id"])')"
  LAB_NAME="$(printf '%s' "$LAB_PICK" | $PYTHON_BIN -c 'import json,sys; print(json.load(sys.stdin)["lab"])')"
  if printf '%s' "$LAB_PICK" | $PYTHON_BIN -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("kept") else 1)'; then
    _say "Keeping ${LAB_NAME}"
  else
    _say "Selected ${LAB_NAME}"
  fi
  echo "Using lab: ${LAB_NAME}"
fi

echo "Logging in to ${SERVER_URL} and enrolling ${INVENTORY_ID}…"
ENROLL_JSON="$(
  SERVER_URL="$SERVER_URL" USERNAME="$USERNAME" PASSWORD="$PASSWORD" INVENTORY_ID="$INVENTORY_ID" PET_NAME="$PET_NAME" LAB_ID="$LAB_ID" $PYTHON_BIN - <<'PY'
import json, os, urllib.error, urllib.request
payload = {
    "username": os.environ["USERNAME"],
    "password": os.environ["PASSWORD"],
    "inventory_id": os.environ["INVENTORY_ID"],
}
pet = (os.environ.get("PET_NAME") or "").strip()
if pet:
    payload["pet_name"] = pet
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
TOKEN="$(printf '%s' "$ENROLL_JSON" | $PYTHON_BIN -c 'import json,sys; print(json.load(sys.stdin)["registration_token"])')"
REMOTE_URL="$(printf '%s' "$ENROLL_JSON" | $PYTHON_BIN -c 'import json,sys; print(json.load(sys.stdin).get("server_url") or "")')"
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

WHEELS_DIR="$AGENT_SRC/wheels"
if [[ ! -d "$WHEELS_DIR" ]] || ! compgen -G "$WHEELS_DIR"/*.whl >/dev/null; then
  echo "ERROR: offline wheelhouse missing in agent pack ($WHEELS_DIR)."
  echo "On the LabWatch server run: ./scripts/linux/prefetch-agent-wheels.sh"
  echo "Then recreate api/web so /agent-pack.tgz includes wheels."
  exit 1
fi

# Always wipe venv — a leftover 3.8 venv from a failed install makes get-pip.py fail
# ("minimum supported Python version is 3.10") even when PYTHON_BIN is 3.12.
echo "Creating fresh agent venv with $($PYTHON_BIN -V 2>&1)…"
rm -rf "$PREFIX/venv"
if ! "$PYTHON_BIN" -m venv --without-pip --clear "$PREFIX/venv" 2>/dev/null; then
  rm -rf "$PREFIX/venv"
  "$PYTHON_BIN" -m venv --clear "$PREFIX/venv"
fi
if [[ ! -x "$PREFIX/venv/bin/python" ]]; then
  echo "ERROR: venv python missing at $PREFIX/venv/bin/python"
  exit 1
fi
if ! "$PREFIX/venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "ERROR: agent venv is still on $($PREFIX/venv/bin/python -V 2>&1) — need 3.10+."
  echo "Removing broken venv and LabWatch python; re-run installer after:"
  echo "  sudo rm -rf $PREFIX/venv $PREFIX/python"
  rm -rf "$PREFIX/venv"
  exit 1
fi
echo "Agent venv Python: $($PREFIX/venv/bin/python -V 2>&1)"

if [[ ! -x "$PREFIX/venv/bin/pip" ]]; then
  if [[ -f "$WHEELS_DIR/get-pip.py" ]]; then
    "$PREFIX/venv/bin/python" "$WHEELS_DIR/get-pip.py" --no-index --find-links="$WHEELS_DIR"
  else
    echo "ERROR: get-pip.py missing from wheelhouse; cannot bootstrap pip offline."
    exit 1
  fi
fi
# Prefer LabWatch-bundled wheels (no outer network). Fall back to PyPI via campus proxy.
_pip_offline() {
  "$PREFIX/venv/bin/python" -m pip install -q --no-index --find-links="$WHEELS_DIR" "$@"
}
_pip_online() {
  # Prefer direct PyPI; campus proxy only if direct fails.
  if [[ "$PROXY_READY" == "1" ]]; then
    "$PREFIX/venv/bin/python" -m pip install -q "$@" || return 1
    return 0
  fi
  if "$PREFIX/venv/bin/python" -m pip install -q "$@"; then
    DIRECT_OK=1
    return 0
  fi
  _say "Direct PyPI failed — campus proxy required…"
  _ensure_campus_proxy || return 1
  "$PREFIX/venv/bin/python" -m pip install -q "$@"
}

echo "Installing Python deps from LabWatch wheelhouse (offline)…"
if ! _pip_offline -U pip setuptools wheel; then
  echo "Offline pip bootstrap failed — trying PyPI (direct internet first)…"
  _pip_online -U pip setuptools wheel || {
    echo "ERROR: could not install pip/setuptools/wheel"
    exit 1
  }
fi
if ! _pip_offline -r "$AGENT_SRC/requirements.txt"; then
  echo "Offline requirements incomplete — trying PyPI (direct internet first)…"
  _pip_online -r "$AGENT_SRC/requirements.txt" || {
    echo "ERROR: could not install agent requirements"
    exit 1
  }
fi
# Optional sqlite fallback when stdlib _sqlite3 is missing.
if ! "$PREFIX/venv/bin/python" -c 'import sqlite3; sqlite3.connect(":memory:").close()' 2>/dev/null; then
  echo "NOTE: stdlib sqlite3 missing — installing pysqlite3-binary…"
  OPT_REQ="$AGENT_SRC/requirements-optional-linux.txt"
  if [[ -f "$OPT_REQ" ]]; then
    _pip_offline -r "$OPT_REQ" || _pip_online -r "$OPT_REQ" || {
      echo "ERROR: need sqlite3. Prefer: apt install python3 python3-venv"
      exit 1
    }
  else
    _pip_offline "pysqlite3-binary>=0.5.4" || _pip_online "pysqlite3-binary>=0.5.4" || {
      echo "ERROR: need sqlite3. Prefer: apt install python3 python3-venv"
      exit 1
    }
  fi
fi
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

LAB_TOML="$(printf '%s' "$LAB_NAME" | $PYTHON_BIN -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
PET_TOML="$(printf '%s' "$PET_NAME" | $PYTHON_BIN -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
cat > "$CONFIG_DIR/config.toml" <<EOF
[server]
url = "${SERVER_URL}"
registration_token = "${TOKEN}"
inventory_id = "${INVENTORY_ID}"
pet_name = ${PET_TOML}
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
# Only kill the main process on stop — update watchdogs must survive (also use systemd-run).
KillMode=process
Restart=always
RestartSec=5
User=root
Nice=10

[Install]
WantedBy=multi-user.target
EOF

# Keep lab PCs awake and networking out of power-save so the agent stays reachable.
_harden_power_and_network() {
  _say "Disabling sleep/hibernate and NIC/Wi-Fi power saving…"
  for unit in sleep.target suspend.target hibernate.target hybrid-sleep.target; do
    systemctl mask "$unit" >/dev/null 2>&1 || true
  done
  mkdir -p /etc/systemd/logind.conf.d
  cat > /etc/systemd/logind.conf.d/99-labwatch-no-idle.conf <<'EOF'
[Login]
IdleAction=ignore
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
EOF
  # Reload logind if present (ignore failure on containers / old systemd).
  systemctl reload systemd-logind 2>/dev/null || true

  if [[ -d /etc/NetworkManager ]]; then
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/99-labwatch-wifi-powersave.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF
    systemctl reload NetworkManager 2>/dev/null || true
  fi

  # Runtime: Wi-Fi power_save off + disable EEE on wired NICs.
  if [[ -d /sys/class/net ]]; then
    for iface in /sys/class/net/*; do
      name="$(basename "$iface")"
      [[ "$name" == "lo" ]] && continue
      if [[ -d "$iface/wireless" ]]; then
        iw dev "$name" set power_save off 2>/dev/null || iwconfig "$name" power off 2>/dev/null || true
      else
        ethtool --set-eee "$name" eee off 2>/dev/null || true
        # Disable NIC wake-on-lan autoneg quirks that drop link on some lab switches — leave WOL as-is.
      fi
    done
  fi

  # Drop-in unit: re-apply Wi-Fi powersave off after boot / resume.
  cat > /etc/systemd/system/labwatch-keep-awake.service <<'EOF'
[Unit]
Description=LabWatch keep network awake (no Wi-Fi power save)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'for i in /sys/class/net/*; do n=$(basename "$i"); [[ $n == lo ]] && continue; if [[ -d $i/wireless ]]; then iw dev "$n" set power_save off 2>/dev/null || iwconfig "$n" power off 2>/dev/null || true; else ethtool --set-eee "$n" eee off 2>/dev/null || true; fi; done'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now labwatch-keep-awake.service >/dev/null 2>&1 || true
  _say "OK: sleep/hibernate masked; Wi-Fi/NIC power-save disabled."
}

_harden_power_and_network

systemctl daemon-reload
systemctl enable labwatch-agent
systemctl restart labwatch-agent
sleep 2
if ! systemctl is-active --quiet labwatch-agent; then
  echo "Agent failed to stay running. Last logs:"
  journalctl -u labwatch-agent -n 40 --no-pager || true
  exit 1
fi
unset PROXY_PASSWORD PASSWORD || true
echo "Installed ${INVENTORY_ID} (${LAB_NAME:-lab}) → ${SERVER_URL}"
echo -n "Collector tools:"
for t in dmidecode lspci lsblk smartctl nvidia-smi; do
  if command -v "$t" >/dev/null; then echo -n " $t"; else echo -n " NO-$t"; fi
done
echo
echo "Update later with the same curl command; Enter keeps this machine ID and lab."
echo "Commands: labwatch-agent status|once ; systemctl status labwatch-agent"
