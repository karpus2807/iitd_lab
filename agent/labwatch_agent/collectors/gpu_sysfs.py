"""Enrich non-NVIDIA GPUs from Linux DRM/sysfs (Intel i915/xe, AMD amdgpu)."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from labwatch_agent.util import read_int, read_text

_PCI_VENDOR = {
    "8086": "Intel",
    "10de": "NVIDIA",
    "1002": "AMD",
    "1022": "AMD",
}


def vendor_from_text(text: str) -> str | None:
    """Detect GPU vendor without false AMD matches (e.g. 'Corporation' contains 'ati')."""
    low = (text or "").lower()
    if "nvidia" in low or "[10de:" in low:
        return "NVIDIA"
    if "intel" in low or "[8086:" in low:
        return "Intel"
    if "advanced micro devices" in low or "[1002:" in low or "[1022:" in low:
        return "AMD"
    if re.search(r"(^|[^a-z])(amd|radeon)([^a-z]|$)", low):
        return "AMD"
    if re.search(r"(^|[^a-z])ati([^a-z]|$)", low) and "corporation" not in low:
        return "AMD"
    return None


def normalize_pci_bus(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    # 0000:00:02.0 or 00:02.0
    m = re.search(r"(?:([0-9a-f]{4}):)?([0-9a-f]{2}):([0-9a-f]{2})\.([0-9a-f])", text, re.I)
    if not m:
        return text.split()[0] if text.split() else text
    domain, bus, dev, fn = m.groups()
    domain = (domain or "0000").lower()
    return f"{domain}:{bus.lower()}:{dev.lower()}.{fn.lower()}"


def classify_gpu_kind(*, vendor: str | None, model: str | None, pci_bus: str | None, driver: str | None, vram_bytes: int | None) -> str:
    """Return 'integrated' or 'discrete'."""
    blob = f"{vendor or ''} {model or ''} {driver or ''}".lower()
    pci = normalize_pci_bus(pci_bus) or ""
    # Classic Intel/AMD iGPU on root complex 00:02.x / 00:01.x style.
    if re.search(r":00:0[12]\.[0-9a-f]$", pci) and ("intel" in blob or "amd" in blob or "radeon" in blob):
        if "nvidia" not in blob:
            return "integrated"
    if any(x in blob for x in ("uhd graphics", "hd graphics", "iris", "radeon graphics", "vega graphics", "igpu")):
        return "integrated"
    if driver in {"i915", "xe"} and (vram_bytes is None or vram_bytes < 512 * 1024**2):
        return "integrated"
    if "nvidia" in blob or driver in {"nvidia", "nvidiafb"}:
        return "discrete"
    if driver == "amdgpu" and vram_bytes and vram_bytes >= 1024**3:
        return "discrete"
    if vram_bytes and vram_bytes >= 1024**3:
        return "discrete"
    if "intel" in blob or driver in {"i915", "xe"}:
        return "integrated"
    return "discrete"


def _read_hwmon_temp_c(device: Path) -> float | None:
    for path in sorted(device.glob("hwmon/hwmon*/temp*_input")):
        raw = read_int(str(path))
        if raw is None:
            continue
        # millidegrees
        if raw > 200:
            return round(raw / 1000.0, 1)
        return float(raw)
    return None


def _read_hwmon_power_w(device: Path) -> float | None:
    for name in ("power1_average", "power1_input"):
        for path in sorted(device.glob(f"hwmon/hwmon*/{name}")):
            raw = read_int(str(path))
            if raw is None:
                continue
            # microwatts
            if raw > 10_000:
                return round(raw / 1_000_000.0, 3)
            return float(raw)
    return None


def _read_graphics_clock_mhz(card: Path, device: Path) -> float | None:
    for rel in (
        "gt_cur_freq_mhz",
        "gt/gt0/freq0/cur_freq",
        "gt/gt0/rps_cur_freq_mhz",
    ):
        raw = read_int(str(device / rel)) if (device / rel).exists() else read_int(str(card / rel))
        if raw is None:
            continue
        if raw > 10_000:  # Hz
            return round(raw / 1_000_000.0, 1)
        return float(raw)
    # AMD pp_dpm_sclk current marked with *
    sclk = read_text(str(device / "pp_dpm_sclk"))
    if sclk:
        for line in sclk.splitlines():
            if "*" in line:
                m = re.search(r"(\d+)\s*Mhz", line, re.I)
                if m:
                    return float(m.group(1))
    return None


def _read_memory_clock_mhz(device: Path) -> float | None:
    mclk = read_text(str(device / "pp_dpm_mclk"))
    if mclk:
        for line in mclk.splitlines():
            if "*" in line:
                m = re.search(r"(\d+)\s*Mhz", line, re.I)
                if m:
                    return float(m.group(1))
    return None


def _read_vram_bytes(device: Path) -> tuple[int | None, int | None]:
    total = read_int(str(device / "mem_info_vram_total"))
    used = read_int(str(device / "mem_info_vram_used"))
    if total and total > 0:
        return total, used
    # Some Intel expose stolen / GTT only — treat as shared, not discrete VRAM.
    return None, None


def _driver_from_uevent(device: Path) -> str | None:
    text = read_text(str(device / "uevent")) or ""
    for line in text.splitlines():
        if line.startswith("DRIVER="):
            return line.split("=", 1)[1].strip() or None
    link = device / "driver"
    if link.exists():
        try:
            return os.path.basename(os.path.realpath(str(link)))
        except OSError:
            return None
    return None


def _pci_from_uevent(device: Path) -> str | None:
    text = read_text(str(device / "uevent")) or ""
    for line in text.splitlines():
        if line.startswith("PCI_SLOT_NAME="):
            return normalize_pci_bus(line.split("=", 1)[1].strip())
    return normalize_pci_bus(device.name if ":" in device.name else None)


def _vendor_from_ids(device: Path) -> str | None:
    vid = (read_text(str(device / "vendor")) or "").strip().lower().replace("0x", "")
    return _PCI_VENDOR.get(vid)


def _sample_engine_util_pct(card: Path) -> float | None:
    """Best-effort Intel/AMD engine busy% via DRM busy counters (two samples)."""
    engines = list(card.glob("engine/*/busy")) + list((card / "device").glob("engine/*/busy"))
    if not engines:
        # xe: gt/gt0/engines/*/busy
        engines = list((card / "device").glob("gt/*/engines/*/busy")) + list(card.glob("gt/*/engines/*/busy"))
    if not engines:
        return None
    paths = [str(p) for p in engines[:8]]

    def snapshot() -> list[int]:
        vals = []
        for p in paths:
            v = read_int(p)
            if v is not None:
                vals.append(v)
        return vals

    a = snapshot()
    if not a:
        return None
    time.sleep(0.12)
    b = snapshot()
    if len(a) != len(b) or not b:
        return None
    # busy counters are ns; delta / wall ≈ util. Cap at 100.
    deltas = [max(0, y - x) for x, y in zip(a, b)]
    if not deltas:
        return None
    # Average busy across engines, convert ns over ~120ms window.
    avg = sum(deltas) / len(deltas)
    wall_ns = 0.12 * 1e9
    pct = min(100.0, round((avg / wall_ns) * 100.0, 1))
    return pct


def iter_drm_gpus() -> list[dict[str, Any]]:
    """Return one dict per physical DRM card (skip connectors like card0-HDMI-A-1)."""
    rows: list[dict[str, Any]] = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        if not card.name[4:].isdigit():
            continue
        device = card / "device"
        if not device.is_dir():
            continue
        pci = _pci_from_uevent(device)
        vendor = _vendor_from_ids(device)
        driver = _driver_from_uevent(device)
        vram_total, vram_used = _read_vram_bytes(device)
        model = None
        # Prefer kernel product name if present
        for attr in ("product_name", "label"):
            model = read_text(str(device / attr))
            if model:
                break
        rows.append(
            {
                "card": card.name,
                "pci_bus": pci,
                "vendor": vendor,
                "driver_version": driver,  # kernel module name; version filled elsewhere if known
                "driver_module": driver,
                "vram_bytes": vram_total,
                "vram_used_bytes": vram_used,
                "temperature_c": _read_hwmon_temp_c(device),
                "power_w": _read_hwmon_power_w(device),
                "graphics_clock_mhz": _read_graphics_clock_mhz(card, device),
                "memory_clock_mhz": _read_memory_clock_mhz(device),
                "utilization_pct": _sample_engine_util_pct(card),
                "model": model,
            }
        )
    return rows


def modinfo_version(module: str | None) -> str | None:
    if not module:
        return None
    # /sys/module/<name>/version
    ver = read_text(f"/sys/module/{module}/version")
    if ver:
        return ver.strip()
    src = read_text(f"/sys/module/{module}/srcversion")
    return src.strip() if src else None


def enrich_linux_gpu(gpu: dict[str, Any], drm_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Merge DRM sysfs telemetry into a GPU inventory dict."""
    drm_rows = drm_rows if drm_rows is not None else iter_drm_gpus()
    pci = normalize_pci_bus(gpu.get("pci_bus"))
    match = None
    if pci:
        for row in drm_rows:
            if normalize_pci_bus(row.get("pci_bus")) == pci:
                match = row
                break
    if match is None and len(drm_rows) == 1 and not gpu.get("vendor"):
        match = drm_rows[0]
    if match is None and gpu.get("vendor"):
        # Match by vendor when only one DRM card of that vendor exists.
        same = [r for r in drm_rows if (r.get("vendor") or "").lower() == (gpu.get("vendor") or "").lower()]
        if len(same) == 1:
            match = same[0]

    out = dict(gpu)
    extra = dict(out.get("extra") or {})
    if match:
        for key in (
            "temperature_c",
            "power_w",
            "graphics_clock_mhz",
            "memory_clock_mhz",
            "utilization_pct",
            "vram_bytes",
            "pci_bus",
        ):
            if out.get(key) in (None, "", []) and match.get(key) not in (None, ""):
                out[key] = match[key]
        if not out.get("vendor"):
            out["vendor"] = match.get("vendor")
        mod = match.get("driver_module")
        ver = modinfo_version(mod) or mod
        if not out.get("driver_version") and ver:
            out["driver_version"] = ver
        if match.get("vram_used_bytes") is not None:
            extra["vram_used_bytes"] = match["vram_used_bytes"]
        if mod:
            extra["driver_module"] = mod
        if match.get("card"):
            extra["drm_card"] = match["card"]

    vendor = out.get("vendor") or vendor_from_text(str(out.get("model") or ""))
    out["vendor"] = vendor
    kind = classify_gpu_kind(
        vendor=vendor,
        model=out.get("model"),
        pci_bus=out.get("pci_bus"),
        driver=extra.get("driver_module") or out.get("driver_version"),
        vram_bytes=out.get("vram_bytes"),
    )
    extra["gpu_kind"] = kind
    if kind == "integrated":
        out["slot_designation"] = out.get("slot_designation") or "Integrated"
        extra.setdefault("memory_kind", "shared")
        # Shared memory reporting: keep vram_bytes as Windows-style aperture if present,
        # but UI should label it as shared graphics memory.
        if out.get("vram_bytes"):
            extra["shared_graphics_bytes"] = out["vram_bytes"]
    else:
        out["slot_designation"] = out.get("slot_designation") or "Dedicated"
        extra.setdefault("memory_kind", "dedicated")
    out["extra"] = extra
    out["pci_bus"] = normalize_pci_bus(out.get("pci_bus")) or out.get("pci_bus")
    return out
