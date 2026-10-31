"""Persist detailed import/export/activity reports for the UI Logs tab."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OpReport, User, utcnow


def _ip(request) -> str | None:  # noqa: ANN001
    if request is None:
        return None
    return request.client.host if request.client else None


async def create_report(
    db: AsyncSession,
    *,
    area: str,
    action: str,
    user: User | None = None,
    filename: str = "",
    summary: dict | None = None,
    rows: list[dict] | None = None,
    request=None,  # noqa: ANN001
) -> OpReport:
    report = OpReport(
        area=(area or "system").strip().lower()[:32],
        action=(action or "activity").strip().lower()[:64],
        filename=(filename or "")[:255],
        username=(user.username if user else "") or "",
        user_id=user.id if user else None,
        summary=summary or {},
        rows=list(rows or []),
        ip_address=_ip(request),
    )
    db.add(report)
    await db.flush()
    return report


def report_out(row: OpReport, *, include_rows: bool = True) -> dict[str, Any]:
    out = {
        "id": str(row.id),
        "created_at": row.created_at,
        "area": row.area,
        "action": row.action,
        "filename": row.filename or "",
        "username": row.username or "",
        "summary": row.summary or {},
        "ip_address": row.ip_address,
        "row_count": len(row.rows or []),
    }
    if include_rows:
        out["rows"] = row.rows or []
    return out


async def list_reports(
    db: AsyncSession,
    *,
    area: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[OpReport], int]:
    from sqlalchemy import func

    filters = []
    if area and area != "all":
        filters.append(OpReport.area == area)
    if action and action != "all":
        filters.append(OpReport.action == action)
    count_q = select(func.count()).select_from(OpReport)
    stmt = select(OpReport).order_by(OpReport.created_at.desc())
    if filters:
        count_q = count_q.where(*filters)
        stmt = stmt.where(*filters)
    total = (await db.execute(count_q)).scalar_one()
    rows = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    return list(rows), int(total or 0)


async def get_report(db: AsyncSession, report_id: UUID) -> OpReport | None:
    return await db.get(OpReport, report_id)


async def clear_reports(db: AsyncSession, *, older_than_days: int | None) -> int:
    """Delete reports. older_than_days=None/0 → all; else older than N days."""
    if not older_than_days or older_than_days <= 0:
        deleted = (await db.execute(delete(OpReport))).rowcount or 0
        return int(deleted)
    cut = utcnow() - timedelta(days=int(older_than_days))
    deleted = (await db.execute(delete(OpReport).where(OpReport.created_at < cut))).rowcount or 0
    return int(deleted)
