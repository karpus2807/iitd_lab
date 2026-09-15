from __future__ import annotations

import glob
import os
import platform
import socket
import uuid
from typing import Any

import psutil

from labwatch_agent.parsers.dmidecode import parse_memory_from_dmidecode, parse_slots_from_dmidecode, parse_system_from_dmidecode
from labwatch_agent.parsers.nvidia import parse_nvidia_smi_csv
from labwatch_agent.util import is_virtual_from_dmi, read_int, read_text, run_cmd, which


def collect_os() -> dict[str, Any]:
    uname = platform.uname()
    boot = psutil.boot_time()
    return {
        "name": platform.system(),
        "version": platform.version(),
        "kernel": uname.release,
        "architecture": uname.machine,
        "hostname": socket.gethostname(),
        "boot_time": None,
        "uptime_seconds": max(psutil.time.time() - boot, 0) if hasattr(psutil, "time") else None,
    }


def collect_os_safe() -> dict[str, Any]:
    try:
        import time

        boot = psutil.boot_time()
        return {
            "name": platform.system(),
            "version": platform.version() if os.name == "nt" else " ".join(platform.linux_distribution() if hasattr(platform, "linux_distribution") else [platform.platform()]),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "hostname": socket.gethostname(),
            "uptime_seconds": time.time() - boot,
        }
    except Exception as exc:
        return {"name": platform.system(), "hostname": socket.gethostname(), "notes": [str(exc)]}


def linux_os() -> dict[str, Any]:
    import time

    pretty = None
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        text = read_text(path)
        if not text:
            continue
        data = {}
        for line in text.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k] = v.strip().strip('"')
        pretty = data.get("PRETTY_NAME") or data.get("NAME")
        version = data.get("VERSION_ID") or data.get("VERSION")
        break
    else:
        version = platform.version()
    boot = psutil.boot_time()
    return {
        "name": pretty or "Linux",
        "version": version if pretty else platform.version(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "uptime_seconds": time.time() - boot,
    }


def windows_os() -> dict[str, Any]:
    import time

    boot = psutil.boot_time()
    return {
        "name": "Windows",
        "version": platform.version(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "uptime_seconds": time.time() - boot,
    }


def collect_cpu_linux() -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    info: dict[str, Any] = {
        "architecture": platform.machine(),
        "logical_processors": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "usage_pct": psutil.cpu_percent(interval=0.15),
        "uptime_seconds": None,
    }
    try:
        freq = psutil.cpu_freq()
        if freq:
            info["current_frequency_mhz"] = freq.current
            info["base_frequency_mhz"] = freq.min or None
            if freq.max:
                info["base_frequency_mhz"] = freq.max
    except Exception:
        notes.append("CPU frequency not reported")
    try:
        load = os.getloadavg()
        info["load_avg_1"], info["load_avg_5"], info["load_avg_15"] = load
    except OSError:
        pass
    cpuinfo = read_text("/proc/cpuinfo") or ""
    for line in cpuinfo.splitlines():
        if line.startswith("model name") and not info.get("model"):
            info["model"] = line.split(":", 1)[1].strip()
        elif line.startswith("vendor_id") and not info.get("manufacturer"):
            info["manufacturer"] = line.split(":", 1)[1].strip()
        elif line.startswith("cpu family") and not info.get("family"):
            info["family"] = line.split(":", 1)[1].strip()
        elif line.startswith("physical id"):
            pass
    physical_ids = {line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith("physical id")}
    if physical_ids:
        info["physical_sockets"] = len(physical_ids)
    if not info.get("model"):
        model = _lscpu_field("Model name") or _lscpu_field("BIOS Model name")
        if model:
            info["model"] = model
    if not info.get("manufacturer"):
        vendor = _lscpu_field("Vendor ID") or _lscpu_field("BIOS Vendor")
        if vendor:
            info["manufacturer"] = vendor
    info["temperature_c"] = _cpu_temp_linux()
    if info["temperature_c"] is None:
        notes.append("CPU temperature not exposed")
    try:
        import time

        info["uptime_seconds"] = time.time() - psutil.boot_time()
    except Exception:
        pass
    info["topology_status"] = "PARTIAL"
    info["notes"] = notes
    return info, notes


def _cpu_temp_linux() -> float | None:
    temps = []
    try:
        if hasattr(psutil, "sensors_temperatures"):
            data = psutil.sensors_temperatures() or {}
            for name, entries in data.items():
                if name.lower() in {"coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"}:
                    for e in entries:
                        if e.current is not None:
                            temps.append(e.current)
    except Exception:
        pass
    if temps:
        return max(temps)
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        raw = read_int(path)
        if raw is not None:
            value = raw / 1000.0 if raw > 200 else float(raw)
            temps.append(value)
    return max(temps) if temps else None


def _lscpu_field(label: str) -> str | None:
    if not which("lscpu"):
        return None
    code, out, err = run_cmd(["lscpu"])
    if code != 0 or not out:
        return None
    prefix = label.lower() + ":"
    for line in out.splitlines():
        if line.lower().startswith(prefix):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def collect_dmi_sysfs() -> dict[str, Any]:
    """Fill identity/motherboard/BIOS when dmidecode is missing. Root can read most of these."""
    base = "/sys/class/dmi/id"
    if not os.path.isdir(base):
        base = "/sys/devices/virtual/dmi/id"
    skip = {"", "unknown", "none", "not specified", "not provided", "to be filled by o.e.m.", "0"}

    def g(name: str) -> str | None:
        val = read_text(f"{base}/{name}")
        if not val:
            return None
        cleaned = val.strip()
        if cleaned.lower() in skip:
            return None
        return cleaned

    return {
        "system_manufacturer": g("sys_vendor"),
        "system_model": g("product_name"),
        "system_serial": g("product_serial"),
        "system_uuid": g("product_uuid"),
        "board_manufacturer": g("board_vendor"),
        "board_model": g("board_name"),
        "board_serial": g("board_serial"),
        "board_version": g("board_version"),
        "bios_vendor": g("bios_vendor"),
        "bios_version": g("bios_version"),
        "bios_date": g("bios_date"),
        "chassis_type": g("chassis_type"),
    }

def collect_memory_usage() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "used_bytes": int(vm.used),
        "available_bytes": int(vm.available),
        "usage_pct": float(vm.percent),
        "total_physical_bytes": int(vm.total),
    }


def collect_memory_linux() -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    usage = collect_memory_usage()
    result = {
        **usage,
        "max_supported_bytes": None,
        "slot_count": None,
        "occupied_slots": None,
        "free_slots": None,
        "topology_status": "UNKNOWN",
        "modules": [],
        "notes": notes,
        "unlocated_empty_slots": None,
    }
    if which("dmidecode"):
        code, out, err = run_cmd(["dmidecode", "-t", "memory"])
        if code == 0 and out.strip():
            parsed = parse_memory_from_dmidecode(out)
            result.update(parsed)
            notes.extend(parsed.get("notes") or [])
        else:
            notes.append("dmidecode memory query failed or permission denied; RAM topology marked unknown.")
    else:
        notes.append("dmidecode not installed; RAM slot topology not exposed.")
    result["notes"] = notes
    return result, notes


def collect_system_linux() -> dict[str, Any]:
    notes = []
    data = {
        "motherboard": {"manufacturer": None, "model": None, "serial_number": None, "version": None, "notes": []},
        "bios": {
            "vendor": None,
            "version": None,
            "release_date": None,
            "system_manufacturer": None,
            "system_model": None,
            "system_serial": None,
            "system_uuid": None,
            "notes": [],
        },
        "is_virtual": False,
        "virtualization": None,
    }
    text = ""
    if which("dmidecode"):
        code, out, err = run_cmd(["dmidecode", "-t", "system", "-t", "baseboard", "-t", "bios", "-t", "chassis"])
        if code == 0:
            text = out
        else:
            notes.append("dmidecode system/BIOS query failed or permission denied.")
    parsed = parse_system_from_dmidecode(text) if text else {}
    sysfs = collect_dmi_sysfs()
    for key, value in sysfs.items():
        if value and not parsed.get(key):
            parsed[key] = value
    if not text and not any(sysfs.values()):
        notes.append("No DMI data (install dmidecode; /sys/class/dmi/id was empty).")
    elif not text:
        notes.append("dmidecode missing; using /sys/class/dmi/id for system identity.")
    data["motherboard"] = {
        "manufacturer": parsed.get("board_manufacturer"),
        "model": parsed.get("board_model"),
        "serial_number": parsed.get("board_serial"),
        "version": parsed.get("board_version"),
        "notes": notes,
    }
    data["bios"] = {
        "vendor": parsed.get("bios_vendor"),
        "version": parsed.get("bios_version"),
        "release_date": parsed.get("bios_date"),
        "system_manufacturer": parsed.get("system_manufacturer"),
        "system_model": parsed.get("system_model"),
        "system_serial": parsed.get("system_serial"),
        "system_uuid": parsed.get("system_uuid"),
        "notes": notes,
    }
    virt, label = is_virtual_from_dmi(parsed.get("system_manufacturer"), parsed.get("system_model"), parsed.get("bios_vendor"))
    cpuinfo = (read_text("/proc/cpuinfo") or "").lower()
    if "hypervisor" in cpuinfo:
        virt = True
        label = label or "Hypervisor"
    data["is_virtual"] = virt
    data["virtualization"] = label
    return data


def collect_pcie_linux() -> dict[str, Any]:
    if which("dmidecode"):
        code, out, err = run_cmd(["dmidecode", "-t", "slot"])
        if code == 0 and out.strip():
            return parse_slots_from_dmidecode(out)
    return {
        "topology_status": "UNKNOWN",
        "topology_note": "Physical slot topology not exposed by firmware/OS",
        "slots": [],
        "gpu_capable_total": None,
        "gpu_capable_occupied": None,
        "gpu_capable_free": None,
        "pci_devices": _lspci_devices(),
        "notes": ["dmidecode slot data unavailable"],
    }


def _lspci_devices() -> list[dict[str, Any]]:
    if not which("lspci"):
        return []
    code, out, err = run_cmd(["lspci", "-Dmm"])
    if code != 0:
        return []
    devices = []
    for line in out.splitlines():
        devices.append({"raw": line})
    return devices


def collect_gpus_linux() -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    gpus: list[dict[str, Any]] = []
    if which("nvidia-smi"):
        query = (
            "--query-gpu=index,name,uuid,serial,memory.total,memory.used,"
            "utilization.gpu,temperature.gpu,power.draw,clocks.gr,clocks.mem,pci.bus_id,driver_version"
        )
        code, out, err = run_cmd(["nvidia-smi", query, "--format=csv,noheader,nounits"])
        if code == 0:
            gpus = parse_nvidia_smi_csv(out)
        else:
            notes.append("nvidia-smi failed; NVIDIA metrics marked unavailable.")
    else:
        notes.append("nvidia-smi not present.")
    if not gpus:
        # PCI VGA/3D devices without inventing performance data.
        if which("lspci"):
            code, out, err = run_cmd(["lspci", "-nn"])
            idx = 0
            for line in out.splitlines():
                low = line.lower()
                if "vga compatible" in low or "3d controller" in low or "display controller" in low:
                    vendor = "NVIDIA" if "nvidia" in low else "AMD" if ("amd" in low or "ati" in low) else "Intel" if "intel" in low else None
                    gpus.append(
                        {
                            "index": idx,
                            "vendor": vendor,
                            "model": line.split(":", 2)[-1].strip() if ":" in line else line.strip(),
                            "pci_bus": line.split()[0] if line.split() else None,
                        }
                    )
                    idx += 1
            if not gpus:
                notes.append("No GPU devices reported by PCI enumeration.")
    return gpus, notes


def collect_storage_linux() -> dict[str, Any]:
    notes: list[str] = []
    disks = []
    if which("lsblk"):
        code, out, err = run_cmd(["lsblk", "-b", "-d", "-J", "-o", "NAME,MODEL,SERIAL,SIZE,TRAN,TYPE,ROTA"])
        if code == 0 and out.strip():
            try:
                import json

                payload = json.loads(out)
                for dev in payload.get("blockdevices", []):
                    if dev.get("type") not in {"disk", None}:
                        continue
                    rota = dev.get("rota")
                    tran = (dev.get("tran") or "").lower()
                    media = None
                    if tran == "nvme":
                        media = "NVMe"
                    elif str(rota) in {"0", "false"}:
                        media = "SSD"
                    elif str(rota) in {"1", "true"}:
                        media = "HDD"
                    disks.append(
                        {
                            "name": dev.get("name"),
                            "model": dev.get("model") or None,
                            "serial_number": dev.get("serial") or None,
                            "capacity_bytes": int(dev["size"]) if dev.get("size") else None,
                            "interface": dev.get("tran"),
                            "media_type": media,
                            "smart_status": None,
                            "temperature_c": None,
                        }
                    )
            except Exception as exc:
                notes.append(f"lsblk parse failed: {exc}")
        else:
            notes.append("lsblk failed")
    else:
        notes.append("lsblk not installed")
    if which("smartctl"):
        for d in disks:
            code, out, err = run_cmd(["smartctl", "-A", "-H", "-j", f"/dev/{d['name']}"])
            if code not in {0, 4} or not out.strip():
                continue
            try:
                import json

                smart = json.loads(out)
                health = smart.get("smart_status", {}).get("passed")
                if health is True:
                    d["smart_status"] = "PASSED"
                elif health is False:
                    d["smart_status"] = "FAILED"
                temp = smart.get("temperature", {}).get("current")
                if temp is not None:
                    d["temperature_c"] = temp
            except Exception:
                continue
    else:
        notes.append("smartctl not installed; SMART health not collected.")
    filesystems = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in {"squashfs", "overlay", "tmpfs"}:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        filesystems.append(
            {
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "device": part.device,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
            }
        )
    return {"disks": disks, "filesystems": filesystems, "notes": notes}


def collect_network() -> dict[str, Any]:
    notes = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    io = psutil.net_io_counters(pernic=True)
    interfaces = []
    macs = []
    for name, addr_list in addrs.items():
        ipv4, ipv6, mac = [], [], None
        for a in addr_list:
            if a.family == socket.AF_INET:
                ipv4.append(a.address)
            elif a.family == socket.AF_INET6:
                ipv6.append(a.address.split("%")[0])
            elif getattr(psutil, "AF_LINK", None) == a.family or str(a.family) == "AddressFamily.AF_PACKET":
                mac = a.address
        st = stats.get(name)
        counters = io.get(name)
        if mac:
            macs.append(mac)
        interfaces.append(
            {
                "name": name,
                "mac": mac,
                "ipv4": ipv4,
                "ipv6": ipv6,
                "is_up": bool(st.isup) if st else False,
                "speed_mbps": int(st.speed) if st and st.speed and st.speed > 0 else None,
                "rx_bytes": counters.bytes_recv if counters else None,
                "tx_bytes": counters.bytes_sent if counters else None,
            }
        )
    return {"hostname": socket.gethostname(), "interfaces": interfaces, "macs": macs, "notes": notes}


def collect_identity(agent_uuid: str, system: dict[str, Any], net: dict[str, Any], osinfo: dict[str, Any]) -> dict[str, Any]:
    bios = system.get("bios") or {}
    mb = system.get("motherboard") or {}
    return {
        "hostname": osinfo.get("hostname") or socket.gethostname(),
        "os_name": osinfo.get("name"),
        "os_version": osinfo.get("version"),
        "kernel_version": osinfo.get("kernel"),
        "architecture": osinfo.get("architecture") or platform.machine(),
        "machine_uuid": _machine_id(),
        "system_uuid": bios.get("system_uuid"),
        "bios_uuid": bios.get("system_uuid"),
        "motherboard_serial": mb.get("serial_number"),
        "system_serial": bios.get("system_serial"),
        "mac_addresses": [m for m in net.get("macs", []) if m],
        "agent_uuid": agent_uuid,
        "is_virtual": system.get("is_virtual", False),
        "virtualization": system.get("virtualization"),
        "notes": [],
    }


def _machine_id() -> str | None:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        value = read_text(path)
        if value:
            return value
    try:
        return str(uuid.getnode())
    except Exception:
        return None


def collect_metrics(prev_net=None, prev_disk=None, prev_ts=None) -> tuple[dict[str, Any], dict]:
    import time

    now = time.time()
    vm = psutil.virtual_memory()
    cpu_freq = None
    try:
        f = psutil.cpu_freq()
        cpu_freq = f.current if f else None
    except Exception:
        pass
    disk_io = psutil.disk_io_counters()
    net_io = psutil.net_io_counters()
    disk_read = disk_write = net_tx = net_rx = None
    dt = (now - prev_ts) if prev_ts else None
    if dt and dt > 0 and prev_disk and disk_io:
        disk_read = max((disk_io.read_bytes - prev_disk.read_bytes) / dt, 0)
        disk_write = max((disk_io.write_bytes - prev_disk.write_bytes) / dt, 0)
    if dt and dt > 0 and prev_net and net_io:
        net_tx = max((net_io.bytes_sent - prev_net.bytes_sent) / dt, 0)
        net_rx = max((net_io.bytes_recv - prev_net.bytes_recv) / dt, 0)
    fs_used = fs_total = 0
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            fs_used += u.used
            fs_total += u.total
        except OSError:
            continue
    gpus = []
    if which("nvidia-smi"):
        query = "--query-gpu=index,uuid,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,clocks.gr,clocks.mem"
        code, out, err = run_cmd(["nvidia-smi", query, "--format=csv,noheader,nounits"])
        if code == 0:
            for i, parsed in enumerate(parse_nvidia_smi_csv(_pad_metrics_csv(out))):
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
    payload = {
        "cpu_usage_pct": psutil.cpu_percent(interval=0.1),
        "cpu_temp_c": _cpu_temp_linux() if os.name != "nt" else None,
        "cpu_freq_mhz": cpu_freq,
        "ram_used_bytes": vm.used,
        "ram_total_bytes": vm.total,
        "ram_available_bytes": vm.available,
        "ram_usage_pct": vm.percent,
        "disk_read_bps": disk_read,
        "disk_write_bps": disk_write,
        "disk_used_bytes": fs_used or None,
        "disk_total_bytes": fs_total or None,
        "net_tx_bps": net_tx,
        "net_rx_bps": net_rx,
        "gpus": gpus,
    }
    return payload, {"net": net_io, "disk": disk_io, "ts": now}


def _pad_metrics_csv(text: str) -> str:
    # metrics query has fewer columns; reuse parser by padding to expected layout
    lines = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        # index, uuid, util, temp, mem_used, mem_total, power, gclock, mclock
        if len(parts) >= 6:
            rebuilt = [
                parts[0],
                "GPU",
                parts[1],
                "N/A",
                parts[5] if len(parts) > 5 else "",
                parts[4] if len(parts) > 4 else "",
                parts[2] if len(parts) > 2 else "",
                parts[3] if len(parts) > 3 else "",
                parts[6] if len(parts) > 6 else "",
                parts[7] if len(parts) > 7 else "",
                parts[8] if len(parts) > 8 else "",
            ]
            lines.append(", ".join(rebuilt))
    return "\n".join(lines)
