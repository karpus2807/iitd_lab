from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import delete, func, select

from app.api.deps import AdminUser, CurrentUser, DbDep, OperatorUser, write_audit
from app.enums import AlertStatus
from app.models import Alert, AlertRule, Machine, Notification, utcnow
from app.schemas.api import AlertRuleIn

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


async def _sync_open_alert_flag(db, machine_id: UUID | None) -> None:
    if machine_id is None:
        return
    machine = await db.get(Machine, machine_id)
    if machine is None:
        return
    remaining = (
        await db.execute(
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.machine_id == machine_id,
                Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
            )
        )
    ).scalar_one()
    machine.has_open_alerts = bool(remaining)


async def _mark_related_notifications_read(db, machine_id: UUID | None) -> None:
    if machine_id is None:
        return
    mid = str(machine_id)
    rows = (await db.execute(select(Notification).where(Notification.read.is_(False)))).scalars().all()
    for row in rows:
        if str((row.payload or {}).get("machine_id") or "") == mid:
            row.read = True


@router.get("/summary")
async def alert_summary(db: DbDep, user: CurrentUser):
    open_n = (
        await db.execute(select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.OPEN.value))
    ).scalar_one()
    ack_n = (
        await db.execute(
            select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.ACKNOWLEDGED.value)
        )
    ).scalar_one()
    resolved_n = (
        await db.execute(select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.RESOLVED.value))
    ).scalar_one()
    return {
        "open": int(open_n or 0),
        "acknowledged": int(ack_n or 0),
        "resolved": int(resolved_n or 0),
        "active": int(open_n or 0) + int(ack_n or 0),
    }


@router.get("")
async def list_alerts(
    db: DbDep,
    user: CurrentUser,
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = None,
    machine_id: UUID | None = None,
):
    stmt = select(Alert, Machine.hostname).outerjoin(Machine, Alert.machine_id == Machine.id)
    if status_filter:
        stmt = stmt.where(Alert.status == status_filter)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if machine_id:
        stmt = stmt.where(Alert.machine_id == machine_id)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(500)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": str(a.id),
            "machine_id": str(a.machine_id) if a.machine_id else None,
            "hostname": hostname,
            "severity": a.severity,
            "status": a.status,
            "title": a.title,
            "message": a.message,
            "event_type": a.event_type,
            "created_at": a.created_at,
            "acknowledged_at": a.acknowledged_at,
            "resolved_at": a.resolved_at,
        }
        for a, hostname in rows
    ]


@router.post("/{alert_id}/acknowledge")
async def acknowledge(alert_id: UUID, db: DbDep, user: OperatorUser):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = AlertStatus.ACKNOWLEDGED.value
    alert.acknowledged_by_id = user.id
    alert.acknowledged_at = utcnow()
    await _sync_open_alert_flag(db, alert.machine_id)
    await write_audit(db, "alert.acknowledge", user=user, machine_id=alert.machine_id, details={"alert_id": str(alert_id)})
    await db.commit()
    return {"ok": True}


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: UUID, db: DbDep, user: OperatorUser):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = AlertStatus.RESOLVED.value
    alert.resolved_at = utcnow()
    await _sync_open_alert_flag(db, alert.machine_id)
    await _mark_related_notifications_read(db, alert.machine_id)
    await write_audit(db, "alert.resolve", user=user, machine_id=alert.machine_id)
    await db.commit()
    return {"ok": True}


@router.delete("")
async def clear_alerts(
    db: DbDep,
    user: OperatorUser,
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
):
    stmt = delete(Alert)
    wanted = (status_filter or "").strip().upper()
    if wanted:
        if wanted not in {AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value, AlertStatus.RESOLVED.value}:
            raise HTTPException(400, "status must be OPEN, ACKNOWLEDGED, or RESOLVED")
        stmt = stmt.where(Alert.status == wanted)
    result = await db.execute(stmt)
    machines = (await db.execute(select(Machine))).scalars().all()
    for machine in machines:
        await _sync_open_alert_flag(db, machine.id)
    if not wanted:
        notes = (await db.execute(select(Notification).where(Notification.read.is_(False)))).scalars().all()
        for row in notes:
            row.read = True
    await write_audit(
        db,
        "alert.clear",
        user=user,
        details={"status": wanted or "ALL", "deleted": result.rowcount or 0},
        request=request,
    )
    await db.commit()
    return {"ok": True, "deleted": result.rowcount or 0}


@router.delete("/{alert_id}")
async def delete_alert(alert_id: UUID, db: DbDep, user: OperatorUser, request: Request):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    machine_id = alert.machine_id
    await db.delete(alert)
    await _sync_open_alert_flag(db, machine_id)
    await write_audit(db, "alert.delete", user=user, machine_id=machine_id, details={"alert_id": str(alert_id)}, request=request)
    await db.commit()
    return {"ok": True}


@router.get("/rules")
async def list_rules(db: DbDep, user: CurrentUser):
    rows = (await db.execute(select(AlertRule).order_by(AlertRule.name))).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "enabled": r.enabled,
            "severity": r.severity,
            "rule_type": r.rule_type,
            "event_type": r.event_type,
            "metric_name": r.metric_name,
            "operator": r.operator,
            "threshold": r.threshold,
            "cooldown_seconds": r.cooldown_seconds,
        }
        for r in rows
    ]


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: UUID, body: AlertRuleIn, db: DbDep, user: AdminUser):
    rule = await db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    for field, value in body.model_dump().items():
        setattr(rule, field, value)
    await write_audit(db, "alert.rule_update", user=user, details={"rule": rule.name})
    await db.commit()
    return {"ok": True}
