from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import AgentStatus, EventType, MachineStatus
from app.models import Agent, HardwareEvent, Machine, utcnow
from app.services.addresses import normalize_ips, primary_ip
from app.services.alerts import record_status_event


def apply_reported_addresses(machine: Machine, reported: list[str], db: AsyncSession | None = None) -> HardwareEvent | None:
    """Update displayed IPs. Never used to identify or split a machine."""
    new_ips = normalize_ips(reported)
    if not new_ips:
        return None
    new_primary = primary_ip(new_ips)
    old_primary = machine.current_ip
    old_set = set(machine.current_ips or [])
    machine.current_ips = new_ips
    event = None
    if new_primary and new_primary != old_primary:
        machine.previous_ip = old_primary
        machine.current_ip = new_primary
        machine.ip_changed_at = utcnow()
        if old_primary:
            event = HardwareEvent(
                machine_id=machine.id,
                event_type=EventType.IP_CHANGED.value,
                severity="INFO",
                component_path="network.ip",
                previous_value={"ip": old_primary, "ips": sorted(old_set)},
                new_value={"ip": new_primary, "ips": new_ips},
                summary=f"IP changed {old_primary} → {new_primary} (same machine)",
                detected_by="SERVER",
            )
            if db is not None:
                db.add(event)
    elif new_primary:
        machine.current_ip = new_primary
    return event


async def apply_heartbeat(db: AsyncSession, machine: Machine, agent: Agent, healthy: bool) -> None:
    now = utcnow()
    agent.last_heartbeat_at = now
    machine.last_seen_at = now
    if machine.first_seen_at is None:
        machine.first_seen_at = now
    target = MachineStatus.ONLINE.value if healthy else MachineStatus.AGENT_UNHEALTHY.value
    if machine.status != target:
        await record_status_event(db, machine, target)
        machine.status = target


async def reconcile_machine_status(db: AsyncSession) -> None:
    settings = get_settings()
    now = utcnow()
    offline_after = timedelta(seconds=settings.offline_after_seconds)
    agents = (await db.execute(select(Agent).where(Agent.status == AgentStatus.ACTIVE.value))).scalars().all()
    for agent in agents:
        machine = await db.get(Machine, agent.machine_id)
        if not machine:
            continue
        if agent.last_heartbeat_at is None:
            if machine.status != MachineStatus.NEVER_CONNECTED.value:
                machine.status = MachineStatus.NEVER_CONNECTED.value
            continue
        age = now - agent.last_heartbeat_at
        if age > offline_after:
            if machine.status != MachineStatus.OFFLINE.value:
                await record_status_event(db, machine, MachineStatus.OFFLINE.value)
                machine.status = MachineStatus.OFFLINE.value
