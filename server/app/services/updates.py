"""GitHub release listing and host-side apply/downgrade for LabWatch."""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app import __version__
from app.config import get_settings

logger = logging.getLogger("labwatch.updates")

TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.]+)?$")
SECRET_IN_URL = re.compile(r"://[^/@:]+:[^/@]+@")
CAMPUS_PROXY = "http://10.10.78.21:3128"
SESSION_RE = re.compile(
    r'sessionid"[^>]*value="([a-zA-Z0-9]{16})"|value="([a-zA-Z0-9]{16})"[^>]*name="sessionid"',
    re.IGNORECASE,
)
IDLE_STATUS = {
    "state": "idle",
    "tag": None,
    "message": "",
    "requested_at": None,
    "finished_at": None,
    "log_tail": "",
    "progress": None,
    "step": "",
    "stuck": False,
    "can_cancel": False,
}

# Apply watchdog: unlock the Updates UI when a run hangs.
STUCK_MAX_AGE_SEC = 20 * 60
STUCK_QUEUED_SEC = 5 * 60
STUCK_NO_HELPER_SEC = 3 * 60
ACTIVE_APPLY_STATES = frozenset({"queued", "running"})


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if tag and not tag.startswith("v") and re.match(r"^\d+\.\d+", tag):
        return f"v{tag}"
    return tag


def version_tuple(tag: str) -> tuple[int, int, int]:
    raw = (tag or "0.0.0").lstrip("vV").split("-", 1)[0]
    parts = []
    for piece in raw.split(".")[:3]:
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def current_version() -> str:
    return __version__.strip()


def current_tag() -> str:
    return normalize_tag(current_version())


def repo_dir() -> Path:
    settings = get_settings()
    raw = settings.repo_dir.strip() or os.environ.get("LABWATCH_REPO_DIR", "").strip()
    if raw:
        return Path(raw)
    opt = Path("/opt/labwatch")
    if (opt / "docker-compose.yml").is_file():
        return opt
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    path = repo_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def status_path() -> Path:
    return data_dir() / "update-status.json"


def request_path() -> Path:
    return data_dir() / "update-request.json"


def cache_path() -> Path:
    return data_dir() / "releases-cache.json"


def apply_log_path() -> Path:
    return data_dir() / "update-apply.log"


def read_apply_log(max_chars: int = 48000) -> str:
    """Tail of the host apply log for the live terminal panel."""
    path = apply_log_path()
    if not path.is_file():
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > max_chars * 4:
        raw = raw[-(max_chars * 4) :]
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _apply_age_seconds(data: dict[str, Any]) -> float | None:
    for key in ("updated_at", "requested_at"):
        dt = _parse_iso(data.get(key))
        if dt is not None:
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    return None


def labwatch_apply_helper_running() -> bool | None:
    """True if the host apply helper container is alive. None if Docker is unavailable."""
    if not Path("/var/run/docker.sock").exists():
        return None
    try:
        status, body = _docker_api("GET", "/v1.41/containers/labwatch-apply/json")
        if status == 404:
            return False
        if status >= 300 or not isinstance(body, dict):
            return None
        state = body.get("State") or {}
        return bool(state.get("Running"))
    except Exception:  # noqa: BLE001
        return None


def kill_apply_helper() -> None:
    """Force-remove the host apply helper container if present."""
    if not Path("/var/run/docker.sock").exists():
        return
    try:
        _docker_api("DELETE", "/v1.41/containers/labwatch-apply?force=true")
    except Exception:  # noqa: BLE001
        logger.warning("Could not remove labwatch-apply helper", exc_info=True)


def clear_apply_request() -> None:
    try:
        request_path().unlink(missing_ok=True)
    except TypeError:
        # Python <3.8 missing_ok fallback (agent hosts only; server is 3.12+)
        path = request_path()
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("Could not clear update-request.json", exc_info=True)


def _append_apply_log(line: str) -> None:
    try:
        with apply_log_path().open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except OSError:
        logger.warning("Could not append update-apply.log", exc_info=True)


def detect_apply_stuck(data: dict[str, Any]) -> tuple[bool, str]:
    """Return (stuck, reason) for an in-flight apply."""
    state = str(data.get("state") or "")
    if state not in ACTIVE_APPLY_STATES:
        return False, ""
    age = _apply_age_seconds(data)
    if age is None:
        return False, ""
    helper = labwatch_apply_helper_running()
    if state == "queued" and age >= STUCK_QUEUED_SEC:
        return True, f"Queued for {int(age // 60)}m with no host apply start"
    if age >= STUCK_MAX_AGE_SEC:
        return True, f"Apply exceeded {STUCK_MAX_AGE_SEC // 60} minute limit"
    if state == "running" and helper is False and age >= STUCK_NO_HELPER_SEC:
        return True, "Host apply helper exited but status never finished"
    return False, ""


def resolve_stuck_apply(reason: str) -> dict[str, Any]:
    """Mark a hung apply as error and unlock the Updates UI."""
    kill_apply_helper()
    clear_apply_request()
    msg = f"Apply stuck — {reason}. Reset done; you can run Updates again."
    _append_apply_log(f"===== {utcnow_iso()} auto-unstuck: {reason} =====")
    return write_status(
        state="error",
        message=msg,
        progress=0,
        step="stuck",
        finished_at=utcnow_iso(),
        stuck=False,
        can_cancel=False,
    )


def cancel_apply(username: str, *, reason: str | None = None) -> dict[str, Any]:
    """Stop a queued/running apply so a new one can be started."""
    current = _read_status_file()
    state = str(current.get("state") or "idle")
    tag = current.get("tag")
    kill_apply_helper()
    clear_apply_request()
    detail = reason or f"Cancelled by {username}"
    _append_apply_log(f"===== {utcnow_iso()} cancel by {username}: {detail} =====")
    if state not in ACTIVE_APPLY_STATES and state not in {"error", "ok", "cancelled"}:
        return write_status(
            state="idle",
            message="",
            progress=None,
            step="",
            tag=None,
            finished_at=None,
            stuck=False,
            can_cancel=False,
        )
    return write_status(
        state="cancelled",
        message=f"{detail}" + (f" (was {tag})" if tag else ""),
        progress=0,
        step="cancelled",
        finished_at=utcnow_iso(),
        stuck=False,
        can_cancel=False,
    )


def _read_status_file() -> dict[str, Any]:
    path = status_path()
    if not path.is_file():
        return dict(IDLE_STATUS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**IDLE_STATUS, **data}
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read update status")
    return dict(IDLE_STATUS)


def read_status() -> dict[str, Any]:
    data = _read_status_file()
    # Auto-unlock hung installs so Admins are not permanently blocked.
    stuck, reason = detect_apply_stuck(data)
    if stuck:
        data = resolve_stuck_apply(reason)
    else:
        state = str(data.get("state") or "")
        data["stuck"] = False
        data["can_cancel"] = state in ACTIVE_APPLY_STATES
    log = read_apply_log()
    data["log_tail"] = log
    data["log"] = log
    # Infer rough progress if older apply scripts did not write percent.
    if data.get("progress") is None and (data.get("state") or "") in ACTIVE_APPLY_STATES:
        msg = (data.get("message") or "").lower()
        if data.get("state") == "queued":
            data["progress"] = 5
            data["step"] = data.get("step") or "queued"
        elif "fetch" in msg:
            data["progress"] = 20
            data["step"] = data.get("step") or "fetch"
        elif "rebuild" in msg or "compose" in msg or "docker" in msg:
            data["progress"] = 55
            data["step"] = data.get("step") or "rebuild"
        elif "started" in msg:
            data["progress"] = 12
            data["step"] = data.get("step") or "start"
        else:
            data["progress"] = 35
            data["step"] = data.get("step") or "running"
    elif data.get("state") == "ok" and data.get("progress") is None:
        data["progress"] = 100
    elif data.get("state") in {"error", "cancelled"} and data.get("progress") is None:
        data["progress"] = 0
    return data


def write_status(**fields: Any) -> dict[str, Any]:
    current = _read_status_file()
    current.update(fields)
    current["updated_at"] = utcnow_iso()
    # Do not persist the live log blob / ephemeral UI flags inside status JSON.
    current.pop("log", None)
    current.pop("stuck", None)
    current.pop("can_cancel", None)
    path = status_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    tmp.replace(path)
    return read_status()


def write_request(tag: str, username: str) -> None:
    payload = {
        "tag": normalize_tag(tag),
        "requested_by": username,
        "requested_at": utcnow_iso(),
    }
    path = request_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def redact_secrets(text: str) -> str:
    return SECRET_IN_URL.sub("://***:***@", str(text or ""))


def _proxy_url(username: str | None = None, password: str | None = None) -> str | None:
    settings = get_settings()
    raw = ""
    for value in (settings.https_proxy, settings.http_proxy):
        if value and value.strip():
            raw = value.strip()
            break
    user = (username or "").strip()
    if not raw:
        if not user:
            return None
        raw = CAMPUS_PROXY
    parts = urlsplit(raw)
    scheme = parts.scheme or "http"
    host = parts.hostname or "10.10.78.21"
    port = parts.port or (443 if scheme == "https" else 3128)
    netloc = f"{host}:{port}" if port else host
    if user:
        netloc = f"{quote(user, safe='')}:{quote(password or '', safe='')}@{netloc}"
    return urlunsplit((scheme, netloc, parts.path or "", "", ""))


def _extract_session_id(html: str) -> str | None:
    match = SESSION_RE.search(html or "")
    if not match:
        return None
    return match.group(1) or match.group(2)


async def campus_proxy_cgi_login(username: str, password: str) -> str:
    """Authenticate this host on IITD squid via proxy.cgi (IP session; not HTTP Basic).

    The CGI page must be hit *without* HTTP(S)_PROXY, otherwise squid loops 302→proxy.cgi.
    After success, outbound CONNECT via CAMPUS_PROXY works until the session expires.
    """
    user = (username or "").strip()
    if not user:
        raise RuntimeError("Proxy username is required")
    if not password:
        raise RuntimeError("Proxy password is required")
    settings = get_settings()
    cgi = (settings.proxy_cgi_url or "").strip() or "https://proxy21.iitd.ac.in/cgi-bin/proxy.cgi"

    # trust_env=False: never send CGI through squid (that is the 302 failure mode).
    async with httpx.AsyncClient(timeout=25.0, trust_env=False, follow_redirects=True, verify=False) as client:
        page = await client.get(cgi)
        page.raise_for_status()
        session_id = _extract_session_id(page.text)
        if not session_id:
            raise RuntimeError(
                "Could not read proxy.cgi session id. Check LABWATCH_PROXY_CGI / campus network."
            )
        response = await client.post(
            cgi,
            data={
                "sessionid": session_id,
                "action": "Validate",
                "userid": user,
                "pass": password,
            },
        )
        response.raise_for_status()
        body = response.text or ""

    low = body.lower()
    if "logged in successfully" in low or "already logged in" in low:
        logger.info("Campus proxy.cgi login ok for user=%s", user)
        return session_id
    if "does'not match" in low or "does not match" in low or ("invalid" in low and "password" in low):
        raise RuntimeError("Campus proxy rejected the login. Check username and password.")
    if "session expired" in low:
        raise RuntimeError("Campus proxy session expired; try Fetch again.")
    raise RuntimeError(
        "Campus proxy login failed (unexpected proxy.cgi response). "
        "Confirm IITD kerberos id/password and proxy category (proxy21)."
    )


async def _http_get_releases(url: str, headers: dict[str, str], limit: int, proxy: str | None) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=25.0, proxy=proxy, follow_redirects=True, trust_env=False) as client:
            response = await client.get(url, headers=headers, params={"per_page": max(limit, 10)})
    except httpx.ProxyError as exc:
        msg = str(exc)
        if "302" in msg or "Moved Temporarily" in msg or "proxy.cgi" in msg.lower():
            raise RuntimeError(
                "Campus proxy returned 302 (not logged in). "
                "Enter IITD proxy username/password so LabWatch can complete proxy.cgi login."
            ) from exc
        raise RuntimeError(f"Campus proxy CONNECT failed: {redact_secrets(msg)}") from exc
    content_type = response.headers.get("content-type", "")
    location = response.headers.get("location", "")
    if response.status_code == 302 or "proxy.cgi" in location.lower():
        raise RuntimeError(
            "Campus proxy returned 302 to proxy.cgi — login required. "
            "Use Updates proxy username/password (IITD kerberos)."
        )
    if response.status_code in {401, 407} or "html" in content_type.lower():
        if proxy:
            raise RuntimeError(
                "Campus proxy rejected the request (HTML/407). "
                "Re-enter IITD proxy credentials and Fetch again."
            )
        raise RuntimeError("GitHub returned a non-JSON response (direct fetch blocked).")
    response.raise_for_status()
    try:
        rows = response.json()
    except Exception as exc:  # noqa: BLE001
        if proxy:
            raise RuntimeError("GitHub fetch did not return JSON. Check proxy username and password.") from exc
        raise RuntimeError("GitHub fetch did not return JSON over direct connection.") from exc
    if not isinstance(rows, list):
        raise ValueError("GitHub releases response was not a list")
    releases = []
    for row in rows:
        if row.get("draft"):
            continue
        tag = normalize_tag(str(row.get("tag_name") or ""))
        if not tag:
            continue
        releases.append(
            {
                "tag": tag,
                "name": row.get("name") or tag,
                "published_at": row.get("published_at"),
                "html_url": row.get("html_url"),
                "notes": (row.get("body") or "").strip(),
                "prerelease": bool(row.get("prerelease")),
            }
        )
        if len(releases) >= limit:
            break
    return releases


async def fetch_github_releases(
    limit: int | None = None,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch releases. Tries direct first when no proxy user is given; otherwise uses campus proxy."""
    settings = get_settings()
    limit = limit or settings.updates_builds
    url = f"{settings.github_api.rstrip('/')}/repos/{settings.github_repo}/releases"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"LabWatch/{current_version()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    user = (proxy_user or "").strip()
    if user:
        # IITD squid: CGI login binds this host IP; do NOT put Basic Auth in the proxy URL
        # (that path gets CONNECT 302 → proxy.cgi).
        await campus_proxy_cgi_login(user, proxy_password or "")
        proxy = _proxy_url(None, None) or CAMPUS_PROXY
        releases = await _http_get_releases(url, headers, limit, proxy)
    else:
        # Prefer direct GitHub; only fall back to env proxy (no credentials) if configured.
        try:
            releases = await _http_get_releases(url, headers, limit, None)
        except Exception as direct_exc:  # noqa: BLE001
            env_proxy = _proxy_url(None, None)
            if not env_proxy:
                raise direct_exc
            try:
                releases = await _http_get_releases(url, headers, limit, env_proxy)
            except Exception:
                raise direct_exc from None
    cache_path().write_text(json.dumps({"fetched_at": utcnow_iso(), "releases": releases}, indent=2), encoding="utf-8")
    return releases


def load_cached_releases() -> list[dict[str, Any]]:
    path = cache_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("releases") if isinstance(payload, dict) else payload
        return rows if isinstance(rows, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def annotate_builds(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    running = current_tag()
    latest_tag = releases[0]["tag"] if releases else None
    builds = []
    for index, row in enumerate(releases):
        tag = normalize_tag(row["tag"])
        action = "reinstall"
        if tag == running:
            action = "current"
        elif version_tuple(tag) > version_tuple(running):
            action = "update"
        elif version_tuple(tag) < version_tuple(running):
            action = "downgrade"
        builds.append(
            {
                **row,
                "tag": tag,
                "is_current": tag == running,
                "is_latest": tag == latest_tag or index == 0,
                "action": action,
            }
        )
    return builds


def _catalog_payload(
    *,
    releases: list[dict[str, Any]],
    source: str,
    error: str | None,
    used_proxy: bool,
    proxy_required: bool,
) -> dict[str, Any]:
    settings = get_settings()
    builds = annotate_builds(releases[: settings.updates_builds])
    latest = next((b for b in builds if b.get("is_latest")), None)
    current = next((b for b in builds if b.get("is_current")), None)
    return {
        "enabled": settings.updates_enabled,
        "github_repo": settings.github_repo,
        "github_url": f"https://github.com/{settings.github_repo}",
        "current": {
            "version": current_version(),
            "tag": current_tag(),
            "in_catalog": bool(current),
        },
        "latest": {"tag": latest["tag"], "name": latest["name"]} if latest else None,
        "builds": builds,
        "source": source,
        "source_error": error,
        "needs_fetch": source not in {"github", "cache"},
        "used_proxy": used_proxy,
        "proxy_required": proxy_required,
        "direct_ok": source == "github" and not used_proxy,
        "apply_ready": apply_ready(),
        "status": read_status(),
    }


async def list_builds(
    *,
    live: bool = False,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    source = "idle"
    error = None
    releases: list[dict[str, Any]] = []
    used_proxy = bool((proxy_user or "").strip())
    if live:
        try:
            releases = await fetch_github_releases(
                settings.updates_builds,
                proxy_user=proxy_user,
                proxy_password=proxy_password,
            )
            source = "github"
        except Exception as exc:  # noqa: BLE001 — surface GitHub/proxy failures to the admin UI
            logger.warning("GitHub releases fetch failed: %s", redact_secrets(str(exc)))
            error = redact_secrets(str(exc))
            source = "unavailable"
            cached = load_cached_releases()
            if cached:
                releases = cached
                source = "cache"
    else:
        releases = load_cached_releases()
        if releases:
            source = "cache"
    fetched_via_proxy = bool(used_proxy and source == "github")
    # Fetch button only needed when direct GitHub is not available.
    proxy_required = not (source == "github" and not fetched_via_proxy)
    return _catalog_payload(
        releases=releases,
        source=source,
        error=error,
        used_proxy=fetched_via_proxy,
        proxy_required=proxy_required,
    )


def cached_catalog() -> dict[str, Any]:
    settings = get_settings()
    releases = load_cached_releases()[: settings.updates_builds]
    builds = annotate_builds(releases)
    latest = next((b for b in builds if b.get("is_latest")), None)
    current = next((b for b in builds if b.get("is_current")), None)
    return {
        "builds": builds,
        "latest": {"tag": latest["tag"], "name": latest["name"]} if latest else None,
        "current": {
            "version": current_version(),
            "tag": current_tag(),
            "in_catalog": bool(current),
        },
    }


def allowed_tags_from_cache() -> set[str]:
    return {normalize_tag(str(row.get("tag") or "")) for row in cached_catalog()["builds"] if row.get("tag")}


def apply_ready() -> dict[str, Any]:
    repo = repo_dir()
    docker = _which("docker")
    git = _which("git")
    sock = Path("/var/run/docker.sock").exists()
    script = repo / "scripts" / "linux" / "apply-requested-update.sh"
    return {
        "repo_dir": str(repo),
        "repo_exists": repo.is_dir(),
        "git_dir": (repo / ".git").exists(),
        "apply_script": script.is_file(),
        "docker_cli": bool(docker),
        "git_cli": bool(git),
        "docker_sock": sock,
        "can_spawn": bool(sock and repo.is_dir() and script.is_file()),
        "host_watcher": Path("/etc/systemd/system/labwatch-updater.path").is_file(),
    }


def _which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def validate_tag(tag: str, allowed: set[str] | None = None) -> str:
    tag = normalize_tag(tag)
    if not TAG_RE.match(tag):
        raise ValueError("Tag must look like v1.2.3")
    if allowed is not None and tag not in allowed:
        raise ValueError("Select one of the last 3 GitHub builds")
    return tag


def start_apply(
    tag: str,
    username: str,
    allowed_tags: set[str] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.updates_enabled:
        raise RuntimeError("Updates are disabled")
    tag = validate_tag(tag, allowed_tags)
    current = read_status()
    state = str(current.get("state") or "")
    if state in ACTIVE_APPLY_STATES:
        if current.get("stuck") or force:
            cancel_apply(username, reason=f"Superseded by new apply to {tag}")
        else:
            raise RuntimeError(
                f"Update already {state} for {current.get('tag')}. "
                "Cancel it first, or wait — stuck runs auto-reset after a few minutes."
            )
    running = current_tag()
    action = "reinstall"
    if version_tuple(tag) > version_tuple(running):
        action = "update"
    elif version_tuple(tag) < version_tuple(running):
        action = "downgrade"
    write_request(tag, username)
    # Truncate previous apply log so the UI terminal starts clean for this run.
    try:
        apply_log_path().write_text(
            f"===== {utcnow_iso()} queue {action} {tag} by {username} =====\n",
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Could not reset update-apply.log")
    write_status(
        state="queued",
        tag=tag,
        action=action,
        message=f"{action.title()} to {tag} queued by {username}",
        requested_at=utcnow_iso(),
        finished_at=None,
        log_tail="",
        requested_by=username,
        progress=5,
        step="queued",
    )
    spawned = spawn_host_apply(tag)
    if not spawned:
        write_status(
            state="queued",
            progress=8,
            step="waiting-host",
            message=(
                f"{action.title()} to {tag} is waiting for the host updater. "
                "On the server run: sudo ./scripts/linux/install-host-updater.sh"
            ),
        )
    return read_status()


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost")
        self._unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(self._unix_path)
        self.sock = sock


def _docker_api(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    conn = _UnixHTTPConnection("/var/run/docker.sock")
    payload = json.dumps(body) if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    parsed: Any = None
    if raw:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", "replace")
    return response.status, parsed


def spawn_host_apply(tag: str) -> bool:
    """Start apply outside the API cgroup so compose restart cannot kill it."""
    repo = repo_dir()
    script = repo / "scripts" / "linux" / "apply-requested-update.sh"
    if Path("/var/run/docker.sock").exists() and script.is_file():
        try:
            _docker_api("DELETE", "/v1.41/containers/labwatch-apply?force=true")
            status, created = _docker_api(
                "POST",
                "/v1.41/containers/create?name=labwatch-apply",
                {
                    "Image": "python:3.12-slim",
                    "Cmd": ["chroot", "/host", "/bin/sh", str(script), tag],
                    "Env": [
                        f"LABWATCH_REPO_DIR={repo}",
                        f"LABWATCH_TARGET_TAG={tag}",
                    ],
                    "HostConfig": {
                        "Privileged": True,
                        "PidMode": "host",
                        "Binds": ["/:/host"],
                        "AutoRemove": True,
                    },
                },
            )
            if status >= 300:
                raise RuntimeError(f"container create failed ({status}): {created}")
            cid = created.get("Id") if isinstance(created, dict) else None
            start_status, start_body = _docker_api("POST", f"/v1.41/containers/{cid}/start")
            if start_status >= 300:
                raise RuntimeError(f"container start failed ({start_status}): {start_body}")
            write_status(
                state="running",
                progress=12,
                step="host-apply",
                message=f"Host apply started for {tag}",
                log_tail=str(cid),
            )
            logger.info("Spawned host apply container %s", cid)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Docker engine apply helper failed: %s", exc)
    if script.is_file() and _which("git") and _which("docker"):
        log = data_dir() / "update-apply.log"
        handle = log.open("a", encoding="utf-8")
        subprocess.Popen(
            ["/bin/sh", str(script), tag],
            cwd=str(repo),
            start_new_session=True,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, "LABWATCH_REPO_DIR": str(repo), "LABWATCH_TARGET_TAG": tag},
        )
        return True
    return False


def watch_forever(poll_seconds: float = 4.0) -> None:
    logger.info("LabWatch updater watching %s", request_path())
    while True:
        path = request_path()
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                tag = normalize_tag(str(payload.get("tag") or ""))
                state = read_status().get("state")
                if tag and state == "queued":
                    if not spawn_host_apply(tag):
                        logger.warning("Update %s queued but no apply backend is available", tag)
            except Exception:
                logger.exception("Updater failed to process request")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    watch_forever()
