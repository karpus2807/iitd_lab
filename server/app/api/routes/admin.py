from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import __version__ as server_version
from app.api.deps import AdminUser, DbDep, write_audit
from app.config import get_settings
from app.enums import AgentStatus
from app.models import Agent, Lab, Machine, NotificationChannelConfig, RefreshToken, RegistrationToken, User, utcnow
from app.schemas.api import RegistrationTokenCreate, UserCreate, UserOut, UserUpdate
from app.security import hash_password, hash_token, new_secret
from app.services.agent_pack import agent_pack_version, version_tuple as _version_tuple

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Agents below this version ignore heartbeat commands[] — one manual reinstall first.
REMOTE_UPDATE_MIN = (1, 1, 40)


_UPDATE_ACTIVE = frozenset({"queued", "sent", "running", "downloading", "applying"})
_UPDATE_PROGRESS = {
    "queued": 12,
    "sent": 35,
    "downloading": 55,
    "running": 70,
    "applying": 85,
    "ok": 100,
    "error": 0,
    "cancelled": 0,
}


def _update_progress(status: str) -> int | None:
    key = (status or "").strip().lower()
    if not key:
        return None
    return _UPDATE_PROGRESS.get(key)


def _remote_update_capable(agent_version: str) -> bool:
    return _version_tuple(agent_version) >= REMOTE_UPDATE_MIN


class AgentUpdateBody(BaseModel):
    agent_ids: list[UUID] = Field(default_factory=list)


async def _active_admin_count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(User).where(User.role == "ADMIN", User.is_active.is_(True)))
    ).scalar_one()


@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbDep, admin: AdminUser):
    return (await db.execute(select(User).order_by(User.username))).scalars().all()


@router.post("/users", response_model=UserOut)
async def create_user(body: UserCreate, db: DbDep, admin: AdminUser, request: Request):
    if (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none():
        raise HTTPException(409, "Username taken")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    await write_audit(db, "user.create", user=admin, details={"username": body.username, "role": body.role}, request=request)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: UUID, body: UserUpdate, db: DbDep, admin: AdminUser, request: Request):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = body.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        user.password_hash = hash_password(data.pop("password"))
    if "username" in data and data["username"]:
        name = data["username"].strip()
        clash = (
            await db.execute(select(User).where(User.username == name, User.id != user.id))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(409, "Username taken")
        user.username = name
        data.pop("username")
    if "email" in data and data["email"]:
        clash = (
            await db.execute(select(User).where(User.email == data["email"], User.id != user.id))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(409, "Email taken")
    if "role" in data and data["role"] and data["role"] != "ADMIN" and user.role == "ADMIN":
        if await _active_admin_count(db) <= 1:
            raise HTTPException(400, "Cannot demote the last administrator")
    if "is_active" in data and data["is_active"] is False and user.role == "ADMIN":
        if await _active_admin_count(db) <= 1:
            raise HTTPException(400, "Cannot disable the last administrator")
    for k, v in data.items():
        setattr(user, k, v)
    await write_audit(db, "user.update", user=admin, details={"target": user.username}, request=request)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}")
async def delete_user(user_id: UUID, db: DbDep, admin: AdminUser, request: Request):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "You cannot delete your own account")
    if user.role == "ADMIN" and await _active_admin_count(db) <= 1:
        raise HTTPException(400, "Cannot delete the last administrator")
    name = user.username
    tokens = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalars().all()
    for row in tokens:
        await db.delete(row)
    await db.delete(user)
    await write_audit(db, "user.delete", user=admin, details={"username": name}, request=request)
    await db.commit()
    return {"ok": True}


@router.post("/tokens")
async def create_token(body: RegistrationTokenCreate, db: DbDep, admin: AdminUser, request: Request):
    raw = "lw_" + new_secret(24)
    expires = utcnow() + timedelta(hours=body.expires_hours) if body.expires_hours else None
    row = RegistrationToken(
        token_hash=hash_token(raw),
        token_prefix=raw[:10],
        label=body.label,
        lab_id=body.lab_id,
        created_by_id=admin.id,
        expires_at=expires,
        max_uses=body.max_uses,
    )
    db.add(row)
    await write_audit(db, "token.create", user=admin, details={"label": body.label}, request=request)
    await db.commit()
    await db.refresh(row)
    return {
        "id": str(row.id),
        "token": raw,
        "prefix": row.token_prefix,
        "label": row.label,
        "lab_id": str(row.lab_id) if row.lab_id else None,
        "expires_at": row.expires_at,
        "max_uses": row.max_uses,
        "note": "Store this token now; it will not be shown again.",
    }


def _token_status(row: RegistrationToken) -> str:
    now = utcnow()
    if row.revoked:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= now:
        return "expired"
    if row.max_uses is not None and int(row.use_count or 0) >= int(row.max_uses):
        return "exhausted"
    if int(row.use_count or 0) > 0:
        return "used"
    return "unused"


@router.get("/tokens")
async def list_tokens(db: DbDep, admin: AdminUser):
    settings = get_settings()
    # Opportunistic cleanup when admin opens Tokens (hourly job also runs this).
    from app.services.retention import prune_unused_registration_tokens

    await prune_unused_registration_tokens(db)
    await db.commit()

    rows = (await db.execute(select(RegistrationToken).order_by(RegistrationToken.created_at.desc()))).scalars().all()
    counts: dict[str, int] = {}
    if rows:
        ids = [r.id for r in rows]
        enrolled = (
            await db.execute(
                select(Agent.registration_token_id, func.count())
                .where(Agent.registration_token_id.in_(ids))
                .group_by(Agent.registration_token_id)
            )
        ).all()
        counts = {str(tid): int(n) for tid, n in enrolled if tid}

    auto_days = settings.unused_registration_token_days
    now = utcnow()
    out = []
    for r in rows:
        status = _token_status(r)
        unused_deletes_at = None
        unused_deletes_in_hours = None
        if status == "unused" and auto_days > 0 and r.created_at:
            unused_deletes_at = r.created_at + timedelta(days=auto_days)
            secs = (unused_deletes_at - now).total_seconds()
            unused_deletes_in_hours = max(0, int(secs // 3600))
        out.append(
            {
                "id": str(r.id),
                "prefix": r.token_prefix,
                "label": r.label,
                "lab_id": str(r.lab_id) if r.lab_id else None,
                "expires_at": r.expires_at,
                "max_uses": r.max_uses,
                "use_count": r.use_count,
                "last_used_at": r.last_used_at,
                "enrolled_agents": counts.get(str(r.id), 0),
                "status": status,
                "revoked": r.revoked,
                "created_at": r.created_at,
                "unused_auto_delete_days": auto_days,
                "unused_deletes_at": unused_deletes_at,
                "unused_deletes_in_hours": unused_deletes_in_hours,
            }
        )
    return out


@router.post("/tokens/{token_id}/revoke")
async def revoke_token(token_id: UUID, db: DbDep, admin: AdminUser, request: Request):
    row = await db.get(RegistrationToken, token_id)
    if not row:
        raise HTTPException(404, "Token not found")
    row.revoked = True
    await write_audit(db, "token.revoke", user=admin, details={"id": str(token_id)}, request=request)
    await db.commit()
    return {"ok": True}


@router.get("/agents")
async def list_agents(db: DbDep, admin: AdminUser):
    # Compare to shipped agent pack — not LabWatch UI/API VERSION.
    pack = agent_pack_version()
    pack_t = _version_tuple(pack)
    rows = (await db.execute(select(Agent, Machine).join(Machine, Agent.machine_id == Machine.id))).all()
    # Drop timed-out in-flight updates so a leftover fleet queue does not look live.
    _expire_stale_updates([a for a, _m in rows])
    await db.commit()
    agents = []
    for a, m in rows:
        ver = a.agent_version or ""
        ver_t = _version_tuple(ver) if ver else (0, 0, 0)
        update_available = bool(ver) and ver_t < pack_t
        up_to_date = bool(ver) and ver_t >= pack_t
        display_status = a.update_status or ""
        if up_to_date and display_status.lower() == "ok":
            display_status = ""
        agents.append(
            {
                "id": str(a.id),
                "agent_id": a.agent_public_id,
                "machine_id": str(m.id),
                "hostname": m.hostname,
                "inventory_id": m.inventory_id or "",
                "status": a.status,
                "health": a.health,
                "version": ver,
                "last_heartbeat_at": a.last_heartbeat_at,
                "approved": m.approved,
                "update_status": display_status,
                "update_message": (a.update_message or "") if display_status else "",
                "update_target_version": a.update_target_version or "",
                "update_requested_at": a.update_requested_at,
                "update_progress": _update_progress(display_status),
                "update_active": (a.update_status or "").lower() in _UPDATE_ACTIVE,
                "update_failed": (a.update_status or "").lower() in {"error", "cancelled"},
                "remote_update_capable": _remote_update_capable(ver),
                "update_available": update_available,
                "up_to_date": up_to_date,
                "current_version": pack,
                "agent_pack_version": pack,
                "server_version": server_version,
            }
        )
    active = [x for x in agents if x["update_active"]]
    failed = [x for x in agents if x["update_failed"]]
    finished_ok = [x for x in agents if (x.get("update_status") or "").lower() == "ok"]
    job_total = len(active) + len(failed) + len(
        [x for x in finished_ok if x.get("update_requested_at")]
    )
    # Live job snapshot for the Admin Agents progress panel.
    tracked = active + failed
    if active or failed:
        pcts = [int(x["update_progress"] or 0) for x in active]
        if active:
            progress = round(sum(pcts) / len(pcts)) if pcts else 0
        elif failed and not active:
            progress = 0
        else:
            progress = 0
        done_n = len([x for x in finished_ok if x.get("update_target_version")])
        update_job = {
            "active": bool(active),
            "state": "error" if failed and not active else ("running" if active else "idle"),
            "progress": progress if active else (100 if not failed else 0),
            "queued": len([x for x in active if x["update_status"] == "queued"]),
            "in_flight": len(active),
            "failed": len(failed),
            "done": done_n,
            "total": max(len(tracked), job_total),
            "target_version": next(
                (x.get("update_target_version") for x in active + failed + finished_ok if x.get("update_target_version")),
                pack,
            ),
            "message": (
                f"{len(active)} updating · {len(failed)} failed"
                if active or failed
                else ""
            ),
            "errors": [
                {
                    "id": x["id"],
                    "hostname": x["hostname"],
                    "message": x.get("update_message") or x.get("update_status") or "error",
                }
                for x in failed[:20]
            ],
        }
    else:
        update_job = {
            "active": False,
            "state": "idle",
            "progress": None,
            "queued": 0,
            "in_flight": 0,
            "failed": 0,
            "done": 0,
            "total": 0,
            "target_version": pack,
            "message": "",
            "errors": [],
        }
    return {
        "current_version": pack,
        "agent_pack_version": pack,
        "server_version": server_version,
        "agents": agents,
        "update_job": update_job,
    }


# Queued/sent updates older than this are marked error so a prior batch
# cannot look like a new "update all" run.
_UPDATE_STALE_AFTER = timedelta(minutes=45)


def _queue_agent_update(agent: Agent, target_version: str) -> None:
    agent.update_status = "queued"
    agent.update_requested_at = utcnow()
    agent.update_command_id = str(uuid4())
    agent.update_message = "waiting for agent heartbeat"
    agent.update_target_version = target_version


def _expire_stale_updates(agents: list[Agent]) -> None:
    now = utcnow()
    for agent in agents:
        st = (agent.update_status or "").lower()
        if st not in _UPDATE_ACTIVE:
            continue
        started = agent.update_requested_at
        if not started:
            continue
        try:
            age = now - started
        except TypeError:
            age = now.replace(tzinfo=None) - started.replace(tzinfo=None)
        if age > _UPDATE_STALE_AFTER:
            agent.update_status = "error"
            agent.update_message = "update timed out (stale) — re-queue this agent only"


@router.post("/agents/update")
async def queue_agent_updates(body: AgentUpdateBody, db: DbDep, admin: AdminUser, request: Request):
    """Queue updates for the given agent IDs only (never auto-selects the fleet).

    Target is the current agent pack version (labwatch_agent.__version__), one jump.
    """
    if not body.agent_ids:
        raise HTTPException(400, "Select at least one agent")
    # De-dupe while preserving order
    seen: set[UUID] = set()
    ids: list[UUID] = []
    for agent_id in body.agent_ids:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        ids.append(agent_id)
    target = agent_pack_version()
    target_t = _version_tuple(target)
    queued: list[str] = []
    skipped: list[dict] = []
    for agent_id in ids:
        agent = await db.get(Agent, agent_id)
        if not agent:
            skipped.append({"id": str(agent_id), "reason": "not_found"})
            continue
        if agent.status == AgentStatus.REVOKED.value:
            skipped.append({"id": str(agent_id), "reason": "revoked"})
            continue
        if agent.agent_version and _version_tuple(agent.agent_version) >= target_t:
            skipped.append({"id": str(agent.id), "reason": "already_current", "version": agent.agent_version})
            continue
        _queue_agent_update(agent, target)
        queued.append(str(agent.id))
    if not queued:
        raise HTTPException(
            400,
            "No agents queued — selected hosts are already on the current agent pack "
            f"({target}) or were skipped.",
        )
    await write_audit(
        db,
        "agent.update_queue",
        user=admin,
        details={"queued": queued, "skipped": skipped, "target_version": target, "count": len(queued)},
        request=request,
    )
    await db.commit()
    return {"ok": True, "queued": queued, "skipped": skipped, "target_version": target, "count": len(queued)}


@router.post("/agents/{agent_id}/update")
async def queue_one_agent_update(agent_id: UUID, db: DbDep, admin: AdminUser, request: Request):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.status == AgentStatus.REVOKED.value:
        raise HTTPException(400, "Agent is revoked")
    target = agent_pack_version()
    if agent.agent_version and _version_tuple(agent.agent_version) >= _version_tuple(target):
        raise HTTPException(400, f"Agent already on pack {agent.agent_version} (current {target})")
    _queue_agent_update(agent, target)
    await write_audit(
        db,
        "agent.update_queue",
        user=admin,
        machine_id=agent.machine_id,
        details={"queued": [str(agent.id)], "target_version": target},
        request=request,
    )
    await db.commit()
    return {
        "ok": True,
        "queued": [str(agent.id)],
        "target_version": target,
        "remote_update_capable": _remote_update_capable(agent.agent_version or ""),
    }


@router.post("/agents/{agent_id}/revoke")
async def revoke_agent(agent_id: UUID, db: DbDep, admin: AdminUser, request: Request):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    agent.status = AgentStatus.REVOKED.value
    agent.revoked_at = utcnow()
    await write_audit(db, "agent.revoke", user=admin, machine_id=agent.machine_id, request=request)
    await db.commit()
    return {"ok": True}


@router.post("/agents/{agent_id}/approve")
async def approve_agent(agent_id: UUID, db: DbDep, admin: AdminUser, request: Request):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    machine = await db.get(Machine, agent.machine_id)
    agent.status = AgentStatus.ACTIVE.value
    if machine:
        machine.approved = True
    await write_audit(db, "agent.approve", user=admin, machine_id=agent.machine_id, request=request)
    await db.commit()
    return {"ok": True}


@router.post("/agents/{agent_id}/rotate")
async def rotate_agent(agent_id: UUID, db: DbDep, admin: AdminUser, request: Request):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    secret = new_secret(32)
    agent.secret_hash = hash_token(secret)
    agent.status = AgentStatus.ACTIVE.value
    await write_audit(db, "agent.rotate", user=admin, machine_id=agent.machine_id, request=request)
    await db.commit()
    return {"agent_id": agent.agent_public_id, "agent_secret": secret, "note": "Shown once. Update the agent state file."}


@router.get("/settings")
async def get_settings_admin(db: DbDep, admin: AdminUser):
    settings = get_settings()
    channels = (await db.execute(select(NotificationChannelConfig))).scalars().all()
    return {
        "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
        "offline_after_seconds": settings.offline_after_seconds,
        "unhealthy_after_seconds": settings.unhealthy_after_seconds,
        "require_agent_approval": settings.require_agent_approval,
        "metrics_raw_retention_days": settings.metrics_raw_retention_days,
        "metrics_hourly_retention_days": settings.metrics_hourly_retention_days,
        "smtp_enabled": settings.smtp_enabled,
        "notification_channels": [
            {"channel": c.channel, "enabled": c.enabled, "config": {k: v for k, v in (c.config or {}).items() if k != "password"}}
            for c in channels
        ],
    }


@router.put("/notifications/{channel}")
async def update_channel(channel: str, body: dict, db: DbDep, admin: AdminUser):
    row = (
        await db.execute(select(NotificationChannelConfig).where(NotificationChannelConfig.channel == channel.upper()))
    ).scalar_one_or_none()
    if not row:
        row = NotificationChannelConfig(channel=channel.upper(), enabled=bool(body.get("enabled")), config=body.get("config") or {})
        db.add(row)
    else:
        if "enabled" in body:
            row.enabled = bool(body["enabled"])
        if "config" in body:
            row.config = body["config"]
    await db.commit()
    return {"ok": True}


class SmtpBody(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    username: str = ""
    password: str | None = None
    from_addr: str = ""
    starttls: bool = True
    use_ssl: bool = False
    validate_certs: bool = True


class SmtpTestBody(BaseModel):
    to: str = Field(min_length=3)


@router.get("/smtp")
async def get_smtp(db: DbDep, admin: AdminUser):
    from app.services.smtp_config import get_smtp_config, public_smtp_view

    cfg = await get_smtp_config(db)
    return public_smtp_view(cfg)


@router.put("/smtp")
async def put_smtp(body: SmtpBody, db: DbDep, admin: AdminUser, request: Request):
    from app.services.smtp_config import public_smtp_view, save_smtp_config

    payload = body.model_dump()
    if body.password is None:
        payload.pop("password", None)
    cfg = await save_smtp_config(db, payload)
    await write_audit(db, "smtp.update", user=admin, details={"host": cfg.get("host"), "enabled": cfg.get("enabled")}, request=request)
    await db.commit()
    return public_smtp_view(cfg)


@router.post("/smtp/test")
async def test_smtp(body: SmtpTestBody, db: DbDep, admin: AdminUser, request: Request):
    from app.services.smtp_config import send_email

    try:
        await send_email(
            db,
            to=body.to.strip(),
            subject="[LabWatch] SMTP test",
            body="LabWatch SMTP configuration works.\n",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"SMTP test failed: {exc}") from exc
    await write_audit(db, "smtp.test", user=admin, details={"to": body.to.strip()}, request=request)
    await db.commit()
    return {"ok": True, "sent_to": body.to.strip()}
