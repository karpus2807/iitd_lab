from pydantic import BaseModel, Field

from app.api.deps import AdminUser, DbDep, write_audit
from app.services import updates as update_svc
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/admin", tags=["updates"])


class ApplyBuildBody(BaseModel):
    tag: str = Field(min_length=2, max_length=64)
    force: bool = False


class FetchBuildsBody(BaseModel):
    proxy_user: str = ""
    proxy_password: str = ""


class CancelUpdateBody(BaseModel):
    reason: str = ""


@router.get("/updates")
async def list_updates(admin: AdminUser):
    """Auto-fetch GitHub releases without proxy when the network allows it."""
    catalog = await update_svc.list_builds(live=True)
    return catalog


@router.post("/updates/fetch")
async def fetch_updates(body: FetchBuildsBody, db: DbDep, admin: AdminUser, request: Request):
    user = (body.proxy_user or "").strip()
    password = body.proxy_password or ""
    # Proxy credentials optional: empty → try direct; with user → campus proxy.
    if user and not password:
        raise HTTPException(400, "Proxy password is required when a proxy username is set")
    catalog = await update_svc.list_builds(live=True, proxy_user=user or None, proxy_password=password or None)
    await write_audit(
        db,
        "server.update.fetch",
        user=admin,
        details={
            "proxy_user": user or None,
            "used_proxy": catalog.get("used_proxy"),
            "source": catalog.get("source"),
        },
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
        status = update_svc.start_apply(
            body.tag,
            admin.username,
            allowed_tags=allowed,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    await write_audit(
        db,
        "server.update.apply",
        user=admin,
        details={
            "tag": update_svc.normalize_tag(body.tag),
            "state": status.get("state"),
            "force": body.force,
        },
        request=request,
    )
    await db.commit()
    return {"ok": True, "status": status, "builds": catalog.get("builds")}


@router.post("/updates/cancel")
async def cancel_update(body: CancelUpdateBody, db: DbDep, admin: AdminUser, request: Request):
    status = update_svc.cancel_apply(admin.username, reason=body.reason.strip() or None)
    await write_audit(
        db,
        "server.update.cancel",
        user=admin,
        details={"state": status.get("state"), "tag": status.get("tag"), "message": status.get("message")},
        request=request,
    )
    await db.commit()
    return {"ok": True, "status": status}
