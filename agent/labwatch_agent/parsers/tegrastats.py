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
    gr3d = re.search(r"GR3D_FREQ\s+(\d+(?:\.\d+)?)\s*%", blob, re.I)
    if gr3d:
        result["utilization_pct"] = float(gr3d.group(1))
    gpu_temp = re.search(r"(?:GPU|gpu)@(\d+(?:\.\d+)?)\s*C", blob)
    if gpu_temp:
        result["temperature_c"] = float(gpu_temp.group(1))
    cpu_temp = re.search(r"(?:CPU|cpu)@(\d+(?:\.\d+)?)\s*C", blob)
    if cpu_temp:
        result["cpu_temperature_c"] = float(cpu_temp.group(1))
    return result
