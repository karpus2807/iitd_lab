"""Poll cadence + static inventory fingerprint helpers."""

from labwatch_agent.collectors import inventory_static_fingerprint
from labwatch_agent.config import AgentConfig
from labwatch_agent.service import _apply_server_intervals


def _sample_inventory(**overrides):
    base = {
        "identity": {
            "machine_uuid": "m1",
            "system_uuid": "s1",
            "motherboard_serial": "mb1",
            "system_serial": "sys1",
            "hostname": "lab-pc-01",
        },
        "cpu": {"model": "Ryzen", "manufacturer": "AMD", "physical_cores": 8, "logical_processors": 16},
        "memory": {
            "modules": [
                {
                    "slot_locator": "DIMM0",
                    "serial_number": "SN1",
                    "part_number": "P1",
                    "capacity_bytes": 16_000_000_000,
                    "manufacturer": "Samsung",
                }
            ]
        },
        "gpus": [
            {
                "vendor": "NVIDIA",
                "model": "RTX 4090",
                "pci_bus": "0000:01:00.0",
                "pci_device_id": "2684",
                "serial_number": "G1",
                "uuid": "GPU-1",
                "vram_bytes": 24_000_000_000,
                "driver_version": "560.31",
                "utilization_pct": 90,
                "temperature_c": 70,
            }
        ],
        "storage": {
            "disks": [
                {"name": "nvme0n1", "model": "Samsung", "serial_number": "D1", "capacity_bytes": 1_000_000_000_000}
            ]
        },
        "motherboard": {"manufacturer": "ASUS", "product_name": "Z690", "serial_number": "MBSN"},
        "bios": {"vendor": "AMI", "version": "1.0"},
    }
    base.update(overrides)
    return base


def test_inventory_fingerprint_ignores_live_telemetry():
    a = _sample_inventory()
    b = _sample_inventory()
    b["gpus"][0]["utilization_pct"] = 5
    b["gpus"][0]["temperature_c"] = 40
    b["collected_at"] = "never-compared"
    assert inventory_static_fingerprint(a) == inventory_static_fingerprint(b)


def test_inventory_fingerprint_changes_on_hw_swap():
    a = _sample_inventory()
    b = _sample_inventory()
    b["gpus"][0]["uuid"] = "GPU-REPLACED"
    assert inventory_static_fingerprint(a) != inventory_static_fingerprint(b)


def test_apply_server_intervals_updates_and_ignores_junk():
    cfg = AgentConfig(heartbeat_interval=60, metric_interval=180, inventory_interval=3600)
    _apply_server_intervals(
        cfg,
        {
            "heartbeat_interval": 90,
            "metric_interval": "240",
            "inventory_interval": 5,  # below floor — ignored
            "noise": 1,
        },
    )
    assert cfg.heartbeat_interval == 90
    assert cfg.metric_interval == 240
    assert cfg.inventory_interval == 3600


def test_default_intervals_are_relaxed():
    cfg = AgentConfig()
    assert cfg.heartbeat_interval == 60
    assert cfg.metric_interval == 180
    assert cfg.inventory_interval == 3600
