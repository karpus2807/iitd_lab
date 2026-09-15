from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentAgent, DbDep
from app.config import get_settings
from app.enums import AgentStatus, EventType, MachineStatus
from app.models import (
    Agent,
    AgentLog,
    HardwareEvent,
    Lab,
    Machine,
    RegistrationToken,
    utcnow,
)
from app.schemas.inventory import (
    AgentEventPayload,
    AgentLogPayload,
    HeartbeatPayload,
    IdentityInfo,
    InventoryPayload,
    MetricsPayload,
)
from app.security import hash_token, identity_fingerprint, new_secret, token_matches
from app.services.heartbeat import apply_heartbeat, apply_reported_addresses
from app.services.inventory import persist_inventory
from app.models import GpuMetricSample, MetricSample

router = APIRouter(prefix="/api/agents", tags=["agents"])


class RegisterRequest(BaseModel):
    registration_token: str
    identity: IdentityInfo
    agent_uuid: str = Field(min_length=8)
    agent_version: str = ""


class RegisterResponse(BaseModel):
    machine_id: str
    agent_id: str
    agent_secret: str
    approved: bool
    heartbeat_interval: int
    metric_interval: int
    inventory_interval: int


async def _valid_token(db, raw: str) -> RegistrationToken:
    tokens = (await db.execute(select(RegistrationToken).where(RegistrationToken.revoked.is_(False)))).scalars().all()
    now = utcnow()
    for tok in tokens:
        if not token_matches(raw, tok.token_hash):
            continue
        if tok.expires_at and tok.expires_at < now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Registration token expired")
        if tok.max_uses is not None and tok.use_count >= tok.max_uses:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Registration token exhausted")
        return tok
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid registration token")


async def _match_machine(db, identity: IdentityInfo, agent_uuid: str) -> Machine | None:
    """Resolve a returning host without using IP address.

    Order: persistent agent UUID, then SMBIOS/system UUID fingerprint,
    then system UUID / machine UUID. DHCP or LAN switches must not create
    a second machine row.
    """
    agent = (await db.execute(select(Agent).where(Agent.agent_public_id == agent_uuid))).scalar_one_or_none()
    if agent:
        return await db.get(Machine, agent.machine_id)
    fp = identity_fingerprint(
        [identity.system_uuid, identity.machine_uuid, identity.motherboard_serial, identity.system_serial]
    )
    if identity.system_uuid or identity.machine_uuid or identity.motherboard_serial:
        found = (
            await db.execute(select(Machine).where(Machine.identity_fingerprint == fp))
        ).scalar_one_or_none()
        if found:
            return found
    if identity.system_uuid:
        found = (await db.execute(select(Machine).where(Machine.system_uuid == identity.system_uuid))).scalar_one_or_none()
        if found:
            return found
    if identity.machine_uuid:
        found = (await db.execute(select(Machine).where(Machine.machine_uuid == identity.machine_uuid))).scalar_one_or_none()
        if found:
            return found
    return None


@router.post("/register", response_model=RegisterResponse)
async def register_agent(body: RegisterRequest, db: DbDep):
    settings = get_settings()
    token = await _valid_token(db, body.registration_token)
    identity = body.identity
    machine = await _match_machine(db, identity, body.agent_uuid)
    created = False
    if machine is None:
        fp = identity_fingerprint(
            [identity.system_uuid, identity.machine_uuid, identity.motherboard_serial, identity.system_serial, body.agent_uuid]
        )
        lab_id = token.lab_id
        if lab_id is None:
            lab = (
                await db.execute(select(Lab).where(func.lower(Lab.name) == "unassigned"))
            ).scalars().first()
            if lab is None:
                lab = (await db.execute(select(Lab).order_by(Lab.created_at.asc()))).scalars().first()
            lab_id = lab.id if lab else None
        machine = Machine(
            lab_id=lab_id,
            hostname=identity.hostname,
            display_name=identity.hostname,
            os_name=identity.os_name,
            os_version=identity.os_version,
            kernel_version=identity.kernel_version or "",
            architecture=identity.architecture,
            machine_uuid=identity.machine_uuid,
            system_uuid=identity.system_uuid or identity.bios_uuid,
            motherboard_serial=identity.motherboard_serial,
            system_serial=identity.system_serial,
            is_virtual=identity.is_virtual,
            virtualization=identity.virtualization,
            status=MachineStatus.NEVER_CONNECTED.value,
            approved=not settings.require_agent_approval,
            identity_fingerprint=fp,
        )
        db.add(machine)
        await db.flush()
        created = True
        db.add(
            HardwareEvent(
                machine_id=machine.id,
                event_type=EventType.MACHINE_REGISTERED.value,
                severity="INFO",
                summary=f"Machine registered ({identity.hostname})",
                detected_by="SERVER",
            )
        )
    else:
        existing_agent = (await db.execute(select(Agent).where(Agent.machine_id == machine.id))).scalar_one_or_none()
        if existing_agent and existing_agent.status == AgentStatus.REVOKED.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent revoked; ask an administrator to re-enable it")

    secret = new_secret(32)
    agent = (await db.execute(select(Agent).where(Agent.machine_id == machine.id))).scalar_one_or_none()
    status_value = AgentStatus.PENDING.value if settings.require_agent_approval and not machine.approved else AgentStatus.ACTIVE.value
    if agent:
        agent.secret_hash = hash_token(secret)
        agent.agent_public_id = body.agent_uuid
        agent.agent_version = body.agent_version
        agent.status = status_value
        agent.registration_token_id = token.id
        agent.revoked_at = None
    else:
        agent = Agent(
            machine_id=machine.id,
            agent_public_id=body.agent_uuid,
            secret_hash=hash_token(secret),
            status=status_value,
            agent_version=body.agent_version,
            registration_token_id=token.id,
        )
        db.add(agent)
    token.use_count += 1
    machine.approved = machine.approved or not settings.require_agent_approval
    await db.commit()
    return RegisterResponse(
        machine_id=str(machine.id),
        agent_id=body.agent_uuid,
        agent_secret=secret,
        approved=machine.approved,
        heartbeat_interval=settings.heartbeat_interval_seconds,
        metric_interval=settings.heartbeat_interval_seconds,
        inventory_interval=300,
    )


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatPayload, db: DbDep, agent: CurrentAgent):
    machine = await db.get(Machine, agent.machine_id)
    if not machine or not machine.approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Machine not approved")
    agent.agent_version = body.agent_version or agent.agent_version
    agent.health = body.status
    if body.hostname:
        machine.hostname = body.hostname
        if not machine.display_name:
            machine.display_name = body.hostname
    if body.ip_addresses:
        apply_reported_addresses(machine, body.ip_addresses, db)
    await apply_heartbeat(db, machine, agent, healthy=body.status == "healthy")
    if body.collector_errors:
        db.add(
            AgentLog(
                machine_id=machine.id,
                level="WARNING",
                message="Collector errors reported",
                details={"errors": body.collector_errors},
            )
        )
    await db.commit()
    return {"ok": True, "server_time": utcnow().isoformat(), "status": machine.status}


@router.post("/inventory")
async def inventory(body: InventoryPayload, db: DbDep, agent: CurrentAgent):
    machine = await db.get(Machine, agent.machine_id)
    if not machine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
    events = await persist_inventory(db, machine, body)
    agent.last_inventory_at = utcnow()
    await db.commit()
    return {"ok": True, "events": len(events)}


@router.post("/metrics")
async def metrics(body: MetricsPayload, db: DbDep, agent: CurrentAgent):
    from app.services.alerts import evaluate_metrics

    machine = await db.get(Machine, agent.machine_id)
    if not machine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
    collected = body.collected_at or utcnow()
    db.add(
        MetricSample(
            machine_id=machine.id,
            collected_at=collected,
            cpu_usage_pct=body.cpu_usage_pct,
            cpu_temp_c=body.cpu_temp_c,
            cpu_freq_mhz=body.cpu_freq_mhz,
            ram_used_bytes=body.ram_used_bytes,
            ram_total_bytes=body.ram_total_bytes,
            ram_available_bytes=body.ram_available_bytes,
            ram_usage_pct=body.ram_usage_pct,
            disk_read_bps=body.disk_read_bps,
            disk_write_bps=body.disk_write_bps,
            disk_used_bytes=body.disk_used_bytes,
            disk_total_bytes=body.disk_total_bytes,
            net_tx_bps=body.net_tx_bps,
            net_rx_bps=body.net_rx_bps,
        )
    )
    for gpu in body.gpus:
        db.add(
            GpuMetricSample(
                machine_id=machine.id,
                gpu_index=gpu.index,
                gpu_key=gpu.gpu_key,
                collected_at=collected,
                utilization_pct=gpu.utilization_pct,
                temperature_c=gpu.temperature_c,
                vram_used_bytes=gpu.vram_used_bytes,
                vram_total_bytes=gpu.vram_total_bytes,
                power_w=gpu.power_w,
                graphics_clock_mhz=gpu.graphics_clock_mhz,
                memory_clock_mhz=gpu.memory_clock_mhz,
            )
        )
    agent.last_metrics_at = utcnow()
    disk_pct = None
    if body.disk_total_bytes and body.disk_used_bytes is not None and body.disk_total_bytes > 0:
        disk_pct = 100.0 * body.disk_used_bytes / body.disk_total_bytes
    gpu_temp = max((g.temperature_c for g in body.gpus if g.temperature_c is not None), default=None)
    await evaluate_metrics(
        db,
        machine,
        {
            "cpu_temp_c": body.cpu_temp_c,
            "gpu_temp_c": gpu_temp,
            "ram_usage_pct": body.ram_usage_pct,
            "disk_usage_pct": disk_pct,
            "cpu_usage_pct": body.cpu_usage_pct,
        },
    )
    await db.commit()
    return {"ok": True}


@router.post("/events")
async def events(items: list[AgentEventPayload], db: DbDep, agent: CurrentAgent):
    for item in items:
        db.add(
            HardwareEvent(
                machine_id=agent.machine_id,
                event_type=item.event_type,
                severity=item.severity,
                component_path=item.component_path,
                previous_value=item.previous_value,
                new_value=item.new_value,
                summary=item.summary,
                detected_by="AGENT",
                created_at=item.created_at or utcnow(),
            )
        )
    await db.commit()
    return {"ok": True, "accepted": len(items)}


@router.post("/logs")
async def logs(items: list[AgentLogPayload], db: DbDep, agent: CurrentAgent):
    for item in items:
        db.add(
            AgentLog(
                machine_id=agent.machine_id,
                level=item.level,
                message=item.message,
                details=item.details,
                created_at=item.created_at or utcnow(),
            )
        )
    await db.commit()
    return {"ok": True, "accepted": len(items)}
