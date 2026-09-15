from app.enums import EventType
from app.schemas.inventory import (
    CPUInfo,
    DiskInfo,
    GPUInfo,
    InventoryPayload,
    MemoryInfo,
    MemoryModule,
    NicInfo,
    NetworkInfo,
    StorageInfo,
)
from app.services.diff import diff_inventory


def _ram(locator: str, gb: int | None, **kwargs) -> MemoryModule:
    if gb is None:
        return MemoryModule(slot_locator=locator, occupied=False)
    return MemoryModule(
        slot_locator=locator,
        occupied=True,
        capacity_bytes=gb * 1024**3,
        manufacturer=kwargs.get("manufacturer", "Samsung"),
        part_number=kwargs.get("part_number", "M393A2K"),
        serial_number=kwargs.get("serial", f"SN-{locator}"),
        memory_type="DDR4",
        speed_mts=kwargs.get("speed", 3200),
        form_factor="DIMM",
    )


def test_ram_module_removed():
    before = InventoryPayload(
        memory=MemoryInfo(
            slot_count=4,
            occupied_slots=3,
            free_slots=1,
            modules=[
                _ram("A1", 16),
                _ram("A2", 16),
                _ram("B1", 16),
                _ram("B2", None),
            ],
        )
    )
    after = InventoryPayload(
        memory=MemoryInfo(
            slot_count=4,
            occupied_slots=2,
            free_slots=2,
            modules=[
                _ram("A1", 16),
                _ram("A2", 16),
                _ram("B1", None),
                _ram("B2", None),
            ],
        )
    )
    events = diff_inventory(before, after)
    types = [e.event_type for e in events]
    assert EventType.RAM_REMOVED.value in types
    removed = [e for e in events if e.event_type == EventType.RAM_REMOVED.value][0]
    assert removed.component_path.endswith("B1")
    assert removed.previous_value["capacity_bytes"] == 16 * 1024**3
    assert removed.new_value["state"] == "EMPTY"
    assert removed.severity == "CRITICAL"


def test_ram_module_added():
    before = InventoryPayload(memory=MemoryInfo(modules=[_ram("A1", 16), _ram("A2", None)]))
    after = InventoryPayload(memory=MemoryInfo(modules=[_ram("A1", 16), _ram("A2", 16)]))
    events = diff_inventory(before, after)
    assert any(e.event_type == EventType.RAM_ADDED.value for e in events)


def test_ram_speed_and_serial_change():
    before = InventoryPayload(memory=MemoryInfo(modules=[_ram("A1", 16, speed=2666, serial="AAA")]))
    after = InventoryPayload(memory=MemoryInfo(modules=[_ram("A1", 16, speed=3200, serial="BBB")]))
    events = diff_inventory(before, after)
    changed = [e for e in events if e.event_type == EventType.RAM_CHANGED.value]
    assert changed
    assert "speed" in changed[0].summary
    assert "serial" in changed[0].summary


def test_gpu_removed():
    before = InventoryPayload(
        gpus=[
            GPUInfo(index=0, model="RTX 4090", pci_bus="0000:01:00.0", vram_bytes=24 * 1024**3, slot_designation="Slot 1"),
            GPUInfo(index=1, model="RTX 3090", pci_bus="0000:02:00.0", vram_bytes=24 * 1024**3, slot_designation="Slot 2"),
        ]
    )
    after = InventoryPayload(
        gpus=[
            GPUInfo(index=0, model="RTX 4090", pci_bus="0000:01:00.0", vram_bytes=24 * 1024**3, slot_designation="Slot 1"),
        ]
    )
    events = diff_inventory(before, after)
    removed = [e for e in events if e.event_type == EventType.GPU_REMOVED.value]
    assert len(removed) == 1
    assert "RTX 3090" in removed[0].summary
    assert removed[0].new_value["state"] == "EMPTY"


def test_gpu_added_and_replaced():
    before = InventoryPayload(gpus=[GPUInfo(index=0, model="RTX 3090", pci_bus="0000:01:00.0", serial_number="S1")])
    after = InventoryPayload(gpus=[GPUInfo(index=0, model="RTX 4090", pci_bus="0000:01:00.0", serial_number="S2")])
    events = diff_inventory(before, after)
    types = {e.event_type for e in events}
    assert EventType.GPU_REMOVED.value in types
    assert EventType.GPU_ADDED.value in types


def test_gpu_vram_change_same_identity():
    before = InventoryPayload(gpus=[GPUInfo(index=0, model="RTX 4090", uuid="GPU-1", vram_bytes=24 * 1024**3)])
    after = InventoryPayload(gpus=[GPUInfo(index=0, model="RTX 4090", uuid="GPU-1", vram_bytes=48 * 1024**3)])
    events = diff_inventory(before, after)
    assert any(e.event_type == EventType.GPU_CHANGED.value for e in events)


def test_disk_removed_and_added():
    before = InventoryPayload(
        storage=StorageInfo(disks=[DiskInfo(name="nvme0n1", model="Samsung 980", serial_number="NV1", capacity_bytes=10**12)])
    )
    after = InventoryPayload(
        storage=StorageInfo(disks=[DiskInfo(name="sda", model="WD HDD", serial_number="WD1", capacity_bytes=2 * 10**12)])
    )
    events = diff_inventory(before, after)
    types = {e.event_type for e in events}
    assert EventType.DISK_REMOVED.value in types
    assert EventType.DISK_ADDED.value in types


def test_no_events_on_identical_inventory():
    inv = InventoryPayload(
        cpu=CPUInfo(model="Xeon", physical_cores=8),
        memory=MemoryInfo(modules=[_ram("A1", 16)]),
        gpus=[GPUInfo(index=0, model="RTX 4090", uuid="g1")],
    )
    assert diff_inventory(inv, inv) == []


def test_first_snapshot_has_no_diff():
    after = InventoryPayload(memory=MemoryInfo(modules=[_ram("A1", 16)]))
    assert diff_inventory(None, after) == []


def test_cpu_change_ignores_first_discovery():
    before = InventoryPayload(cpu=CPUInfo(model=None))
    after = InventoryPayload(cpu=CPUInfo(model="Ryzen 9"))
    assert diff_inventory(before, after) == []
    before2 = InventoryPayload(cpu=CPUInfo(model="Ryzen 7"))
    events = diff_inventory(before2, after)
    assert any(e.event_type == EventType.CPU_CHANGED.value for e in events)


def test_network_adapter_added():
    before = InventoryPayload(network=NetworkInfo(interfaces=[NicInfo(name="eth0", mac="aa:bb:cc:dd:ee:ff")]))
    after = InventoryPayload(
        network=NetworkInfo(
            interfaces=[
                NicInfo(name="eth0", mac="aa:bb:cc:dd:ee:ff"),
                NicInfo(name="eth1", mac="11:22:33:44:55:66"),
            ]
        )
    )
    events = diff_inventory(before, after)
    assert any(e.event_type == EventType.NETWORK_ADAPTER_CHANGED.value for e in events)
