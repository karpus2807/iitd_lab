"""Pluggable notification dispatch. Channels are registered, never hard-coded at call sites."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import NotificationChannel
from app.models import Notification, NotificationChannelConfig, User

logger = logging.getLogger(__name__)


class NotificationBackend(ABC):
    channel: str

    @abstractmethod
    async def send(self, db: AsyncSession, title: str, body: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class DashboardBackend(NotificationBackend):
    channel = NotificationChannel.DASHBOARD.value

    async def send(self, db: AsyncSession, title: str, body: str, payload: dict[str, Any]) -> None:
        users = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
        if not users:
            db.add(Notification(user_id=None, channel=self.channel, title=title, body=body, payload=payload))
            return
        for user in users:
            if user.role in ("ADMIN", "OPERATOR"):
                db.add(
                    Notification(
                        user_id=user.id,
                        channel=self.channel,
                        title=title,
                        body=body,
                        payload=payload,
                    )
                )


class EmailBackend(NotificationBackend):
    """Alert emails via Admin → Mail (smtp_config), not a separate env-only path.

    Kept as a NotificationChannel so Admin can toggle EMAIL independently; the
    original env SMTP fields remain as fallback inside smtp_config.get_smtp_config.
    """

    channel = NotificationChannel.EMAIL.value

    async def send(self, db: AsyncSession, title: str, body: str, payload: dict[str, Any]) -> None:
        cfg = (
            await db.execute(
                select(NotificationChannelConfig).where(NotificationChannelConfig.channel == self.channel)
            )
        ).scalar_one_or_none()
        if cfg is not None and not cfg.enabled:
            return
        try:
            from app.services.smtp_config import get_smtp_config, send_email

            smtp = await get_smtp_config(db)
            if not smtp.get("enabled") or not smtp.get("host"):
                logger.info("Email notifications skipped — SMTP not enabled (Admin → Mail)")
                return
            users = (
                await db.execute(select(User).where(User.is_active.is_(True), User.role.in_(["ADMIN", "OPERATOR"])))
            ).scalars().all()
            recipients = [u.email for u in users if (u.email or "").strip()]
            if not recipients:
                return
            subject = f"[LabWatch] {title}"
            for to in recipients:
                await send_email(db, to=to, subject=subject, body=body)
        except Exception:
            logger.exception("Email notification failed")


class WebhookBackend(NotificationBackend):
    channel = NotificationChannel.WEBHOOK.value

    async def send(self, db: AsyncSession, title: str, body: str, payload: dict[str, Any]) -> None:
        cfg = (
            await db.execute(
                select(NotificationChannelConfig).where(NotificationChannelConfig.channel == self.channel)
            )
        ).scalar_one_or_none()
        if not cfg or not cfg.enabled:
            return
        url = (cfg.config or {}).get("url")
        if not url:
            return
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"title": title, "body": body, "payload": payload})
        except Exception:
            logger.exception("Webhook notification failed")


_REGISTRY: dict[str, NotificationBackend] = {
    NotificationChannel.DASHBOARD.value: DashboardBackend(),
    NotificationChannel.EMAIL.value: EmailBackend(),
    NotificationChannel.WEBHOOK.value: WebhookBackend(),
}


def register_backend(backend: NotificationBackend) -> None:
    _REGISTRY[backend.channel] = backend


async def notify(db: AsyncSession, title: str, body: str, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}
    for backend in _REGISTRY.values():
        try:
            await backend.send(db, title, body, payload)
        except Exception:
            logger.exception("Notification backend %s failed", backend.channel)
