from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Bios,
    CpuInventory,
    Filesystem,
    GpuDevice,
    HardwareEvent,
    HardwareSnapshot,
    Machine,
    MemorySlot,
    MemorySummary,
    Motherboard,
    NetworkInterface,
    PcieSlot,
    PcieTopology,
    StorageDevice,
)
from app.schemas.inventory import InventoryPayload
from app.security import hash_token
from app.services.alerts import evaluate_hardware_events
from app.services.diff import diff_inventory
from app.services.heartbeat import apply_reported_addresses


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def _dt(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


async def persist_inventory(db: AsyncSession, machine: Machine, payload: InventoryPayload) -> list[HardwareEvent]:
    previous_row = (
        await db.execute(
            select(HardwareSnapshot)
            .where(HardwareSnapshot.machine_id == machine.id)
            .order_by(HardwareSnapshot.collected_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    previous = None
    if previous_row is not None:
        try:
            previous = InventoryPayload.model_validate(previous_row.payload)
        except Exception:
            previous = None
    events = diff_inventory(previous, payload)
    collected_at = _dt(payload.collected_at)
    fingerprint = hash_token(payload.model_dump_json(exclude={"collected_at"}))

    db.add(
        HardwareSnapshot(
            machine_id=machine.id,
            collected_at=collected_at,
            payload=payload.model_dump(mode="json"),
            fingerprint=fingerprint,
        )
    )

    ident = payload.identity
    osinfo = payload.os
    machine.hostname = _clip(ident.hostname or osinfo.hostname or machine.hostname, 255) or ""
    machine.os_name = _clip(osinfo.name or ident.os_name or machine.os_name, 120) or ""
    machine.os_version = _clip(osinfo.version or ident.os_version or machine.os_version, 255) or ""
    machine.kernel_version = _clip(osinfo.kernel or ident.kernel_version or machine.kernel_version, 255) or ""
    machine.architecture = _clip(osinfo.architecture or ident.architecture or machine.architecture, 64) or ""
    machine.machine_uuid = _clip(ident.machine_uuid or machine.machine_uuid, 128)
    machine.system_uuid = _clip(ident.system_uuid or ident.bios_uuid or machine.system_uuid, 128)
    machine.motherboard_serial = _clip(
        ident.motherboard_serial or payload.motherboard.serial_number or machine.motherboard_serial, 128
    )
    machine.system_serial = _clip(ident.system_serial or payload.bios.system_serial or machine.system_serial, 128)
    machine.is_virtual = ident.is_virtual
    machine.virtualization = _clip(ident.virtualization or machine.virtualization, 120)
    machine.gpu_count = len(payload.gpus)
    apply_reported_addresses(
        machine,
        [ip for nic in payload.network.interfaces for ip in (nic.ipv4 or []) + (nic.ipv6 or [])],
    )
    if events:
        machine.last_hardware_change_at = collected_at

    stored_events: list[HardwareEvent] = []
    for ev in events:
        row = HardwareEvent(
            machine_id=machine.id,
            event_type=ev.event_type,
            severity=ev.severity,
            component_path=ev.component_path,
            previous_value=ev.previous_value,
            new_value=ev.new_value,
            summary=ev.summary,
            detected_by="SERVER",
            created_at=collected_at,
        )
        db.add(row)
        stored_events.append(row)

    await _replace_normalized(db, machine.id, payload)
    if events:
        await evaluate_hardware_events(db, machine, events)
    await db.flush()
    return stored_events


async def _replace_normalized(db: AsyncSession, machine_id: UUID, payload: InventoryPayload) -> None:
    cpu = payload.cpu
    existing_cpu = await db.get(CpuInventory, machine_id)
    cpu_data = dict(
        manufacturer=_clip(cpu.manufacturer, 120),
        model=_clip(cpu.model, 255),
        family=_clip(cpu.family, 120),
        architecture=_clip(cpu.architecture, 64),
        physical_sockets=cpu.physical_sockets,
        physical_cores=cpu.physical_cores,
        logical_processors=cpu.logical_processors,
        base_frequency_mhz=cpu.base_frequency_mhz,
        current_frequency_mhz=cpu.current_frequency_mhz,
        usage_pct=cpu.usage_pct,
        temperature_c=cpu.temperature_c,
        load_avg_1=cpu.load_avg_1,
        load_avg_5=cpu.load_avg_5,
        load_avg_15=cpu.load_avg_15,
        uptime_seconds=cpu.uptime_seconds,
        topology_status=cpu.topology_status,
        notes=cpu.notes,
        raw={},
    )
    if existing_cpu:
        for k, v in cpu_data.items():
            setattr(existing_cpu, k, v)
    else:
        db.add(CpuInventory(machine_id=machine_id, **cpu_data))

    mem = payload.memory
    existing_mem = await db.get(MemorySummary, machine_id)
    mem_data = dict(
        total_physical_bytes=mem.total_physical_bytes,
        max_supported_bytes=mem.max_supported_bytes,
        slot_count=mem.slot_count,
        occupied_slots=mem.occupied_slots,
        free_slots=mem.free_slots,
        used_bytes=mem.used_bytes,
        available_bytes=mem.available_bytes,
        usage_pct=mem.usage_pct,
        topology_status=mem.topology_status,
        unlocated_empty_slots=mem.unlocated_empty_slots,
        notes=mem.notes,
    )
    if existing_mem:
        for k, v in mem_data.items():
            setattr(existing_mem, k, v)
    else:
        db.add(MemorySummary(machine_id=machine_id, **mem_data))

    await db.execute(delete(MemorySlot).where(MemorySlot.machine_id == machine_id))
    for mod in mem.modules:
        db.add(
            MemorySlot(
                machine_id=machine_id,
                slot_locator=_clip(mod.slot_locator, 120) or "",
                bank_locator=_clip(mod.bank_locator, 120),
                occupied=mod.occupied,
                capacity_bytes=mod.capacity_bytes,
                manufacturer=_clip(mod.manufacturer, 120),
                part_number=_clip(mod.part_number, 120),
                serial_number=_clip(mod.serial_number, 120),
                memory_type=_clip(mod.memory_type, 120),
                speed_mts=mod.speed_mts,
                configured_speed_mts=mod.configured_speed_mts,
                ecc=_clip(mod.ecc, 120),
                form_factor=_clip(mod.form_factor, 64),
                rank=_clip(mod.rank, 64),
                locator_known=mod.locator_known,
            )
        )

    await db.execute(delete(GpuDevice).where(GpuDevice.machine_id == machine_id))
    for gpu in payload.gpus:
        db.add(
            GpuDevice(
                machine_id=machine_id,
                gpu_index=gpu.index,
                vendor=_clip(gpu.vendor, 120),
                model=_clip(gpu.model, 255),
                vram_bytes=gpu.vram_bytes,
                pci_bus=_clip(gpu.pci_bus, 128),
                pci_device_id=_clip(gpu.pci_device_id, 64),
                serial_number=_clip(gpu.serial_number, 120),
                uuid=_clip(gpu.uuid, 128),
                driver_version=_clip(gpu.driver_version, 128),
                utilization_pct=gpu.utilization_pct,
                temperature_c=gpu.temperature_c,
                power_w=gpu.power_w,
                graphics_clock_mhz=gpu.graphics_clock_mhz,
                memory_clock_mhz=gpu.memory_clock_mhz,
                slot_designation=_clip(gpu.slot_designation, 120),
                extra=gpu.extra,
            )
        )

    pcie = payload.pcie
    existing_pcie = await db.get(PcieTopology, machine_id)
    pcie_data = dict(
        topology_status=pcie.topology_status,
        topology_note=pcie.topology_note,
        gpu_capable_total=pcie.gpu_capable_total,
        gpu_capable_occupied=pcie.gpu_capable_occupied,
        gpu_capable_free=pcie.gpu_capable_free,
        notes=pcie.notes,
    )
    if existing_pcie:
        for k, v in pcie_data.items():
            setattr(existing_pcie, k, v)
    else:
        db.add(PcieTopology(machine_id=machine_id, **pcie_data))

    await db.execute(delete(PcieSlot).where(PcieSlot.machine_id == machine_id))
    for slot in pcie.slots:
        db.add(
            PcieSlot(
                machine_id=machine_id,
                slot_designation=_clip(slot.slot_designation, 120) or "",
                slot_type=_clip(slot.slot_type, 120),
                generation=_clip(slot.generation, 120),
                width=_clip(slot.width, 64),
                current_usage=_clip(slot.current_usage, 120),
                occupied=slot.occupied,
                is_gpu_capable=slot.is_gpu_capable,
                attached_device=_clip(slot.attached_device, 255),
                bus_address=_clip(slot.bus_address, 64),
            )
        )

    await db.execute(delete(StorageDevice).where(StorageDevice.machine_id == machine_id))
    for disk in payload.storage.disks:
        db.add(
            StorageDevice(
                machine_id=machine_id,
                name=_clip(disk.name, 120) or "",
                model=_clip(disk.model, 255),
                serial_number=_clip(disk.serial_number, 120),
                capacity_bytes=disk.capacity_bytes,
                interface=_clip(disk.interface, 64),
                media_type=_clip(disk.media_type, 64),
                smart_status=_clip(disk.smart_status, 64),
                temperature_c=disk.temperature_c,
                extra=disk.extra,
            )
        )
    await db.execute(delete(Filesystem).where(Filesystem.machine_id == machine_id))
    for fs in payload.storage.filesystems:
        db.add(
            Filesystem(
                machine_id=machine_id,
                mountpoint=_clip(fs.mountpoint, 255) or "",
                fstype=_clip(fs.fstype, 64),
                device=_clip(fs.device, 120),
                total_bytes=fs.total_bytes,
                used_bytes=fs.used_bytes,
            )
        )

    await db.execute(delete(NetworkInterface).where(NetworkInterface.machine_id == machine_id))
    for nic in payload.network.interfaces:
        db.add(
            NetworkInterface(
                machine_id=machine_id,
                name=_clip(nic.name, 120) or "",
                mac=_clip(nic.mac, 32),
                ipv4=nic.ipv4,
                ipv6=nic.ipv6,
                is_up=nic.is_up,
                speed_mbps=nic.speed_mbps,
                rx_bytes=nic.rx_bytes,
                tx_bytes=nic.tx_bytes,
            )
        )

    mb = payload.motherboard
    existing_mb = await db.get(Motherboard, machine_id)
    mb_data = dict(
        manufacturer=_clip(mb.manufacturer, 120),
        model=_clip(mb.model, 255),
        serial_number=_clip(mb.serial_number, 120),
        version=_clip(mb.version, 120),
    )
    if existing_mb:
        for k, v in mb_data.items():
            setattr(existing_mb, k, v)
    else:
        db.add(Motherboard(machine_id=machine_id, **mb_data))

    bios = payload.bios
    existing_bios = await db.get(Bios, machine_id)
    bios_data = dict(
        vendor=_clip(bios.vendor, 120),
        version=_clip(bios.version, 120),
        release_date=_clip(bios.release_date, 64),
        system_manufacturer=_clip(bios.system_manufacturer, 120),
        system_model=_clip(bios.system_model, 255),
        system_serial=_clip(bios.system_serial, 120),
        system_uuid=_clip(bios.system_uuid, 128),
    )
    if existing_bios:
        for k, v in bios_data.items():
            setattr(existing_bios, k, v)
    else:
        db.add(Bios(machine_id=machine_id, **bios_data))
