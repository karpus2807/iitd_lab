from __future__ import annotations

_NA = {"", "[n/a]", "n/a", "[not supported]", "not supported", "none", "null"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NA:
        return None
    return text


def _num(value: str | None, cast=float):
    text = _clean(value)
    if text is None:
        return None
    try:
        return cast(text)
    except (TypeError, ValueError):
        return None


def parse_nvidia_smi_csv(text: str) -> list[dict]:
    """Parse nvidia-smi CSV. Jetson often returns N/A for memory/util/temp."""
    gpus: list[dict] = []
    rows = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not rows:
        return []
    header_map = None
    first = rows[0].lower()
    if "index" in first and ("name" in first or "uuid" in first):
        header_map = [h.strip().lower() for h in rows[0].split(",")]
        rows = rows[1:]
    for line in rows:
        parts = [p.strip() for p in line.split(",")]
        if header_map and len(parts) >= 2:
            by_name = {header_map[i]: parts[i] if i < len(parts) else "" for i in range(len(header_map))}
            index = int(_num(by_name.get("index"), float) or 0)
            mem_total = _num(by_name.get("memory.total") or by_name.get("memory.total [mib]"))
            mem_used = _num(by_name.get("memory.used") or by_name.get("memory.used [mib]"))
            gpus.append(_gpu_row(
                index=index,
                name=_clean(by_name.get("name")),
                uuid=_clean(by_name.get("uuid")),
                serial=_clean(by_name.get("serial")),
                mem_total_mb=mem_total,
                mem_used_mb=mem_used,
                util=_num(by_name.get("utilization.gpu") or by_name.get("utilization.gpu [%]")),
                temp=_num(by_name.get("temperature.gpu") or by_name.get("temperature.gpu")),
                power=_num(by_name.get("power.draw") or by_name.get("power.draw [w]")),
                gclock=_num(by_name.get("clocks.gr") or by_name.get("clocks.current.graphics [mhz]")),
                mclock=_num(by_name.get("clocks.mem") or by_name.get("clocks.current.memory [mhz]")),
                pci=_clean(by_name.get("pci.bus_id") or by_name.get("pci.bus_id")),
                driver=_clean(by_name.get("driver_version")),
            ))
            continue
        if len(parts) < 2:
            continue
        gpus.append(_gpu_row(
            index=int(_num(parts[0], float) or 0),
            name=_clean(parts[1] if len(parts) > 1 else None),
            uuid=_clean(parts[2] if len(parts) > 2 else None),
            serial=_clean(parts[3] if len(parts) > 3 else None),
            mem_total_mb=_num(parts[4] if len(parts) > 4 else None),
            mem_used_mb=_num(parts[5] if len(parts) > 5 else None),
            util=_num(parts[6] if len(parts) > 6 else None),
            temp=_num(parts[7] if len(parts) > 7 else None),
            power=_num(parts[8] if len(parts) > 8 else None),
            gclock=_num(parts[9] if len(parts) > 9 else None),
            mclock=_num(parts[10] if len(parts) > 10 else None),
            pci=_clean(parts[11] if len(parts) > 11 else None),
            driver=_clean(parts[12] if len(parts) > 12 else None),
        ))
    return gpus


def _gpu_row(**kwargs) -> dict:
    mem_total_mb = kwargs.pop("mem_total_mb")
    mem_used_mb = kwargs.pop("mem_used_mb")
    return {
        "index": kwargs.get("index") or 0,
        "vendor": "NVIDIA",
        "model": kwargs.get("name"),
        "uuid": kwargs.get("uuid"),
        "serial_number": kwargs.get("serial"),
        "vram_bytes": int(mem_total_mb * 1024 * 1024) if mem_total_mb is not None else None,
        "vram_used_bytes": int(mem_used_mb * 1024 * 1024) if mem_used_mb is not None else None,
        "utilization_pct": kwargs.get("util"),
        "temperature_c": kwargs.get("temp"),
        "power_w": kwargs.get("power"),
        "graphics_clock_mhz": kwargs.get("gclock"),
        "memory_clock_mhz": kwargs.get("mclock"),
        "pci_bus": kwargs.get("pci"),
        "driver_version": kwargs.get("driver"),
    }
