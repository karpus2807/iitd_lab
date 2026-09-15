from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbDep, OperatorUser, write_audit
from app.enums import AlertStatus
from app.models import Alert, AlertRule, Machine, utcnow
from app.schemas.api import AlertRuleIn

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


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
    machine = await db.get(Machine, alert.machine_id) if alert.machine_id else None
    if machine:
        remaining = (
            await db.execute(
                select(Alert).where(
                    Alert.machine_id == machine.id,
                    Alert.id != alert.id,
                    Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
                )
            )
        ).scalars().all()
        machine.has_open_alerts = bool(remaining)
    await write_audit(db, "alert.resolve", user=user, machine_id=alert.machine_id)
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
