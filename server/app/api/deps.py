from collections.abc import Callable
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import AgentStatus, UserRole
from app.models import Agent, AuditLog, User, utcnow
from app.security import decode_token, hash_token, new_secret, token_matches, verify_password

bearer = HTTPBearer(auto_error=False)
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db.get(User, UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable:
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN.value))]
OperatorUser = Annotated[User, Depends(require_roles(UserRole.ADMIN.value, UserRole.OPERATOR.value))]


async def get_current_agent(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
    x_agent_id: Annotated[str | None, Header()] = None,
    x_agent_secret: Annotated[str | None, Header()] = None,
) -> Agent:
    agent_id = x_agent_id
    secret = x_agent_secret
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if ":" in token:
            agent_id, secret = token.split(":", 1)
    if not agent_id or not secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Agent credentials required")
    agent = (await db.execute(select(Agent).where(Agent.agent_public_id == agent_id))).scalar_one_or_none()
    if not agent or not token_matches(secret, agent.secret_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent credentials")
    if agent.status == AgentStatus.REVOKED.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent revoked")
    if agent.status == AgentStatus.PENDING.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent pending approval")
    return agent


CurrentAgent = Annotated[Agent, Depends(get_current_agent)]


async def write_audit(
    db: AsyncSession,
    action: str,
    *,
    user: User | None = None,
    machine_id: UUID | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> None:
    ip = None
    if request is not None:
        ip = request.client.host if request.client else None
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else None,
            machine_id=machine_id,
            action=action,
            details=details or {},
            ip_address=ip,
        )
    )


def issue_refresh_token() -> tuple[str, str, object]:
    raw = new_secret(32)
    return raw, hash_token(raw), utcnow() + timedelta(days=7)
