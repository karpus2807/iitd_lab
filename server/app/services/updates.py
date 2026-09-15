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
IDLE_STATUS = {
    "state": "idle",
    "tag": None,
    "message": "",
    "requested_at": None,
    "finished_at": None,
    "log_tail": "",
}


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


def read_status() -> dict[str, Any]:
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


def write_status(**fields: Any) -> dict[str, Any]:
    current = read_status()
    current.update(fields)
    path = status_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    tmp.replace(path)
    return current


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


async def fetch_github_releases(
    limit: int | None = None,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    limit = limit or settings.updates_builds
    url = f"{settings.github_api.rstrip('/')}/repos/{settings.github_repo}/releases"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"LabWatch/{current_version()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    proxy = _proxy_url(proxy_user, proxy_password)
    async with httpx.AsyncClient(timeout=25.0, proxy=proxy, follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params={"per_page": max(limit, 10)})
        content_type = response.headers.get("content-type", "")
        if response.status_code in {401, 407} or "html" in content_type.lower():
            raise RuntimeError("Campus proxy rejected the login. Check username and password.")
        response.raise_for_status()
        try:
            rows = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("GitHub fetch did not return JSON. Check proxy username and password.") from exc
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
        "needs_fetch": source != "github",
        "apply_ready": apply_ready(),
        "status": read_status(),
    }


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


def start_apply(tag: str, username: str, allowed_tags: set[str] | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.updates_enabled:
        raise RuntimeError("Updates are disabled")
    tag = validate_tag(tag, allowed_tags)
    running = current_tag()
    action = "reinstall"
    if version_tuple(tag) > version_tuple(running):
        action = "update"
    elif version_tuple(tag) < version_tuple(running):
        action = "downgrade"
    write_request(tag, username)
    write_status(
        state="queued",
        tag=tag,
        action=action,
        message=f"{action.title()} to {tag} queued by {username}",
        requested_at=utcnow_iso(),
        finished_at=None,
        log_tail="",
        requested_by=username,
    )
    spawned = spawn_host_apply(tag)
    if not spawned:
        write_status(
            state="queued",
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
            write_status(state="running", message=f"Host apply started for {tag}", log_tail=str(cid))
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
