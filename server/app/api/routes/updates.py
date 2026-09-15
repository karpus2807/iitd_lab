from pydantic import BaseModel, Field

from app.api.deps import AdminUser, DbDep, write_audit
from app.services import updates as update_svc
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/admin", tags=["updates"])


class ApplyBuildBody(BaseModel):
    tag: str = Field(min_length=2, max_length=64)


@router.get("/updates")
async def list_updates(admin: AdminUser):
    return await update_svc.list_builds()


@router.get("/updates/status")
async def update_status(admin: AdminUser):
    return {
        "current": {"version": update_svc.current_version(), "tag": update_svc.current_tag()},
        "apply_ready": update_svc.apply_ready(),
        "status": update_svc.read_status(),
    }


@router.post("/updates/apply")
async def apply_build(body: ApplyBuildBody, db: DbDep, admin: AdminUser, request: Request):
    catalog = await update_svc.list_builds()
    allowed = {b["tag"] for b in catalog.get("builds") or []}
    try:
        status = update_svc.start_apply(body.tag, admin.username, allowed_tags=allowed or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(403, str(exc)) from exc
    await write_audit(
        db,
        "server.update.apply",
        user=admin,
        details={"tag": update_svc.normalize_tag(body.tag), "state": status.get("state")},
        request=request,
    )
    await db.commit()
    return {"ok": True, "status": status, "builds": catalog.get("builds")}
