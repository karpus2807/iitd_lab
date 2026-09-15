from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import AdminUser, DbDep
from app.models import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit(db: DbDep, admin: AdminUser, action: str | None = None, limit: int = Query(200, le=1000)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at,
            "username": r.username,
            "action": r.action,
            "details": r.details,
            "ip_address": r.ip_address,
            "machine_id": str(r.machine_id) if r.machine_id else None,
        }
        for r in rows
    ]
