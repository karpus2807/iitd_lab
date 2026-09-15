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
    channel = NotificationChannel.EMAIL.value

    async def send(self, db: AsyncSession, title: str, body: str, payload: dict[str, Any]) -> None:
        from app.config import get_settings

        settings = get_settings()
        if not settings.smtp_enabled or not settings.smtp_host:
            logger.info("Email notifications disabled; skipping")
            return
        try:
            import aiosmtplib
            from email.message import EmailMessage

            users = (await db.execute(select(User).where(User.is_active.is_(True), User.role.in_(["ADMIN", "OPERATOR"])))).scalars().all()
            if not users:
                return
            msg = EmailMessage()
            msg["From"] = settings.smtp_from
            msg["To"] = ", ".join(u.email for u in users)
            msg["Subject"] = f"[LabWatch] {title}"
            msg.set_content(body)
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=settings.smtp_password or None,
                start_tls=settings.smtp_starttls,
            )
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
