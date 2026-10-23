"""Apply a server-pushed agent-pack update and restart the local service."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

logger = logging.getLogger("labwatch.agent")

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def install_prefix() -> Path:
    """PREFIX where run.py + labwatch_agent/ live (e.g. /opt/labwatch-agent)."""
    return Path(__file__).resolve().parent.parent


def _read_version(init_py: Path) -> str:
    text = init_py.read_text(encoding="utf-8", errors="replace")
    match = _VERSION_RE.search(text)
    return match.group(1) if match else ""


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def apply_pack(pack_bytes: bytes, *, target_version: str = "") -> str:
    """Extract agent-pack.tgz, install wheels + code into PREFIX. Returns new version."""
    prefix = install_prefix()
    if not (prefix / "labwatch_agent").is_dir():
        raise RuntimeError(f"Unexpected install layout under {prefix}")

    with tempfile.TemporaryDirectory(prefix="labwatch-upd-") as tmp:
        tmp_path = Path(tmp)
        pack_file = tmp_path / "agent-pack.tgz"
        pack_file.write_bytes(pack_bytes)
        extract = tmp_path / "src"
        extract.mkdir()
        with tarfile.open(pack_file, "r:gz") as tar:
            tar.extractall(extract)

        agent_src = extract / "labwatch_agent"
        req = extract / "requirements.txt"
        wheels = extract / "wheels"
        if not agent_src.is_dir():
            raise RuntimeError("agent-pack.tgz missing labwatch_agent/")
        if not req.is_file():
            raise RuntimeError("agent-pack.tgz missing requirements.txt")
        if not wheels.is_dir() or not any(wheels.glob("*.whl")):
            raise RuntimeError("agent-pack.tgz missing offline wheels/")

        new_version = _read_version(agent_src / "__init__.py") or target_version or "unknown"
        venv_python = prefix / "venv" / "bin" / "python"
        if os.name == "nt":
            venv_python = prefix / "venv" / "Scripts" / "python.exe"
        if not venv_python.is_file():
            raise RuntimeError(f"venv python missing at {venv_python}")

        pip_base = [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "-q",
            "--no-index",
            f"--find-links={wheels}",
        ]
        subprocess.run(
            [*pip_base, "-U", "pip", "setuptools", "wheel"],
            check=True,
            timeout=300,
        )
        subprocess.run(
            [*pip_base, "-r", str(req)],
            check=True,
            timeout=600,
        )
        # Optional Linux sqlite fallback — never fail the update if missing.
        optional = extract / "requirements-optional-linux.txt"
        if optional.is_file() and os.name != "nt":
            try:
                subprocess.run(
                    [*pip_base, "-r", str(optional)],
                    check=False,
                    timeout=300,
                )
            except Exception:
                logger.warning("Optional pysqlite3-binary install skipped during self-update")
        _copy_tree(agent_src, prefix / "labwatch_agent")
        logger.info("Agent files updated to %s under %s", new_version, prefix)
        return new_version


def schedule_restart() -> None:
    """Restart the agent service after this process exits."""
    if os.name == "nt":
        # Windows installer registers Scheduled Task "LabWatchAgent".
        ps = (
            "Start-Sleep -Seconds 2; "
            "Stop-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue; "
            "Start-Sleep -Seconds 1; "
            "Start-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue"
        )
        try:
            flags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                flags |= subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "DETACHED_PROCESS"):
                flags |= subprocess.DETACHED_PROCESS
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
        except Exception as exc:
            logger.warning("Could not schedule Windows task restart: %s", exc)
        return
    try:
        subprocess.Popen(
            ["systemctl", "restart", "labwatch-agent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        logger.warning("Could not schedule systemctl restart: %s", exc)
