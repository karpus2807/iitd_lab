"""IP addresses are display attributes only — never machine identity."""

from __future__ import annotations

import ipaddress
from typing import Iterable


def _clean_ip(raw: str) -> str | None:
    value = (raw or "").split("%")[0].strip()
    if not value:
        return None
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        return None
    return str(addr)


def normalize_ips(values: Iterable[str] | None) -> list[str]:
    seen: list[str] = []
    for raw in values or []:
        ip = _clean_ip(str(raw))
        if ip and ip not in seen:
            seen.append(ip)
    return seen


def primary_ip(ips: list[str]) -> str | None:
    ipv4_private: list[str] = []
    ipv4_global: list[str] = []
    ipv6: list[str] = []
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_unspecified or addr.is_multicast or addr.is_link_local:
            continue
        if addr.version == 4 and addr.is_private:
            ipv4_private.append(ip)
        elif addr.version == 4:
            ipv4_global.append(ip)
        else:
            ipv6.append(ip)
    for group in (ipv4_private, ipv4_global, ipv6):
        if group:
            return group[0]
    return None
