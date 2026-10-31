"""Runtime SMTP config stored in settings table (Admin Mail UI), with env fallback."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Setting

SMTP_KEY = "smtp"


def _env_smtp() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": bool(s.smtp_enabled),
        "host": s.smtp_host or "",
        "port": int(s.smtp_port or 587),
        "username": s.smtp_username or "",
        "password": s.smtp_password or "",
        "from_addr": s.smtp_from or "",
        "starttls": bool(s.smtp_starttls),
    }


async def get_smtp_config(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(select(Setting).where(Setting.key == SMTP_KEY))).scalar_one_or_none()
    base = _env_smtp()
    if not row or not isinstance(row.value, dict):
        return base
    merged = {**base, **{k: v for k, v in row.value.items() if v is not None}}
    # empty password in DB means keep previous/env password
    if not str(merged.get("password") or "").strip():
        merged["password"] = base.get("password") or (row.value.get("password") if row.value else "") or ""
    merged["port"] = int(merged.get("port") or 587)
    merged["enabled"] = bool(merged.get("enabled"))
    merged["starttls"] = bool(merged.get("starttls", True))
    return merged


def public_smtp_view(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(cfg.get("enabled")),
        "host": cfg.get("host") or "",
        "port": int(cfg.get("port") or 587),
        "username": cfg.get("username") or "",
        "password_set": bool(str(cfg.get("password") or "").strip()),
        "from_addr": cfg.get("from_addr") or "",
        "starttls": bool(cfg.get("starttls", True)),
    }


async def save_smtp_config(db: AsyncSession, body: dict[str, Any]) -> dict[str, Any]:
    current = await get_smtp_config(db)
    next_cfg = {
        "enabled": bool(body.get("enabled", current.get("enabled"))),
        "host": str(body.get("host", current.get("host") or "")).strip(),
        "port": int(body.get("port", current.get("port") or 587)),
        "username": str(body.get("username", current.get("username") or "")).strip(),
        "from_addr": str(body.get("from_addr", current.get("from_addr") or "")).strip(),
        "starttls": bool(body.get("starttls", current.get("starttls", True))),
        "password": current.get("password") or "",
    }
    if "password" in body and str(body.get("password") or "").strip():
        next_cfg["password"] = str(body["password"])
    row = (await db.execute(select(Setting).where(Setting.key == SMTP_KEY))).scalar_one_or_none()
    if not row:
        row = Setting(key=SMTP_KEY, value=next_cfg)
        db.add(row)
    else:
        row.value = next_cfg
    await db.flush()
    return next_cfg


async def send_email(db: AsyncSession, *, to: str, subject: str, body: str) -> None:
    cfg = await get_smtp_config(db)
    if not cfg.get("enabled") or not cfg.get("host"):
        raise RuntimeError("SMTP is not enabled. Configure it under Admin → Mail.")
    to_addr = (to or "").strip()
    if not to_addr:
        raise RuntimeError("Recipient email is empty")
    import aiosmtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = cfg.get("from_addr") or cfg.get("username") or "labwatch@localhost"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    await aiosmtplib.send(
        msg,
        hostname=cfg["host"],
        port=int(cfg.get("port") or 587),
        username=cfg.get("username") or None,
        password=cfg.get("password") or None,
        start_tls=bool(cfg.get("starttls", True)),
    )
