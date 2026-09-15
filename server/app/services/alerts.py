from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AlertSeverity, AlertStatus, EventType, MachineStatus
from app.models import Alert, AlertRule, HardwareEvent, Machine, utcnow
from app.schemas.inventory import DiffEvent
from app.services.notifications.dispatcher import notify


DEFAULT_RULES = [
    {
        "name": "Machine offline",
        "rule_type": "EVENT",
        "event_type": EventType.MACHINE_OFFLINE.value,
        "severity": AlertSeverity.WARNING.value,
        "description": "Agent heartbeat missed beyond threshold",
    },
    {
        "name": "GPU removed",
        "rule_type": "EVENT",
        "event_type": EventType.GPU_REMOVED.value,
        "severity": AlertSeverity.CRITICAL.value,
        "description": "A GPU disappeared from inventory",
    },
    {
        "name": "GPU changed",
        "rule_type": "EVENT",
        "event_type": EventType.GPU_CHANGED.value,
        "severity": AlertSeverity.CRITICAL.value,
        "description": "GPU identity or capacity changed",
    },
    {
        "name": "RAM removed",
        "rule_type": "EVENT",
        "event_type": EventType.RAM_REMOVED.value,
        "severity": AlertSeverity.CRITICAL.value,
        "description": "A RAM module was removed",
    },
    {
        "name": "RAM changed",
        "rule_type": "EVENT",
        "event_type": EventType.RAM_CHANGED.value,
        "severity": AlertSeverity.WARNING.value,
        "description": "A RAM module changed",
    },
    {
        "name": "Disk removed",
        "rule_type": "EVENT",
        "event_type": EventType.DISK_REMOVED.value,
        "severity": AlertSeverity.CRITICAL.value,
        "description": "A disk disappeared from inventory",
    },
    {
        "name": "CPU changed",
        "rule_type": "EVENT",
        "event_type": EventType.CPU_CHANGED.value,
        "severity": AlertSeverity.CRITICAL.value,
        "description": "CPU identity changed",
    },
    {
        "name": "CPU temperature high",
        "rule_type": "METRIC",
        "metric_name": "cpu_temp_c",
        "operator": ">",
        "threshold": 90,
        "severity": AlertSeverity.CRITICAL.value,
        "description": "CPU temperature exceeds threshold",
    },
    {
        "name": "GPU temperature high",
        "rule_type": "METRIC",
        "metric_name": "gpu_temp_c",
        "operator": ">",
        "threshold": 85,
        "severity": AlertSeverity.WARNING.value,
        "description": "GPU temperature exceeds threshold",
    },
    {
        "name": "RAM usage high",
        "rule_type": "METRIC",
        "metric_name": "ram_usage_pct",
        "operator": ">",
        "threshold": 95,
        "severity": AlertSeverity.WARNING.value,
        "description": "Memory utilization exceeds threshold",
    },
    {
        "name": "Disk usage high",
        "rule_type": "METRIC",
        "metric_name": "disk_usage_pct",
        "operator": ">",
        "threshold": 90,
        "severity": AlertSeverity.WARNING.value,
        "description": "Disk utilization exceeds threshold",
    },
]


async def seed_default_rules(db: AsyncSession) -> None:
    existing = set((await db.execute(select(AlertRule.name))).scalars().all())
    for spec in DEFAULT_RULES:
        if spec["name"] in existing:
            continue
        db.add(AlertRule(**spec))
    await db.flush()


def _compare(op: str, left: float, right: float) -> bool:
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    return False


async def _open_or_update_alert(
    db: AsyncSession,
    machine: Machine,
    rule: AlertRule,
    title: str,
    message: str,
    event_type: str | None,
) -> Alert | None:
    existing = (
        await db.execute(
            select(Alert).where(
                Alert.machine_id == machine.id,
                Alert.rule_id == rule.id,
                Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
            )
        )
    ).scalar_one_or_none()
    now = utcnow()
    if existing:
        if rule.cooldown_seconds and existing.updated_at and (now - existing.updated_at) < timedelta(seconds=rule.cooldown_seconds):
            existing.updated_at = now
            return existing
        existing.message = message
        existing.updated_at = now
        return existing
    alert = Alert(
        machine_id=machine.id,
        rule_id=rule.id,
        severity=rule.severity,
        status=AlertStatus.OPEN.value,
        title=title,
        message=message,
        event_type=event_type,
    )
    db.add(alert)
    machine.has_open_alerts = True
    await notify(
        db,
        title=title,
        body=message,
        payload={"machine_id": str(machine.id), "hostname": machine.hostname, "severity": rule.severity},
    )
    return alert


async def evaluate_hardware_events(db: AsyncSession, machine: Machine, events: list[DiffEvent | HardwareEvent]) -> None:
    rules = (await db.execute(select(AlertRule).where(AlertRule.enabled.is_(True), AlertRule.rule_type == "EVENT"))).scalars().all()
    by_type = {r.event_type: r for r in rules if r.event_type}
    for event in events:
        event_type = event.event_type if isinstance(event, DiffEvent) else event.event_type
        summary = event.summary if isinstance(event, DiffEvent) else event.summary
        rule = by_type.get(event_type)
        if not rule:
            continue
        await _open_or_update_alert(
            db,
            machine,
            rule,
            title=f"{machine.hostname or machine.display_name}: {rule.name}",
            message=summary,
            event_type=event_type,
        )


async def evaluate_metrics(db: AsyncSession, machine: Machine, values: dict[str, float | None]) -> None:
    rules = (await db.execute(select(AlertRule).where(AlertRule.enabled.is_(True), AlertRule.rule_type == "METRIC"))).scalars().all()
    for rule in rules:
        if not rule.metric_name or rule.threshold is None:
            continue
        raw = values.get(rule.metric_name)
        if raw is None:
            continue
        triggered = _compare(rule.operator, float(raw), float(rule.threshold))
        existing = (
            await db.execute(
                select(Alert).where(
                    Alert.machine_id == machine.id,
                    Alert.rule_id == rule.id,
                    Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
                )
            )
        ).scalar_one_or_none()
        if triggered:
            await _open_or_update_alert(
                db,
                machine,
                rule,
                title=f"{machine.hostname or machine.display_name}: {rule.name}",
                message=f"{rule.metric_name}={raw} {rule.operator} {rule.threshold}",
                event_type=None,
            )
        elif existing:
            existing.status = AlertStatus.RESOLVED.value
            existing.resolved_at = utcnow()
    open_count = (
        await db.execute(
            select(Alert).where(
                Alert.machine_id == machine.id,
                Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
            )
        )
    ).scalars().all()
    machine.has_open_alerts = bool(open_count)


async def record_status_event(db: AsyncSession, machine: Machine, new_status: str) -> HardwareEvent | None:
    """Emit ONLINE/OFFLINE events without duplicating storms."""
    now = utcnow()
    event_type = None
    summary = None
    if new_status == MachineStatus.OFFLINE.value:
        event_type = EventType.MACHINE_OFFLINE.value
        summary = f"{machine.hostname} went offline"
    elif new_status == MachineStatus.ONLINE.value:
        event_type = EventType.MACHINE_ONLINE.value
        summary = f"{machine.hostname} came online"
    elif new_status == MachineStatus.AGENT_UNHEALTHY.value:
        event_type = EventType.MACHINE_UNHEALTHY.value
        summary = f"{machine.hostname} agent is unhealthy"
    if not event_type:
        return None

    last = (
        await db.execute(
            select(HardwareEvent)
            .where(HardwareEvent.machine_id == machine.id, HardwareEvent.event_type.in_([
                EventType.MACHINE_ONLINE.value,
                EventType.MACHINE_OFFLINE.value,
                EventType.MACHINE_UNHEALTHY.value,
            ]))
            .order_by(HardwareEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last and last.event_type == event_type:
        return None
    event = HardwareEvent(
        machine_id=machine.id,
        event_type=event_type,
        severity=AlertSeverity.WARNING.value if event_type != EventType.MACHINE_ONLINE.value else AlertSeverity.INFO.value,
        summary=summary or "",
        previous_value={"status": machine.status},
        new_value={"status": new_status},
        detected_by="SERVER",
        created_at=now,
    )
    db.add(event)
    if event_type == EventType.MACHINE_OFFLINE.value:
        await evaluate_hardware_events(db, machine, [event])
    if event_type == EventType.MACHINE_ONLINE.value:
        existing = (
            await db.execute(
                select(Alert).where(
                    Alert.machine_id == machine.id,
                    Alert.event_type == EventType.MACHINE_OFFLINE.value,
                    Alert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
                )
            )
        ).scalars().all()
        for alert in existing:
            alert.status = AlertStatus.RESOLVED.value
            alert.resolved_at = now
    return event
