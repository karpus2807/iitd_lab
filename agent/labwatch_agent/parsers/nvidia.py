from __future__ import annotations


def parse_nvidia_smi_csv(text: str) -> list[dict]:
    gpus = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("index"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        def num(idx, cast=float):
            try:
                if idx >= len(parts) or parts[idx] in {"[N/A]", "N/A", ""}:
                    return None
                return cast(parts[idx])
            except (TypeError, ValueError):
                return None

        index = int(num(0, float) or 0)
        name = parts[1] if len(parts) > 1 else None
        uuid = parts[2] if len(parts) > 2 and parts[2] not in {"[N/A]", "N/A"} else None
        serial = parts[3] if len(parts) > 3 and parts[3] not in {"[N/A]", "N/A"} else None
        mem_total_mb = num(4)
        mem_used_mb = num(5)
        util = num(6)
        temp = num(7)
        power = num(8) if len(parts) > 8 else None
        gclock = num(9) if len(parts) > 9 else None
        mclock = num(10) if len(parts) > 10 else None
        pci = parts[11] if len(parts) > 11 and parts[11] not in {"[N/A]", "N/A"} else None
        driver = parts[12] if len(parts) > 12 and parts[12] not in {"[N/A]", "N/A"} else None
        gpus.append(
            {
                "index": index,
                "vendor": "NVIDIA",
                "model": name,
                "uuid": uuid,
                "serial_number": serial,
                "vram_bytes": int(mem_total_mb * 1024 * 1024) if mem_total_mb is not None else None,
                "vram_used_bytes": int(mem_used_mb * 1024 * 1024) if mem_used_mb is not None else None,
                "utilization_pct": util,
                "temperature_c": temp,
                "power_w": power,
                "graphics_clock_mhz": gclock,
                "memory_clock_mhz": mclock,
                "pci_bus": pci,
                "driver_version": driver,
            }
        )
    return gpus
