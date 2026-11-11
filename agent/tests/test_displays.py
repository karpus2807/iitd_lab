from labwatch_agent.collectors.displays import (
    _inches_from_cm,
    _pnp_brand,
    collect_displays_windows,
    parse_edid,
)


def _edid_dell_sample() -> bytes:
    """Minimal EDID: Dell, product 0xA0C9, serial ASCII, 53×30 cm (~24"), 1920×1080."""
    edid = bytearray(128)
    edid[0:8] = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
    # DEL → D=4 E=5 L=12
    raw = (4 << 10) | (5 << 5) | 12
    edid[8] = (raw >> 8) & 0xFF
    edid[9] = raw & 0xFF
    edid[10] = 0xC9
    edid[11] = 0xA0  # product little-endian → A0C9
    edid[12:16] = (0x12345678).to_bytes(4, "little")
    edid[16] = 12
    edid[17] = 2024 - 1990
    edid[21] = 53
    edid[22] = 30
    # Preferred timing 1920x1080 @ ~60Hz (approx pixel clock)
    # pixel_clock_10khz = 14850 (148.5 MHz)
    pc = 14850
    edid[54] = pc & 0xFF
    edid[55] = (pc >> 8) & 0xFF
    h_active, h_blank = 1920, 280
    v_active, v_blank = 1080, 45
    edid[56] = h_active & 0xFF
    edid[57] = h_blank & 0xFF
    edid[58] = ((h_active >> 8) << 4) | (h_blank >> 8)
    edid[59] = v_active & 0xFF
    edid[60] = v_blank & 0xFF
    edid[61] = ((v_active >> 8) << 4) | (v_blank >> 8)
    # Monitor name descriptor 0xFC
    name = b"DELL P2419H"
    block = bytearray(18)
    block[3] = 0xFC
    block[5 : 5 + len(name)] = name
    edid[72:90] = block
    # Serial ASCII descriptor 0xFF
    ser = b"CN0ABC123"
    block2 = bytearray(18)
    block2[3] = 0xFF
    block2[5 : 5 + len(ser)] = ser
    edid[90:108] = block2
    return bytes(edid)


def test_pnp_brand_dell():
    assert _pnp_brand("DEL") == "Dell"
    assert _pnp_brand("SAM") == "Samsung"


def test_inches_from_cm():
    assert _inches_from_cm(53, 30) == 24.0


def test_parse_edid_identity_fields():
    parsed = parse_edid(_edid_dell_sample())
    assert parsed["manufacturer_code"] == "DEL"
    assert parsed["manufacturer"] == "Dell"
    assert parsed["product_code"] == "A0C9"
    assert parsed["serial_number"] == "CN0ABC123"
    assert parsed["model"] == "DELL P2419H"
    assert parsed["size_inches"] == 24.0
    assert parsed["width_px"] == 1920
    assert parsed["height_px"] == 1080
    assert parsed["year_week"] == "2024-W12"


def test_collect_displays_windows_from_decoded_wmi_and_edid():
    edid_hex = _edid_dell_sample().hex()
    raw = {
        "monitors": [
            {
                "source": "wmi",
                "instance_name": r"DISPLAY\DELA0C9\5&123&0&UID123",
                "active": True,
                "manufacturer_code": "DEL",
                "product_code": "A0C9",
                "serial_number": "",
                "friendly_name": "",
                "week": 12,
                "year": 2024,
                "width_cm": None,
                "height_cm": None,
                "video_output_technology": 10,
            }
        ],
        "edids": [
            {
                "source": "registry",
                "display_hw_id": "DELA0C9",
                "instance_id": "5&123&0&UID123",
                "edid_hex": edid_hex,
            }
        ],
        "video": [
            {
                "Name": "Intel UHD",
                "CurrentHorizontalResolution": 1920,
                "CurrentVerticalResolution": 1080,
                "CurrentRefreshRate": 60,
            }
        ],
    }
    out = collect_displays_windows(raw)
    assert len(out["displays"]) == 1
    d = out["displays"][0]
    assert d["manufacturer"] == "Dell"
    assert d["serial_number"] == "CN0ABC123"
    assert d["size_inches"] == 24.0
    assert d["connection"] == "DisplayPort"
    assert d["model"] == "DELL P2419H"
    assert d["width_px"] == 1920


def test_collect_displays_windows_registry_only():
    edid_hex = _edid_dell_sample().hex()
    out = collect_displays_windows(
        {
            "monitors": [],
            "edids": [{"display_hw_id": "DELA0C9", "edid_hex": edid_hex}],
            "video": [],
        }
    )
    assert len(out["displays"]) == 1
    assert out["displays"][0]["manufacturer"] == "Dell"
    assert out["displays"][0]["serial_number"] == "CN0ABC123"


def test_collect_displays_windows_registry_survives_wmi_error_note():
    """Live bug: PS -Command returned empty; winreg EDID must still populate displays."""
    edid_hex = _edid_dell_sample().hex()
    out = collect_displays_windows(
        {
            "monitors": [],
            "edids": [{"display_hw_id": "SAM0C09", "instance_id": "1&2&3", "edid_hex": edid_hex}],
            "video": [],
            "error": "powershell exit 1, empty stdout",
        }
    )
    assert len(out["displays"]) == 1
    assert out["displays"][0]["size_inches"] == 24.0
    assert any("empty stdout" in n for n in out["notes"])
