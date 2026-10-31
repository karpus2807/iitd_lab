"""Import/export activity reports + retention clear."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbDep, OperatorUser, write_audit
from app.services import op_reports as svc

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
async def list_op_reports(
    db: DbDep,
    user: CurrentUser,
    area: str = Query(default="scholars"),
    action: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    rows, total = await svc.list_reports(db, area=area, action=action, limit=limit, offset=offset)
    return {
        "items": [svc.report_out(r, include_rows=False) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{report_id}")
async def get_op_report(report_id: UUID, db: DbDep, user: CurrentUser):
    row = await svc.get_report(db, report_id)
    if not row:
        raise HTTPException(404, "Report not found")
    return svc.report_out(row, include_rows=True)


class ClearReportsBody(BaseModel):
    # 0 / null = clear all; else delete reports older than N days
    older_than_days: int | None = Field(default=0, ge=0, le=3650)


@router.post("/clear")
async def clear_op_reports(
    body: ClearReportsBody,
    db: DbDep,
    user: OperatorUser,
    request: Request,
):
    days = body.older_than_days
    deleted = await svc.clear_reports(db, older_than_days=days)
    await write_audit(
        db,
        "reports.clear",
        user=user,
        details={"deleted": deleted, "older_than_days": days or 0},
        request=request,
    )
    await db.commit()
    return {"ok": True, "deleted": deleted, "older_than_days": days or 0}
