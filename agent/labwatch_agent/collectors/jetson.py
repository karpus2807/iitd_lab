from __future__ import annotations

import glob
import re
import time
from typing import Any

from labwatch_agent.collectors.platform import board_model, is_jetson, is_soc_board
from labwatch_agent.parsers.tegrastats import parse_tegrastats
from labwatch_agent.util import read_int, read_text, run_cmd, which

_TEGRA_CACHE: dict[str, Any] | None = None
_TEGRA_TS = 0.0


def collect_jetson_gpu() -> dict[str, Any] | None:
    if not is_jetson():
        return None
    extra: dict[str, Any] = {
        "memory_kind": "unified",
        "platform": "jetson",
        "bus": "soc",
        "unsupported": ["pci_bus", "pci_slot", "serial_number", "discrete_vram"],
        "supported": [
            "temperature_c",
            "utilization_pct",
            "power_w",
            "graphics_clock_mhz",
            "memory_clock_mhz",
            "unified_memory",
            "driver_version",
        ],
    }
    model = board_model() or "NVIDIA Jetson"
    if "nvidia" not in model.lower():
        model = f"NVIDIA {model}"
    stats = _tegrastats_once()
    rails = dict(stats.get("power_rails") or {})
    rails.update(_hwmon_power_rails())
    extra["power_rails"] = {k: round(v, 3) for k, v in rails.items() if v is not None}
    extra["l4t_version"] = _jetson_l4t()
    ram_total = stats.get("ram_total_mb")
    ram_used = stats.get("ram_used_mb")
    if ram_total:
        extra["unified_ram_bytes"] = int(ram_total) * 1024 * 1024
        extra["unified_ram_used_bytes"] = int(ram_used or 0) * 1024 * 1024
    else:
        try:
            import psutil

            vm = psutil.virtual_memory()
            extra["unified_ram_bytes"] = int(vm.total)
            extra["unified_ram_used_bytes"] = int(vm.used)
        except Exception:
            pass
    gpu_clock = _gpu_clock_mhz() or stats.get("graphics_clock_mhz")
    mem_clock = _emc_clock_mhz() or stats.get("emc_clock_mhz")
    gpu = {
        "index": 0,
        "vendor": "NVIDIA",
        "model": model,
        "slot_designation": "SoC (nvgpu)",
        "utilization_pct": _gpu_load_pct(),
        "temperature_c": _thermal_celsius("gpu-therm", "gpu", "gv11b", "ga10b"),
        "graphics_clock_mhz": gpu_clock,
        "memory_clock_mhz": mem_clock,
        "power_w": _pick_watts(rails, "POM_5V_GPU", "VDD_GPU", "GPU", "VDD_GPU_SOC", "GPU_SOC"),
        "driver_version": extra.get("l4t_version"),
        "pci_bus": None,
        "pci_device_id": None,
        "serial_number": None,
        "vram_bytes": extra.get("unified_ram_bytes"),
        "extra": extra,
    }
    if gpu["utilization_pct"] is None and stats.get("utilization_pct") is not None:
        gpu["utilization_pct"] = stats["utilization_pct"]
    if gpu["temperature_c"] is None and stats.get("temperature_c") is not None:
        gpu["temperature_c"] = stats["temperature_c"]
    extra["board_power_w"] = _pick_watts(rails, "VDD_IN", "POM_5V_IN", "VIN_SYS", "VIN")
    extra["cpu_power_w"] = _pick_watts(rails, "POM_5V_CPU", "VDD_CPU_CV", "VDD_CPU", "CPU")
    extra["soc_power_w"] = _pick_watts(rails, "VDD_SOC", "SOC")
    return gpu


def collect_jetson_memory() -> dict[str, Any]:
    if not (is_jetson() or is_soc_board()):
        return {}
    extra: dict[str, Any] = {"memory_kind": "unified", "form_factor": "soldered"}
    model = (board_model() or "").lower()
    if "orin" in model:
        extra["memory_type"] = "LPDDR5"
    elif "xavier" in model:
        extra["memory_type"] = "LPDDR4x"
    elif any(token in model for token in ("nano", "tx1", "tx2", "tegra", "jetson")):
        extra["memory_type"] = "LPDDR4"
    stats = _tegrastats_once() if is_jetson() else {}
    emc = _emc_clock_mhz() or stats.get("emc_clock_mhz")
    if emc:
        extra["emc_clock_mhz"] = emc
        extra["speed_mts"] = int(round(emc))
    return extra


def jetson_cpu_temp() -> float | None:
    return _thermal_celsius("cpu-therm", "cpu", "soc_thermal")


def _tegrastats_once() -> dict[str, Any]:
    global _TEGRA_CACHE, _TEGRA_TS
    now = time.time()
    if _TEGRA_CACHE is not None and now - _TEGRA_TS < 8:
        return _TEGRA_CACHE
    parsed: dict[str, Any] = {}
    if which("tegrastats"):
        code, out, err = run_cmd(["tegrastats", "--interval", "1000", "--count", "1"], timeout=4)
        if code != 0 or not (out or "").strip():
            code, out, err = run_cmd(["timeout", "2", "tegrastats"], timeout=3)
        parsed = parse_tegrastats(out or err)
    _TEGRA_CACHE = parsed
    _TEGRA_TS = now
    return parsed


def _gpu_load_pct() -> float | None:
    paths = glob.glob("/sys/devices/gpu.*/load")
    paths += glob.glob("/sys/devices/platform/gpu.*/load")
    paths += glob.glob("/sys/devices/platform/*.gpu/load")
    paths += glob.glob("/sys/devices/platform/*gpu*/load")
    for path in paths:
        raw = read_int(path)
        if raw is None:
            continue
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


def _emc_clock_mhz() -> float | None:
    for path in (
        "/sys/kernel/debug/bpmp/debug/clk/emc/rate",
        "/sys/kernel/debug/clk/emc/clk_rate",
        "/sys/kernel/debug/bpmp/debug/clk/emc/emc_rate",
    ):
        raw = read_int(path)
        if not raw:
            continue
        if raw > 1_000_000:
            return round(raw / 1_000_000.0, 1)
        if raw > 10_000:
            return round(raw / 1000.0, 1)
        return float(raw)
    return None


def _hwmon_power_rails() -> dict[str, float]:
    rails: dict[str, float] = {}
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        name = (read_text(f"{hwmon}/name") or "").strip()
        for idx in range(1, 5):
            label = (
                read_text(f"{hwmon}/in{idx}_label")
                or read_text(f"{hwmon}/curr{idx}_label")
                or read_text(f"{hwmon}/power{idx}_label")
                or ""
            ).strip()
            if not label and name:
                label = f"{name}_ch{idx}"
            elif not label:
                continue
            watts = None
            power_uw = read_int(f"{hwmon}/power{idx}_input")
            if power_uw is not None:
                watts = power_uw / 1_000_000.0
            else:
                mv = read_int(f"{hwmon}/in{idx}_input")
                ma = read_int(f"{hwmon}/curr{idx}_input")
                if mv is not None and ma is not None:
                    watts = (mv * ma) / 1_000_000.0
            if watts is None:
                continue
            rails[label] = watts
    return rails


def _pick_watts(rails: dict[str, float], *needles: str) -> float | None:
    items = [(str(name).lower().replace(" ", "_"), float(watts)) for name, watts in rails.items() if watts is not None]
    for needle in needles:
        want = needle.lower().replace(" ", "_")
        for key, watts in items:
            if key == want:
                return round(watts, 3)
        for key, watts in items:
            parts = key.split("_")
            if want == "soc" and "gpu" in parts:
                continue
            if want in parts or key.endswith("_" + want) or key.startswith(want + "_"):
                return round(watts, 3)
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


def _jetson_l4t() -> str | None:
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


def _jetson_driver() -> str | None:
    return _jetson_l4t()


def merge_gpu(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    extra = dict(base.get("extra") or {})
    extra.update(overlay.get("extra") or {})
    for key, value in overlay.items():
        if key == "extra":
            continue
        if out.get(key) in (None, "") and value not in (None, ""):
            out[key] = value
    smi_model = (out.get("model") or "").lower()
    overlay_model = overlay.get("model")
    if overlay_model and (not out.get("model") or "nvgpu" in smi_model):
        out["model"] = overlay_model
    if extra.get("memory_kind") == "unified" or extra.get("bus") == "soc":
        extra["bus"] = "soc"
        extra["memory_kind"] = extra.get("memory_kind") or "unified"
        out["slot_designation"] = overlay.get("slot_designation") or out.get("slot_designation") or "SoC (nvgpu)"
        out["pci_bus"] = None
        out["pci_device_id"] = None
        out["serial_number"] = None
        if out.get("vram_bytes") is None and extra.get("unified_ram_bytes"):
            out["vram_bytes"] = extra["unified_ram_bytes"]
    out["extra"] = extra
    return out
