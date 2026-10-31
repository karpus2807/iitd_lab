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
        "use_ssl": False,
        "validate_certs": True,
    }


def _normalize_tls(cfg: dict[str, Any]) -> dict[str, Any]:
    """IITD: STARTTLS on 25, or implicit SSL/TLS on 465. Never both."""
    port = int(cfg.get("port") or 587)
    use_ssl = bool(cfg.get("use_ssl"))
    starttls = bool(cfg.get("starttls", True))
    if port == 465:
        use_ssl = True
        starttls = False
    elif use_ssl:
        starttls = False
    cfg["port"] = port
    cfg["use_ssl"] = use_ssl
    cfg["starttls"] = starttls
    cfg["validate_certs"] = bool(cfg.get("validate_certs", True))
    return cfg


async def get_smtp_config(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(select(Setting).where(Setting.key == SMTP_KEY))).scalar_one_or_none()
    base = _env_smtp()
    if not row or not isinstance(row.value, dict):
        return _normalize_tls(dict(base))
    merged = {**base, **{k: v for k, v in row.value.items() if v is not None}}
    # empty password in DB means keep previous/env password
    if not str(merged.get("password") or "").strip():
        merged["password"] = base.get("password") or (row.value.get("password") if row.value else "") or ""
    merged["enabled"] = bool(merged.get("enabled"))
    return _normalize_tls(merged)


def public_smtp_view(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = _normalize_tls(dict(cfg))
    return {
        "enabled": bool(cfg.get("enabled")),
        "host": cfg.get("host") or "",
        "port": int(cfg.get("port") or 587),
        "username": cfg.get("username") or "",
        "password_set": bool(str(cfg.get("password") or "").strip()),
        "from_addr": cfg.get("from_addr") or "",
        "starttls": bool(cfg.get("starttls", True)),
        "use_ssl": bool(cfg.get("use_ssl")),
        "validate_certs": bool(cfg.get("validate_certs", True)),
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
        "use_ssl": bool(body.get("use_ssl", current.get("use_ssl", False))),
        "validate_certs": bool(body.get("validate_certs", current.get("validate_certs", True))),
        "password": current.get("password") or "",
    }
    if "password" in body and str(body.get("password") or "").strip():
        next_cfg["password"] = str(body["password"])
    next_cfg = _normalize_tls(next_cfg)
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
    user = str(cfg.get("username") or "").strip() or None
    password = str(cfg.get("password") or "").strip() or None
    if not user or not password:
        raise RuntimeError("SMTP username and password are required (IITD authenticates outbound mail).")

    import aiosmtplib
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid, parseaddr

    from_addr = str(cfg.get("from_addr") or user).strip()
    _, from_email = parseaddr(from_addr)
    domain = (from_email.split("@", 1)[1] if "@" in (from_email or "") else "") or "localhost"

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    # IITD amavis rejects mail missing Date (554 BAD HEADER)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(body)

    port = int(cfg.get("port") or 587)
    use_tls = bool(cfg.get("use_ssl"))  # implicit SSL (465)
    start_tls = bool(cfg.get("starttls")) and not use_tls  # STARTTLS (25)
    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg["host"],
            port=port,
            username=user,
            password=password,
            use_tls=use_tls,
            start_tls=start_tls,
            validate_certs=bool(cfg.get("validate_certs", True)),
        )
    except Exception as exc:  # noqa: BLE001
        mode = "SSL/TLS" if use_tls else ("STARTTLS" if start_tls else "plain")
        raise RuntimeError(
            f"{exc} (host={cfg['host']}:{port}, mode={mode}, user={user})"
        ) from exc
