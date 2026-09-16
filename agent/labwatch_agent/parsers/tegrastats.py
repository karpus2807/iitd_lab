from __future__ import annotations

import re


def parse_tegrastats(text: str) -> dict:
    """Parse a tegrastats line from Jetson L4T."""
    blob = " ".join((text or "").splitlines())
    result: dict = {}
    ram = re.search(r"RAM\s+(\d+)\s*/\s*(\d+)\s*MB", blob, re.I)
    if ram:
        result["ram_used_mb"] = int(ram.group(1))
        result["ram_total_mb"] = int(ram.group(2))
    gr3d = re.search(r"GR3D_FREQ\s+(\d+(?:\.\d+)?)\s*%(?:@(\d+(?:\.\d+)?))?", blob, re.I)
    if gr3d:
        result["utilization_pct"] = float(gr3d.group(1))
        if gr3d.group(2):
            result["graphics_clock_mhz"] = float(gr3d.group(2))
    gpu_temp = re.search(r"(?:GPU|gpu)@(\d+(?:\.\d+)?)\s*C", blob)
    if gpu_temp:
        result["temperature_c"] = float(gpu_temp.group(1))
    cpu_temp = re.search(r"(?:CPU|cpu)@(\d+(?:\.\d+)?)\s*C", blob)
    if cpu_temp:
        result["cpu_temperature_c"] = float(cpu_temp.group(1))
    emc = re.search(r"EMC_FREQ\s+(\d+(?:\.\d+)?)\s*%(?:@(\d+(?:\.\d+)?))?", blob, re.I)
    if emc:
        result["emc_util_pct"] = float(emc.group(1))
        if emc.group(2):
            result["emc_clock_mhz"] = float(emc.group(2))
    rails: dict[str, float] = {}
    for match in re.finditer(
        r"\b((?:VDD|POM|VIN)[_A-Z0-9]+)\s+(\d+(?:\.\d+)?)(?:mW)?(?:/(\d+(?:\.\d+)?)(?:mW)?)?",
        blob,
        re.I,
    ):
        name = match.group(1).upper()
        rails[name] = float(match.group(2)) / 1000.0
    if rails:
        result["power_rails"] = rails
    return result
