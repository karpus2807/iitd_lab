from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.models import (
    Agent,
    AgentLog,
    Alert,
    Bios,
    CpuInventory,
    Filesystem,
    GpuDevice,
    GpuMetricSample,
    HardwareEvent,
    HardwareSnapshot,
    Lab,
    Machine,
    MemorySlot,
    MemorySummary,
    MetricHourly,
    MetricSample,
    Motherboard,
    NetworkInterface,
    PcieSlot,
    PcieTopology,
    StorageDevice,
)
from app.schemas.api import MachineListItem, MachineUpdate

router = APIRouter(prefix="/api/machines", tags=["machines"])


def _unknown(value):
    return value if value not in (None, "", "unknown") else None


@router.get("", response_model=list[MachineListItem])
async def list_machines(
    db: DbDep,
    user: CurrentUser,
    lab_id: UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    inventory_id: str | None = None,
    os_name: str | None = None,
    has_alerts: bool | None = None,
    has_gpu: bool | None = None,
    virtual: bool | None = None,
):
    stmt = select(Machine, Lab.name).outerjoin(Lab, Machine.lab_id == Lab.id)
    if lab_id:
        stmt = stmt.where(Machine.lab_id == lab_id)
    if status:
        stmt = stmt.where(Machine.status == status)
    if os_name:
        stmt = stmt.where(func.lower(Machine.os_name).like(f"%{os_name.lower()}%"))
    if has_alerts is True:
        stmt = stmt.where(Machine.has_open_alerts.is_(True))
    if has_gpu is True:
        stmt = stmt.where(Machine.gpu_count > 0)
    if has_gpu is False:
        stmt = stmt.where(Machine.gpu_count == 0)
    if virtual is True:
        stmt = stmt.where(Machine.is_virtual.is_(True))
    if virtual is False:
        stmt = stmt.where(Machine.is_virtual.is_(False))
    if inventory_id:
        stmt = stmt.where(Machine.inventory_id == inventory_id.strip())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Machine.hostname).like(like),
                func.lower(Machine.display_name).like(like),
                func.lower(func.coalesce(Machine.inventory_id, "")).like(like),
                func.lower(func.coalesce(Machine.current_ip, "")).like(like),
            )
        )
    stmt = stmt.order_by(Machine.hostname.asc())
    rows = (await db.execute(stmt)).all()
    return [
        MachineListItem(
            id=m.id,
            hostname=m.hostname,
            display_name=m.display_name,
            inventory_id=m.inventory_id,
            lab_id=m.lab_id,
            lab_name=lab_name,
            status=m.status,
            os_name=m.os_name,
            architecture=m.architecture,
            current_ip=m.current_ip,
            current_ips=m.current_ips or [],
            previous_ip=m.previous_ip,
            last_seen_at=m.last_seen_at,
            gpu_count=m.gpu_count,
            has_open_alerts=m.has_open_alerts,
            is_virtual=m.is_virtual,
            last_hardware_change_at=m.last_hardware_change_at,
            approved=m.approved,
        )
        for m, lab_name in rows
    ]


@router.get("/{machine_id}")
async def get_machine(machine_id: UUID, db: DbDep, user: CurrentUser):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    lab = await db.get(Lab, machine.lab_id) if machine.lab_id else None
    agent = (await db.execute(select(Agent).where(Agent.machine_id == machine.id))).scalar_one_or_none()
    return {
        "id": str(machine.id),
        "hostname": machine.hostname,
        "display_name": machine.display_name,
        "inventory_id": machine.inventory_id,
        "lab_id": str(machine.lab_id) if machine.lab_id else None,
        "lab_name": lab.name if lab else None,
        "status": machine.status,
        "os_name": machine.os_name,
        "os_version": machine.os_version,
        "kernel_version": machine.kernel_version,
        "architecture": machine.architecture,
        "current_ip": machine.current_ip,
        "current_ips": machine.current_ips or [],
        "previous_ip": machine.previous_ip,
        "ip_changed_at": machine.ip_changed_at,
        "last_seen_at": machine.last_seen_at,
        "first_seen_at": machine.first_seen_at,
        "is_virtual": machine.is_virtual,
        "virtualization": machine.virtualization or "Unknown / Not reported",
        "gpu_count": machine.gpu_count,
        "has_open_alerts": machine.has_open_alerts,
        "approved": machine.approved,
        "machine_uuid": machine.machine_uuid,
        "system_uuid": machine.system_uuid,
        "agent": {
            "id": agent.agent_public_id if agent else None,
            "status": agent.status if agent else None,
            "version": agent.agent_version if agent else None,
            "health": agent.health if agent else None,
            "last_heartbeat_at": agent.last_heartbeat_at if agent else None,
            "last_inventory_at": agent.last_inventory_at if agent else None,
        },
    }


@router.patch("/{machine_id}")
async def update_machine(machine_id: UUID, body: MachineUpdate, db: DbDep, user: OperatorUser):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    data = body.model_dump(exclude_unset=True)
    if "display_name" in data:
        machine.display_name = data["display_name"]
    if "inventory_id" in data and data["inventory_id"] is not None:
        from app.services.public_url import normalize_inventory_id

        inv = normalize_inventory_id(data["inventory_id"])
        clash = (
            await db.execute(select(Machine).where(Machine.inventory_id == inv, Machine.id != machine.id))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(409, f"Machine ID {inv} is already in use")
        machine.inventory_id = inv
        if not machine.display_name or machine.display_name == machine.hostname:
            machine.display_name = inv
    if "lab_id" in data:
        if data["lab_id"] is not None:
            lab = await db.get(Lab, data["lab_id"])
            if lab is None:
                raise HTTPException(400, "Unknown lab")
        machine.lab_id = data["lab_id"]
    if "approved" in data:
        machine.approved = data["approved"]
        agent = (await db.execute(select(Agent).where(Agent.machine_id == machine.id))).scalar_one_or_none()
        if agent and data["approved"] and agent.status == "PENDING":
            agent.status = "ACTIVE"
    await db.commit()
    return {"ok": True}


@router.delete("/{machine_id}")
async def delete_machine(machine_id: UUID, db: DbDep, user: OperatorUser, request: Request):
    machine = await db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    label = machine.inventory_id or machine.display_name or machine.hostname or str(machine.id)
    await write_audit(
        db,
        "machine.delete",
        user=user,
        machine_id=machine.id,
        details={"inventory_id": machine.inventory_id, "hostname": machine.hostname},
        request=request,
    )
    agent = (await db.execute(select(Agent).where(Agent.machine_id == machine.id))).scalar_one_or_none()
    if agent:
        await db.delete(agent)
        await db.flush()
    await db.delete(machine)
    await db.commit()
    return {"ok": True, "deleted": label}


async def _hardware_dict(db: AsyncSession, machine_id: UUID) -> dict:
    cpu = await db.get(CpuInventory, machine_id)
    mem = await db.get(MemorySummary, machine_id)
    slots = (await db.execute(select(MemorySlot).where(MemorySlot.machine_id == machine_id))).scalars().all()
    gpus = (await db.execute(select(GpuDevice).where(GpuDevice.machine_id == machine_id).order_by(GpuDevice.gpu_index))).scalars().all()
    pcie_top = await db.get(PcieTopology, machine_id)
    pcie_slots = (await db.execute(select(PcieSlot).where(PcieSlot.machine_id == machine_id))).scalars().all()
    disks = (await db.execute(select(StorageDevice).where(StorageDevice.machine_id == machine_id))).scalars().all()
    fs = (await db.execute(select(Filesystem).where(Filesystem.machine_id == machine_id))).scalars().all()
    nics = (await db.execute(select(NetworkInterface).where(NetworkInterface.machine_id == machine_id))).scalars().all()
    mb = await db.get(Motherboard, machine_id)
    bios = await db.get(Bios, machine_id)

    def present(v, fallback="Unknown / Not reported"):
        return v if v not in (None, "") else fallback

    return {
        "cpu": None
        if not cpu
        else {
            "manufacturer": present(cpu.manufacturer),
            "model": present(cpu.model),
            "family": present(cpu.family),
            "architecture": present(cpu.architecture),
            "physical_sockets": cpu.physical_sockets,
            "physical_cores": cpu.physical_cores,
            "logical_processors": cpu.logical_processors,
            "base_frequency_mhz": cpu.base_frequency_mhz,
            "current_frequency_mhz": cpu.current_frequency_mhz,
            "usage_pct": cpu.usage_pct,
            "temperature_c": cpu.temperature_c,
            "load_avg_1": cpu.load_avg_1,
            "load_avg_5": cpu.load_avg_5,
            "load_avg_15": cpu.load_avg_15,
            "uptime_seconds": cpu.uptime_seconds,
            "topology_status": cpu.topology_status,
            "notes": cpu.notes,
        },
        "memory": None
        if not mem
        else {
            "total_physical_bytes": mem.total_physical_bytes,
            "max_supported_bytes": mem.max_supported_bytes,
            "slot_count": mem.slot_count,
            "occupied_slots": mem.occupied_slots,
            "free_slots": mem.free_slots,
            "used_bytes": mem.used_bytes,
            "available_bytes": mem.available_bytes,
            "usage_pct": mem.usage_pct,
            "topology_status": mem.topology_status,
            "unlocated_empty_slots": mem.unlocated_empty_slots,
            "notes": mem.notes,
            "slots": [
                {
                    "slot_locator": s.slot_locator,
                    "bank_locator": s.bank_locator,
                    "occupied": s.occupied,
                    "capacity_bytes": s.capacity_bytes,
                    "manufacturer": present(s.manufacturer) if s.occupied else None,
                    "part_number": present(s.part_number) if s.occupied else None,
                    "serial_number": present(s.serial_number) if s.occupied else None,
                    "memory_type": present(s.memory_type) if s.occupied else None,
                    "speed_mts": s.speed_mts,
                    "configured_speed_mts": s.configured_speed_mts,
                    "ecc": present(s.ecc) if s.occupied else None,
                    "form_factor": present(s.form_factor) if s.occupied else None,
                    "rank": present(s.rank) if s.occupied else None,
                    "locator_known": s.locator_known,
                }
                for s in slots
            ],
        },
        "gpus": [
            {
                "index": g.gpu_index,
                "vendor": present(g.vendor),
                "model": present(g.model),
                "vram_bytes": g.vram_bytes,
                "pci_bus": present(g.pci_bus),
                "pci_device_id": present(g.pci_device_id),
                "serial_number": present(g.serial_number),
                "uuid": present(g.uuid),
                "driver_version": present(g.driver_version),
                "utilization_pct": g.utilization_pct,
                "temperature_c": g.temperature_c,
                "power_w": g.power_w,
                "graphics_clock_mhz": g.graphics_clock_mhz,
                "memory_clock_mhz": g.memory_clock_mhz,
                "slot_designation": present(g.slot_designation),
            }
            for g in gpus
        ],
        "pcie": {
            "topology_status": pcie_top.topology_status if pcie_top else "UNKNOWN",
            "topology_note": (pcie_top.topology_note if pcie_top else "Physical slot topology not exposed by firmware/OS"),
            "gpu_capable_total": pcie_top.gpu_capable_total if pcie_top else None,
            "gpu_capable_occupied": pcie_top.gpu_capable_occupied if pcie_top else None,
            "gpu_capable_free": pcie_top.gpu_capable_free if pcie_top else None,
            "notes": pcie_top.notes if pcie_top else [],
            "slots": [
                {
                    "slot_designation": s.slot_designation,
                    "slot_type": present(s.slot_type),
                    "generation": present(s.generation),
                    "width": present(s.width),
                    "current_usage": present(s.current_usage),
                    "occupied": s.occupied,
                    "is_gpu_capable": s.is_gpu_capable,
                    "attached_device": present(s.attached_device),
                    "bus_address": present(s.bus_address),
                }
                for s in pcie_slots
            ],
        },
        "storage": {
            "disks": [
                {
                    "name": d.name,
                    "model": present(d.model),
                    "serial_number": present(d.serial_number),
                    "capacity_bytes": d.capacity_bytes,
                    "interface": present(d.interface),
                    "media_type": present(d.media_type),
                    "smart_status": present(d.smart_status),
                    "temperature_c": d.temperature_c,
                }
                for d in disks
            ],
            "filesystems": [
                {
                    "mountpoint": f.mountpoint,
                    "fstype": f.fstype,
                    "device": f.device,
                    "total_bytes": f.total_bytes,
                    "used_bytes": f.used_bytes,
                }
                for f in fs
            ],
        },
        "network": [
            {
                "name": n.name,
                "mac": present(n.mac),
                "ipv4": n.ipv4,
                "ipv6": n.ipv6,
                "is_up": n.is_up,
                "speed_mbps": n.speed_mbps,
            }
            for n in nics
        ],
        "motherboard": None
        if not mb
        else {
            "manufacturer": present(mb.manufacturer),
            "model": present(mb.model),
            "serial_number": present(mb.serial_number),
            "version": present(mb.version),
        },
        "bios": None
        if not bios
        else {
            "vendor": present(bios.vendor),
            "version": present(bios.version),
            "release_date": present(bios.release_date),
            "system_manufacturer": present(bios.system_manufacturer),
            "system_model": present(bios.system_model),
            "system_serial": present(bios.system_serial),
            "system_uuid": present(bios.system_uuid),
        },
    }


@router.get("/{machine_id}/hardware")
async def machine_hardware(machine_id: UUID, db: DbDep, user: CurrentUser):
    if not await db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    return await _hardware_dict(db, machine_id)


@router.get("/{machine_id}/metrics")
async def machine_metrics(
    machine_id: UUID,
    db: DbDep,
    user: CurrentUser,
    range: str = Query("24h"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    if not await db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    now = datetime.now(timezone.utc)
    spans = {"1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7, "30d": 24 * 30}
    if start and end:
        t0, t1 = start, end
    else:
        hours = spans.get(range, 24)
        t0, t1 = now - timedelta(hours=hours), now
    use_hourly = (t1 - t0) > timedelta(days=7)
    if use_hourly:
        rows = (
            await db.execute(
                select(MetricHourly)
                .where(MetricHourly.machine_id == machine_id, MetricHourly.hour_start.between(t0, t1))
                .order_by(MetricHourly.hour_start.asc())
            )
        ).scalars().all()
        samples = [
            {"collected_at": r.hour_start, **(r.values or {}), "source": "hourly"}
            for r in rows
        ]
    else:
        rows = (
            await db.execute(
                select(MetricSample)
                .where(MetricSample.machine_id == machine_id, MetricSample.collected_at.between(t0, t1))
                .order_by(MetricSample.collected_at.asc())
            )
        ).scalars().all()
        samples = [
            {
                "collected_at": r.collected_at,
                "cpu_usage_pct": r.cpu_usage_pct,
                "cpu_temp_c": r.cpu_temp_c,
                "cpu_freq_mhz": r.cpu_freq_mhz,
                "ram_usage_pct": r.ram_usage_pct,
                "ram_used_bytes": r.ram_used_bytes,
                "ram_total_bytes": r.ram_total_bytes,
                "disk_used_bytes": r.disk_used_bytes,
                "disk_total_bytes": r.disk_total_bytes,
                "disk_read_bps": r.disk_read_bps,
                "disk_write_bps": r.disk_write_bps,
                "net_tx_bps": r.net_tx_bps,
                "net_rx_bps": r.net_rx_bps,
                "source": "raw",
            }
            for r in rows
        ]
    gpus = (
        await db.execute(
            select(GpuMetricSample)
            .where(GpuMetricSample.machine_id == machine_id, GpuMetricSample.collected_at.between(t0, t1))
            .order_by(GpuMetricSample.collected_at.asc())
        )
    ).scalars().all()
    return {
        "start": t0,
        "end": t1,
        "samples": samples,
        "gpus": [
            {
                "collected_at": g.collected_at,
                "index": g.gpu_index,
                "gpu_key": g.gpu_key,
                "utilization_pct": g.utilization_pct,
                "temperature_c": g.temperature_c,
                "vram_used_bytes": g.vram_used_bytes,
                "vram_total_bytes": g.vram_total_bytes,
                "power_w": g.power_w,
                "graphics_clock_mhz": g.graphics_clock_mhz,
                "memory_clock_mhz": g.memory_clock_mhz,
            }
            for g in gpus
        ],
    }


@router.get("/{machine_id}/events")
async def machine_events(machine_id: UUID, db: DbDep, user: CurrentUser, limit: int = 200):
    if not await db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    rows = (
        await db.execute(
            select(HardwareEvent)
            .where(HardwareEvent.machine_id == machine_id)
            .order_by(HardwareEvent.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "event_type": r.event_type,
            "severity": r.severity,
            "summary": r.summary,
            "component_path": r.component_path,
            "previous_value": r.previous_value,
            "new_value": r.new_value,
            "detected_by": r.detected_by,
            "acknowledged": r.acknowledged,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/{machine_id}/logs")
async def machine_logs(machine_id: UUID, db: DbDep, user: CurrentUser, limit: int = 200):
    if not await db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    rows = (
        await db.execute(
            select(AgentLog)
            .where(AgentLog.machine_id == machine_id)
            .order_by(AgentLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "level": r.level,
            "message": r.message,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/{machine_id}/snapshots")
async def machine_snapshots(machine_id: UUID, db: DbDep, user: CurrentUser, limit: int = 20):
    if not await db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    rows = (
        await db.execute(
            select(HardwareSnapshot)
            .where(HardwareSnapshot.machine_id == machine_id)
            .order_by(HardwareSnapshot.collected_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [{"id": str(r.id), "collected_at": r.collected_at, "fingerprint": r.fingerprint} for r in rows]


@router.get("/{machine_id}/alerts")
async def machine_alerts(machine_id: UUID, db: DbDep, user: CurrentUser):
    if not await db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    rows = (
        await db.execute(
            select(Alert).where(Alert.machine_id == machine_id).order_by(Alert.created_at.desc()).limit(100)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "severity": r.severity,
            "status": r.status,
            "title": r.title,
            "message": r.message,
            "created_at": r.created_at,
            "resolved_at": r.resolved_at,
        }
        for r in rows
    ]
