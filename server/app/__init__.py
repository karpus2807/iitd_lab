"""LabWatch monitoring server."""

from pathlib import Path


def _read_version() -> str:
    for candidate in (
        Path("/app/VERSION"),
        Path(__file__).resolve().parents[2] / "VERSION",
        Path(__file__).resolve().parents[1] / "VERSION",
    ):
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8").strip()
            if text:
                return text
    return "1.1.19"


__version__ = _read_version()
