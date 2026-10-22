from sqlalchemy import delete, func, select, update

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.enums import AlertStatus, MachineStatus
from app.models import Alert, HardwareEvent, Lab, Machine

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

RECENT_HW_EVENT_TYPES = [
    "RAM_REMOVED",
    "RAM_ADDED",
    "RAM_CHANGED",
    "GPU_REMOVED",
    "GPU_ADDED",
    "GPU_CHANGED",
    "DISK_REMOVED",
    "DISK_ADDED",
    "DISK_CHANGED",
    "CPU_CHANGED",
    "MOTHERBOARD_CHANGED",
]


@router.get("/summary")
async def summary(db: DbDep, user: CurrentUser):
    total = (await db.execute(select(func.count()).select_from(Machine))).scalar_one()
    status_rows = (await db.execute(select(Machine.status, func.count()).group_by(Machine.status))).all()
    by_status = {row[0]: row[1] for row in status_rows}
    open_alerts = (
        await db.execute(
            select(func.count()).select_from(Alert).where(Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]))
        )
    ).scalar_one()
    gpu_total = (await db.execute(select(func.coalesce(func.sum(Machine.gpu_count), 0)))).scalar_one()
    hw_changes = (
        await db.execute(select(func.count()).select_from(Machine).where(Machine.last_hardware_change_at.is_not(None)))
    ).scalar_one()
    labs = (await db.execute(select(Lab).order_by(Lab.name))).scalars().all()
    lab_stats = []
    for lab in labs:
        c = (await db.execute(select(func.count()).select_from(Machine).where(Machine.lab_id == lab.id))).scalar_one()
        o = (
            await db.execute(
                select(func.count())
                .select_from(Machine)
                .where(Machine.lab_id == lab.id, Machine.status == MachineStatus.ONLINE.value)
            )
        ).scalar_one()
        lab_stats.append({"id": str(lab.id), "name": lab.name, "machines": c, "online": o})
    recent = (
        await db.execute(
            select(HardwareEvent, Machine.hostname)
            .join(Machine, HardwareEvent.machine_id == Machine.id)
            .where(HardwareEvent.event_type.in_(RECENT_HW_EVENT_TYPES))
            .order_by(HardwareEvent.created_at.desc())
            .limit(15)
        )
    ).all()
    return {
        "machines": total,
        "online": by_status.get(MachineStatus.ONLINE.value, 0),
        "offline": by_status.get(MachineStatus.OFFLINE.value, 0),
        "never_connected": by_status.get(MachineStatus.NEVER_CONNECTED.value, 0),
        "unhealthy": by_status.get(MachineStatus.AGENT_UNHEALTHY.value, 0),
        "alerts": open_alerts,
        "gpus": int(gpu_total or 0),
        "machines_with_hardware_changes": hw_changes,
        "labs": lab_stats,
        "recent_changes": [
            {
                "id": str(e.id),
                "hostname": hostname,
                "machine_id": str(e.machine_id),
                "event_type": e.event_type,
                "summary": e.summary,
                "severity": e.severity,
                "created_at": e.created_at,
            }
            for e, hostname in recent
        ],
    }


@router.delete("/recent-changes")
async def clear_recent_hardware_changes(db: DbDep, user: OperatorUser, request: Request):
    """Clear recent hardware-change events and reset the HW-changes counter."""
    deleted = await db.execute(delete(HardwareEvent).where(HardwareEvent.event_type.in_(RECENT_HW_EVENT_TYPES)))
    await db.execute(update(Machine).values(last_hardware_change_at=None).where(Machine.last_hardware_change_at.is_not(None)))
    await write_audit(db, "dashboard.clear_recent_changes", user=user, request=request)
    await db.commit()
    return {"ok": True, "deleted": deleted.rowcount or 0}
