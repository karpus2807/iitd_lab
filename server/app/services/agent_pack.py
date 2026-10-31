"""Agent pack version (independent of LabWatch server/UI VERSION).

Server releases often bump VERSION for UI/API only. Agents should only show
"update available" when labwatch_agent.__version__ in the shipped pack is newer.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.services.updates import repo_dir

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def version_tuple(value: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for piece in (value or "").strip().lstrip("v").split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def _read_version_file(path: Path) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    match = _VERSION_RE.search(text)
    return (match.group(1) if match else "").strip()


@lru_cache(maxsize=1)
def agent_pack_version() -> str:
    """Version string inside agent/labwatch_agent on this checkout (the pack)."""
    init_py = repo_dir() / "agent" / "labwatch_agent" / "__init__.py"
    return _read_version_file(init_py) or "0.0.0"


def clear_agent_pack_version_cache() -> None:
    agent_pack_version.cache_clear()
