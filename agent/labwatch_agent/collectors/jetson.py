from __future__ import annotations

import glob
import os
import re
from typing import Any

from labwatch_agent.collectors.platform import board_model, is_jetson
from labwatch_agent.parsers.tegrastats import parse_tegrastats
from labwatch_agent.util import read_int, read_text, run_cmd, which


def collect_jetson_gpu() -> dict[str, Any] | None:
    if not is_jetson():
        return None
    extra: dict[str, Any] = {"memory_kind": "unified", "platform": "jetson"}
    model = board_model() or "NVIDIA Jetson"
    if "nvidia" not in model.lower():
        model = f"NVIDIA {model}"
    gpu = {
        "index": 0,
        "vendor": "NVIDIA",
        "model": model,
        "slot_designation": "SoC (nvgpu)",
        "utilization_pct": _gpu_load_pct(),
        "temperature_c": _thermal_celsius("gpu-therm", "gpu", "gv11b", "ga10b"),
        "graphics_clock_mhz": _gpu_clock_mhz(),
        "driver_version": _jetson_driver(),
        "pci_bus": None,
        "vram_bytes": None,
        "extra": extra,
    }
    stats = _tegrastats_once()
    if stats:
        if gpu["utilization_pct"] is None and stats.get("utilization_pct") is not None:
            gpu["utilization_pct"] = stats["utilization_pct"]
        if gpu["temperature_c"] is None and stats.get("temperature_c") is not None:
            gpu["temperature_c"] = stats["temperature_c"]
        if stats.get("ram_total_mb"):
            extra["unified_ram_bytes"] = int(stats["ram_total_mb"]) * 1024 * 1024
            extra["unified_ram_used_bytes"] = int(stats.get("ram_used_mb") or 0) * 1024 * 1024
    return gpu


def jetson_cpu_temp() -> float | None:
    return _thermal_celsius("cpu-therm", "cpu", "soc_thermal")


def _tegrastats_once() -> dict[str, Any]:
    if not which("tegrastats"):
        return {}
    code, out, err = run_cmd(["tegrastats", "--interval", "1000", "--count", "1"], timeout=4)
    if code != 0 or not out.strip():
        code, out, err = run_cmd(["timeout", "2", "tegrastats"], timeout=3)
    return parse_tegrastats(out or err)


def _gpu_load_pct() -> float | None:
    paths = glob.glob("/sys/devices/gpu.*/load")
    paths += glob.glob("/sys/devices/platform/gpu.*/load")
    paths += glob.glob("/sys/devices/platform/*.gpu/load")
    paths += glob.glob("/sys/devices/platform/*gpu*/load")
    for path in paths:
        raw = read_int(path)
        if raw is None:
            continue
        # L4T reports 0-1000 for 0-100%
        if raw > 100:
            return round(raw / 10.0, 1)
        return float(raw)
    return None


def _gpu_clock_mhz() -> float | None:
    for path in glob.glob("/sys/class/devfreq/*gpu*/cur_freq") + glob.glob("/sys/class/devfreq/*ga10b*/cur_freq"):
        raw = read_int(path)
        if raw and raw > 1000:
            return round(raw / 1_000_000.0, 1)
        if raw:
            return float(raw)
    return None


def _thermal_celsius(*needles: str) -> float | None:
    temps = []
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        typ = (read_text(f"{zone}/type") or "").lower()
        if not any(n in typ for n in needles):
            continue
        raw = read_int(f"{zone}/temp")
        if raw is None:
            continue
        temps.append(raw / 1000.0 if raw > 200 else float(raw))
    return max(temps) if temps else None


def _jetson_driver() -> str | None:
    nv = read_text("/etc/nv_tegra_release")
    if nv:
        rev = re.search(r"R(\d+).*REVISION:\s*([0-9.]+)", nv)
        if rev:
            return f"L4T R{rev.group(1)}.{rev.group(2)}"
        return nv.splitlines()[0][:120]
    for path in ("/sys/module/nvidia/version", "/proc/driver/nvidia/version"):
        text = read_text(path)
        if text:
            return text.splitlines()[0][:120]
    return None


def merge_gpu(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    extra = dict(base.get("extra") or {})
    extra.update(overlay.get("extra") or {})
    for key, value in overlay.items():
        if key == "extra":
            continue
        if out.get(key) in (None, "") and value not in (None, ""):
            out[key] = value
    out["extra"] = extra
    if extra.get("memory_kind") == "unified":
        out.setdefault("slot_designation", overlay.get("slot_designation") or "SoC (nvgpu)")
    return out
