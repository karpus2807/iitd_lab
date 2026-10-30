"""Store / load scholar enrolment photos under data/scholar-photos."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from app.config import get_settings

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_BYTES = 5 * 1024 * 1024


def photo_root() -> Path:
    settings = get_settings()
    base = Path(settings.repo_dir).resolve() if settings.repo_dir else Path.cwd().resolve()
    root = base / "data" / "scholar-photos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_ext(filename: str | None, content_type: str | None) -> str:
    name = (filename or "").lower()
    for ext in ALLOWED_EXT:
        if name.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    return ".jpg"


def save_photo(scholar_id: UUID, data: bytes, filename: str | None = None, content_type: str | None = None) -> str:
    if not data:
        raise ValueError("Empty photo")
    if len(data) > MAX_BYTES:
        raise ValueError("Photo too large (max 5 MB)")
    ext = _safe_ext(filename, content_type)
    rel = f"{scholar_id}{ext}"
    path = photo_root() / rel
    # remove previous extensions for same id
    for old in photo_root().glob(f"{scholar_id}.*"):
        if old.name != rel:
            try:
                old.unlink()
            except OSError:
                pass
    path.write_bytes(data)
    return rel


def resolve_photo(rel: str) -> Path | None:
    if not rel:
        return None
    name = Path(rel).name
    if not re.fullmatch(r"[0-9a-fA-F-]{36}\.(jpg|jpeg|png|webp|gif)", name):
        return None
    path = photo_root() / name
    return path if path.is_file() else None


def delete_photo(rel: str) -> None:
    path = resolve_photo(rel)
    if path:
        try:
            path.unlink()
        except OSError:
            pass
