from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AgentLog, AuditLog, GpuMetricSample, MetricHourly, MetricSample, utcnow


async def rollup_and_prune(db: AsyncSession) -> dict[str, int]:
    settings = get_settings()
    now = utcnow()
    raw_cut = now - timedelta(days=settings.metrics_raw_retention_days)
    hourly_cut = now - timedelta(days=settings.metrics_hourly_retention_days)

    window_start = now - timedelta(hours=48)
    samples = (
        await db.execute(select(MetricSample).where(MetricSample.collected_at >= window_start))
    ).scalars().all()
    buckets: dict[tuple, dict] = {}
    for s in samples:
        hour = s.collected_at.replace(minute=0, second=0, microsecond=0)
        key = (s.machine_id, hour)
        b = buckets.setdefault(
            key,
            {
                "count": 0,
                "cpu_usage": [],
                "cpu_temp": [],
                "ram_usage": [],
                "net_tx": [],
                "net_rx": [],
            },
        )
        b["count"] += 1
        if s.cpu_usage_pct is not None:
            b["cpu_usage"].append(s.cpu_usage_pct)
        if s.cpu_temp_c is not None:
            b["cpu_temp"].append(s.cpu_temp_c)
        if s.ram_usage_pct is not None:
            b["ram_usage"].append(s.ram_usage_pct)
        if s.net_tx_bps is not None:
            b["net_tx"].append(s.net_tx_bps)
        if s.net_rx_bps is not None:
            b["net_rx"].append(s.net_rx_bps)

    written = 0
    for (machine_id, hour), b in buckets.items():
        existing = (
            await db.execute(
                select(MetricHourly).where(MetricHourly.machine_id == machine_id, MetricHourly.hour_start == hour)
            )
        ).scalar_one_or_none()
        values = {
            "cpu_usage_avg": sum(b["cpu_usage"]) / len(b["cpu_usage"]) if b["cpu_usage"] else None,
            "cpu_usage_max": max(b["cpu_usage"]) if b["cpu_usage"] else None,
            "cpu_temp_avg": sum(b["cpu_temp"]) / len(b["cpu_temp"]) if b["cpu_temp"] else None,
            "cpu_temp_max": max(b["cpu_temp"]) if b["cpu_temp"] else None,
            "ram_usage_avg": sum(b["ram_usage"]) / len(b["ram_usage"]) if b["ram_usage"] else None,
            "ram_usage_max": max(b["ram_usage"]) if b["ram_usage"] else None,
            "net_tx_avg": sum(b["net_tx"]) / len(b["net_tx"]) if b["net_tx"] else None,
            "net_rx_avg": sum(b["net_rx"]) / len(b["net_rx"]) if b["net_rx"] else None,
        }
        if existing:
            existing.sample_count = b["count"]
            existing.values = values
        else:
            db.add(MetricHourly(machine_id=machine_id, hour_start=hour, sample_count=b["count"], values=values))
            written += 1

    deleted_raw = (await db.execute(delete(MetricSample).where(MetricSample.collected_at < raw_cut))).rowcount or 0
    deleted_gpu = (await db.execute(delete(GpuMetricSample).where(GpuMetricSample.collected_at < raw_cut))).rowcount or 0
    deleted_hourly = (await db.execute(delete(MetricHourly).where(MetricHourly.hour_start < hourly_cut))).rowcount or 0
    deleted_agent_logs = 0
    if settings.agent_log_retention_days:
        cut = now - timedelta(days=settings.agent_log_retention_days)
        deleted_agent_logs = (await db.execute(delete(AgentLog).where(AgentLog.created_at < cut))).rowcount or 0
    deleted_audit = 0
    if settings.audit_log_retention_days:
        cut = now - timedelta(days=settings.audit_log_retention_days)
        deleted_audit = (await db.execute(delete(AuditLog).where(AuditLog.created_at < cut))).rowcount or 0
    await db.flush()
    return {
        "hourly_written": written,
        "deleted_raw": deleted_raw,
        "deleted_gpu": deleted_gpu,
        "deleted_hourly": deleted_hourly,
        "deleted_agent_logs": deleted_agent_logs,
        "deleted_audit": deleted_audit,
    }
