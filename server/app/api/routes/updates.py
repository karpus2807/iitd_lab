from pydantic import BaseModel, Field

from app.api.deps import AdminUser, DbDep, write_audit
from app.services import updates as update_svc
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/admin", tags=["updates"])


class ApplyBuildBody(BaseModel):
    tag: str = Field(min_length=2, max_length=64)


class FetchBuildsBody(BaseModel):
    proxy_user: str = ""
    proxy_password: str = ""


@router.get("/updates")
async def list_updates(admin: AdminUser):
    return await update_svc.list_builds(live=False)


@router.post("/updates/fetch")
async def fetch_updates(body: FetchBuildsBody, db: DbDep, admin: AdminUser, request: Request):
    user = (body.proxy_user or "").strip()
    password = body.proxy_password or ""
    if not user or not password:
        raise HTTPException(400, "Proxy username and password are required")
    catalog = await update_svc.list_builds(live=True, proxy_user=user, proxy_password=password)
    await write_audit(
        db,
        "server.update.fetch",
        user=admin,
        details={"proxy_user": user, "source": catalog.get("source")},
        request=request,
    )
    await db.commit()
    return catalog


@router.get("/updates/status")
async def update_status(admin: AdminUser):
    return {
        "current": {"version": update_svc.current_version(), "tag": update_svc.current_tag()},
        "apply_ready": update_svc.apply_ready(),
        "status": update_svc.read_status(),
    }


@router.post("/updates/apply")
async def apply_build(body: ApplyBuildBody, db: DbDep, admin: AdminUser, request: Request):
    allowed = update_svc.allowed_tags_from_cache()
    if not allowed:
        raise HTTPException(400, "Fetch GitHub releases first")
    catalog = update_svc.cached_catalog()
    try:
        status = update_svc.start_apply(body.tag, admin.username, allowed_tags=allowed)
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
