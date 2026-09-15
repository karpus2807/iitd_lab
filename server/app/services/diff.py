"""Hardware inventory comparison engine.

Compares two inventory payloads and emits structured change events.
Never infers missing hardware; only diffs values that were actually reported.
"""

from __future__ import annotations

from typing import Any

from app.enums import AlertSeverity, EventType
from app.schemas.inventory import DiffEvent, InventoryPayload, MemoryModule


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in {"", "unknown", "none", "n/a", "not available", "unknown / not reported"}:
            return None
        return stripped
    return value


def _changed(old: Any, new: Any) -> bool:
    return _clean(old) != _clean(new)


def _module_key(mod: MemoryModule) -> str:
    locator = (mod.slot_locator or "").strip()
    if locator:
        return f"locator:{locator.lower()}"
    serial = _clean(mod.serial_number)
    if serial:
        return f"serial:{str(serial).lower()}"
    return f"anon:{mod.manufacturer}:{mod.capacity_bytes}:{mod.part_number}"


def _module_public(mod: MemoryModule) -> dict[str, Any]:
    if not mod.occupied:
        return {
            "slot": mod.slot_locator,
            "state": "EMPTY",
            "capacity_bytes": None,
        }
    return {
        "slot": mod.slot_locator,
        "state": "OCCUPIED",
        "capacity_bytes": mod.capacity_bytes,
        "manufacturer": mod.manufacturer,
        "part_number": mod.part_number,
        "serial_number": mod.serial_number,
        "memory_type": mod.memory_type,
        "speed_mts": mod.speed_mts,
        "configured_speed_mts": mod.configured_speed_mts,
        "form_factor": mod.form_factor,
        "ecc": mod.ecc,
        "rank": mod.rank,
    }


def _gpu_key(gpu) -> str:
    if _clean(gpu.uuid):
        return f"uuid:{str(gpu.uuid).lower()}"
    if _clean(gpu.serial_number):
        return f"serial:{str(gpu.serial_number).lower()}"
    if _clean(gpu.pci_bus):
        return f"pci:{str(gpu.pci_bus).lower()}"
    return f"model:{gpu.vendor}:{gpu.model}:{gpu.vram_bytes}:{gpu.index}"


def _gpu_public(gpu) -> dict[str, Any]:
    return {
        "index": gpu.index,
        "vendor": gpu.vendor,
        "model": gpu.model,
        "vram_bytes": gpu.vram_bytes,
        "serial_number": gpu.serial_number,
        "uuid": gpu.uuid,
        "pci_bus": gpu.pci_bus,
        "driver_version": gpu.driver_version,
        "slot_designation": gpu.slot_designation,
    }


def _disk_key(disk) -> str:
    if _clean(disk.serial_number):
        return f"serial:{str(disk.serial_number).lower()}"
    if _clean(disk.name) and _clean(disk.model):
        return f"name:{disk.name.lower()}:{str(disk.model).lower()}"
    return f"name:{disk.name}:{disk.capacity_bytes}"


def _disk_public(disk) -> dict[str, Any]:
    return {
        "name": disk.name,
        "model": disk.model,
        "serial_number": disk.serial_number,
        "capacity_bytes": disk.capacity_bytes,
        "interface": disk.interface,
        "media_type": disk.media_type,
    }


def _nic_key(nic) -> str:
    if _clean(nic.mac):
        return f"mac:{str(nic.mac).lower()}"
    return f"name:{nic.name.lower()}"


HARDWARE_EVENT_SEVERITY = {
    EventType.RAM_REMOVED.value: AlertSeverity.CRITICAL.value,
    EventType.RAM_ADDED.value: AlertSeverity.WARNING.value,
    EventType.RAM_CHANGED.value: AlertSeverity.WARNING.value,
    EventType.GPU_REMOVED.value: AlertSeverity.CRITICAL.value,
    EventType.GPU_ADDED.value: AlertSeverity.WARNING.value,
    EventType.GPU_CHANGED.value: AlertSeverity.CRITICAL.value,
    EventType.DISK_REMOVED.value: AlertSeverity.CRITICAL.value,
    EventType.DISK_ADDED.value: AlertSeverity.WARNING.value,
    EventType.DISK_CHANGED.value: AlertSeverity.WARNING.value,
    EventType.CPU_CHANGED.value: AlertSeverity.CRITICAL.value,
    EventType.MOTHERBOARD_CHANGED.value: AlertSeverity.CRITICAL.value,
    EventType.BIOS_CHANGED.value: AlertSeverity.INFO.value,
    EventType.NETWORK_ADAPTER_CHANGED.value: AlertSeverity.INFO.value,
    EventType.PCIE_CHANGED.value: AlertSeverity.WARNING.value,
}


def _event(event_type: EventType, path: str, previous: Any, new: Any, summary: str) -> DiffEvent:
    return DiffEvent(
        event_type=event_type.value,
        severity=HARDWARE_EVENT_SEVERITY.get(event_type.value, AlertSeverity.INFO.value),
        component_path=path,
        previous_value=previous if isinstance(previous, dict) else ({"value": previous} if previous is not None else None),
        new_value=new if isinstance(new, dict) else ({"value": new} if new is not None else None),
        summary=summary,
    )


def _diff_memory(old: InventoryPayload, new: InventoryPayload) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    old_mods = {_module_key(m): m for m in old.memory.modules}
    new_mods = {_module_key(m): m for m in new.memory.modules}

    for key, before in old_mods.items():
        after = new_mods.get(key)
        if after is None:
            if before.occupied:
                events.append(
                    _event(
                        EventType.RAM_REMOVED,
                        f"memory.slots.{before.slot_locator}",
                        _module_public(before),
                        {"slot": before.slot_locator, "state": "EMPTY"},
                        f"RAM module removed from slot {before.slot_locator}",
                    )
                )
            continue
        if before.occupied and not after.occupied:
            events.append(
                _event(
                    EventType.RAM_REMOVED,
                    f"memory.slots.{before.slot_locator}",
                    _module_public(before),
                    _module_public(after),
                    f"RAM module removed from slot {before.slot_locator}",
                )
            )
            continue
        if not before.occupied and after.occupied:
            events.append(
                _event(
                    EventType.RAM_ADDED,
                    f"memory.slots.{after.slot_locator}",
                    _module_public(before),
                    _module_public(after),
                    f"RAM module added to slot {after.slot_locator}",
                )
            )
            continue
        if before.occupied and after.occupied:
            fields = [
                ("capacity_bytes", "capacity"),
                ("manufacturer", "manufacturer"),
                ("part_number", "part number"),
                ("serial_number", "serial"),
                ("speed_mts", "speed"),
                ("configured_speed_mts", "configured speed"),
                ("memory_type", "type"),
            ]
            changes = [label for field, label in fields if _changed(getattr(before, field), getattr(after, field))]
            if changes:
                events.append(
                    _event(
                        EventType.RAM_CHANGED,
                        f"memory.slots.{after.slot_locator}",
                        _module_public(before),
                        _module_public(after),
                        f"RAM changed in slot {after.slot_locator}: {', '.join(changes)}",
                    )
                )

    for key, after in new_mods.items():
        if key not in old_mods and after.occupied:
            events.append(
                _event(
                    EventType.RAM_ADDED,
                    f"memory.slots.{after.slot_locator}",
                    {"state": "EMPTY"},
                    _module_public(after),
                    f"RAM module added to slot {after.slot_locator}",
                )
            )
    return events


def _diff_gpus(old: InventoryPayload, new: InventoryPayload) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    old_gpus = {_gpu_key(g): g for g in old.gpus}
    new_gpus = {_gpu_key(g): g for g in new.gpus}

    for key, before in old_gpus.items():
        after = new_gpus.get(key)
        if after is None:
            slot = before.slot_designation or before.pci_bus or f"GPU {before.index}"
            events.append(
                _event(
                    EventType.GPU_REMOVED,
                    f"gpu.{slot}",
                    _gpu_public(before),
                    {"state": "EMPTY", "slot": slot},
                    f"GPU removed ({before.model or 'unknown'}) from {slot}",
                )
            )
            continue
        fields = [
            ("model", "model"),
            ("serial_number", "serial"),
            ("vram_bytes", "VRAM"),
            ("pci_bus", "PCI bus"),
            ("driver_version", "driver"),
            ("vendor", "vendor"),
        ]
        changes = [label for field, label in fields if _changed(getattr(before, field), getattr(after, field))]
        if changes:
            events.append(
                _event(
                    EventType.GPU_CHANGED,
                    f"gpu.{after.index}",
                    _gpu_public(before),
                    _gpu_public(after),
                    f"GPU changed ({after.model or 'unknown'}): {', '.join(changes)}",
                )
            )

    for key, after in new_gpus.items():
        if key not in old_gpus:
            slot = after.slot_designation or after.pci_bus or f"GPU {after.index}"
            events.append(
                _event(
                    EventType.GPU_ADDED,
                    f"gpu.{slot}",
                    {"state": "EMPTY"},
                    _gpu_public(after),
                    f"GPU added ({after.model or 'unknown'}) at {slot}",
                )
            )
    return events


def _diff_disks(old: InventoryPayload, new: InventoryPayload) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    old_disks = {_disk_key(d): d for d in old.storage.disks}
    new_disks = {_disk_key(d): d for d in new.storage.disks}

    for key, before in old_disks.items():
        after = new_disks.get(key)
        if after is None:
            events.append(
                _event(
                    EventType.DISK_REMOVED,
                    f"storage.{before.name or before.serial_number}",
                    _disk_public(before),
                    {"state": "MISSING"},
                    f"Disk removed ({before.model or before.name or 'unknown'})",
                )
            )
            continue
        fields = [("model", "model"), ("capacity_bytes", "capacity"), ("serial_number", "serial"), ("interface", "interface")]
        changes = [label for field, label in fields if _changed(getattr(before, field), getattr(after, field))]
        if changes:
            events.append(
                _event(
                    EventType.DISK_CHANGED,
                    f"storage.{after.name}",
                    _disk_public(before),
                    _disk_public(after),
                    f"Disk changed ({after.model or after.name}): {', '.join(changes)}",
                )
            )
    for key, after in new_disks.items():
        if key not in old_disks:
            events.append(
                _event(
                    EventType.DISK_ADDED,
                    f"storage.{after.name or after.serial_number}",
                    None,
                    _disk_public(after),
                    f"Disk added ({after.model or after.name or 'unknown'})",
                )
            )
    return events


def _scalar_change(event_type: EventType, path: str, label: str, old_val: Any, new_val: Any) -> DiffEvent | None:
    if old_val is None and new_val is None:
        return None
    if not _changed(old_val, new_val):
        return None
    if old_val is None or new_val is None:
        # First-time discovery is not a hardware change.
        return None
    return _event(event_type, path, {"value": old_val}, {"value": new_val}, f"{label} changed")


def _diff_cpu(old: InventoryPayload, new: InventoryPayload) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    for field, label in [
        ("model", "CPU model"),
        ("manufacturer", "CPU manufacturer"),
        ("physical_cores", "CPU physical cores"),
        ("logical_processors", "CPU logical processors"),
        ("physical_sockets", "CPU sockets"),
    ]:
        ev = _scalar_change(EventType.CPU_CHANGED, f"cpu.{field}", label, getattr(old.cpu, field), getattr(new.cpu, field))
        if ev:
            events.append(ev)
    return events


def _diff_board(old: InventoryPayload, new: InventoryPayload) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    for field, label in [("manufacturer", "Motherboard manufacturer"), ("model", "Motherboard model"), ("serial_number", "Motherboard serial")]:
        ev = _scalar_change(
            EventType.MOTHERBOARD_CHANGED,
            f"motherboard.{field}",
            label,
            getattr(old.motherboard, field),
            getattr(new.motherboard, field),
        )
        if ev:
            events.append(ev)
    for field, label in [("vendor", "BIOS vendor"), ("version", "BIOS version"), ("release_date", "BIOS release date")]:
        ev = _scalar_change(EventType.BIOS_CHANGED, f"bios.{field}", label, getattr(old.bios, field), getattr(new.bios, field))
        if ev:
            events.append(ev)
    return events


def _diff_nics(old: InventoryPayload, new: InventoryPayload) -> list[DiffEvent]:
    events: list[DiffEvent] = []
    old_nics = {_nic_key(n): n for n in old.network.interfaces if n.mac or n.name}
    new_nics = {_nic_key(n): n for n in new.network.interfaces if n.mac or n.name}
    for key, before in old_nics.items():
        if key not in new_nics:
            events.append(
                _event(
                    EventType.NETWORK_ADAPTER_CHANGED,
                    f"network.{before.name}",
                    {"name": before.name, "mac": before.mac, "state": "present"},
                    {"state": "missing"},
                    f"Network adapter removed ({before.name})",
                )
            )
    for key, after in new_nics.items():
        if key not in old_nics:
            events.append(
                _event(
                    EventType.NETWORK_ADAPTER_CHANGED,
                    f"network.{after.name}",
                    {"state": "missing"},
                    {"name": after.name, "mac": after.mac, "state": "present"},
                    f"Network adapter added ({after.name})",
                )
            )
    return events


def diff_inventory(previous: InventoryPayload | None, current: InventoryPayload) -> list[DiffEvent]:
    if previous is None:
        return []
    events: list[DiffEvent] = []
    events.extend(_diff_memory(previous, current))
    events.extend(_diff_gpus(previous, current))
    events.extend(_diff_disks(previous, current))
    events.extend(_diff_cpu(previous, current))
    events.extend(_diff_board(previous, current))
    events.extend(_diff_nics(previous, current))
    return events
