from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any


UNKNOWN = "Unknown / Not reported"


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run_cmd(args: list[str], timeout: int = 12) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 1, "", str(exc)


def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except OSError:
        return None


def read_int(path: str) -> int | None:
    raw = read_text(path)
    if raw is None:
        return None
    try:
        return int(raw.split()[0])
    except (TypeError, ValueError):
        return None


def parse_size_to_bytes(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().lower().replace(",", "")
    if text in {"no module installed", "unknown", "none", "not specified"}:
        return None
    multipliers = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    parts = text.replace(":", " ").split()
    num = None
    unit = "b"
    for p in parts:
        try:
            num = float(p)
            continue
        except ValueError:
            if p in multipliers:
                unit = p
    if num is None:
        # e.g. "16384 MB"
        return None
    return int(num * multipliers.get(unit, 1))


def parse_dmi_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    last_key = None
    for line in text.splitlines():
        if line.startswith("Handle "):
            if current:
                blocks.append(current)
            current = {"_handle": line.strip(), "_type": None, "_values": {}}
            last_key = None
            continue
        if current is None:
            continue
        if current["_type"] is None and line.strip() and not line.startswith("\t"):
            current["_type"] = line.strip()
            continue
        if line.startswith("\t\t") and last_key:
            current["_values"].setdefault(last_key, [])
            if not isinstance(current["_values"][last_key], list):
                current["_values"][last_key] = [current["_values"][last_key]]
            current["_values"][last_key].append(line.strip())
            continue
        if line.startswith("\t") and ":" in line:
            key, val = line.strip().split(":", 1)
            last_key = key.strip()
            current["_values"][last_key] = val.strip()
    if current:
        blocks.append(current)
    return blocks


def dmi_get(block: dict[str, Any], key: str) -> str | None:
    val = block.get("_values", {}).get(key)
    if val is None:
        return None
    if isinstance(val, list):
        val = ", ".join(val)
    val = str(val).strip()
    if val.lower() in {"", "unknown", "none", "not specified", "not provided", "to be filled by o.e.m.", "0", "[empty]", "empty"}:
        return None
    return val


def is_virtual_from_dmi(sys_vendor: str | None, product: str | None, bios_vendor: str | None) -> tuple[bool, str | None]:
    blob = " ".join(x.lower() for x in [sys_vendor or "", product or "", bios_vendor or ""])
    mapping = [
        ("kvm", "KVM"),
        ("qemu", "QEMU"),
        ("vmware", "VMware"),
        ("virtualbox", "VirtualBox"),
        ("xen", "Xen"),
        ("hyper-v", "Hyper-V"),
        ("microsoft corporation", "Hyper-V"),
        ("parallels", "Parallels"),
        ("bhyve", "bhyve"),
        ("openstack", "OpenStack"),
        ("amazon", "Amazon EC2"),
        ("google", "Google Compute Engine"),
    ]
    for needle, label in mapping:
        if needle in blob:
            if needle == "microsoft corporation" and "virtual" not in blob and "hyper" not in blob:
                continue
            return True, label
    if "virtual" in blob:
        return True, product or "Virtual machine"
    return False, None
