from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import AdminUser, DbDep, write_audit
from app.config import get_settings
from app.enums import AgentStatus
from app.models import Agent, Lab, Machine, NotificationChannelConfig, RegistrationToken, User, utcnow
from app.schemas.api import RegistrationTokenCreate, UserCreate, UserOut, UserUpdate
from app.security import hash_password, hash_token, new_secret

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
    for k, v in data.items():
        setattr(user, k, v)
    await write_audit(db, "user.update", user=admin, details={"target": user.username}, request=request)
    await db.commit()
    await db.refresh(user)
    return user


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


@router.get("/tokens")
async def list_tokens(db: DbDep, admin: AdminUser):
    rows = (await db.execute(select(RegistrationToken).order_by(RegistrationToken.created_at.desc()))).scalars().all()
    return [
        {
            "id": str(r.id),
            "prefix": r.token_prefix,
            "label": r.label,
            "lab_id": str(r.lab_id) if r.lab_id else None,
            "expires_at": r.expires_at,
            "max_uses": r.max_uses,
            "use_count": r.use_count,
            "revoked": r.revoked,
            "created_at": r.created_at,
        }
        for r in rows
    ]


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
    rows = (await db.execute(select(Agent, Machine).join(Machine, Agent.machine_id == Machine.id))).all()
    return [
        {
            "id": str(a.id),
            "agent_id": a.agent_public_id,
            "machine_id": str(m.id),
            "hostname": m.hostname,
            "status": a.status,
            "health": a.health,
            "version": a.agent_version,
            "last_heartbeat_at": a.last_heartbeat_at,
            "approved": m.approved,
        }
        for a, m in rows
    ]


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
