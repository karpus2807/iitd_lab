from pathlib import Path

from labwatch_agent.collectors.disks import is_physical_disk
from labwatch_agent.collectors.linux import _sanitize_memory_topology
from labwatch_agent.parsers.dmidecode import parse_memory_from_dmidecode, parse_slots_from_dmidecode, parse_system_from_dmidecode
from labwatch_agent.parsers.nvidia import parse_nvidia_smi_csv
from labwatch_agent.parsers.tegrastats import parse_tegrastats

FIX = Path(__file__).parent / "fixtures"


def test_memory_slots_occupied_and_empty():
    text = (FIX / "dmidecode_memory.txt").read_text()
    parsed = parse_memory_from_dmidecode(text)
    assert parsed["slot_count"] == 4
    assert parsed["occupied_slots"] == 3
    assert parsed["free_slots"] == 1
    assert parsed["max_supported_bytes"] == 128 * 1000**3 or parsed["max_supported_bytes"] == 128 * 1024**3
    locators = {m["slot_locator"]: m for m in parsed["modules"]}
    assert locators["A1"]["occupied"] is True
    assert locators["A1"]["capacity_bytes"] == 16 * 1000**3 or locators["A1"]["capacity_bytes"] == 16 * 1024**3
    assert locators["A1"]["manufacturer"] == "Samsung"
    assert locators["A1"]["speed_mts"] == 3200
    assert locators["B2"]["occupied"] is False
    assert locators["B2"]["capacity_bytes"] is None
    assert parsed["topology_status"] == "DETECTED"


def test_memory_unknown_when_empty_text():
    parsed = parse_memory_from_dmidecode("")
    assert parsed["topology_status"] == "UNKNOWN"
    assert parsed["slot_count"] is None
    assert parsed["modules"] == []


def test_system_and_bios_parse():
    text = (FIX / "dmidecode_system.txt").read_text()
    parsed = parse_system_from_dmidecode(text)
    assert parsed["system_manufacturer"] == "ExampleCorp"
    assert parsed["board_model"] == "Z690-BOARD"
    assert parsed["bios_vendor"] == "American Megatrends Inc."
    assert parsed["system_uuid"]


def test_pcie_slots_do_not_assume_gpu_capable():
    text = (FIX / "dmidecode_slots.txt").read_text()
    parsed = parse_slots_from_dmidecode(text)
    assert parsed["topology_status"] == "DETECTED"
    assert len(parsed["slots"]) == 4
    # Only the slot whose designation contains GPU is counted as GPU-capable.
    assert parsed["gpu_capable_total"] == 1
    assert parsed["gpu_capable_occupied"] == 1
    x16 = [s for s in parsed["slots"] if s["slot_designation"] == "Slot 1"][0]
    assert x16["is_gpu_capable"] is None


def test_nvidia_smi_parser():
    csv = "0, NVIDIA RTX 4090, GPU-abc, 12345, 24564, 18000, 72, 57, 320.12, 2100, 10501, 00000000:01:00.0, 560.31"
    gpus = parse_nvidia_smi_csv(csv)
    assert len(gpus) == 1
    assert gpus[0]["model"] == "NVIDIA RTX 4090"
    assert gpus[0]["utilization_pct"] == 72
    assert gpus[0]["temperature_c"] == 57
    assert gpus[0]["vendor"] == "NVIDIA"
    assert gpus[0]["vram_bytes"] == int(24564 * 1024 * 1024)


def test_nvidia_smi_jetson_na_fields():
    csv = "0, Orin (nvgpu), [N/A], [N/A], [N/A], [N/A], [N/A], [N/A], [N/A], [N/A], [N/A], [N/A], 540.5.0"
    gpus = parse_nvidia_smi_csv(csv)
    assert len(gpus) == 1
    assert gpus[0]["model"] == "Orin (nvgpu)"
    assert gpus[0]["driver_version"] == "540.5.0"
    assert gpus[0]["utilization_pct"] is None
    assert gpus[0]["vram_bytes"] is None


def test_tegrastats_gpu_util_and_temp():
    line = "RAM 1997/30698MB CPU [1%@1113] GR3D_FREQ 12% GPU@44.5C CPU@45C"
    parsed = parse_tegrastats(line)
    assert parsed["utilization_pct"] == 12
    assert parsed["temperature_c"] == 44.5
    assert parsed["ram_total_mb"] == 30698


def test_physical_disk_filter_drops_zram_and_boot():
    assert is_physical_disk("nvme0n1")
    assert is_physical_disk("mmcblk0")
    assert is_physical_disk("sda")
    assert not is_physical_disk("zram0")
    assert not is_physical_disk("mmcblk0boot0")
    assert not is_physical_disk("mmcblk0rpmb")
    assert not is_physical_disk("loop0")


def test_jetson_dmidecode_does_not_invent_empty_dimm():
    text = (FIX / "dmidecode_jetson_memory.txt").read_text()
    parsed = parse_memory_from_dmidecode(text)
    notes: list[str] = []
    parsed["total_physical_bytes"] = 61 * 1024**3
    _sanitize_memory_topology(parsed, notes)
    assert parsed["modules"] == []
    assert parsed["slot_count"] is None
    assert parsed["free_slots"] is None
    assert parsed["max_supported_bytes"] is None
    assert any("unified" in n.lower() or "soc" in n.lower() or parsed["topology_status"] == "UNKNOWN" for n in notes) or parsed["topology_status"] == "UNKNOWN"
