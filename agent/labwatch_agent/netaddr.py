"""Host address helpers. IP is never a machine identity — only a displayed attribute."""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable

SKIP_IFACE_PREFIXES = (
    "lo",
    "docker",
    "veth",
    "br-",
    "virbr",
    "cni",
    "flannel",
    "kube",
    "vmnet",
    "vboxnet",
)


def _iface_skipped(name: str) -> bool:
    low = name.lower()
    return any(low == p or low.startswith(p) for p in SKIP_IFACE_PREFIXES)


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


def normalize_ips(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        ip = _clean_ip(raw)
        if ip and ip not in seen:
            seen.append(ip)
    return seen


def primary_ip(ips: list[str]) -> str | None:
    """Prefer a private IPv4 LAN address; never loopback."""
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


def collect_host_addresses() -> dict:
    """Live IPs/MACs from attached NICs. Changes when the machine switches LAN."""
    import psutil

    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    ips: list[str] = []
    macs: list[str] = []
    for name, addr_list in addrs.items():
        if _iface_skipped(name):
            continue
        st = stats.get(name)
        if st is not None and not st.isup:
            continue
        for a in addr_list:
            if a.family == socket.AF_INET or a.family == socket.AF_INET6:
                ip = _clean_ip(a.address)
                if ip and ip not in ips:
                    ips.append(ip)
            elif getattr(psutil, "AF_LINK", None) == a.family or str(a.family) in {"AddressFamily.AF_PACKET", "AddressFamily.AF_LINK"}:
                mac = (a.address or "").lower()
                if mac and mac not in {"00:00:00:00:00:00", ""} and mac not in macs:
                    macs.append(mac)
    return {"ip_addresses": ips, "primary_ip": primary_ip(ips), "mac_addresses": macs}
