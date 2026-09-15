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
    previous = InventoryPayload.model_validate(previous_row.payload) if previous_row else None
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
    machine.hostname = ident.hostname or osinfo.hostname or machine.hostname
    machine.os_name = osinfo.name or ident.os_name or machine.os_name
    machine.os_version = osinfo.version or ident.os_version or machine.os_version
    machine.kernel_version = osinfo.kernel or ident.kernel_version or machine.kernel_version
    machine.architecture = osinfo.architecture or ident.architecture or machine.architecture
    machine.machine_uuid = ident.machine_uuid or machine.machine_uuid
    machine.system_uuid = ident.system_uuid or ident.bios_uuid or machine.system_uuid
    machine.motherboard_serial = ident.motherboard_serial or payload.motherboard.serial_number
    machine.system_serial = ident.system_serial or payload.bios.system_serial
    machine.is_virtual = ident.is_virtual
    machine.virtualization = ident.virtualization
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
        manufacturer=cpu.manufacturer,
        model=cpu.model,
        family=cpu.family,
        architecture=cpu.architecture,
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
                slot_locator=mod.slot_locator,
                bank_locator=mod.bank_locator,
                occupied=mod.occupied,
                capacity_bytes=mod.capacity_bytes,
                manufacturer=mod.manufacturer,
                part_number=mod.part_number,
                serial_number=mod.serial_number,
                memory_type=mod.memory_type,
                speed_mts=mod.speed_mts,
                configured_speed_mts=mod.configured_speed_mts,
                ecc=mod.ecc,
                form_factor=mod.form_factor,
                rank=mod.rank,
                locator_known=mod.locator_known,
            )
        )

    await db.execute(delete(GpuDevice).where(GpuDevice.machine_id == machine_id))
    for gpu in payload.gpus:
        db.add(
            GpuDevice(
                machine_id=machine_id,
                gpu_index=gpu.index,
                vendor=gpu.vendor,
                model=gpu.model,
                vram_bytes=gpu.vram_bytes,
                pci_bus=gpu.pci_bus,
                pci_device_id=gpu.pci_device_id,
                serial_number=gpu.serial_number,
                uuid=gpu.uuid,
                driver_version=gpu.driver_version,
                utilization_pct=gpu.utilization_pct,
                temperature_c=gpu.temperature_c,
                power_w=gpu.power_w,
                graphics_clock_mhz=gpu.graphics_clock_mhz,
                memory_clock_mhz=gpu.memory_clock_mhz,
                slot_designation=gpu.slot_designation,
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
                slot_designation=slot.slot_designation,
                slot_type=slot.slot_type,
                generation=slot.generation,
                width=slot.width,
                current_usage=slot.current_usage,
                occupied=slot.occupied,
                is_gpu_capable=slot.is_gpu_capable,
                attached_device=slot.attached_device,
                bus_address=slot.bus_address,
            )
        )

    await db.execute(delete(StorageDevice).where(StorageDevice.machine_id == machine_id))
    for disk in payload.storage.disks:
        db.add(
            StorageDevice(
                machine_id=machine_id,
                name=disk.name,
                model=disk.model,
                serial_number=disk.serial_number,
                capacity_bytes=disk.capacity_bytes,
                interface=disk.interface,
                media_type=disk.media_type,
                smart_status=disk.smart_status,
                temperature_c=disk.temperature_c,
                extra=disk.extra,
            )
        )
    await db.execute(delete(Filesystem).where(Filesystem.machine_id == machine_id))
    for fs in payload.storage.filesystems:
        db.add(
            Filesystem(
                machine_id=machine_id,
                mountpoint=fs.mountpoint,
                fstype=fs.fstype,
                device=fs.device,
                total_bytes=fs.total_bytes,
                used_bytes=fs.used_bytes,
            )
        )

    await db.execute(delete(NetworkInterface).where(NetworkInterface.machine_id == machine_id))
    for nic in payload.network.interfaces:
        db.add(
            NetworkInterface(
                machine_id=machine_id,
                name=nic.name,
                mac=nic.mac,
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
    mb_data = dict(manufacturer=mb.manufacturer, model=mb.model, serial_number=mb.serial_number, version=mb.version)
    if existing_mb:
        for k, v in mb_data.items():
            setattr(existing_mb, k, v)
    else:
        db.add(Motherboard(machine_id=machine_id, **mb_data))

    bios = payload.bios
    existing_bios = await db.get(Bios, machine_id)
    bios_data = dict(
        vendor=bios.vendor,
        version=bios.version,
        release_date=bios.release_date,
        system_manufacturer=bios.system_manufacturer,
        system_model=bios.system_model,
        system_serial=bios.system_serial,
        system_uuid=bios.system_uuid,
    )
    if existing_bios:
        for k, v in bios_data.items():
            setattr(existing_bios, k, v)
    else:
        db.add(Bios(machine_id=machine_id, **bios_data))
