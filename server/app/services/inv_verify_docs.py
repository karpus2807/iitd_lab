"""Store inventory-assign verification PDFs under data/inv-verify-docs."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from app.config import get_settings

ALLOWED_EXT = {".pdf"}
MAX_BYTES = 15 * 1024 * 1024


def doc_root() -> Path:
    settings = get_settings()
    base = Path(settings.repo_dir).resolve() if settings.repo_dir else Path.cwd().resolve()
    root = base / "data" / "inv-verify-docs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_pdf(data: bytes, filename: str | None, content_type: str | None) -> bool:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return True
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return True
    return data[:5] == b"%PDF-"


def save_doc(
    scholar_id: UUID,
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    if not data:
        raise ValueError("Empty document")
    if len(data) > MAX_BYTES:
        raise ValueError("Document too large (max 15 MB)")
    if not _is_pdf(data, filename, content_type):
        raise ValueError("Only PDF documents are accepted for inventory verification")
    if not data.startswith(b"%PDF"):
        raise ValueError("File does not look like a valid PDF")
    rel = f"{scholar_id}.pdf"
    path = doc_root() / rel
    for old in doc_root().glob(f"{scholar_id}.*"):
        if old.name != rel:
            try:
                old.unlink()
            except OSError:
                pass
    path.write_bytes(data)
    return rel


def resolve_doc(rel: str) -> Path | None:
    if not rel:
        return None
    name = Path(rel).name
    if not re.fullmatch(r"[0-9a-fA-F-]{36}\.pdf", name):
        return None
    path = doc_root() / name
    return path if path.is_file() else None


def delete_doc(rel: str) -> None:
    path = resolve_doc(rel)
    if path:
        try:
            path.unlink()
        except OSError:
            pass
