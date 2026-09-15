from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AlertSeverity
from app.models import Alert, AlertRule, Machine
from app.schemas.inventory import DiffEvent, GPUInfo, InventoryPayload, MemoryInfo, MemoryModule
from app.services.alerts import DEFAULT_RULES, evaluate_hardware_events, evaluate_metrics, record_status_event, seed_default_rules
from app.services.diff import diff_inventory


def ram(locator, gb):
    if gb is None:
        return MemoryModule(slot_locator=locator, occupied=False)
    return MemoryModule(slot_locator=locator, occupied=True, capacity_bytes=gb * 1024**3, manufacturer="Samsung", serial_number=f"S{locator}")


async def test_metric_alert_opens_and_resolves(db_session: AsyncSession):
    await seed_default_rules(db_session)
    machine = Machine(hostname="LAB-PC-001", display_name="LAB-PC-001")
    db_session.add(machine)
    await db_session.flush()
    await evaluate_metrics(db_session, machine, {"cpu_temp_c": 95})
    await db_session.flush()
    from sqlalchemy import select

    alerts = (await db_session.execute(select(Alert).where(Alert.machine_id == machine.id))).scalars().all()
    assert alerts
    assert machine.has_open_alerts
    await evaluate_metrics(db_session, machine, {"cpu_temp_c": 40})
    await db_session.flush()
    alerts = (await db_session.execute(select(Alert).where(Alert.machine_id == machine.id))).scalars().all()
    assert all(a.status == "RESOLVED" for a in alerts if a.event_type is None)


async def test_offline_events_not_duplicated(db_session: AsyncSession):
    machine = Machine(hostname="LAB-PC-002", status="ONLINE")
    db_session.add(machine)
    await db_session.flush()
    e1 = await record_status_event(db_session, machine, "OFFLINE")
    machine.status = "OFFLINE"
    e2 = await record_status_event(db_session, machine, "OFFLINE")
    assert e1 is not None
    assert e2 is None
    e3 = await record_status_event(db_session, machine, "ONLINE")
    assert e3 is not None


async def test_hardware_event_creates_gpu_removed_alert(db_session: AsyncSession):
    await seed_default_rules(db_session)
    machine = Machine(hostname="LAB-PC-042")
    db_session.add(machine)
    await db_session.flush()
    before = InventoryPayload(gpus=[GPUInfo(index=0, model="RTX 3090", pci_bus="0000:02:00.0", slot_designation="Slot 2")])
    after = InventoryPayload(gpus=[])
    events = diff_inventory(before, after)
    await evaluate_hardware_events(db_session, machine, events)
    await db_session.flush()
    from sqlalchemy import select

    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert any("GPU" in a.title or "GPU" in a.message for a in alerts)
