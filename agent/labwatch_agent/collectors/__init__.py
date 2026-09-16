from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone
from typing import Any

from labwatch_agent.collectors import linux as linux_col
from labwatch_agent.collectors import windows as win_col
from labwatch_agent.collectors.linux import collect_identity, collect_network


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_inventory(agent_uuid: str) -> tuple[dict[str, Any], list[str]]:
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
        pcie = safe("pcie", win_col.collect_pcie_windows, {"topology_status": "UNKNOWN", "slots": [], "topology_note": "Physical slot topology not exposed by firmware/OS"})
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
            gpus, gpu_notes = linux_col.collect_gpus_linux()
        except Exception as exc:
            errors.append(f"gpu: {exc}")
            gpus, gpu_notes = [], [str(exc)]
        pcie = safe("pcie", linux_col.collect_pcie_linux, {"topology_status": "UNKNOWN", "slots": [], "topology_note": "Physical slot topology not exposed by firmware/OS"})
        storage = safe("storage", linux_col.collect_storage_linux, {"disks": [], "filesystems": [], "notes": []})
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
