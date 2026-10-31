"""Create / verify email OTP challenges and send codes via SMTP."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailOtpChallenge, utcnow
from app.services.smtp_config import send_email

OTP_TTL_MINUTES = 15
OTP_MAX_ATTEMPTS = 5
PURPOSE_ENROLL = "scholar_enroll"
PURPOSE_IMPORT = "scholar_import"
PURPOSE_INV_ASSIGN = "inv_assign"


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def create_challenge(
    db: AsyncSession,
    *,
    purpose: str,
    email: str,
    payload: dict[str, Any],
    created_by: str = "",
) -> tuple[EmailOtpChallenge, str]:
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        raise ValueError("A valid email is required for OTP verification")
    code = generate_code()
    row = EmailOtpChallenge(
        purpose=purpose,
        email=email_norm,
        code_hash=_hash_code(code),
        payload=payload or {},
        expires_at=utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
        created_by=created_by or "",
        attempts=0,
    )
    db.add(row)
    await db.flush()
    return row, code


async def send_otp_mail(db: AsyncSession, *, to: str, code: str, context: str) -> None:
    subject = f"[LabWatch] OTP for {context}"
    body = (
        f"Your LabWatch verification code is: {code}\n\n"
        f"Context: {context}\n"
        f"This code expires in {OTP_TTL_MINUTES} minutes.\n"
        f"If you did not request this, ignore this email.\n"
    )
    await send_email(db, to=to, subject=subject, body=body)


async def get_challenge(db: AsyncSession, challenge_id: UUID) -> EmailOtpChallenge | None:
    return await db.get(EmailOtpChallenge, challenge_id)


async def verify_challenge(
    db: AsyncSession,
    *,
    challenge_id: UUID,
    code: str,
    purpose: str | None = None,
) -> EmailOtpChallenge:
    row = await db.get(EmailOtpChallenge, challenge_id)
    if not row:
        raise ValueError("OTP challenge not found")
    if purpose and row.purpose != purpose:
        raise ValueError("OTP challenge purpose mismatch")
    if row.consumed_at is not None:
        raise ValueError("OTP already used")
    if row.expires_at <= utcnow():
        raise ValueError("OTP expired — request a new one")
    if row.attempts >= OTP_MAX_ATTEMPTS:
        raise ValueError("Too many invalid OTP attempts")
    row.attempts = int(row.attempts or 0) + 1
    if _hash_code(code) != row.code_hash:
        await db.flush()
        raise ValueError("Invalid OTP")
    row.consumed_at = utcnow()
    await db.flush()
    return row


async def expire_open_for_email(db: AsyncSession, purpose: str, email: str) -> None:
    email_norm = (email or "").strip().lower()
    rows = (
        await db.execute(
            select(EmailOtpChallenge).where(
                EmailOtpChallenge.purpose == purpose,
                EmailOtpChallenge.email == email_norm,
                EmailOtpChallenge.consumed_at.is_(None),
            )
        )
    ).scalars().all()
    now = utcnow()
    for row in rows:
        row.expires_at = now
