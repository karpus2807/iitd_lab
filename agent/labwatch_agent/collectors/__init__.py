from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from labwatch_agent.collectors import linux as linux_col
from labwatch_agent.collectors import windows as win_col
from labwatch_agent.collectors.linux import collect_identity, collect_network


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_inventory(agent_uuid: str, *, full: bool = True) -> tuple[dict[str, Any], list[str]]:
    """Collect hardware inventory.

    full=True (default hourly): dmidecode, SMART, full GPU identity.
    full=False: lighter path for rare forced refresh without SMART / live GPU sampling.
    Live CPU/RAM/GPU util belongs in collect_metrics(), not here.
    """
    errors: list[str] = []
    notes: list[str] = []

    def safe(label: str, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            notes.append(f"{label} collector failed; partial data returned.")
            return fallback

    if os.name == "nt":
        # Full CIM refresh is expensive — only on full inventory ticks.
        if full:
            win_col.refresh_cim()
        osinfo = safe("os", win_col.collect_os_windows, {"name": "Windows", "hostname": "unknown"})
        try:
            cpu, cpu_notes = win_col.collect_cpu_windows()
        except Exception as exc:
            errors.append(f"cpu: {exc}")
            cpu, cpu_notes = {}, [str(exc)]
        try:
            memory, mem_notes = win_col.collect_memory_windows()
        except Exception as exc:
            errors.append(f"memory: {exc}")
            memory, mem_notes = {"topology_status": "UNKNOWN", "modules": [], "notes": [str(exc)]}, [str(exc)]
        system = safe("system", win_col.collect_system_windows, {"motherboard": {}, "bios": {}, "is_virtual": False})
        try:
            gpus, gpu_notes = win_col.collect_gpus_windows()
        except Exception as exc:
            errors.append(f"gpu: {exc}")
            gpus, gpu_notes = [], [str(exc)]
        pcie = safe(
            "pcie",
            win_col.collect_pcie_windows,
            {"topology_status": "UNKNOWN", "slots": [], "topology_note": "Physical slot topology not exposed by firmware/OS"},
        )
        storage = safe("storage", win_col.collect_storage_windows, {"disks": [], "filesystems": [], "notes": []})
        notes.extend(cpu_notes + mem_notes + gpu_notes)
    elif os.name == "posix":
        osinfo = safe("os", linux_col.linux_os, {"name": "Linux"})
        try:
            cpu, cpu_notes = linux_col.collect_cpu_linux()
        except Exception as exc:
            errors.append(f"cpu: {exc}")
            cpu, cpu_notes = {}, [str(exc)]
        try:
            memory, mem_notes = linux_col.collect_memory_linux()
        except Exception as exc:
            errors.append(f"memory: {exc}")
            memory, mem_notes = {"topology_status": "UNKNOWN", "modules": [], "notes": [str(exc)]}, [str(exc)]
        system = safe("system", linux_col.collect_system_linux, {"motherboard": {}, "bios": {}, "is_virtual": False})
        try:
            gpus, gpu_notes = linux_col.collect_gpus_linux(include_live=False)
        except Exception as exc:
            errors.append(f"gpu: {exc}")
            gpus, gpu_notes = [], [str(exc)]
        if full:
            pcie = safe(
                "pcie",
                linux_col.collect_pcie_linux,
                {"topology_status": "UNKNOWN", "slots": [], "topology_note": "Physical slot topology not exposed by firmware/OS"},
            )
            storage = safe(
                "storage",
                lambda: linux_col.collect_storage_linux(include_smart=True),
                {"disks": [], "filesystems": [], "notes": []},
            )
        else:
            pcie = {
                "topology_status": "SKIPPED",
                "slots": [],
                "topology_note": "PCIe slot map skipped on light inventory",
                "notes": ["light inventory"],
            }
            storage = safe(
                "storage",
                lambda: linux_col.collect_storage_linux(include_smart=False),
                {"disks": [], "filesystems": [], "notes": []},
            )
            notes.append("Light inventory: skipped SMART and PCIe dmidecode (full scan hourly).")
        notes.extend(cpu_notes + mem_notes + gpu_notes)
    else:
        raise RuntimeError(f"Unsupported OS: {os.name}. LabWatch agent supports Linux and Windows (macOS later).")

    net = safe("network", collect_network, {"interfaces": [], "macs": [], "hostname": osinfo.get("hostname")})
    identity = collect_identity(agent_uuid, system, net, osinfo)
    payload = {
        "collected_at": _now(),
        "identity": identity,
        "os": osinfo,
        "cpu": cpu,
        "memory": memory,
        "gpus": gpus,
        "pcie": pcie,
        "storage": storage,
        "network": {"hostname": net.get("hostname"), "interfaces": net.get("interfaces", []), "notes": net.get("notes", [])},
        "motherboard": system.get("motherboard") or {},
        "bios": system.get("bios") or {},
        "collection_notes": notes + errors,
    }
    return payload, errors


def inventory_static_fingerprint(payload: dict[str, Any]) -> str:
    """Hash of fields that should not change without a hardware swap."""
    static = {
        "identity": {
            k: (payload.get("identity") or {}).get(k)
            for k in ("machine_uuid", "system_uuid", "motherboard_serial", "system_serial", "hostname")
        },
        "cpu": {
            k: (payload.get("cpu") or {}).get(k)
            for k in ("model", "manufacturer", "physical_cores", "logical_processors")
        },
        "memory_modules": [
            {k: m.get(k) for k in ("slot_locator", "serial_number", "part_number", "capacity_bytes", "manufacturer")}
            for m in ((payload.get("memory") or {}).get("modules") or [])
        ],
        "gpus": [
            {k: g.get(k) for k in ("vendor", "model", "pci_bus", "pci_device_id", "serial_number", "uuid", "vram_bytes", "driver_version")}
            for g in (payload.get("gpus") or [])
        ],
        "disks": [
            {k: d.get(k) for k in ("name", "model", "serial_number", "capacity_bytes")}
            for d in ((payload.get("storage") or {}).get("disks") or [])
        ],
        "motherboard": {
            k: (payload.get("motherboard") or {}).get(k) for k in ("manufacturer", "product_name", "serial_number")
        },
        "bios": {k: (payload.get("bios") or {}).get(k) for k in ("vendor", "version")},
    }
    blob = json.dumps(static, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def collect_metrics(prev=None) -> tuple[dict[str, Any], dict]:
    prev = prev or {}
    try:
        if os.name == "nt":
            payload, nxt = win_col.collect_metrics_windows(prev.get("net"), prev.get("disk"), prev.get("ts"))
        else:
            payload, nxt = linux_col.collect_metrics(prev.get("net"), prev.get("disk"), prev.get("ts"))
        payload["collected_at"] = _now()
        return payload, nxt
    except Exception:
        return {"collected_at": _now(), "gpus": []}, {}
