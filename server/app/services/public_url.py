"""Reach hobbit by DNS hostname (Wi-Fi and LAN), never by a LAN-only IP."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from app.config import get_settings

DEFAULT_PUBLIC_HOST = "hobbit2.cse.iitd.ac.in"
INVENTORY_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}(/[A-Za-z0-9][A-Za-z0-9._-]{0,31}){1,5}$"
)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def hostname_server_url(request: Request | None = None) -> str:
    settings = get_settings()
    raw = (settings.public_url or "").strip()
    host = DEFAULT_PUBLIC_HOST
    scheme = "http"
    port: int | None = None
    if raw:
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        scheme = parsed.scheme or "http"
        if parsed.hostname and not _is_ip(parsed.hostname):
            host = parsed.hostname
        if parsed.port:
            port = parsed.port
    elif request is not None:
        forwarded = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").strip()
        host_part = forwarded.split(",")[0].strip()
        if ":" in host_part and not host_part.startswith("["):
            name, maybe_port = host_part.rsplit(":", 1)
            if maybe_port.isdigit():
                port = int(maybe_port)
                host_part = name
        if host_part and not _is_ip(host_part):
            host = host_part
        proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        if proto:
            scheme = proto
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def normalize_inventory_id(raw: str) -> str:
    value = (raw or "").strip()
    if not INVENTORY_RE.match(value):
        raise HTTPException(
            400,
            "Machine ID must look like 12345/2012/12 (letters, digits, and slashes)",
        )
    return value
