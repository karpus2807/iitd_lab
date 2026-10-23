from types import SimpleNamespace

from app.services.inventory import _gpu_telemetry_ok


def test_gpu_telemetry_ok_uses_pct():
    assert _gpu_telemetry_ok(SimpleNamespace(extra={"telemetry_pct": 50}, temperature_c=None, utilization_pct=None, power_w=None, graphics_clock_mhz=None, driver_version=None, pci_bus=None, pci_device_id=None, memory_clock_mhz=None, vram_bytes=None, slot_designation=None))
    assert not _gpu_telemetry_ok(SimpleNamespace(extra={"telemetry_pct": 49}, temperature_c=None, utilization_pct=None, power_w=None, graphics_clock_mhz=None, driver_version=None, pci_bus=None, pci_device_id=None, memory_clock_mhz=None, vram_bytes=None, slot_designation=None))


def test_gpu_telemetry_ok_legacy_half_fields():
    gpu = SimpleNamespace(
        extra={"gpu_kind": "integrated"},
        temperature_c=40,
        utilization_pct=5,
        power_w=None,
        graphics_clock_mhz=600,
        driver_version="i915",
        pci_bus="0000:00:02.0",
        pci_device_id=None,
        memory_clock_mhz=None,
        vram_bytes=None,
        slot_designation="Integrated",
    )
    assert _gpu_telemetry_ok(gpu)
