"""Apply a server-pushed agent-pack update and restart the local service.

On failure during apply, restores the previous labwatch_agent tree.
After restart, a short watchdog restores the previous tree if the service
does not become active (Linux systemd / Windows scheduled task).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
from pathlib import Path

logger = logging.getLogger("labwatch.agent")

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')
BACKUP_NAME = "labwatch_agent.prev"


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


def _backup_current(prefix: Path) -> Path | None:
    """Snapshot current package so a failed update can restore it."""
    current = prefix / "labwatch_agent"
    if not current.is_dir():
        return None
    backup = prefix / BACKUP_NAME
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(current, backup)
    return backup


def _restore_backup(prefix: Path, backup: Path | None) -> None:
    if not backup or not backup.is_dir():
        return
    current = prefix / "labwatch_agent"
    if current.exists():
        shutil.rmtree(current)
    shutil.move(str(backup), str(current))
    logger.warning("Restored previous agent package from %s", BACKUP_NAME)


def apply_pack(pack_bytes: bytes, *, target_version: str = "") -> str:
    """Extract agent-pack.tgz, install wheels + code into PREFIX. Returns new version.

    Always targets the pack shipped by the server (current release), not a
    step-by-step version ladder. Rolls back package files if install fails.
    """
    prefix = install_prefix()
    if not (prefix / "labwatch_agent").is_dir():
        raise RuntimeError(f"Unexpected install layout under {prefix}")

    backup = _backup_current(prefix)
    try:
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
            # Sanity: new package must still be importable / versioned.
            installed = _read_version(prefix / "labwatch_agent" / "__init__.py")
            if not installed:
                raise RuntimeError("Updated package is missing __version__")
            logger.info("Agent files updated to %s under %s", installed, prefix)
            return installed
    except Exception:
        _restore_backup(prefix, backup)
        raise


def schedule_restart() -> None:
    """Restart the agent service after this process exits; rollback if it stays down."""
    prefix = install_prefix()
    backup = prefix / BACKUP_NAME
    if os.name == "nt":
        _schedule_restart_windows(prefix, backup)
        return
    _schedule_restart_linux(prefix, backup)


def _schedule_restart_linux(prefix: Path, backup: Path) -> None:
    # Detached bash watchdog: restart, wait for active, else restore prev package.
    backup_q = str(backup).replace("'", "'\"'\"'")
    prefix_q = str(prefix).replace("'", "'\"'\"'")
    script = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -e
        sleep 2
        systemctl restart labwatch-agent || true
        for i in 1 2 3 4 5 6 7 8; do
          sleep 4
          if systemctl is-active --quiet labwatch-agent; then
            exit 0
          fi
        done
        if [ -d '{backup_q}' ]; then
          echo "labwatch-agent failed to stay up — restoring previous package" >&2
          rm -rf '{prefix_q}/labwatch_agent'
          mv '{backup_q}' '{prefix_q}/labwatch_agent'
          systemctl restart labwatch-agent || true
        fi
        """
    )
    try:
        subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        logger.warning("Could not schedule systemctl restart/rollback: %s", exc)
        try:
            subprocess.Popen(
                ["systemctl", "restart", "labwatch-agent"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as exc2:
            logger.warning("Could not schedule systemctl restart: %s", exc2)


def _schedule_restart_windows(prefix: Path, backup: Path) -> None:
    # Windows installer registers Scheduled Task "LabWatchAgent".
    backup_ps = str(backup).replace("'", "''")
    current_ps = str(prefix / "labwatch_agent").replace("'", "''")
    ps = textwrap.dedent(
        f"""\
        Start-Sleep -Seconds 2
        Stop-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Start-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue
        $ok = $false
        for ($i = 0; $i -lt 8; $i++) {{
          Start-Sleep -Seconds 4
          $t = Get-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue
          if ($t -and $t.State -eq 'Running') {{ $ok = $true; break }}
        }}
        if (-not $ok -and (Test-Path '{backup_ps}')) {{
          if (Test-Path '{current_ps}') {{ Remove-Item -Recurse -Force '{current_ps}' }}
          Move-Item '{backup_ps}' '{current_ps}'
          Stop-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue
          Start-Sleep -Seconds 1
          Start-ScheduledTask -TaskName LabWatchAgent -ErrorAction SilentlyContinue
        }}
        """
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
        logger.warning("Could not schedule Windows task restart/rollback: %s", exc)
