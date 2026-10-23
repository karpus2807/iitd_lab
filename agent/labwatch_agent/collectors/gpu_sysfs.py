"""Enrich non-NVIDIA GPUs from Linux DRM/sysfs (Intel i915/xe, AMD amdgpu).

Market vendors we target on lab PCs:
  NVIDIA  — nvidia-smi (primary)
  AMD     — amdgpu DRM sysfs (+ optional rocm-smi later)
  Intel   — i915 / xe DRM sysfs (temp/power/clocks/util when kernel exposes them)

No paid SDKs. Prefer kernel sysfs (free, always present when driver is bound).
Optional apt packages: intel-gpu-tools (intel_gpu_top), mesa-utils — not required.
"""

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
    if re.search(r":00:0[12]\.[0-9a-f]$", pci) and ("intel" in blob or "amd" in blob or "radeon" in blob):
        if "nvidia" not in blob:
            return "integrated"
    if any(x in blob for x in ("uhd graphics", "hd graphics", "iris", "radeon graphics", "vega graphics", "igpu", "arrow lake", "alder lake", "meteor lake", "lunar lake")):
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


def _read_mhz_value(raw: int | None) -> float | None:
    if raw is None:
        return None
    if raw <= 0:
        return None
    if raw > 10_000:  # Hz
        return round(raw / 1_000_000.0, 1)
    return float(raw)


def _first_int(paths: list[Path]) -> int | None:
    for path in paths:
        if not path.exists():
            continue
        raw = read_int(str(path))
        if raw is not None:
            return raw
    return None


def _hwmon_roots(device: Path, card: Path) -> list[Path]:
    roots: list[Path] = []
    for base in (device, card, device / "tile0", device / "tile1"):
        if not base.exists():
            continue
        roots.extend(sorted(base.glob("hwmon/hwmon*")))
    # Global hwmon entries whose device symlink points at this PCI device.
    try:
        target = os.path.realpath(str(device))
    except OSError:
        target = ""
    if target:
        for hw in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                if os.path.realpath(str(hw / "device")) == target:
                    roots.append(hw)
            except OSError:
                continue
    # Dedupe
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _read_hwmon_temp_c(device: Path, card: Path) -> float | None:
    """Prefer GPU/package temps; skip critically high junk."""
    best: float | None = None
    for hw in _hwmon_roots(device, card):
        for path in sorted(hw.glob("temp*_input")):
            raw = read_int(str(path))
            if raw is None:
                continue
            val = round(raw / 1000.0, 1) if raw > 200 else float(raw)
            if val < 1 or val > 125:
                continue
            # Prefer labels mentioning gpu/pkg/edge when present.
            label_path = Path(str(path).replace("_input", "_label"))
            label = (read_text(str(label_path)) or "").lower()
            if any(x in label for x in ("gpu", "pkg", "package", "edge", "asic")):
                return val
            if best is None:
                best = val
    return best


def _read_hwmon_power_w(device: Path, card: Path) -> float | None:
    for hw in _hwmon_roots(device, card):
        for name in ("power1_average", "power1_input", "power2_average", "power2_input"):
            path = hw / name
            if not path.exists():
                continue
            raw = read_int(str(path))
            if raw is None or raw <= 0:
                continue
            if raw > 10_000:  # microwatts
                return round(raw / 1_000_000.0, 3)
            return float(raw)
        # energy counters: sample twice → watts
        energy = hw / "energy1_input"
        if energy.exists():
            a = read_int(str(energy))
            time.sleep(0.2)
            b = read_int(str(energy))
            if a is not None and b is not None and b > a:
                # microjoules over 0.2s → watts
                return round((b - a) / 0.2 / 1_000_000.0, 3)
    return None


def _read_graphics_clock_mhz(card: Path, device: Path) -> float | None:
    candidates: list[Path] = []
    for base in (device, card, *(device.glob("tile*")), *(device.glob("gt*")), *(card.glob("gt*"))):
        if not base.exists():
            continue
        for name in (
            "gt_cur_freq_mhz",
            "gt_act_freq_mhz",
            "gt_RP0_freq_mhz",
            "gt_RP1_freq_mhz",
            "rps_cur_freq_mhz",
            "freq0/cur_freq",
            "gt0/freq0/cur_freq",
            "gt0/rps_cur_freq_mhz",
        ):
            candidates.append(base / name)
        candidates.extend(base.glob("gt*/gt_cur_freq_mhz"))
        candidates.extend(base.glob("gt*/gt_act_freq_mhz"))
        candidates.extend(base.glob("**/gt_cur_freq_mhz"))
    raw = _first_int(candidates[:80])
    mhz = _read_mhz_value(raw)
    if mhz is not None:
        return mhz
    # AMD pp_dpm_sclk current marked with *
    sclk = read_text(str(device / "pp_dpm_sclk"))
    if sclk:
        for line in sclk.splitlines():
            if "*" in line:
                m = re.search(r"(\d+)\s*Mhz", line, re.I)
                if m:
                    val = float(m.group(1))
                    return val if val > 0 else None
    return None


def _read_memory_clock_mhz(device: Path) -> float | None:
    mclk = read_text(str(device / "pp_dpm_mclk"))
    if mclk:
        for line in mclk.splitlines():
            if "*" in line:
                m = re.search(r"(\d+)\s*Mhz", line, re.I)
                if m:
                    val = float(m.group(1))
                    return val if val > 0 else None
    for path in device.glob("**/mem_cur_freq_mhz"):
        mhz = _read_mhz_value(read_int(str(path)))
        if mhz:
            return mhz
    return None


def _read_vram_bytes(device: Path) -> tuple[int | None, int | None]:
    total = read_int(str(device / "mem_info_vram_total"))
    used = read_int(str(device / "mem_info_vram_used"))
    if total and total > 0:
        return total, used
    # Intel stolen memory (shared aperture) — useful as shared graphics size.
    stolen = read_int(str(device / "mem_info_stolen_total")) or read_int(str(device / "stolen"))
    if stolen and stolen > 0:
        return stolen, None
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


def _sample_engine_util_pct(card: Path, device: Path) -> float | None:
    """Best-effort util via DRM engine busy counters or xe gtidle residency."""
    engines = (
        list(card.glob("engine/*/busy"))
        + list(device.glob("engine/*/busy"))
        + list(device.glob("gt/*/engines/*/busy"))
        + list(card.glob("gt/*/engines/*/busy"))
        + list(device.glob("tile*/gt*/engines/*/busy"))
    )
    if engines:
        paths = [str(p) for p in engines[:12]]

        def snapshot() -> list[int]:
            vals = []
            for p in paths:
                v = read_int(p)
                if v is not None:
                    vals.append(v)
            return vals

        a = snapshot()
        if a:
            time.sleep(0.15)
            b = snapshot()
            if len(a) == len(b) and b:
                deltas = [max(0, y - x) for x, y in zip(a, b)]
                avg = sum(deltas) / len(deltas)
                wall_ns = 0.15 * 1e9
                return min(100.0, round((avg / wall_ns) * 100.0, 1))

    # xe: idle_residency_ms decreases when GPU is busy
    idle_paths = list(device.glob("tile*/gt*/gtidle/idle_residency_ms")) + list(
        device.glob("gt*/gtidle/idle_residency_ms")
    )
    if idle_paths:
        p = str(idle_paths[0])
        a = read_int(p)
        t0 = time.time()
        time.sleep(0.2)
        b = read_int(p)
        dt_ms = max(1.0, (time.time() - t0) * 1000.0)
        if a is not None and b is not None and b >= a:
            idle_delta = b - a
            busy = max(0.0, 1.0 - (idle_delta / dt_ms))
            return min(100.0, round(busy * 100.0, 1))
    return None


def _intel_gpu_top_util_pct() -> float | None:
    """Optional: intel_gpu_top from intel-gpu-tools (free apt package)."""
    import json
    import shutil
    import subprocess

    if not shutil.which("intel_gpu_top"):
        return None
    try:
        # One JSON sample (~100ms). Needs CAP_PERFMON or root on some kernels.
        proc = subprocess.run(
            ["intel_gpu_top", "-J", "-s", "100", "-o", "-"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            return None
        text = proc.stdout.strip()
        # Output may be a stream of JSON objects; take the last complete object.
        payload = None
        for chunk in text.split("\n{"):
            blob = chunk if chunk.startswith("{") else "{" + chunk
            try:
                payload = json.loads(blob)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            return None
        engines = payload.get("engines") or {}
        busy_vals: list[float] = []
        if isinstance(engines, dict):
            for eng in engines.values():
                if isinstance(eng, dict) and eng.get("busy") is not None:
                    try:
                        busy_vals.append(float(eng["busy"]))
                    except (TypeError, ValueError):
                        pass
        if not busy_vals:
            # Older format: engines list
            for eng in engines if isinstance(engines, list) else []:
                if isinstance(eng, dict) and eng.get("busy") is not None:
                    try:
                        busy_vals.append(float(eng["busy"]))
                    except (TypeError, ValueError):
                        pass
        if not busy_vals:
            return None
        return min(100.0, round(max(busy_vals), 1))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _thermal_zone_gpu_temp_c() -> float | None:
    """Fallback GPU/SoC temps from thermal zones (avoid pure CPU package labels)."""
    base = Path("/sys/class/thermal")
    if not base.is_dir():
        return None
    best: float | None = None
    for zone in sorted(base.glob("thermal_zone*")):
        ztype = (read_text(str(zone / "type")) or "").lower()
        if not any(x in ztype for x in ("gpu", "graphics", "iwl", "soc", "nvgpu", "tegra")):
            continue
        if "cpu" in ztype and "gpu" not in ztype:
            continue
        raw = read_int(str(zone / "temp"))
        if raw is None:
            continue
        val = round(raw / 1000.0, 1) if raw > 200 else float(raw)
        if 1 <= val <= 125:
            return val
        best = val if best is None else best
    return best


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
        for attr in ("product_name", "label"):
            model = read_text(str(device / attr))
            if model:
                break
        rows.append(
            {
                "card": card.name,
                "pci_bus": pci,
                "vendor": vendor,
                "driver_module": driver,
                "vram_bytes": vram_total,
                "vram_used_bytes": vram_used,
                "temperature_c": _read_hwmon_temp_c(device, card),
                "power_w": _read_hwmon_power_w(device, card),
                "graphics_clock_mhz": _read_graphics_clock_mhz(card, device),
                "memory_clock_mhz": _read_memory_clock_mhz(device),
                "utilization_pct": _sample_engine_util_pct(card, device),
                "model": model,
                "driver_bound": bool(driver),
            }
        )
    # Fill util/temp gaps with optional tools / thermal zones (once per scan).
    need_util = any(r.get("utilization_pct") is None for r in rows)
    need_temp = any(r.get("temperature_c") is None for r in rows)
    intel_util = _intel_gpu_top_util_pct() if need_util else None
    zone_temp = _thermal_zone_gpu_temp_c() if need_temp else None
    for r in rows:
        if r.get("utilization_pct") is None and intel_util is not None and (r.get("vendor") or "").lower() == "intel":
            r["utilization_pct"] = intel_util
        if r.get("temperature_c") is None and zone_temp is not None:
            r["temperature_c"] = zone_temp
    return rows


def modinfo_version(module: str | None) -> str | None:
    """Human-readable module version only — never return srcversion hashes."""
    if not module:
        return None
    ver = (read_text(f"/sys/module/{module}/version") or "").strip()
    if ver and not re.fullmatch(r"[0-9A-Fa-f]{16,}", ver):
        return ver
    return None


def compute_telemetry_pct(gpu: dict[str, Any]) -> float:
    """Fraction of applicable telemetry fields that are populated (0–100)."""
    extra = gpu.get("extra") or {}
    kind = (extra.get("gpu_kind") or gpu.get("slot_designation") or "").lower()
    integrated = kind in {"integrated", "soc"} or "integrated" in kind
    checks: list[bool] = [
        gpu.get("temperature_c") is not None,
        gpu.get("utilization_pct") is not None,
        gpu.get("power_w") is not None,
        bool(gpu.get("graphics_clock_mhz")),
        bool(gpu.get("driver_version") or extra.get("driver_module")),
        bool(gpu.get("pci_bus") or gpu.get("pci_device_id")),
    ]
    if not integrated:
        checks.append(gpu.get("memory_clock_mhz") is not None)
        checks.append(gpu.get("vram_bytes") is not None)
    else:
        # Shared memory is expected; count as present when kind is known.
        checks.append(True)
    if not checks:
        return 0.0
    return round(100.0 * sum(1 for c in checks if c) / len(checks), 1)


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
            if out.get(key) in (None, "", [], 0) and match.get(key) not in (None, "", 0):
                out[key] = match[key]
        if not out.get("vendor"):
            out["vendor"] = match.get("vendor")
        mod = match.get("driver_module")
        ver = modinfo_version(mod)
        # Prefer "i915 1.2.3" or plain module name — never opaque srcversion hashes.
        display_driver = None
        if mod and ver:
            display_driver = f"{mod} {ver}"
        elif mod:
            display_driver = mod
        elif ver:
            display_driver = ver
        # Replace hash-looking driver_version from older agents.
        prev = str(out.get("driver_version") or "")
        if display_driver and (not prev or re.fullmatch(r"[0-9A-Fa-f]{16,}", prev)):
            out["driver_version"] = display_driver
        if match.get("vram_used_bytes") is not None:
            extra["vram_used_bytes"] = match["vram_used_bytes"]
        if mod:
            extra["driver_module"] = mod
        if match.get("card"):
            extra["drm_card"] = match["card"]
        if match.get("driver_bound"):
            extra["driver_status"] = "ok"
            extra["driver_ok"] = True
        else:
            extra["driver_status"] = "unbound"
            extra["driver_ok"] = False
    else:
        # PCI device seen but no DRM card — driver likely missing/blacklisted.
        if out.get("pci_bus") or out.get("model"):
            extra.setdefault("driver_status", "not_bound")
            extra.setdefault("driver_ok", False)

    # Normalize zero clocks to missing (Arrow Lake idle often reports 0).
    if out.get("graphics_clock_mhz") in (0, 0.0):
        out["graphics_clock_mhz"] = None
    if out.get("memory_clock_mhz") in (0, 0.0):
        out["memory_clock_mhz"] = None

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
        if out.get("vram_bytes"):
            extra["shared_graphics_bytes"] = out["vram_bytes"]
    else:
        out["slot_designation"] = out.get("slot_designation") or "Dedicated"
        extra.setdefault("memory_kind", "dedicated")

    out["extra"] = extra
    out["pci_bus"] = normalize_pci_bus(out.get("pci_bus")) or out.get("pci_bus")
    extra["telemetry_pct"] = compute_telemetry_pct(out)
    out["extra"] = extra
    return out


def dedupe_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate PCI rows (same bus)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for g in gpus:
        key = normalize_pci_bus(g.get("pci_bus")) or f"idx:{g.get('index')}:{g.get('model')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    for i, g in enumerate(out):
        g["index"] = i
    return out
