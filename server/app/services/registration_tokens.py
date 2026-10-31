"""Registration-token monitoring + machine-based supersede revoke.

Agents authenticate with agent_secret after enroll; registration_token_id on the
Agent row is how we know which enrollment token still "owns" that host. Last-used
is updated from live heartbeats, not only at /register.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, RegistrationToken, utcnow

# Avoid rewriting last_used_at on every ~30s heartbeat.
_TOUCH_MIN_AGE = timedelta(seconds=60)


async def touch_token_last_used(db: AsyncSession, token_id: UUID | None) -> None:
    if not token_id:
        return
    row = await db.get(RegistrationToken, token_id)
    if not row or row.revoked:
        return
    now = utcnow()
    if row.last_used_at and (now - row.last_used_at) < _TOUCH_MIN_AGE:
        return
    row.last_used_at = now


async def revoke_superseded_token(
    db: AsyncSession,
    *,
    old_token_id: UUID | None,
    new_token_id: UUID,
) -> bool:
    """Revoke previous enrollment token when a machine moves to a new one.

    Only when no remaining agents are still linked to the old token (shared lab
    tokens stay alive while other machines use them). Never time-based.
    """
    if not old_token_id or old_token_id == new_token_id:
        return False
    remaining = (
        await db.execute(
            select(func.count()).select_from(Agent).where(Agent.registration_token_id == old_token_id)
        )
    ).scalar_one()
    if int(remaining or 0) > 0:
        return False
    old = await db.get(RegistrationToken, old_token_id)
    if not old or old.revoked:
        return False
    old.revoked = True
    return True
