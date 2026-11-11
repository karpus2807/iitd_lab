"""Connected display / monitor inventory (EDID + Windows WMI).

Reports manufacturer, serial/service tag, diagonal size, resolution, and
connector type. Never invents missing fields — blanks stay None.
"""

from __future__ import annotations

import glob
import math
import os
import re
from typing import Any

from labwatch_agent.util import read_text, run_cmd, which

# Common PNP / EDID manufacturer IDs → brand (extend as needed).
_PNP_MANUFACTURERS: dict[str, str] = {
    "AAC": "Acer",
    "ACR": "Acer",
    "ACI": "Asus",
    "ACT": "Targa",
    "ADI": "ADI",
    "AOC": "AOC",
    "API": "Acer",
    "APP": "Apple",
    "ASC": "Asus",
    "ASM": "Asus",
    "AUS": "Asus",
    "BNQ": "BenQ",
    "BOE": "BOE",
    "CMN": "Chimei Innolux",
    "CMO": "Chi Mei Optoelectronics",
    "CPS": "Chunghwa",
    "CPQ": "Compaq",
    "CTL": "Creative",
    "DEL": "Dell",
    "DPC": "Delta",
    "DWE": "Daewoo",
    "ECS": "ELITEGROUP",
    "ENC": "Eizo",
    "EIZ": "Eizo",
    "EPI": "Envision",
    "GSM": "LG",
    "GWY": "Gateway",
    "HEI": "Hyundai",
    "HPN": "HP",
    "HPD": "HP",
    "HPQ": "HP",
    "HSD": "HannStar",
    "HSP": "HannStar",
    "HTC": "Hitachi",
    "HWP": "HP",
    "IBM": "IBM",
    "ICL": "Fujitsu",
    "IVM": "Iiyama",
    "IQT": "ImageQuest",
    "LEN": "Lenovo",
    "LGD": "LG Display",
    "LPL": "LG Philips",
    "LTN": "Lite-On",
    "MAX": "Belinea",
    "MEI": "Panasonic",
    "MEL": "Mitsubishi",
    "MSI": "MSI",
    "NAN": "Nanao",
    "NEC": "NEC",
    "NOK": "Nokia",
    "PHL": "Philips",
    "PGS": "Princeton",
    "PKL": "Amtran",
    "PRT": "Princeton",
    "REL": "Relisys",
    "SAM": "Samsung",
    "SAN": "Sanyo",
    "SEC": "Samsung",
    "SHP": "Sharp",
    "SII": "Seiko",
    "SNY": "Sony",
    "SPC": "Samsung",
    "STN": "Samtron",
    "STP": "Sceptre",
    "SUN": "Sun",
    "SYN": "Synaptics",
    "TCL": "TCL",
    "TEK": "Tektronix",
    "VSC": "ViewSonic",
    "WTC": "Wen Technology",
    "YMH": "Yamaha",
}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "none", "n/a", "null", "default string", "to be filled by o.e.m."}:
        return None
    return text


def _pnp_brand(code: str | None) -> str | None:
    if not code:
        return None
    up = code.strip().upper()
    return _PNP_MANUFACTURERS.get(up) or up


def _inches_from_cm(h_cm: int | None, v_cm: int | None) -> float | None:
    if not h_cm or not v_cm or h_cm <= 0 or v_cm <= 0:
        return None
    # EDID max image size is in cm; diagonal / 2.54 → inches.
    inches = math.sqrt(h_cm * h_cm + v_cm * v_cm) / 2.54
    if inches < 5 or inches > 120:
        return None
    return round(inches, 1)


def _decode_edid_mfg(edid: bytes) -> str | None:
    if len(edid) < 10:
        return None
    raw = (edid[8] << 8) | edid[9]
    chars = [((raw >> 10) & 0x1F) + 64, ((raw >> 5) & 0x1F) + 64, (raw & 0x1F) + 64]
    if any(c < 65 or c > 90 for c in chars):
        return None
    return "".join(chr(c) for c in chars)


def _edid_descriptors(edid: bytes) -> list[bytes]:
    if len(edid) < 128:
        return []
    return [edid[i : i + 18] for i in range(54, 126, 18)]


def _edid_ascii_descriptor(block: bytes, tag: int) -> str | None:
    # Detailed descriptor: pixel clock 0, tag at byte 3.
    if len(block) < 18 or block[0] or block[1] or block[2]:
        return None
    if block[3] != tag:
        return None
    raw = bytes(b for b in block[5:18] if 32 <= b <= 126)
    text = raw.decode("ascii", errors="ignore").strip().rstrip("\x00").strip()
    return text or None


def _edid_preferred_timing(edid: bytes) -> tuple[int | None, int | None, float | None]:
    if len(edid) < 72:
        return None, None, None
    block = edid[54:72]
    pixel_clock_10khz = block[0] | (block[1] << 8)
    if pixel_clock_10khz == 0:
        return None, None, None
    h_active = block[2] | ((block[4] & 0xF0) << 4)
    v_active = block[5] | ((block[7] & 0xF0) << 4)
    h_blank = block[3] | ((block[4] & 0x0F) << 8)
    v_blank = block[6] | ((block[7] & 0x0F) << 8)
    refresh = None
    total_h = h_active + h_blank
    total_v = v_active + v_blank
    if total_h > 0 and total_v > 0:
        refresh = round((pixel_clock_10khz * 10000) / (total_h * total_v), 2)
    return h_active or None, v_active or None, refresh


def parse_edid(edid: bytes) -> dict[str, Any]:
    """Parse a binary EDID block into monitor identity fields."""
    out: dict[str, Any] = {}
    if len(edid) < 128:
        return out
    if edid[0:8] != bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]):
        return out

    mfg_code = _decode_edid_mfg(edid)
    out["manufacturer_code"] = mfg_code
    out["manufacturer"] = _pnp_brand(mfg_code)

    product_code = edid[10] | (edid[11] << 8)
    out["product_code"] = f"{product_code:04X}" if product_code else None

    serial_dword = edid[12] | (edid[13] << 8) | (edid[14] << 16) | (edid[15] << 24)
    out["serial_number"] = str(serial_dword) if serial_dword not in (0, 0x01010101) else None

    week = edid[16]
    year = edid[17] + 1990 if edid[17] else None
    if week and week <= 53 and year:
        out["manufacture_week"] = week
        out["manufacture_year"] = year
        out["year_week"] = f"{year}-W{week:02d}"
    elif year:
        out["manufacture_year"] = year
        out["year_week"] = str(year)

    h_cm, v_cm = edid[21], edid[22]
    out["width_cm"] = h_cm or None
    out["height_cm"] = v_cm or None
    out["size_inches"] = _inches_from_cm(h_cm, v_cm)

    w_px, h_px, refresh = _edid_preferred_timing(edid)
    out["width_px"] = w_px
    out["height_px"] = h_px
    out["refresh_hz"] = refresh

    model_name = None
    serial_ascii = None
    for block in _edid_descriptors(edid):
        name = _edid_ascii_descriptor(block, 0xFC)
        if name:
            model_name = name
        ser = _edid_ascii_descriptor(block, 0xFF)
        if ser:
            serial_ascii = ser
    if serial_ascii:
        out["serial_number"] = serial_ascii
    if model_name:
        out["model"] = model_name
    elif out.get("product_code"):
        # Fallback: brand + product code (e.g. Dell A0C9).
        brand = out.get("manufacturer") or mfg_code or "Monitor"
        out["model"] = f"{brand} {out['product_code']}"

    out["edid_hex"] = edid[:128].hex()
    return out


def _connector_kind(name: str) -> str | None:
    low = name.lower()
    mapping = [
        ("hdmi", "HDMI"),
        ("displayport", "DisplayPort"),
        ("dp-", "DisplayPort"),
        ("edp", "eDP"),
        ("dvi", "DVI"),
        ("vga", "VGA"),
        ("lvds", "LVDS"),
        ("dsi", "DSI"),
        ("usb-c", "USB-C"),
        ("typec", "USB-C"),
        ("thunderbolt", "Thunderbolt"),
        ("virtual", "Virtual"),
        ("writeback", "Writeback"),
    ]
    for needle, label in mapping:
        if needle in low:
            return label
    return None


def _short_connector(sys_name: str) -> str:
    # card0-DP-1 → DP-1
    m = re.match(r"^card\d+-(.+)$", sys_name)
    return m.group(1) if m else sys_name


def collect_displays_linux() -> dict[str, Any]:
    notes: list[str] = []
    displays: list[dict[str, Any]] = []
    paths = sorted(glob.glob("/sys/class/drm/card*-*/status"))
    if not paths:
        notes.append("No DRM connectors under /sys/class/drm (headless or no GPU driver).")
        return {"displays": [], "notes": notes}

    for status_path in paths:
        conn_dir = os.path.dirname(status_path)
        sys_name = os.path.basename(conn_dir)
        if "writeback" in sys_name.lower() or "virtual" in sys_name.lower():
            continue
        status = (read_text(status_path) or "").strip().lower()
        if status != "connected":
            continue

        connector = _short_connector(sys_name)
        connection = _connector_kind(sys_name) or _connector_kind(connector)
        entry: dict[str, Any] = {
            "name": connector,
            "connector": connector,
            "connection": connection,
            "connected": True,
            "manufacturer": None,
            "model": None,
            "serial_number": None,
            "product_code": None,
            "size_inches": None,
            "width_px": None,
            "height_px": None,
            "refresh_hz": None,
            "year_week": None,
            "extra": {"sysfs": conn_dir, "drm_name": sys_name},
        }

        edid_path = os.path.join(conn_dir, "edid")
        try:
            with open(edid_path, "rb") as f:
                edid = f.read()
        except OSError:
            edid = b""
        if edid and len(edid) >= 128:
            parsed = parse_edid(edid)
            for key in (
                "manufacturer",
                "model",
                "serial_number",
                "product_code",
                "size_inches",
                "width_px",
                "height_px",
                "refresh_hz",
                "year_week",
            ):
                if parsed.get(key) is not None:
                    entry[key] = parsed[key]
            extra = entry["extra"]
            if parsed.get("manufacturer_code"):
                extra["manufacturer_code"] = parsed["manufacturer_code"]
            if parsed.get("width_cm"):
                extra["width_cm"] = parsed["width_cm"]
            if parsed.get("height_cm"):
                extra["height_cm"] = parsed["height_cm"]
            if parsed.get("edid_hex"):
                extra["edid_hex"] = parsed["edid_hex"]
            if parsed.get("manufacture_year"):
                extra["manufacture_year"] = parsed["manufacture_year"]
            if parsed.get("manufacture_week"):
                extra["manufacture_week"] = parsed["manufacture_week"]
        else:
            notes.append(f"{connector}: connected but EDID unreadable")

        # Modes file first line sometimes has preferred mode "1920x1080"
        modes = read_text(os.path.join(conn_dir, "modes"))
        if modes and not entry.get("width_px"):
            first = modes.splitlines()[0].strip()
            m = re.match(r"^(\d+)x(\d+)", first)
            if m:
                entry["width_px"] = int(m.group(1))
                entry["height_px"] = int(m.group(2))

        displays.append(entry)

    if which("xrandr"):
        # Optional cross-check only — do not replace sysfs identity.
        code, out, _ = run_cmd(["xrandr", "--query"], timeout=8)
        if code == 0 and out.strip():
            notes.append("xrandr available (sysfs EDID used as primary source).")

    if not displays:
        notes.append("No connected displays reported by DRM.")
    return {"displays": displays, "notes": notes}


_VIDEO_TECH = {
    0: "VGA",
    1: "S-Video",
    4: "DVI",
    5: "HDMI",
    6: "LVDS",
    8: "D-Jpn",
    9: "SDI",
    10: "DisplayPort",
    11: "DisplayPort",
    12: "DisplayPort",
    13: "UDI",
    14: "Miracast",
    15: "Internal",
}


def _wmi_uint16_string(values: Any) -> str | None:
    """Decode legacy UInt16[] blobs (kept for tests / older CIM payloads)."""
    if values is None:
        return None
    if isinstance(values, str):
        return _clean(values)
    if not isinstance(values, list):
        return None
    chars: list[str] = []
    for v in values:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n == 0:
            break
        if 32 <= n <= 126:
            chars.append(chr(n))
    return _clean("".join(chars))


def _year_week(year: Any, week: Any) -> str | None:
    try:
        y = int(year) if year is not None else 0
        if y <= 1980:
            return None
        if week is not None and 1 <= int(week) <= 53:
            return f"{y}-W{int(week):02d}"
        return str(y)
    except (TypeError, ValueError):
        return None


def _connector_from_instance(instance: str) -> str | None:
    # DISPLAY\DELA0C9\5&… → DELA0C9
    m = re.search(r"DISPLAY\\([^\\]+)", instance or "", re.I)
    if m:
        return m.group(1)
    return None


def _entry_from_edid(
    *,
    edid_hex: str,
    name: str | None = None,
    connector: str | None = None,
    connection: str | None = None,
    instance: str | None = None,
    source: str = "registry",
) -> dict[str, Any] | None:
    try:
        raw = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", edid_hex))
    except ValueError:
        return None
    if len(raw) < 128:
        return None
    parsed = parse_edid(raw)
    if not parsed:
        return None
    mfg_code = parsed.get("manufacturer_code")
    model = parsed.get("model")
    product = parsed.get("product_code")
    connector = connector or product or name
    return {
        "name": name or connector or model or "Monitor",
        "connector": connector,
        "connection": connection,
        "connected": True,
        "manufacturer": parsed.get("manufacturer") or _pnp_brand(mfg_code),
        "model": _clean(model),
        "serial_number": _clean(parsed.get("serial_number")),
        "product_code": _clean(product),
        "size_inches": parsed.get("size_inches"),
        "width_px": parsed.get("width_px"),
        "height_px": parsed.get("height_px"),
        "refresh_hz": parsed.get("refresh_hz"),
        "year_week": parsed.get("year_week"),
        "extra": {
            "source": source,
            "instance_name": instance,
            "manufacturer_code": mfg_code,
            "width_cm": parsed.get("width_cm"),
            "height_cm": parsed.get("height_cm"),
            "edid_hex": parsed.get("edid_hex"),
            "display_hw_id": connector,
        },
    }


def _entry_from_wmi_monitor(mid: dict[str, Any]) -> dict[str, Any]:
    instance = str(mid.get("instance_name") or mid.get("InstanceName") or "")
    # New script already decodes to strings; legacy path may still send UInt16[].
    mfg_code = _clean(mid.get("manufacturer_code")) or _wmi_uint16_string(mid.get("ManufacturerName"))
    product = _clean(mid.get("product_code")) or _wmi_uint16_string(mid.get("ProductCodeID"))
    serial = _clean(mid.get("serial_number")) or _wmi_uint16_string(mid.get("SerialNumberID"))
    friendly = _clean(mid.get("friendly_name")) or _wmi_uint16_string(mid.get("UserFriendlyName"))

    try:
        h_cm_i = int(mid["width_cm"]) if mid.get("width_cm") is not None else None
        v_cm_i = int(mid["height_cm"]) if mid.get("height_cm") is not None else None
    except (TypeError, ValueError):
        h_cm_i = v_cm_i = None

    tech = mid.get("video_output_technology")
    try:
        tech_i = int(tech) if tech is not None else None
    except (TypeError, ValueError):
        tech_i = None
    connection = _VIDEO_TECH.get(tech_i) if tech_i is not None else None
    connector = _connector_from_instance(instance) or product
    manufacturer = _pnp_brand(mfg_code)
    # Prefer friendly name; leave model empty when only a short product code exists
    # so registry/EDID can supply the real monitor name (e.g. DELL P2419H).
    model = friendly
    if not model and manufacturer and connector and not product:
        model = f"{manufacturer} {connector}"

    return {
        "name": connector or friendly or "Monitor",
        "connector": connector,
        "connection": connection,
        "connected": True,
        "manufacturer": manufacturer,
        "model": _clean(model),
        "serial_number": serial,
        "product_code": _clean(product),
        "size_inches": _inches_from_cm(h_cm_i, v_cm_i),
        "width_px": None,
        "height_px": None,
        "refresh_hz": None,
        "year_week": _year_week(mid.get("year") or mid.get("YearOfManufacture"), mid.get("week") or mid.get("WeekOfManufacture")),
        "extra": {
            "source": "wmi",
            "instance_name": instance or None,
            "manufacturer_code": mfg_code,
            "width_cm": h_cm_i,
            "height_cm": v_cm_i,
            "video_output_technology": tech_i,
        },
    }


def _merge_edid_into(entry: dict[str, Any], edid_hex: str) -> None:
    parsed_entry = _entry_from_edid(edid_hex=edid_hex, name=entry.get("name"), connector=entry.get("connector"))
    if not parsed_entry:
        return

    def _prefer(key: str, *, richer: bool = False) -> None:
        new = parsed_entry.get(key)
        old = entry.get(key)
        if new in (None, ""):
            return
        if old in (None, ""):
            entry[key] = new
            return
        if not richer:
            return
        # Prefer EDID monitor-name / ASCII serial over short product codes.
        if isinstance(old, str) and isinstance(new, str) and len(new) > len(old):
            entry[key] = new
        elif key in {"size_inches", "width_px", "height_px", "refresh_hz"}:
            entry[key] = new

    for key in ("manufacturer", "product_code", "year_week"):
        _prefer(key)
    for key in ("model", "serial_number", "size_inches", "width_px", "height_px", "refresh_hz"):
        _prefer(key, richer=True)
    extra = entry.setdefault("extra", {})
    for k, v in (parsed_entry.get("extra") or {}).items():
        if k == "source":
            continue
        if extra.get(k) in (None, "") and v not in (None, ""):
            extra[k] = v
    extra["edid_merged"] = True


def _match_edid_for_monitor(entry: dict[str, Any], edids: list[dict[str, Any]]) -> str | None:
    connector = (entry.get("connector") or "").upper()
    product = (entry.get("product_code") or "").upper()
    instance = str((entry.get("extra") or {}).get("instance_name") or "").upper()
    for ed in edids:
        hw = str(ed.get("display_hw_id") or "").upper()
        if not hw:
            continue
        if connector and hw == connector:
            return ed.get("edid_hex")
        if product and hw == product:
            return ed.get("edid_hex")
        if instance and hw in instance:
            return ed.get("edid_hex")
    return None


def collect_displays_windows(cim: dict[str, Any] | None = None) -> dict[str, Any]:
    """Windows monitors via dedicated PowerShell (WmiMonitor* + registry EDID).

    ``cim`` is accepted for tests / legacy callers; live collection uses
    ``windows.collect_monitor_raw()`` so UInt16 arrays are decoded in PowerShell
    and main hardware CIM is not blocked by monitor queries.
    """
    notes: list[str] = []
    raw: dict[str, Any]
    if cim and (cim.get("monitors") is not None or cim.get("monitor_ids") is not None or cim.get("edids") is not None):
        raw = cim
    else:
        try:
            from labwatch_agent.collectors import windows as win_col

            raw = win_col.collect_monitor_raw()
        except Exception as exc:
            return {"displays": [], "notes": [f"Windows display collector failed: {exc}"]}

    if raw.get("error"):
        # Soft note — registry EDID may still have populated monitors.
        notes.append(f"monitor scrape: {raw['error']}")

    monitors = raw.get("monitors") or raw.get("monitor_ids") or []
    if isinstance(monitors, dict):
        monitors = [monitors]
    edids = raw.get("edids") or []
    if isinstance(edids, dict):
        edids = [edids]
    video = raw.get("video") or []
    if isinstance(video, dict):
        video = [video]

    displays: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for mid in monitors:
        if not isinstance(mid, dict):
            continue
        if mid.get("active") is False or mid.get("Active") is False:
            continue
        entry = _entry_from_wmi_monitor(mid)
        edid_hex = _match_edid_for_monitor(entry, edids)
        if edid_hex:
            _merge_edid_into(entry, edid_hex)
        key = (entry.get("serial_number") or entry.get("connector") or entry.get("name") or "").lower()
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        displays.append(entry)

    # Registry-only monitors (WMI empty or partial).
    for ed in edids:
        if not isinstance(ed, dict):
            continue
        hex_blob = ed.get("edid_hex")
        if not hex_blob:
            continue
        hw = _clean(ed.get("display_hw_id"))
        key_candidates = {
            (hw or "").lower(),
        }
        parsed = _entry_from_edid(
            edid_hex=str(hex_blob),
            name=hw,
            connector=hw,
            instance=str(ed.get("instance_id") or "") or None,
            source="registry",
        )
        if not parsed:
            continue
        if parsed.get("serial_number"):
            key_candidates.add(str(parsed["serial_number"]).lower())
        if key_candidates & seen_keys:
            continue
        for k in key_candidates:
            if k:
                seen_keys.add(k)
        displays.append(parsed)

    # Fill resolution from primary video controller when EDID timing missing.
    if displays and video:
        primary = video[0] if isinstance(video[0], dict) else {}
        w = primary.get("CurrentHorizontalResolution")
        h = primary.get("CurrentVerticalResolution")
        hz = primary.get("CurrentRefreshRate")
        try:
            w_i = int(w) if w else None
            h_i = int(h) if h else None
            hz_i = float(hz) if hz else None
        except (TypeError, ValueError):
            w_i = h_i = hz_i = None
        if w_i and h_i:
            for entry in displays:
                if not entry.get("width_px"):
                    entry["width_px"] = w_i
                    entry["height_px"] = h_i
                if not entry.get("refresh_hz") and hz_i and hz_i > 1:
                    entry["refresh_hz"] = hz_i
                break  # only attribute primary timing to first monitor

    if not displays:
        notes.append("No monitors from WmiMonitorID or registry EDID (headless / RDP / drivers).")
    else:
        notes.append(f"Windows displays: {len(displays)} (wmi={len(monitors)}, registry_edid={len(edids)})")
    return {"displays": displays, "notes": notes}
