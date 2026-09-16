from __future__ import annotations

import json
import os
import platform
import socket
from typing import Any

import psutil

from labwatch_agent.parsers.nvidia import parse_nvidia_smi_csv
from labwatch_agent.util import is_virtual_from_dmi, run_cmd, which

CIM_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = [ordered]@{
  computer = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, TotalPhysicalMemory, NumberOfProcessors, HypervisorPresent, PCSystemType
  os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, LastBootUpTime, MaxProcessMemorySize
  bios = Get-CimInstance Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate, SerialNumber
  baseboard = Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, SerialNumber, Version
  csprod = Get-CimInstance Win32_ComputerSystemProduct | Select-Object UUID, Name, Vendor, IdentifyingNumber
  processors = @(Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed, CurrentClockSpeed, SocketDesignation, Family)
  memarray = @(Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices, MaxCapacity, MaxCapacityEx)
  memory = @(Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel, DeviceLocator, Capacity, Manufacturer, PartNumber, SerialNumber, Speed, ConfiguredClockSpeed, MemoryType, FormFactor, DataWidth, TotalWidth)
  disks = @(Get-CimInstance Win32_DiskDrive | Select-Object DeviceID, Model, SerialNumber, Size, InterfaceType, MediaType, Status)
  nics = @(Get-CimInstance Win32_NetworkAdapter | Where-Object { $_.PhysicalAdapter -eq $true } | Select-Object Name, MACAddress, Speed, NetEnabled, AdapterType, PNPDeviceID, NetConnectionStatus)
  niccfg = @(Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.MACAddress } | Select-Object Description, MACAddress, IPAddress)
  video = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion, PNPDeviceID, VideoProcessor, CurrentRefreshRate)
}
$out | ConvertTo-Json -Compress -Depth 6
"""


def _cim() -> dict[str, Any]:
    code, out, err = run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-Command", CIM_SCRIPT], timeout=30)
    if code != 0 or not out.strip():
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def collect_os_windows() -> dict[str, Any]:
    import time

    data = _cached_cim()
    osinfo = data.get("os") or {}
    return {
        "name": osinfo.get("Caption") or "Windows",
        "version": osinfo.get("Version") or platform.version(),
        "kernel": osinfo.get("BuildNumber") or platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "uptime_seconds": time.time() - psutil.boot_time(),
    }


_CIM_CACHE: dict[str, Any] | None = None


def _cached_cim() -> dict[str, Any]:
    global _CIM_CACHE
    if _CIM_CACHE is None:
        _CIM_CACHE = _cim()
    return _CIM_CACHE


def refresh_cim() -> None:
    global _CIM_CACHE
    _CIM_CACHE = None


def collect_cpu_windows() -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    data = _cached_cim()
    procs = data.get("processors") or []
    if isinstance(procs, dict):
        procs = [procs]
    first = procs[0] if procs else {}
    cores = sum(int(p.get("NumberOfCores") or 0) for p in procs) or psutil.cpu_count(logical=False)
    logical = sum(int(p.get("NumberOfLogicalProcessors") or 0) for p in procs) or psutil.cpu_count(logical=True)
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = f.current if f else first.get("CurrentClockSpeed")
    except Exception:
        freq = first.get("CurrentClockSpeed")
    info = {
        "manufacturer": first.get("Manufacturer"),
        "model": first.get("Name"),
        "family": str(first.get("Family")) if first.get("Family") is not None else None,
        "architecture": platform.machine(),
        "physical_sockets": len(procs) or None,
        "physical_cores": cores,
        "logical_processors": logical,
        "base_frequency_mhz": first.get("MaxClockSpeed"),
        "current_frequency_mhz": freq,
        "usage_pct": psutil.cpu_percent(interval=0.15),
        "temperature_c": None,
        "topology_status": "PARTIAL" if procs else "UNKNOWN",
        "notes": notes,
    }
    notes.append("CPU temperature is not exposed by standard Windows WMI on most systems.")
    return info, notes


def collect_memory_windows() -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    data = _cached_cim()
    usage = psutil.virtual_memory()
    arrays = data.get("memarray") or []
    if isinstance(arrays, dict):
        arrays = [arrays]
    modules_raw = data.get("memory") or []
    if isinstance(modules_raw, dict):
        modules_raw = [modules_raw]

    slot_count = None
    max_supported = None
    if arrays:
        devices = arrays[0].get("MemoryDevices")
        if devices:
            slot_count = int(devices)
        # MaxCapacity is KB on Win32_PhysicalMemoryArray
        mx = arrays[0].get("MaxCapacityEx") or arrays[0].get("MaxCapacity")
        if mx:
            try:
                mx_int = int(mx)
                # Values are typically kilobytes
                max_supported = mx_int * 1024 if mx_int < 10**12 else mx_int
            except (TypeError, ValueError):
                max_supported = None

    modules = []
    occupied = 0
    for m in modules_raw:
        cap = m.get("Capacity")
        capacity = int(cap) if cap else None
        occupied_flag = capacity is not None and capacity > 0
        if occupied_flag:
            occupied += 1
        locator = m.get("DeviceLocator") or m.get("BankLabel") or f"DIMM-{len(modules)+1}"
        modules.append(
            {
                "slot_locator": locator,
                "bank_locator": m.get("BankLabel"),
                "occupied": occupied_flag,
                "capacity_bytes": capacity,
                "manufacturer": m.get("Manufacturer"),
                "part_number": (m.get("PartNumber") or "").strip() or None,
                "serial_number": m.get("SerialNumber"),
                "memory_type": _win_memory_type(m.get("MemoryType")),
                "speed_mts": m.get("Speed"),
                "configured_speed_mts": m.get("ConfiguredClockSpeed"),
                "ecc": None,
                "form_factor": _win_form_factor(m.get("FormFactor")),
                "rank": None,
                "locator_known": bool(m.get("DeviceLocator") or m.get("BankLabel")),
            }
        )

    topology = "UNKNOWN"
    free_slots = None
    unlocated = None
    if slot_count and modules:
        topology = "DETECTED" if len(modules) >= occupied else "PARTIAL"
        if occupied <= slot_count:
            free_slots = slot_count - occupied
            if len(modules) < slot_count:
                unlocated = slot_count - occupied
                notes.append("Windows WMI often omits empty slot locators; free slot count is derived from MemoryDevices.")
                topology = "PARTIAL"
    elif modules:
        topology = "PARTIAL"
        notes.append("Physical RAM slot count not exposed by WMI.")
    else:
        notes.append("Memory topology not exposed by firmware/OS")

    result = {
        "total_physical_bytes": int(usage.total),
        "max_supported_bytes": max_supported,
        "slot_count": slot_count,
        "occupied_slots": occupied if modules else None,
        "free_slots": free_slots,
        "used_bytes": int(usage.used),
        "available_bytes": int(usage.available),
        "usage_pct": float(usage.percent),
        "topology_status": topology,
        "unlocated_empty_slots": unlocated,
        "modules": modules,
        "notes": notes,
    }
    return result, notes


def _win_memory_type(code) -> str | None:
    mapping = {0: None, 20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}
    try:
        return mapping.get(int(code), f"type-{code}")
    except (TypeError, ValueError):
        return None


def _win_form_factor(code) -> str | None:
    mapping = {8: "DIMM", 12: "SODIMM", 13: "SRIMM"}
    try:
        return mapping.get(int(code), None)
    except (TypeError, ValueError):
        return None


def collect_system_windows() -> dict[str, Any]:
    data = _cached_cim()
    cs = data.get("computer") or {}
    bios = data.get("bios") or {}
    board = data.get("baseboard") or {}
    prod = data.get("csprod") or {}
    virt = bool(cs.get("HypervisorPresent"))
    label = None
    detected, guessed = is_virtual_from_dmi(cs.get("Manufacturer"), cs.get("Model"), bios.get("Manufacturer"))
    if virt or detected:
        virt = True
        label = guessed or "Hypervisor"
    return {
        "motherboard": {
            "manufacturer": board.get("Manufacturer"),
            "model": board.get("Product"),
            "serial_number": board.get("SerialNumber"),
            "version": board.get("Version"),
            "notes": [],
        },
        "bios": {
            "vendor": bios.get("Manufacturer"),
            "version": bios.get("SMBIOSBIOSVersion"),
            "release_date": str(bios.get("ReleaseDate")) if bios.get("ReleaseDate") else None,
            "system_manufacturer": cs.get("Manufacturer") or prod.get("Vendor"),
            "system_model": cs.get("Model") or prod.get("Name"),
            "system_serial": bios.get("SerialNumber") or prod.get("IdentifyingNumber"),
            "system_uuid": prod.get("UUID"),
            "notes": [],
        },
        "is_virtual": virt,
        "virtualization": label,
    }


def collect_gpus_windows() -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    gpus: list[dict[str, Any]] = []
    nvsmi = which("nvidia-smi") or which(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")
    if nvsmi:
        query = (
            "--query-gpu=index,name,uuid,serial,memory.total,memory.used,"
            "utilization.gpu,temperature.gpu,power.draw,clocks.gr,clocks.mem,pci.bus_id,driver_version"
        )
        code, out, err = run_cmd([nvsmi, query, "--format=csv,noheader,nounits"])
        if code == 0:
            gpus = parse_nvidia_smi_csv(out)
        else:
            notes.append("nvidia-smi failed on Windows.")
    if not gpus:
        data = _cached_cim()
        videos = data.get("video") or []
        if isinstance(videos, dict):
            videos = [videos]
        for i, v in enumerate(videos):
            name = v.get("Name") or ""
            if "microsoft basic" in name.lower():
                continue
            vendor = None
            low = name.lower()
            if "nvidia" in low:
                vendor = "NVIDIA"
            elif "amd" in low or "radeon" in low:
                vendor = "AMD"
            elif "intel" in low:
                vendor = "Intel"
            ram = v.get("AdapterRAM")
            gpus.append(
                {
                    "index": i,
                    "vendor": vendor,
                    "model": name,
                    "vram_bytes": int(ram) if ram and int(ram) > 0 else None,
                    "driver_version": v.get("DriverVersion"),
                    "pci_device_id": v.get("PNPDeviceID"),
                }
            )
        if not gpus:
            notes.append("No GPU reported by Win32_VideoController.")
        else:
            notes.append("GPU telemetry (util/temp/power) requires vendor tooling such as nvidia-smi.")
    return gpus, notes


def collect_pcie_windows() -> dict[str, Any]:
    return {
        "topology_status": "UNKNOWN",
        "topology_note": "Physical slot topology not exposed by firmware/OS",
        "slots": [],
        "gpu_capable_total": None,
        "gpu_capable_occupied": None,
        "gpu_capable_free": None,
        "notes": [
            "Windows WMI does not reliably expose physical PCIe slot maps. PCI device list is available via PnP IDs on GPU/disk records."
        ],
    }


def collect_storage_windows() -> dict[str, Any]:
    notes = []
    data = _cached_cim()
    disks_raw = data.get("disks") or []
    if isinstance(disks_raw, dict):
        disks_raw = [disks_raw]
    disks = []
    for d in disks_raw:
        media = d.get("MediaType")
        iface = d.get("InterfaceType")
        media_type = None
        blob = f"{media} {iface} {d.get('Model')}".lower()
        if "nvme" in blob:
            media_type = "NVMe"
        elif "ssd" in blob:
            media_type = "SSD"
        elif "hdd" in blob or "fixed hard disk" in blob:
            media_type = "HDD"
        disks.append(
            {
                "name": d.get("DeviceID"),
                "model": d.get("Model"),
                "serial_number": (d.get("SerialNumber") or "").strip() or None,
                "capacity_bytes": int(d["Size"]) if d.get("Size") else None,
                "interface": iface,
                "media_type": media_type,
                "smart_status": d.get("Status"),
                "temperature_c": None,
            }
        )
    filesystems = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        filesystems.append(
            {
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "device": part.device,
                "total_bytes": u.total,
                "used_bytes": u.used,
            }
        )
    return {"disks": disks, "filesystems": filesystems, "notes": notes}


def collect_metrics_windows(prev_net=None, prev_disk=None, prev_ts=None) -> tuple[dict[str, Any], dict]:
    from labwatch_agent.collectors import linux as linux_col

    payload, nxt = linux_col.collect_metrics(prev_net, prev_disk, prev_ts)
    payload["cpu_temp_c"] = payload.get("cpu_temp_c")
    nvsmi = which("nvidia-smi") or which(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")
    if payload.get("gpus") or not nvsmi:
        return payload, nxt
    query = "--query-gpu=index,uuid,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,clocks.gr,clocks.mem"
    code, out, err = run_cmd([nvsmi, query, "--format=csv,noheader,nounits"])
    if code != 0 or not out.strip():
        return payload, nxt
    gpus = []
    for i, parsed in enumerate(parse_nvidia_smi_csv(linux_col._pad_metrics_csv(out))):
        gpus.append(
            {
                "index": parsed.get("index", i),
                "gpu_key": parsed.get("uuid") or str(i),
                "utilization_pct": parsed.get("utilization_pct"),
                "temperature_c": parsed.get("temperature_c"),
                "vram_used_bytes": parsed.get("vram_used_bytes"),
                "vram_total_bytes": parsed.get("vram_bytes"),
                "power_w": parsed.get("power_w"),
                "graphics_clock_mhz": parsed.get("graphics_clock_mhz"),
                "memory_clock_mhz": parsed.get("memory_clock_mhz"),
            }
        )
    if gpus:
        payload["gpus"] = gpus
    return payload, nxt
